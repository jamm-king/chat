import threading
from uuid import uuid4

import httpx
import pytest
from langchain_core.documents import Document
from pydantic import SecretStr, ValidationError
from sqlalchemy import select
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from sqlalchemy.schema import CreateTable

from app.db import NotionResource, ResourceChunk, ResourceIndex
from app.embeddings import EmbeddingError, OpenAIEmbeddingClient
from app.indexing import DocumentIndexer
from test_ingestions import HEADERS, body, finished, ingestion_app, poll, submit
from test_notion_pages import USER_ID
from test_resource_lifecycle import delete, read


class FakeEmbeddings:
    def __init__(self):
        self.calls = []
        self.gate, self.started, self.done = threading.Event(), threading.Event(), threading.Event()
        self.gate.set()
        self.fail = False
        self.invalid = False

    def embed_documents(self, texts):
        self.calls.append(texts)
        self.started.set()
        try:
            assert self.gate.wait(3)
            if self.fail:
                raise EmbeddingError("Embedding provider request failed", True)
            if self.invalid:
                return [[1.0]] * len(texts)
            return [[1.0, 0.5, 0.25] for _ in texts]
        finally:
            self.done.set()


@pytest.fixture
def indexed_app(ingestion_app):
    client, state, calls, gate, started, engine = ingestion_app
    settings = client.app.state.settings
    settings.embedding_dimensions, settings.embedding_batch_size = 3, 2
    settings.chunk_size, settings.chunk_overlap = 80, 16
    settings.ingestion_timeout_seconds = 2
    embeddings = FakeEmbeddings()
    client.app.state.ingestions.indexer = DocumentIndexer(settings, embeddings)
    try:
        yield client, state, calls, embeddings, engine
    finally:
        embeddings.gate.set()


def index(client, **updates):
    request = body(operation="COLLECT_AND_INDEX", **updates)
    assert submit(client, request).status_code == 202
    return request


def assert_unpublished(engine, resource_id):
    with Session(engine) as session:
        assert session.get(ResourceIndex, resource_id) is None
        assert session.scalars(select(ResourceChunk).where(ResourceChunk.resource_id == resource_id)).all() == []


def test_full_collection_and_index_publishes_vectors_atomically(indexed_app):
    client, state, calls, embeddings, engine = indexed_app
    text = "## 준비물\n\n- [x] 노트북\n- [ ] 충전기\n\n" * 12
    state["markdown"]["markdown"] = text
    embeddings.gate.clear()
    request = index(client)
    assert embeddings.started.wait(1)
    assert poll(client, request).json()["status"] == "INDEXING"
    assert_unpublished(engine, request["resourceId"])
    assert read(client, request["resourceId"]).json()["resource_status"] == "COLLECTED"
    embeddings.gate.set()
    result = finished(client, request)
    assert result["status"] == "SUCCEEDED" and result["resourceStatus"] == "READY"
    assert result["result"]["ready"] and result["result"]["indexedAt"]
    with Session(engine) as session:
        marker = session.get(ResourceIndex, request["resourceId"])
        chunks = session.scalars(select(ResourceChunk).order_by(ResourceChunk.sequence)).all()
        assert marker.chunk_count == result["result"]["chunkCount"] == len(chunks)
        assert marker.dimensions == 3 and marker.embedding_model == "text-embedding-3-small"
        assert [chunk.sequence for chunk in chunks] == list(range(len(chunks)))
        assert all(chunk.user_id == USER_ID and chunk.resource_id == request["resourceId"] for chunk in chunks)
        assert all(len(chunk.embedding) == 3 for chunk in chunks)
        assert all("raw_content" not in chunk.source_metadata for chunk in chunks)
        assert all(len(chunk.content) <= 80 for chunk in chunks)
        assert session.get(NotionResource, request["resourceId"]).raw_content == text
    snapshot = read(client, request["resourceId"]).json()
    assert snapshot["resource_status"] == "READY" and snapshot["chunk_count"] == len(chunks)
    assert snapshot["embedding_dimensions"] == 3
    assert len(calls) == 2 and len(embeddings.calls) > 1


def test_collected_snapshot_is_promoted_without_notion_refetch(indexed_app):
    client, state, calls, _, engine = indexed_app
    first = body()
    submit(client, first)
    assert finished(client, first)["resourceStatus"] == "COLLECTED"
    original = read(client, first["resourceId"]).json()["content"]
    state["status"] = 403
    request = {**first, "jobId": str(uuid4()), "operation": "COLLECT_AND_INDEX"}
    assert submit(client, request).status_code == 202
    assert finished(client, request)["resourceStatus"] == "READY"
    assert len(calls) == 2
    assert read(client, first["resourceId"]).json()["content"] == original
    assert submit(client, {**request, "jobId": str(uuid4())}).json()["error"]["code"] == "RESOURCE_ALREADY_INDEXED"
    with Session(engine) as session:
        assert len(session.scalars(select(ResourceIndex)).all()) == 1


