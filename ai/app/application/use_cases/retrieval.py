from dataclasses import dataclass
from typing import Callable, TypeVar
from urllib.parse import urlsplit

from app.application.ports.documents import EmbeddingClient
from app.application.ports.retrieval import RetrievalOptions, RetrievalStore
from app.application.rag_dto import SearchRequest, SearchResponse, SearchResult, SourceLocator
from app.domain.errors import RagError
from app.domain.retrieval import IndexVersion, RetrievedChunk
from app.domain.vectors import validate_vectors

T = TypeVar("T")


@dataclass(frozen=True)
class ScopeSnapshot:
    user_id: str
    versions: dict[str, IndexVersion]


@dataclass(frozen=True)
class SearchExecution:
    response: SearchResponse
    scope: ScopeSnapshot | None
    chunks: list[RetrievedChunk]


class ResourceAccess:
    def __init__(self, store: RetrievalStore, lock, deleted_resources: set[tuple[str, str]]):
        self.store, self.lock, self.deleted_resources = store, lock, deleted_resources

    def _capture(self, user_id, resource_ids):
        if any((user_id, resource) in self.deleted_resources for resource in resource_ids):
            raise RagError(404, "RESOURCE_NOT_FOUND", "Resource not found")
        versions = self.store.scope(user_id, resource_ids)
        if len(versions) != len(resource_ids):
            raise RagError(404, "RESOURCE_NOT_FOUND", "Resource not found")
        if any(version is None or version.chunk_count < 1 for version in versions.values()):
            raise RagError(409, "RESOURCE_NOT_READY", "Resource is not ready")
        return ScopeSnapshot(user_id, versions)

    def capture(self, user_id, resource_ids):
        with self.lock:
            return self._capture(user_id, resource_ids)

    def finalize(self, scope: ScopeSnapshot | None, build: Callable[[], T]) -> T:
        # The same publication gate is used by collection, indexing and deletion.
        with self.lock:
            if scope is not None:
                try:
                    current = self._capture(scope.user_id, list(scope.versions))
                except RagError:
                    raise RagError(409, "RESOURCE_SCOPE_CHANGED", "Resource scope changed") from None
                if current != scope:
                    raise RagError(409, "RESOURCE_SCOPE_CHANGED", "Resource scope changed")
            return build()


def locator(chunk: RetrievedChunk) -> SourceLocator:
    parsed = urlsplit(chunk.url)
    if len(chunk.url) > 2048 or parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise RagError(503, "AI_SERVICE_UNAVAILABLE", "Stored source URL is invalid")
    return SourceLocator(type="URL", url=chunk.url, section=chunk.section[:500] if chunk.section else None)


class SearchResources:
    def __init__(self, options: RetrievalOptions, store: RetrievalStore, access: ResourceAccess,
                 embeddings: EmbeddingClient | None):
        self.options, self.store, self.access, self.embeddings = options, store, access, embeddings

    def execute(self, request: SearchRequest, check_active=lambda: None) -> SearchExecution:
        check_active()
        if not request.resourceIds:
            return SearchExecution(SearchResponse(results=[]), None, [])
        ids = [str(value) for value in request.resourceIds]
        scope = self.access.capture(str(request.userId), ids)
        if self.embeddings is None:
            raise RagError(409, "OPERATION_NOT_AVAILABLE", "Retrieval is not configured")
        if any(version.model != self.options.embedding_model or version.dimensions != self.options.embedding_dimensions
               for version in scope.versions.values()):
            raise RagError(409, "RESOURCE_NOT_READY", "Resource embedding configuration does not match retrieval")
        vector = validate_vectors(self.embeddings.embed_documents([request.query]), 1,
                                  self.options.embedding_dimensions)[0]
        check_active()
        chunks = self.store.search(str(request.userId), ids, vector, self.options.embedding_model,
                                   self.options.embedding_dimensions, request.topK)
        check_active()
        results = [SearchResult(resourceId=chunk.resource_id, chunkId=chunk.chunk_id,
                                title=chunk.title[:500] if chunk.title else None, content=chunk.content[:8000],
                                rank=index, locator=locator(chunk))
                   for index, chunk in enumerate(chunks, 1)]
        response = SearchResponse(results=results)
        self.access.finalize(scope, lambda: None)
        return SearchExecution(response, scope, chunks)
