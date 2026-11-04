import asyncio
import threading
import time
from datetime import datetime, timezone
from uuid import UUID

from app.application.dto import IngestionJob, IngestionRequest, IngestionResult, JobError
from app.application.ports.documents import DocumentIndexing, DocumentSource, PipelineOptions, ResourceStore
from app.application.ports.execution import JobExecutor
from app.domain.documents import IndexSpecification, TextDocument
from app.domain.errors import EmbeddingError, IndexingError, IngestionError, ResourceError, SourceError, StorageError
from app.domain.jobs import TERMINAL


def now() -> datetime:
    return datetime.now(timezone.utc)


class IngestionManager:
    """Single-process jobs. Only successfully collected documents are persisted."""

    def __init__(self, settings: PipelineOptions, store: ResourceStore, source: DocumentSource,
                 executor: JobExecutor, indexer: DocumentIndexing | None = None):
        self.settings, self.store, self.source, self.executor = settings, store, source, executor
        self.lock = threading.Lock()
        self.requests: dict[UUID, IngestionRequest] = {}
        self.jobs: dict[UUID, IngestionJob] = {}
        self.deadlines: dict[UUID, float] = {}
        self.deleted_resources: set[tuple[str, str]] = set()
        self.indexer = indexer

    def submit(self, body: IngestionRequest) -> tuple[IngestionJob, bool]:
        # Serialize admission so simultaneous requests cannot reserve the same job/resource/page.
        with self.lock:
            if body.job_id in self.requests:
                old = self.requests[body.job_id]
                if old.user_id != body.user_id:
                    raise IngestionError(404, "JOB_NOT_FOUND", "Job not found")
                if old != body:
                    raise IngestionError(409, "JOB_ID_CONFLICT", "Job ID was used with different input")
                if self._is_deleted(body) and self.jobs[body.job_id].status != "CANCELLED":
                    raise IngestionError(409, "RESOURCE_DELETED", "Resource was deleted")
                return self.jobs[body.job_id].model_copy(deep=True), False
            if self._is_deleted(body):
                raise IngestionError(409, "RESOURCE_DELETED", "Resource was deleted")
            if body.parent_resource_id and (str(body.user_id), str(body.parent_resource_id)) in self.deleted_resources:
                raise IngestionError(409, "RESOURCE_DELETED", "Parent resource was deleted")
            if body.operation == "COLLECT_AND_INDEX" and self.indexer is None:
                raise IngestionError(409, "OPERATION_NOT_AVAILABLE", "Indexing is not configured")
            self.store.require_connection(str(body.user_id), str(body.connection_id))
            for job_id, old in self.requests.items():
                if old.resource_id == body.resource_id:
                    if self._normalized_identity(old) != self._normalized_identity(body):
                        raise IngestionError(409, "RESOURCE_ID_CONFLICT", "Resource ID has a different source")
                same_page = old.connection_id == body.connection_id and old.page_id == body.page_id
                if (old.resource_id == body.resource_id or same_page) and self.jobs[job_id].status not in TERMINAL:
                    raise IngestionError(409, "INGESTION_IN_PROGRESS", "Resource collection is already running")
            self.store.validate_registration(self._normalized_identity(body), str(body.resource_id), body.operation)
            job = IngestionJob(
                jobId=body.job_id, userId=body.user_id, resourceId=body.resource_id,
                operation=body.operation, status="QUEUED", resourceStatus="PROCESSING", createdAt=now(),
            )
            self.requests[body.job_id] = body
            self.jobs[body.job_id] = job
            self.deadlines[body.job_id] = time.monotonic() + self.settings.ingestion_timeout_seconds
            return job.model_copy(deep=True), True

    @staticmethod
    def _identity(body: IngestionRequest) -> tuple:
        return (str(body.user_id), str(body.connection_id), str(body.page_id),
                str(body.parent_resource_id) if body.parent_resource_id else None)

    def _normalized_identity(self, body: IngestionRequest) -> tuple:
        identity = self._identity(body)
        if (str(body.user_id), identity[3]) in self.deleted_resources:
            return (*identity[:3], None)
        return identity

    def get(self, job_id: UUID, user_id: UUID) -> IngestionJob:
        with self.lock:
            job = self.jobs.get(job_id)
            if job is None or job.userId != user_id:
                raise IngestionError(404, "JOB_NOT_FOUND", "Job not found")
            return job.model_copy(deep=True)

    def _is_deleted(self, body: IngestionRequest) -> bool:
        return (str(body.user_id), str(body.resource_id)) in self.deleted_resources

    def delete(self, resource_id: UUID, user_id: UUID) -> None:
        user, resource = str(user_id), str(resource_id)
        # Share the collection commit lock so either deletion or completion wins atomically.
        with self.lock:
            self.deleted_resources.add((user, resource))
            for job_id, body in self.requests.items():
                job = self.jobs[job_id]
                if body.user_id == user_id and body.resource_id == resource_id and job.status not in TERMINAL:
                    job.status, job.resourceStatus, job.completedAt = "CANCELLED", "DELETED", now()
                    job.result = None
                    job.error = JobError(code="RESOURCE_DELETED", message="Resource was deleted", retryable=False)
            # Keep the exclusion marker even if physical deletion fails.
            self.store.delete(user, resource)

    def read_resource(self, user_id: str, resource_id: str) -> dict:
        with self.lock:
            if (user_id, resource_id) in self.deleted_resources:
                raise ResourceError(404, "Resource not found")
            return self.store.read(user_id, resource_id)

    def list_resources(self, user_id: str, connection_id: str, limit: int, offset: int) -> list[dict]:
        with self.lock:
            excluded = [resource for user, resource in self.deleted_resources if user == user_id]
            return self.store.list(user_id, connection_id, excluded, limit, offset)

    def validate_legacy_registration(self, user_id: str, parent_resource_id: UUID | None) -> None:
        with self.lock:
            if parent_resource_id and (user_id, str(parent_resource_id)) in self.deleted_resources:
                raise ResourceError(409, "Parent resource was deleted")

    async def start(self, job_id: UUID) -> None:
        await self.executor.start(lambda: self.run(job_id))

    async def shutdown(self) -> None:
        await self.executor.shutdown()

    def _load(self, body: IngestionRequest) -> TextDocument:
        saved = self.store.get(str(body.resource_id))
        if saved is not None:
            if saved.identity[:3] != self._identity(body)[:3]:
                raise IngestionError(409, "RESOURCE_ID_CONFLICT", "Resource ID has a different source")
            return saved.document
        return self.source.load(str(body.user_id), str(body.connection_id), body.page_id)

    def _finish(self, body: IngestionRequest, document: TextDocument) -> None:
        # A timed-out/cancelled fetch can finish in its thread but must never write a late document.
        with self.lock:
            job = self.jobs[body.job_id]
            if job.status in TERMINAL or self._is_deleted(body):
                return
            if time.monotonic() >= self.deadlines[body.job_id]:
                raise TimeoutError
            metadata = document.metadata
            result = IngestionResult(
                title=metadata["title"][:500] if metadata["title"] else None,
                canonicalUrl=metadata["source"], contentStatus=metadata["content_status"],
                referenceCount=len(metadata["references"]),
            )
            self.store.save_snapshot(self._normalized_identity(body), str(body.resource_id), document)
            job.status = "EXTRACTED"
            if body.operation == "COLLECT":
                job.result = result
                job.status, job.resourceStatus, job.completedAt = "SUCCEEDED", "COLLECTED", now()

    def _check_active(self, body: IngestionRequest) -> None:
        with self.lock:
            if self.jobs[body.job_id].status in TERMINAL or self._is_deleted(body):
                raise IndexingError("RESOURCE_DELETED", "Resource was deleted")
            if time.monotonic() >= self.deadlines[body.job_id]:
                raise TimeoutError

    def _publish_index(self, body: IngestionRequest, chunks: list[TextDocument], vectors: list[list[float]]) -> None:
        with self.lock:
            job = self.jobs[body.job_id]
            if job.status in TERMINAL or self._is_deleted(body):
                return
            if time.monotonic() >= self.deadlines[body.job_id]:
                raise TimeoutError
            indexed_at = now()
            specification = IndexSpecification(
                model=self.settings.embedding_model, dimensions=self.settings.embedding_dimensions,
                chunk_size=self.settings.chunk_size, chunk_overlap=self.settings.chunk_overlap,
                chunking_version=self.indexer.chunking_version, indexed_at=indexed_at,
            )
            result = self.store.publish_index(str(body.user_id), str(body.resource_id), chunks, vectors, specification)
            job.result = result
            job.status, job.resourceStatus, job.completedAt = "SUCCEEDED", "READY", now()

    async def _within_deadline(self, body: IngestionRequest, function, *args):
        remaining = self.deadlines[body.job_id] - time.monotonic()
        if remaining <= 0:
            raise TimeoutError
        return await self.executor.call(function, *args, timeout=remaining)

    def _fail(self, job_id: UUID, code: str, message: str, retryable: bool = False) -> None:
        with self.lock:
            job = self.jobs[job_id]
            if job.status in TERMINAL:
                return
            job.status, job.resourceStatus, job.completedAt = "FAILED", "FAILED", now()
            job.error = JobError(code=code, message=message, retryable=retryable)

    async def run(self, job_id: UUID) -> None:
        body = self.requests[job_id]
        with self.lock:
            if self.jobs[job_id].status in TERMINAL:
                return
            self.jobs[job_id].status = "EXTRACTING"
            self.jobs[job_id].startedAt = now()
        try:
            document = await self._within_deadline(body, self._load, body)
            await self.executor.call(self._finish, body, document)
            if body.operation == "COLLECT_AND_INDEX":
                self._check_active(body)
                chunks = await self._within_deadline(body, self.indexer.chunks, document)
                with self.lock:
                    if self.jobs[job_id].status in TERMINAL:
                        return
                    self.jobs[job_id].status = "INDEXING"
                vectors = await self._within_deadline(body, self.indexer.embed, chunks,
                                                      lambda: self._check_active(body))
                await self.executor.call(self._publish_index, body, chunks, vectors)
        except asyncio.CancelledError:
            self._fail(job_id, "INTERNAL_ERROR", "Collection interrupted by service shutdown", True)
            raise
        except TimeoutError:
            self._fail(job_id, "INGESTION_TIMEOUT", "Collection exceeded its deadline", True)
        except SourceError as exc:
            self._fail(job_id, exc.code, str(exc), exc.retryable)
        except EmbeddingError as exc:
            self._fail(job_id, "EMBEDDING_FAILED", str(exc), exc.retryable)
        except IndexingError as exc:
            self._fail(job_id, exc.code, str(exc))
        except IngestionError as exc:
            self._fail(job_id, exc.code, str(exc), exc.retryable)
        except StorageError:
            code = "INDEX_WRITE_FAILED" if self.jobs[job_id].status == "INDEXING" else "INTERNAL_ERROR"
            self._fail(job_id, code, "Resource could not be stored", True)
        except Exception:
            self._fail(job_id, "INTERNAL_ERROR", "Collection failed")