@pytest.mark.parametrize("partial", [True, False])
def test_partial_or_empty_content_is_not_indexed(indexed_app, partial):
    client, state, _, embeddings, engine = indexed_app
    state["markdown"].update({"truncated": partial, "markdown": "Some text" if partial else "\n  "})
    request = index(client)
    result = finished(client, request)
    assert result["status"] == "FAILED"
    assert result["error"]["code"] == ("CONTENT_INCOMPLETE" if partial else "EMPTY_CONTENT")
    assert not embeddings.calls
    assert_unpublished(engine, request["resourceId"])
    assert read(client, request["resourceId"]).status_code == 200


@pytest.mark.parametrize("invalid", [False, True])
def test_embedding_failure_keeps_snapshot_and_can_retry(indexed_app, invalid):
    client, _, calls, embeddings, engine = indexed_app
    embeddings.invalid, embeddings.fail = invalid, not invalid
    request = index(client)
    assert finished(client, request)["error"]["code"] == "EMBEDDING_FAILED"
    assert_unpublished(engine, request["resourceId"])
    assert read(client, request["resourceId"]).json()["resource_status"] == "COLLECTED"
    embeddings.invalid = embeddings.fail = False
    retry = {**request, "jobId": str(uuid4())}
    assert submit(client, retry).status_code == 202
    assert finished(client, retry)["resourceStatus"] == "READY"
    assert len(calls) == 2


def test_index_write_failure_rolls_back_all_chunks(indexed_app, monkeypatch):
    client, _, _, embeddings, engine = indexed_app
    commit = Session.commit

    def fail_marker(session):
        if any(isinstance(row, ResourceIndex) for row in session.new):
            session.flush()
            raise SQLAlchemyError("private database information")
        return commit(session)

    monkeypatch.setattr(Session, "commit", fail_marker)
    request = index(client)
    result = finished(client, request)
    assert result["error"]["code"] == "INDEX_WRITE_FAILED"
    assert "private" not in str(result)
    assert embeddings.calls
    assert_unpublished(engine, request["resourceId"])


def test_deletion_during_embedding_prevents_late_publication(indexed_app):
    client, _, _, embeddings, engine = indexed_app
    embeddings.gate.clear()
    request = index(client)
    assert embeddings.started.wait(1)
    assert delete(client, request["resourceId"]).status_code == 204
    assert poll(client, request).json()["status"] == "CANCELLED"
    embeddings.gate.set()
    assert embeddings.done.wait(1)
    assert_unpublished(engine, request["resourceId"])
    assert read(client, request["resourceId"]).status_code == 404


def test_completed_index_is_deleted_with_snapshot(indexed_app):
    client, _, _, _, engine = indexed_app
    request = index(client)
    assert finished(client, request)["resourceStatus"] == "READY"
    assert delete(client, request["resourceId"]).status_code == 204
    assert_unpublished(engine, request["resourceId"])
    assert read(client, request["resourceId"]).status_code == 404


def test_embedding_deadline_never_publishes_late_vectors(indexed_app):
    client, _, _, embeddings, engine = indexed_app
    client.app.state.settings.ingestion_timeout_seconds = 0.05
    embeddings.gate.clear()
    request = index(client)
    assert embeddings.started.wait(1)
    assert finished(client, request)["error"]["code"] == "INGESTION_TIMEOUT"
    embeddings.gate.set()
    assert embeddings.done.wait(1)
    assert_unpublished(engine, request["resourceId"])


def test_chunking_preserves_text_and_offsets(indexed_app):
    client, _, _, _, _ = indexed_app
    indexer = client.app.state.ingestions.indexer
    text = "## 안내\n\n" + "한국어 문장과 목록을 유지합니다.\n" * 20
    document = Document(page_content=text, metadata={"content_status": "complete", "source": "https://example.com", "page_id": "source-id"})
    chunks = indexer.chunks(document)
    assert len(chunks) > 1
    for chunk in chunks:
        start = chunk.metadata["start_index"]
        assert text[start:start + len(chunk.page_content)] == chunk.page_content
        assert chunk.metadata["source"] == "https://example.com"
    sql = str(CreateTable(ResourceChunk.__table__).compile(dialect=postgresql.dialect()))
    assert "embedding VECTOR" in sql


