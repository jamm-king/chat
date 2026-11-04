from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, inspect, select, text
from pgvector.sqlalchemy import VECTOR
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

from app.schemas import NotionTokenResponse


class Base(DeclarativeBase):
    pass


class NotionConnection(Base):
    __tablename__ = "notion_connections"
    __table_args__ = (UniqueConstraint("user_id", "workspace_id", "bot_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    user_id: Mapped[str] = mapped_column(String(36), index=True)
    workspace_id: Mapped[str] = mapped_column(String(36))
    workspace_name: Mapped[str | None] = mapped_column(Text)
    bot_id: Mapped[str] = mapped_column(String(36))
    access_token_encrypted: Mapped[str] = mapped_column(Text)
    refresh_token_encrypted: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


class NotionResource(Base):
    __tablename__ = "notion_resources"
    __table_args__ = (UniqueConstraint("connection_id", "page_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    user_id: Mapped[str] = mapped_column(String(36), index=True)
    connection_id: Mapped[str] = mapped_column(ForeignKey("notion_connections.id"), index=True)
    page_id: Mapped[str] = mapped_column(String(36))
    parent_resource_id: Mapped[str | None] = mapped_column(ForeignKey("notion_resources.id"), index=True)
    title: Mapped[str | None] = mapped_column(Text)
    url: Mapped[str] = mapped_column(Text)
    raw_content: Mapped[str] = mapped_column(Text)
    content: Mapped[str] = mapped_column(Text)
    content_status: Mapped[str] = mapped_column(String(16))
    references: Mapped[list[dict]] = mapped_column(JSON)
    truncated: Mapped[bool] = mapped_column(Boolean)
    unknown_block_ids: Mapped[list[str]] = mapped_column(JSON)
    warnings: Mapped[list[dict]] = mapped_column(JSON)
    source_updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


class ResourceIndex(Base):
    __tablename__ = "notion_resource_indexes"

    resource_id: Mapped[str] = mapped_column(ForeignKey("notion_resources.id", ondelete="CASCADE"), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(36), index=True)
    embedding_model: Mapped[str] = mapped_column(String(100))
    dimensions: Mapped[int] = mapped_column(Integer)
    chunk_count: Mapped[int] = mapped_column(Integer)
    chunk_size: Mapped[int] = mapped_column(Integer)
    chunk_overlap: Mapped[int] = mapped_column(Integer)
    chunking_version: Mapped[str] = mapped_column(String(64))
    indexed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ResourceChunk(Base):
    __tablename__ = "notion_chunks"
    __table_args__ = (UniqueConstraint("resource_id", "sequence"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    resource_id: Mapped[str] = mapped_column(ForeignKey("notion_resources.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[str] = mapped_column(String(36), index=True)
    sequence: Mapped[int] = mapped_column(Integer)
    content: Mapped[str] = mapped_column(Text)
    source_metadata: Mapped[dict] = mapped_column(JSON)
    embedding: Mapped[list[float]] = mapped_column(VECTOR().with_variant(JSON(), "sqlite"))


def init_db(engine: Engine, enable_indexing: bool = False) -> bool:
    if engine.dialect.name == "postgresql" and enable_indexing:
        with engine.connect() as connection:
            if not connection.scalar(text("SELECT 1 FROM pg_extension WHERE extname = 'vector'")):
                raise RuntimeError("INDEXING_ENABLED requires pgvector: install it and run CREATE EXTENSION vector in the AI database")
    tables = list(Base.metadata.sorted_tables)
    if engine.dialect.name == "postgresql" and not enable_indexing:
        tables = [table for table in tables if table.name != ResourceChunk.__tablename__]
    Base.metadata.create_all(engine, tables=tables)
    return inspect(engine).has_table(ResourceChunk.__tablename__)


def get_connection(session: Session, user_id: str, connection_id: str) -> NotionConnection | None:
    return session.scalar(select(NotionConnection).where(
        NotionConnection.id == connection_id, NotionConnection.user_id == user_id
    ))


def save_connection(
    session: Session, user_id: str, token: NotionTokenResponse,
    access_token_encrypted: str, refresh_token_encrypted: str | None,
) -> NotionConnection:
    connection = session.scalar(select(NotionConnection).where(
        NotionConnection.user_id == user_id,
        NotionConnection.workspace_id == str(token.workspace_id),
        NotionConnection.bot_id == str(token.bot_id),
    ))
    if connection is None:
        connection = NotionConnection(
            user_id=user_id, workspace_id=str(token.workspace_id), bot_id=str(token.bot_id)
        )
        session.add(connection)
    connection.workspace_name = token.workspace_name
    connection.access_token_encrypted = access_token_encrypted
    connection.refresh_token_encrypted = refresh_token_encrypted
    session.commit()
    session.refresh(connection)
    return connection
