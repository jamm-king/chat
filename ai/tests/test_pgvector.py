"""Run against a dedicated database via AI_TEST_POSTGRES_URL; no OpenAI calls."""
import os
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session

from app.db import NotionConnection, NotionResource, ResourceChunk, ResourceIndex, init_db


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
