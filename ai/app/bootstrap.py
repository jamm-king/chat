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
from app.application.ports.retrieval import AnswerGenerator, AutoAnswerGenerator
from app.application.use_cases.indexing import DocumentIndexer
from app.application.use_cases.ingestion import IngestionManager
from app.application.use_cases.retrieval import ResourceAccess, SearchResources
from app.application.use_cases.answers import GenerateAnswer
from app.adapters.outbound.langchain.embeddings import OpenAIEmbeddingClient
from app.adapters.outbound.langchain.answers import LangChainAnswerGenerator
from app.adapters.outbound.langchain.chunking import LangChainTextChunker
from app.adapters.outbound.notion.auth import OAuthStateStore
from app.adapters.outbound.notion.source import NotionDocumentSource
from app.adapters.outbound.persistence.models import init_db
from app.adapters.outbound.persistence.resources import SqlAlchemyResourceStore
from app.adapters.outbound.persistence.retrieval import SqlAlchemyRetrievalStore
from app.adapters.outbound.runtime.asyncio_executor import AsyncioJobExecutor
from app.adapters.inbound.http.api import create_http_app


def create_app(settings: Settings | None = None, *, engine: Engine | None = None,
               notion_client: httpx.Client | None = None,
               embedding_client: EmbeddingClient | None = None,
               answer_generator: AnswerGenerator | None = None,
               auto_answer_generator: AutoAnswerGenerator | None = None) -> FastAPI:
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
        embedding_http, answer_http, manager = None, None, None
        try:
            embedder = embedding_client
            if (config.indexing_enabled or config.rag_enabled) and embedder is None:
                embedding_http = httpx.Client(timeout=config.embedding_timeout_seconds,
                                             transport=httpx.HTTPTransport(retries=0), follow_redirects=False)
                embedder = OpenAIEmbeddingClient(config, embedding_http)
            indexer = None
            if embedder is not None and (config.indexing_enabled or embedding_client is not None):
                indexer = DocumentIndexer(
                    config, embedder, LangChainTextChunker(config.chunk_size, config.chunk_overlap),
                )
            store = SqlAlchemyResourceStore(app.state.sessions)
            manager = IngestionManager(
                config, store, NotionDocumentSource(app.state.sessions, client,
                    config.token_encryption_key.get_secret_value(), config.notion_api_version),
                AsyncioJobExecutor(), indexer,
            )
            app.state.ingestions = manager
            retrieval_store = SqlAlchemyRetrievalStore(app.state.sessions)
            access = ResourceAccess(retrieval_store, manager.lock, manager.deleted_resources)
            app.state.retrieval = SearchResources(
                config, retrieval_store, access, embedder if config.rag_enabled or embedding_client is not None else None,
            )
            generator = answer_generator
            if config.rag_enabled and generator is None:
                answer_http = httpx.Client(timeout=config.answer_provider_timeout_seconds,
                                          transport=httpx.HTTPTransport(retries=0), follow_redirects=False)
                generator = LangChainAnswerGenerator(config, answer_http)
            auto_generator = auto_answer_generator
            if auto_generator is None and isinstance(generator, LangChainAnswerGenerator):
                auto_generator = generator
            app.state.answers = GenerateAnswer(config, app.state.retrieval, generator, auto_generator)
            store.vector_storage_available = await run_in_threadpool(init_db, db_engine,
                                                                      indexer is not None or config.rag_enabled)
            yield
        finally:
            if manager is not None:
                await manager.shutdown()
            if answer_http is not None:
                answer_http.close()
            if embedding_http is not None:
                embedding_http.close()
            if notion_client is None:
                client.close()
            if engine is None:
                db_engine.dispose()

    return create_http_app(lifespan)
