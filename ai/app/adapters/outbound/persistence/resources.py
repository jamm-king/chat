from functools import wraps

from sqlalchemy import delete, select, update
from sqlalchemy.exc import SQLAlchemyError

from app.application.dto import IngestionResult
from app.domain.documents import StoredResource, TextDocument
from app.domain.errors import IngestionError, IndexingError, ResourceError, StorageError
from app.adapters.outbound.persistence.models import (
    NotionResource, ResourceChunk, ResourceIndex, get_connection,
)
from app.adapters.outbound.persistence.mapping import build_resource, validate_parent


def storage_operation(method):
    @wraps(method)
    def wrapped(*args, **kwargs):
        try:
            return method(*args, **kwargs)
        except SQLAlchemyError:
            raise StorageError("Resource could not be stored") from None
    return wrapped


class SqlAlchemyResourceStore:
    def __init__(self, sessions):
        self.sessions = sessions
        self.vector_storage_available = False

    @staticmethod
    def _validate_parent(session, identity):
        try:
            validate_parent(session, *identity)
        except ResourceError as exc:
            code = "RESOURCE_NOT_FOUND" if exc.status == 404 else "INVALID_PARENT_REFERENCE"
            raise IngestionError(404 if exc.status == 404 else 409, code, str(exc)) from None

    @storage_operation
    def require_connection(self, user_id, connection_id):
        with self.sessions() as session:
            if get_connection(session, user_id, connection_id) is None:
                raise IngestionError(404, "CONNECTION_NOT_FOUND", "Connection not found")

    @storage_operation
    def validate_registration(self, identity, resource_id, operation):
        user, connection, page, parent = identity
        with self.sessions() as session:
            existing = session.get(NotionResource, resource_id)
            if existing is not None:
                if (existing.user_id, existing.connection_id, existing.page_id, existing.parent_resource_id) != identity:
                    raise IngestionError(409, "RESOURCE_ID_CONFLICT", "Resource ID has a different source")
                if session.get(ResourceIndex, resource_id) is not None:
                    raise IngestionError(409, "RESOURCE_ALREADY_INDEXED", "Resource is already indexed")
                if operation == "COLLECT":
                    raise IngestionError(409, "RESOURCE_ALREADY_COLLECTED", "Resource is already collected")
            if session.scalar(select(NotionResource.id).where(
                NotionResource.connection_id == connection, NotionResource.page_id == page,
                NotionResource.id != resource_id,
            )) is not None:
                raise IngestionError(409, "RESOURCE_ALREADY_COLLECTED", "Page is already collected")
            self._validate_parent(session, identity)

    @storage_operation
    def get(self, resource_id):
        with self.sessions() as session:
            row = session.get(NotionResource, resource_id)
            if row is None:
                return None
            return StoredResource(
                (row.user_id, row.connection_id, row.page_id, row.parent_resource_id),
                TextDocument(row.content, {
                    "title": row.title, "source": row.url, "page_id": row.page_id,
                    "content_status": row.content_status, "raw_content": row.raw_content,
                    "references": row.references, "truncated": row.truncated,
                    "unknown_block_ids": row.unknown_block_ids, "warnings": row.warnings,
                    "last_edited_time": row.source_updated_at.isoformat(),
                    "collected_at": row.collected_at.isoformat(),
                }),
            )

    @storage_operation
    def save_snapshot(self, identity, resource_id, document):
        with self.sessions() as session:
            self._validate_parent(session, identity)
            if session.get(NotionResource, resource_id) is None:
                session.add(build_resource(document, *identity, resource_id))
            session.commit()

    @storage_operation
    def publish_index(self, user_id, resource_id, chunks, vectors, specification):
        # This is one atomic operation: vectors and the completion marker commit together.
        with self.sessions() as session:
            resource = session.get(NotionResource, resource_id)
            if resource is None or resource.user_id != user_id:
                raise IndexingError("RESOURCE_DELETED", "Resource no longer exists")
            for chunk, vector in zip(chunks, vectors, strict=True):
                session.add(ResourceChunk(
                    resource_id=resource_id, user_id=user_id, sequence=chunk.metadata["sequence"],
                    content=chunk.page_content, source_metadata=chunk.metadata, embedding=vector,
                ))
            session.add(ResourceIndex(
                resource_id=resource_id, user_id=user_id, embedding_model=specification.model,
                dimensions=specification.dimensions, chunk_count=len(chunks),
                chunk_size=specification.chunk_size, chunk_overlap=specification.chunk_overlap,
                chunking_version=specification.chunking_version, indexed_at=specification.indexed_at,
            ))
            session.commit()
            return IngestionResult(
                title=resource.title[:500] if resource.title else None, canonicalUrl=resource.url,
                contentStatus="complete", referenceCount=len(resource.references), ready=True,
                chunkCount=len(chunks), indexedAt=specification.indexed_at,
            )

    @storage_operation
    def delete(self, user_id, resource_id):
        with self.sessions() as session:
            row = session.scalar(select(NotionResource).where(
                NotionResource.id == resource_id, NotionResource.user_id == user_id,
            ))
            if row is None:
                return
            session.execute(update(NotionResource).where(
                NotionResource.parent_resource_id == resource_id, NotionResource.user_id == user_id,
            ).values(parent_resource_id=None))
            if self.vector_storage_available:
                session.execute(delete(ResourceChunk).where(
                    ResourceChunk.resource_id == resource_id, ResourceChunk.user_id == user_id,
                ))
            session.execute(delete(ResourceIndex).where(
                ResourceIndex.resource_id == resource_id, ResourceIndex.user_id == user_id,
            ))
            session.delete(row)
            session.commit()

    @staticmethod
    def _view(row, index):
        result = {column.name: getattr(row, column.name) for column in NotionResource.__table__.columns}
        if index is not None:
            result.update(resource_status="READY", chunk_count=index.chunk_count, indexed_at=index.indexed_at,
                          embedding_model=index.embedding_model, embedding_dimensions=index.dimensions)
        return result

    @storage_operation
    def read(self, user_id, resource_id):
        with self.sessions() as session:
            row = session.scalar(select(NotionResource).where(
                NotionResource.id == resource_id, NotionResource.user_id == user_id,
            ))
            if row is None:
                raise ResourceError(404, "Resource not found")
            return self._view(row, session.get(ResourceIndex, resource_id))

    @storage_operation
    def list(self, user_id, connection_id, excluded, limit, offset):
        with self.sessions() as session:
            rows = session.scalars(select(NotionResource).where(
                NotionResource.user_id == user_id, NotionResource.connection_id == connection_id,
                NotionResource.id.not_in(excluded),
            ).order_by(NotionResource.created_at, NotionResource.id).limit(limit).offset(offset)).all()
            indexes = {index.resource_id: index for index in session.scalars(select(ResourceIndex).where(
                ResourceIndex.user_id == user_id, ResourceIndex.resource_id.in_([row.id for row in rows]),
            ))}
            return [self._view(row, indexes.get(row.id)) for row in rows]
