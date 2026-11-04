import ast
import asyncio
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.application.dto import IngestionRequest, IngestionResult
from app.application.use_cases.ingestion import IngestionManager
from app.application.use_cases.indexing import DocumentIndexer
from app.domain.documents import StoredResource, TextDocument
from app.domain.errors import EmbeddingError, SourceError, StorageError


def test_dependency_direction():
    root = Path(__file__).parents[1] / "app"
    forbidden = {"fastapi", "starlette", "sqlalchemy", "langchain_core", "langchain_openai",
                 "langchain_text_splitters", "httpx", "cryptography", "openai", "pgvector", "pydantic_settings"}
    for layer in ("domain", "application"):
        for path in (root / layer).rglob("*.py"):
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                modules = [node.module or ""] if isinstance(node, ast.ImportFrom) else (
                    [item.name for item in node.names] if isinstance(node, ast.Import) else [])
                for module in modules:
                    assert module.split(".")[0] not in forbidden, (path, module)
                    assert not module.startswith(("app.adapters", "app.bootstrap", "app.config", "app.main")), (path, module)
                    if layer == "domain":
                        assert not module.startswith("app.application"), (path, module)
    for path in (root / "adapters" / "outbound").rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.ImportFrom):
                assert not (node.module or "").startswith("app.adapters.inbound"), path


class InlineExecutor:
    async def call(self, function, *args, timeout=None):
        return function(*args)


class MemoryStore:
    def __init__(self):
        self.documents, self.indexes = {}, {}
        self.failure = None

    def require_connection(self, *_):
        pass

    def validate_registration(self, *_):
        pass

    def get(self, resource_id):
        return self.documents.get(resource_id)

    def save_snapshot(self, identity, resource_id, document):
        self.documents[resource_id] = StoredResource(identity, document)

    def publish_index(self, user_id, resource_id, chunks, vectors, specification):
        if self.failure:
            raise self.failure
        self.indexes[resource_id] = (chunks, vectors, specification)
        return IngestionResult(title="Example", canonicalUrl="https://example.com", contentStatus="complete",
                               referenceCount=0, ready=True, chunkCount=len(chunks), indexedAt=specification.indexed_at)

    def delete(self, user_id, resource_id):
        self.documents.pop(resource_id, None)
        self.indexes.pop(resource_id, None)


class FakeSource:
    def __init__(self):
        self.calls = 0
        self.failure = None

    def load(self, *_):
        self.calls += 1
        if self.failure:
            raise self.failure
        return TextDocument("Example text", {"title": "Example", "source": "https://example.com",
                                            "content_status": "complete", "references": []})


class FakeChunker:
    version = "test-v1"

    def split(self, document):
        return [TextDocument(document.page_content, {**document.metadata, "start_index": 0})]


class FakeEmbeddings:
    def __init__(self):
        self.failure = None

    def embed_documents(self, texts):
        if self.failure:
            raise self.failure
        return [[1.0, 0.5, 0.25] for _ in texts]


def pipeline():
    options = SimpleNamespace(ingestion_timeout_seconds=10, embedding_model="test", embedding_dimensions=3,
                              embedding_batch_size=2, chunk_size=80, chunk_overlap=16)
    store, source, embeddings = MemoryStore(), FakeSource(), FakeEmbeddings()
    manager = IngestionManager(options, store, source, InlineExecutor(),
                               DocumentIndexer(options, embeddings, FakeChunker()))
    request = IngestionRequest(jobId=uuid4(), userId=uuid4(), resourceId=uuid4(), connectionId=uuid4(),
                               pageId=uuid4(), operation="COLLECT_AND_INDEX")
    return manager, request, store, source, embeddings


def execute(manager, request):
    manager.submit(request)
    asyncio.run(manager.run(request.job_id))
    return manager.get(request.job_id, request.user_id)


def test_use_cases_collect_index_and_delete_without_external_adapters():
    manager, request, store, source, _ = pipeline()
    job = execute(manager, request)
    assert job.status == "SUCCEEDED" and job.resourceStatus == "READY" and job.result.ready
    chunks, vectors, specification = store.indexes[str(request.resource_id)]
    assert chunks[0].metadata["sequence"] == 0
    assert vectors == [[1.0, 0.5, 0.25]] and specification.chunking_version == "test-v1"
    assert source.calls == 1
    manager.delete(request.resource_id, request.user_id)
    assert not store.documents and not store.indexes


def test_collected_snapshot_can_be_indexed_without_fetching_again():
    manager, request, store, source, _ = pipeline()
    collected = request.model_copy(update={"operation": "COLLECT"})
    assert execute(manager, collected).resourceStatus == "COLLECTED"
    request = request.model_copy(update={"job_id": uuid4()})
    assert execute(manager, request).resourceStatus == "READY"
    assert source.calls == 1


@pytest.mark.parametrize("component,failure,code", [
    ("source", SourceError("NOTION_ACCESS_DENIED", "Access denied"), "NOTION_ACCESS_DENIED"),
    ("embeddings", EmbeddingError("Provider failed", True), "EMBEDDING_FAILED"),
    ("store", StorageError("Storage failed"), "INDEX_WRITE_FAILED"),
])
def test_port_failures_become_job_errors(component, failure, code):
    manager, request, store, source, embeddings = pipeline()
    {"source": source, "embeddings": embeddings, "store": store}[component].failure = failure
    job = execute(manager, request)
    assert job.status == "FAILED" and job.error.code == code
    assert not store.indexes
    if component != "source":
        assert str(request.resource_id) in store.documents
