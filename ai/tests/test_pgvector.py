"""Run against a dedicated database via AI_TEST_POSTGRES_URL; no OpenAI calls."""
import os
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session

from app.adapters.outbound.persistence.models import NotionConnection, NotionResource, ResourceChunk, ResourceIndex, init_db
from app.adapters.outbound.persistence.resources import SqlAlchemyResourceStore
from app.domain.documents import IndexSpecification, TextDocument
from sqlalchemy.orm import sessionmaker


@pytest.mark.skipif(not os.getenv("AI_TEST_POSTGRES_URL"), reason="Dedicated pgvector database not configured")
def test_pgvector_storage_transaction_and_deletion():
    engine = create_engine(os.environ["AI_TEST_POSTGRES_URL"], hide_parameters=True)
    user, connection, resource = (str(uuid4()) for _ in range(3))
    now = datetime.now(timezone.utc)
    try:
        assert engine.dialect.name == "postgresql"
        assert init_db(engine, True)
        with Session(engine) as session:
            assert session.scalar(text("SELECT extversion FROM pg_extension WHERE extname = 'vector'"))
            session.add(NotionConnection(id=connection, user_id=user, workspace_id=str(uuid4()),
                                        bot_id=str(uuid4()), access_token_encrypted="test"))
            session.flush()
            session.add(NotionResource(
                id=resource, user_id=user, connection_id=connection, page_id=str(uuid4()),
                url="https://example.com", raw_content="test", content="test", content_status="complete",
                references=[], truncated=False, unknown_block_ids=[], warnings=[],
                source_updated_at=now, collected_at=now,
            ))
            session.commit()

            def add_index():
                session.add(ResourceChunk(resource_id=resource, user_id=user, sequence=0, content="test",
                                          source_metadata={"source": "https://example.com"},
                                          embedding=[1.0, 0.5, 0.25]))
                session.add(ResourceIndex(resource_id=resource, user_id=user, embedding_model="test",
                                          dimensions=3, chunk_count=1, chunk_size=1000, chunk_overlap=150,
                                          chunking_version="test", indexed_at=now))

            try:
                add_index()
                session.flush()
                session.rollback()
                assert session.get(ResourceIndex, resource) is None
                assert session.scalar(select(ResourceChunk).where(ResourceChunk.resource_id == resource)) is None
                add_index()
                session.commit()
                session.expire_all()
                chunk = session.scalar(select(ResourceChunk).where(ResourceChunk.resource_id == resource))
                assert list(chunk.embedding) == [1.0, 0.5, 0.25]
                assert session.scalar(text("SELECT pg_typeof(embedding)::text FROM notion_chunks WHERE resource_id = :id"),
                                      {"id": resource}) == "vector"
                session.delete(session.get(NotionResource, resource))
                session.commit()
                session.expire_all()
                assert session.get(ResourceIndex, resource) is None
                assert session.scalar(select(ResourceChunk).where(ResourceChunk.resource_id == resource)) is None
            finally:
                session.rollback()
                if row := session.get(NotionResource, resource):
                    session.delete(row)
                    session.flush()
                session.delete(session.get(NotionConnection, connection))
                session.commit()
    finally:
        engine.dispose()


@pytest.mark.skipif(not os.getenv("AI_TEST_POSTGRES_URL"), reason="Dedicated pgvector database not configured")
def test_resource_store_port_on_postgres():
    engine = create_engine(os.environ["AI_TEST_POSTGRES_URL"], hide_parameters=True)
    sessions = sessionmaker(engine, expire_on_commit=False)
    user, connection, resource, page = (str(uuid4()) for _ in range(4))
    now = datetime.now(timezone.utc)
    store = SqlAlchemyResourceStore(sessions)
    try:
        store.vector_storage_available = init_db(engine, True)
        with sessions() as session:
            session.add(NotionConnection(id=connection, user_id=user, workspace_id=str(uuid4()),
                                        bot_id=str(uuid4()), access_token_encrypted="test"))
            session.commit()
        identity = (user, connection, page, None)
        document = TextDocument("Example", {
            "title": "Example", "source": "https://example.com", "page_id": page,
            "content_status": "complete", "raw_content": "Example", "references": [],
            "truncated": False, "unknown_block_ids": [], "warnings": [],
            "last_edited_time": now.isoformat(), "collected_at": now.isoformat(),
        })
        store.require_connection(user, connection)
        store.validate_registration(identity, resource, "COLLECT_AND_INDEX")
        store.save_snapshot(identity, resource, document)
        assert store.get(resource).document.page_content == "Example"
        chunk = TextDocument("Example", {"sequence": 0, "source": "https://example.com"})
        specification = IndexSpecification("test", 3, 80, 16, "test-v1", now)
        result = store.publish_index(user, resource, [chunk], [[1.0, 0.5, 0.25]], specification)
        assert result.ready and result.chunkCount == 1
        assert store.read(user, resource)["resource_status"] == "READY"
        assert store.list(user, connection, [], 10, 0)[0]["id"] == resource
        assert store.list(user, connection, [resource], 10, 0) == []
        store.delete(user, resource)
        assert store.get(resource) is None
        with sessions() as session:
            assert session.get(ResourceIndex, resource) is None
            assert session.scalar(select(ResourceChunk).where(ResourceChunk.resource_id == resource)) is None
    finally:
        store.delete(user, resource)
        with sessions() as session:
            if row := session.get(NotionConnection, connection):
                session.delete(row)
                session.commit()
        engine.dispose()
