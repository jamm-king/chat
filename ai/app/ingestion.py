import asyncio
import threading
import time
from datetime import datetime, timezone
from uuid import UUID

import httpx
from cryptography.fernet import InvalidToken
from fastapi import HTTPException
from langchain_core.documents import Document
from sqlalchemy import select, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import sessionmaker

from app.config import Settings
from app.db import NotionResource, get_connection
from app.ingestion_schemas import IngestionJob, IngestionRequest, IngestionResult, JobError
from app.loader import load_page
from app.notion_auth import decrypt_token
from app.notion_client import NotionApiError, NotionClient
from app.resources import build_resource, validate_parent
from app.schemas import NotionResourceResponse, NotionResourceSummary

TERMINAL = {"SUCCEEDED", "FAILED", "CANCELLED"}


class IngestionError(Exception):
    def __init__(self, status: int, code: str, message: str, retryable: bool = False):
        super().__init__(message)
        self.status, self.code, self.retryable = status, code, retryable


def now() -> datetime:
    return datetime.now(timezone.utc)


class IngestionManager:
    """Single-process jobs. Only successfully collected documents are persisted."""

    def __init__(self, settings: Settings, sessions: sessionmaker, http: httpx.Client):
        self.settings, self.sessions, self.http = settings, sessions, http
        self.lock = threading.Lock()
        self.requests: dict[UUID, IngestionRequest] = {}
        self.jobs: dict[UUID, IngestionJob] = {}
        self.deadlines: dict[UUID, float] = {}
        self.tasks: set[asyncio.Task] = set()
        self.deleted_resources: set[tuple[str, str]] = set()

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
            if body.operation != "COLLECT":
                raise IngestionError(409, "OPERATION_NOT_AVAILABLE", "Indexing is not available yet")
            with self.sessions() as session:
                if get_connection(session, str(body.user_id), str(body.connection_id)) is None:
                    raise IngestionError(404, "CONNECTION_NOT_FOUND", "Connection not found")
                for job_id, old in self.requests.items():
                    if old.resource_id == body.resource_id:
                        if self._identity(old) != self._identity(body):
                            raise IngestionError(409, "RESOURCE_ID_CONFLICT", "Resource ID has a different source")
                    same_page = old.connection_id == body.connection_id and old.page_id == body.page_id
                    if (old.resource_id == body.resource_id or same_page) and self.jobs[job_id].status not in TERMINAL:
                        raise IngestionError(409, "INGESTION_IN_PROGRESS", "Resource collection is already running")
                existing = session.get(NotionResource, str(body.resource_id))
                if existing is not None:
                    if (existing.user_id, existing.connection_id, existing.page_id, existing.parent_resource_id) != self._identity(body):
                        raise IngestionError(409, "RESOURCE_ID_CONFLICT", "Resource ID has a different source")
                    raise IngestionError(409, "RESOURCE_ALREADY_COLLECTED", "Resource is already collected")
                if session.scalar(select(NotionResource.id).where(
                    NotionResource.connection_id == str(body.connection_id),
                    NotionResource.page_id == str(body.page_id),
                )) is not None:
                    raise IngestionError(409, "RESOURCE_ALREADY_COLLECTED", "Page is already collected")
                self._validate_parent(session, body)
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

    @staticmethod
    def _validate_parent(session, body):
        try:
            validate_parent(session, *IngestionManager._identity(body))
        except HTTPException as exc:
            code = "RESOURCE_NOT_FOUND" if exc.status_code == 404 else "INVALID_PARENT_REFERENCE"
            raise IngestionError(404 if exc.status_code == 404 else 409, code, str(exc.detail)) from None

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
            # Keep the exclusion marker even if physical deletion fails. Caller can retry deletion.
            with self.sessions() as session:
                row = session.scalar(select(NotionResource).where(
                    NotionResource.id == resource, NotionResource.user_id == user,
                ))
                if row is None:
                    return
                session.execute(update(NotionResource).where(
                    NotionResource.parent_resource_id == resource,
                    NotionResource.user_id == user,
                ).values(parent_resource_id=None))
                session.delete(row)
                session.commit()

    def read_resource(self, user_id: str, resource_id: str) -> NotionResourceResponse:
        with self.lock:
            if (user_id, resource_id) in self.deleted_resources:
                raise HTTPException(404, "Resource not found")
            with self.sessions() as session:
                row = session.scalar(select(NotionResource).where(
                    NotionResource.id == resource_id, NotionResource.user_id == user_id,
                ))
                if row is None:
                    raise HTTPException(404, "Resource not found")
                return NotionResourceResponse.model_validate(row)

    def list_resources(self, user_id: str, connection_id: str, limit: int, offset: int) -> list[dict]:
        with self.lock:
            excluded = [resource for user, resource in self.deleted_resources if user == user_id]
            with self.sessions() as session:
                rows = session.scalars(select(NotionResource).where(
                    NotionResource.user_id == user_id, NotionResource.connection_id == connection_id,
                    NotionResource.id.not_in(excluded),
                ).order_by(NotionResource.created_at, NotionResource.id).limit(limit).offset(offset)).all()
                return [NotionResourceSummary.model_validate(row).model_dump(mode="json") for row in rows]

    def persist_legacy_resource(self, session, resource: NotionResource) -> None:
        # Deprecated synchronous registration must use the same finalization gate as async jobs.
        with self.lock:
            if (resource.user_id, resource.id) in self.deleted_resources:
                raise HTTPException(409, "Resource was deleted")
            if (resource.user_id, resource.parent_resource_id) in self.deleted_resources:
                resource.parent_resource_id = None
            else:
                validate_parent(session, resource.user_id, resource.connection_id,
                                resource.page_id, resource.parent_resource_id)
            session.add(resource)
            session.commit()

    def validate_legacy_registration(self, user_id: str, parent_resource_id: UUID | None) -> None:
        with self.lock:
            if parent_resource_id and (user_id, str(parent_resource_id)) in self.deleted_resources:
                raise HTTPException(409, "Parent resource was deleted")

    async def start(self, job_id: UUID) -> None:
        # Called as response background work: schedule execution, never await the collection here.
        task = asyncio.create_task(self.run(job_id))
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)

    async def shutdown(self) -> None:
        tasks = list(self.tasks)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    def _load(self, body: IngestionRequest) -> Document:
        with self.sessions() as session:
            connection = get_connection(session, str(body.user_id), str(body.connection_id))
            if connection is None:
                raise IngestionError(404, "CONNECTION_NOT_FOUND", "Connection not found")
            token = decrypt_token(connection.access_token_encrypted, self.settings.token_encryption_key.get_secret_value())
        client = NotionClient(self.http, token, self.settings.notion_api_version)
        return load_page(client, body.page_id)[0]

    def _finish(self, body: IngestionRequest, document: Document) -> None:
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
            with self.sessions() as session:
                identity = self._identity(body)
                if (str(body.user_id), identity[3]) in self.deleted_resources:
                    identity = (*identity[:3], None)
                else:
                    self._validate_parent(session, body)
                resource = build_resource(document, *identity, str(body.resource_id))
                session.add(resource)
                session.commit()
            job.status = "EXTRACTED"
            job.result = result
            job.status, job.resourceStatus, job.completedAt = "SUCCEEDED", "COLLECTED", now()

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
            remaining = self.deadlines[job_id] - time.monotonic()
            if remaining <= 0:
                raise TimeoutError
            document = await asyncio.wait_for(asyncio.to_thread(self._load, body), timeout=remaining)
            await asyncio.to_thread(self._finish, body, document)
        except asyncio.CancelledError:
            self._fail(job_id, "INTERNAL_ERROR", "Collection interrupted by service shutdown", True)
            raise
        except TimeoutError:
            self._fail(job_id, "INGESTION_TIMEOUT", "Collection exceeded its deadline", True)
        except NotionApiError as exc:
            self._fail(job_id, exc.code, str(exc), exc.status_code in {429, 502, 503, 504})
        except IngestionError as exc:
            self._fail(job_id, exc.code, str(exc), exc.retryable)
        except InvalidToken:
            self._fail(job_id, "INTERNAL_ERROR", "Stored credentials could not be read")
        except SQLAlchemyError:
            self._fail(job_id, "INTERNAL_ERROR", "Resource could not be stored", True)
        except Exception:
            self._fail(job_id, "INTERNAL_ERROR", "Collection failed")