def test_openai_adapter_preserves_batch_order_and_uses_float_format(indexed_app):
    client, _, _, _, _ = indexed_app
    settings = client.app.state.settings.model_copy(update={"openai_api_key": SecretStr("secret-key")})
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json={"data": [
            {"index": 1, "embedding": [0, 1, 0]}, {"index": 0, "embedding": [1, 0, 0]},
        ]})

    with httpx.Client(transport=httpx.MockTransport(handler)) as http:
        result = OpenAIEmbeddingClient(settings, http).embed_documents(["first", "second"])
    assert result == [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]]
    assert calls[0].url == "https://api.openai.com/v1/embeddings"
    assert calls[0].headers["Authorization"] == "Bearer secret-key"
    assert b'"encoding_format":"float"' in calls[0].content


@pytest.mark.parametrize("payload", [
    {"data": [{"index": 0, "embedding": [1]}]},
    {"data": [{"index": 0, "embedding": [0, 0, 0]}]},
    {"data": [{"index": 0, "embedding": [True, 0, 0]}]},
    {"data": [{"index": 0, "embedding": [float('inf'), 0, 0]}]},
    {"data": [{"index": 1, "embedding": [1, 0, 0]}]},
    {"data": []},
])
def test_invalid_embedding_responses_are_rejected(indexed_app, payload):
    client, _, _, _, _ = indexed_app
    settings = client.app.state.settings.model_copy(update={"openai_api_key": SecretStr("secret-key")})
    def handler(request):
        if payload["data"] and any(value == float('inf') for value in payload['data'][0]['embedding']):
            return httpx.Response(200, content=b'{"data":[{"index":0,"embedding":[Infinity,0,0]}]}')
        return httpx.Response(200, json=payload)
    with httpx.Client(transport=httpx.MockTransport(handler)) as http:
        with pytest.raises(EmbeddingError):
            OpenAIEmbeddingClient(settings, http).embed_documents(["text"])


def test_configuration_bounds(indexed_app):
    client, _, _, _, _ = indexed_app
    settings = client.app.state.settings
    data = settings.model_dump()
    for updates in [{"chunk_overlap": 1000}, {"indexing_enabled": True, "openai_api_key": None},
                    {"embedding_dimensions": 2000}, {"chunk_size": 3000}]:
        with pytest.raises(ValidationError):
            type(settings)(_env_file=None, **{**data, **updates})


@pytest.mark.parametrize("status,retryable", [(400, False), (401, False), (429, True), (500, True)])
def test_openai_failures_are_sanitized_without_retry(indexed_app, status, retryable):
    client, _, _, _, _ = indexed_app
    settings = client.app.state.settings.model_copy(update={"openai_api_key": SecretStr("secret-key")})
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(status, json={"error": {"message": "secret-key private body"}})
    with httpx.Client(transport=httpx.MockTransport(handler)) as http:
        with pytest.raises(EmbeddingError) as error:
            OpenAIEmbeddingClient(settings, http).embed_documents(["text"])
    assert error.value.retryable is retryable
    assert "secret-key" not in str(error.value)
    assert len(calls) == 1


def test_embedding_injection_and_ready_marker_survive_restart(indexed_app):
    client, _, calls, embeddings, engine = indexed_app
    from fastapi.testclient import TestClient
    from app.main import create_app
    with TestClient(create_app(client.app.state.settings, engine=engine,
                               notion_client=client.app.state.notion_client,
                               embedding_client=embeddings)) as restarted:
        request = index(restarted)
        assert finished(restarted, request)["resourceStatus"] == "READY"
    with TestClient(create_app(client.app.state.settings, engine=engine,
                               notion_client=client.app.state.notion_client)) as restarted:
        assert read(restarted, request["resourceId"]).json()["resource_status"] == "READY"
        assert poll(restarted, request).status_code == 404
        assert delete(restarted, request["resourceId"]).status_code == 204
    assert_unpublished(engine, request["resourceId"])
    assert len(calls) == 2


def test_detached_child_can_be_promoted_after_parent_deletion(indexed_app):
    client, state, _, _, _ = indexed_app
    child_page = str(uuid4())
    state["markdown"]["markdown"] = f'<page url="https://www.notion.so/{child_page}">Child</page>'
    parent = body()
    submit(client, parent)
    assert finished(client, parent)["resourceStatus"] == "COLLECTED"
    state["page"]["id"] = state["markdown"]["id"] = child_page
    state["markdown"]["markdown"] = "Child text"
    child = body(pageId=child_page, parentResourceId=parent["resourceId"])
    submit(client, child)
    assert finished(client, child)["resourceStatus"] == "COLLECTED"
    assert delete(client, parent["resourceId"]).status_code == 204
    request = {**child, "jobId": str(uuid4()), "parentResourceId": None, "operation": "COLLECT_AND_INDEX"}
    assert submit(client, request).status_code == 202
    assert finished(client, request)["resourceStatus"] == "READY"
