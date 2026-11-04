"""Composition root: concrete adapters, settings and owned client lifetimes."""
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker
from starlette.concurrency import run_in_threadpool

from app.config import Settings
from app.application.ports.documents import EmbeddingClient
from app.application.use_cases.indexing import DocumentIndexer
from app.application.use_cases.ingestion import IngestionManager
from app.adapters.outbound.langchain.embeddings import OpenAIEmbeddingClient
from app.adapters.outbound.langchain.chunking import LangChainTextChunker
from app.adapters.outbound.notion.auth import OAuthStateStore
from app.adapters.outbound.notion.source import NotionDocumentSource
from app.adapters.outbound.persistence.models import init_db
from app.adapters.outbound.persistence.resources import SqlAlchemyResourceStore
from app.adapters.outbound.runtime.asyncio_executor import AsyncioJobExecutor
from app.adapters.inbound.http.api import create_http_app


def create_app(settings: Settings | None = None, *, engine: Engine | None = None,
               notion_client: httpx.Client | None = None,
               embedding_client: EmbeddingClient | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        config = settings or Settings()
        db_engine = engine if engine is not None else create_engine(
            config.database_url.get_secret_value(), hide_parameters=True
        )
        client = notion_client if notion_client is not None else httpx.Client(
            timeout=config.notion_timeout_seconds, follow_redirects=False,
            transport=httpx.HTTPTransport(retries=0),
        )
        app.state.settings = config
        app.state.sessions = sessionmaker(db_engine, expire_on_commit=False)
        app.state.oauth_states = OAuthStateStore()
        app.state.notion_client = client
        embedding_http = None
        embedder = embedding_client
        if config.indexing_enabled and embedder is None:
            embedding_http = httpx.Client(timeout=config.embedding_timeout_seconds,
                                           transport=httpx.HTTPTransport(retries=0), follow_redirects=False)
            embedder = OpenAIEmbeddingClient(config, embedding_http)
        indexer = None
        if embedder is not None:
            indexer = DocumentIndexer(
                config, embedder, LangChainTextChunker(config.chunk_size, config.chunk_overlap),
            )
        store = SqlAlchemyResourceStore(app.state.sessions)
        app.state.ingestions = IngestionManager(
            config, store, NotionDocumentSource(app.state.sessions, client,
                config.token_encryption_key.get_secret_value(), config.notion_api_version),
            AsyncioJobExecutor(), indexer,
        )
        try:
            store.vector_storage_available = await run_in_threadpool(init_db, db_engine, indexer is not None)
            yield
        finally:
            await app.state.ingestions.shutdown()
            if embedding_http is not None:
                embedding_http.close()
            if notion_client is None:
                client.close()
            if engine is None:
                db_engine.dispose()

    return create_http_app(lifespan)
