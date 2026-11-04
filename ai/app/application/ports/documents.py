from collections.abc import Callable
from typing import Protocol
from uuid import UUID

from app.application.dto import IngestionResult
from app.domain.documents import IndexSpecification, StoredResource, TextDocument

Identity = tuple[str, str, str, str | None]


class PipelineOptions(Protocol):
    ingestion_timeout_seconds: float
    embedding_model: str
    embedding_dimensions: int
    embedding_batch_size: int
    chunk_size: int
    chunk_overlap: int


class DocumentSource(Protocol):
    def load(self, user_id: str, connection_id: str, page_id: UUID) -> TextDocument: ...


class ResourceStore(Protocol):
    def require_connection(self, user_id: str, connection_id: str) -> None: ...
    def validate_registration(self, identity: Identity, resource_id: str, operation: str) -> None: ...
    def get(self, resource_id: str) -> StoredResource | None: ...
    def save_snapshot(self, identity: Identity, resource_id: str, document: TextDocument) -> None: ...
    def publish_index(self, user_id: str, resource_id: str, chunks: list[TextDocument],
                      vectors: list[list[float]], specification: IndexSpecification) -> IngestionResult: ...
    def delete(self, user_id: str, resource_id: str) -> None: ...
    def read(self, user_id: str, resource_id: str) -> dict: ...
    def list(self, user_id: str, connection_id: str, excluded: list[str], limit: int, offset: int) -> list[dict]: ...


class TextChunker(Protocol):
    version: str
    def split(self, document: TextDocument) -> list[TextDocument]: ...


class EmbeddingClient(Protocol):
    def embed_documents(self, texts: list[str]) -> list[list[float]]: ...


class DocumentIndexing(Protocol):
    chunking_version: str
    def chunks(self, document: TextDocument) -> list[TextDocument]: ...
    def embed(self, chunks: list[TextDocument], check_active: Callable[[], None]) -> list[list[float]]: ...
