import math

from sqlalchemy import and_, select

from app.adapters.outbound.persistence.models import NotionResource, ResourceChunk, ResourceIndex
from app.adapters.outbound.persistence.resources import storage_operation
from app.domain.errors import StorageError
from app.domain.retrieval import IndexVersion, RetrievedChunk


class SqlAlchemyRetrievalStore:
    def __init__(self, sessions):
        self.sessions = sessions

    @storage_operation
    def scope(self, user_id, resource_ids):
        with self.sessions() as session:
            rows = session.execute(select(NotionResource.id, ResourceIndex).outerjoin(
                ResourceIndex, and_(ResourceIndex.resource_id == NotionResource.id,
                                    ResourceIndex.user_id == user_id),
            ).where(NotionResource.user_id == user_id, NotionResource.id.in_(resource_ids)))
            return {resource: IndexVersion(index.embedding_model, index.dimensions, index.indexed_at, index.chunk_count)
                    if index is not None else None for resource, index in rows}

    @storage_operation
    def search(self, user_id, resource_ids, vector, model, dimensions, top_k):
        with self.sessions() as session:
            statement = select(ResourceChunk, NotionResource).join(
                NotionResource, ResourceChunk.resource_id == NotionResource.id,
            ).join(ResourceIndex, ResourceIndex.resource_id == NotionResource.id).where(
                ResourceChunk.user_id == user_id, NotionResource.user_id == user_id,
                ResourceIndex.user_id == user_id, NotionResource.id.in_(resource_ids),
                ResourceIndex.embedding_model == model, ResourceIndex.dimensions == dimensions,
            )
            if session.bind.dialect.name == "postgresql":
                rows = session.execute(statement.order_by(
                    ResourceChunk.embedding.cosine_distance(vector), ResourceChunk.resource_id,
                    ResourceChunk.sequence, ResourceChunk.id,
                ).limit(top_k)).all()
            else:
                # SQLite JSON storage is for local automated tests; production uses pgvector SQL.
                rows = session.execute(statement).all()

                def distance(row):
                    values = row[0].embedding
                    if len(values) != dimensions or not all(math.isfinite(value) for value in values):
                        raise StorageError("Stored vector is invalid")
                    denominator = math.hypot(*values) * math.hypot(*vector)
                    if denominator == 0:
                        raise StorageError("Stored vector is invalid")
                    return 1 - sum(a * b for a, b in zip(values, vector, strict=True)) / denominator

                rows.sort(key=lambda row: (distance(row), row[0].resource_id, row[0].sequence, row[0].id))
                rows = rows[:top_k]
            return [RetrievedChunk(resource.id, chunk.id, resource.title, chunk.content, resource.url,
                                   chunk.source_metadata.get("section")) for chunk, resource in rows]
