import threading
from concurrent.futures import ThreadPoolExecutor
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.adapters.outbound.persistence.models import ResourceChunk, ResourceIndex
from app.domain.errors import EmbeddingError, RagError, StorageError
from app.domain.retrieval import EvidenceCitation, GeneratedAnswer
from test_ingestions import HEADERS, body, finished, ingestion_app, submit
from test_indexing import index, indexed_app
from test_notion_pages import USER_ID
from test_resource_lifecycle import delete

SEARCH = "/internal/v1/retrieval/search"
ANSWERS = "/internal/v1/answers"


class QueryEmbeddings:
    def __init__(self):
        self.calls = []
        self.failure = None
        self.gate, self.started = threading.Event(), threading.Event()
        self.gate.set()

    def embed_documents(self, texts):
        self.calls.append(texts)
        self.started.set()
        assert self.gate.wait(3)
        if self.failure:
            raise self.failure
        return [[1.0, 0.0, 0.0] for _ in texts]


class FakeGenerator:
    def __init__(self):
        self.calls = []
        self.draft = None
        self.failure = None
        self.gate, self.started = threading.Event(), threading.Event()
        self.gate.set()

    def generate(self, prompt):
        self.calls.append(prompt)
        self.started.set()
        assert self.gate.wait(3)
        if self.failure:
            raise self.failure
        if self.draft is not None:
            return self.draft(prompt) if callable(self.draft) else self.draft
        if prompt.mode == "GENERAL":
            return GeneratedAnswer("ANSWERED", "안녕하세요.", [])
        chunk = prompt.evidence[0]
        return GeneratedAnswer("ANSWERED", "자료의 내용입니다.[1]", [EvidenceCitation(chunk.chunk_id, chunk.content[:30])])


@pytest.fixture
def rag_app(indexed_app):
    client, state, _, _, engine = indexed_app
    query, generator = QueryEmbeddings(), FakeGenerator()
    client.app.state.retrieval.embeddings = query
    client.app.state.answers.generator = generator
    try:
        yield client, state, engine, query, generator
    finally:
        query.gate.set()
        generator.gate.set()


def ready(client):
    request = index(client)
    assert finished(client, request)["resourceStatus"] == "READY"
    return request["resourceId"]


def search(client, resources, **updates):
    return client.post(SEARCH, headers=HEADERS, json={"userId": USER_ID, "query": "준비물은?",
                                                    "resourceIds": resources, **updates})


def answer(client, resources=None, **updates):
    request = {"userId": USER_ID, "mode": "GENERAL", "message": "설명해 줘", "history": []}
    if resources is not None:
        request.update(mode="RESOURCE", resourceIds=resources)
    return client.post(ANSWERS, headers=HEADERS, json={**request, **updates})


def test_search_ranks_scoped_vectors_and_returns_provenance(rag_app):
    client, state, engine, query, _ = rag_app
    state["markdown"]["markdown"] = "첫 번째 문서 문장입니다.\n" * 30
    resource = ready(client)
    with Session(engine) as session:
        chunks = session.scalars(select(ResourceChunk).order_by(ResourceChunk.sequence)).all()
        assert len(chunks) > 2
        for chunk in chunks:
            chunk.embedding = [0.0, 1.0, 0.0]
        chunks[-1].embedding = [1.0, 0.0, 0.0]
        expected = chunks[-1].id
        session.commit()
    response = search(client, [resource], topK=2)
    assert response.status_code == 200
    results = response.json()["results"]
    assert [item["rank"] for item in results] == [1, 2]
    assert results[0]["chunkId"] == expected
    assert all(item["resourceId"] == resource for item in results)
    assert results[0]["locator"]["type"] == "URL"
    assert "score" not in results[0]
    assert response.headers["cache-control"] == "no-store"
    UUID(response.headers["x-request-id"])
    assert query.calls == [["준비물은?"]]


def test_resource_answer_citations_are_rebuilt_from_real_chunks(rag_app):
    client, _, engine, _, generator = rag_app
    resource = ready(client)
    response = answer(client, [resource])
    assert response.status_code == 200
    output = response.json()
    assert output["status"] == "ANSWERED" and "[1]" in output["content"]
    citation = output["citations"][0]
    assert citation["resourceId"] == resource and citation["citationId"] == "1"
    with Session(engine) as session:
        chunk = session.get(ResourceChunk, citation["chunkId"])
        assert citation["excerpt"] in chunk.content
    assert output["context"] == {"historyMessagesUsed": 0, "historyTruncated": False}
    assert len(generator.calls) == 1


def test_general_and_empty_resource_scopes_do_not_retrieve(rag_app):
    client, _, _, query, generator = rag_app
    assert answer(client).json()["status"] == "ANSWERED"
    assert search(client, []).json() == {"results": []}
    empty = answer(client, [], history=[{"role": "USER", "content": "전 질문"},
                                     {"role": "ASSISTANT", "content": "전 답변"}]).json()
    assert empty["status"] == "INSUFFICIENT_EVIDENCE" and empty["citations"] == []
    assert empty["context"] == {"historyMessagesUsed": 0, "historyTruncated": False}
    assert not query.calls and len(generator.calls) == 1


def test_default_model_and_rag_key_requirement(rag_app):
    from pydantic import ValidationError
    client, _, _, _, _ = rag_app
    settings = client.app.state.settings
    assert settings.answer_model == "gpt-6-luna"
    with pytest.raises(ValidationError):
        type(settings)(_env_file=None, **{**settings.model_dump(), "rag_enabled": True, "openai_api_key": None})


def test_all_resources_are_validated_before_embedding(rag_app):
    client, _, _, query, _ = rag_app
    resource = ready(client)
    assert search(client, [resource, str(uuid4())]).status_code == 404
    assert search(client, [resource], userId=str(uuid4())).status_code == 404
    assert answer(client, [resource, str(uuid4())]).status_code == 404
    assert not query.calls


def test_collected_and_model_incompatible_resources_are_not_ready(rag_app):
    client, _, engine, query, _ = rag_app
    request = body()
    submit(client, request)
    assert finished(client, request)["resourceStatus"] == "COLLECTED"
    assert search(client, [request["resourceId"]]).json()["error"]["code"] == "RESOURCE_NOT_READY"
    indexed = {**request, "jobId": str(uuid4()), "operation": "COLLECT_AND_INDEX"}
    submit(client, indexed)
    assert finished(client, indexed)["resourceStatus"] == "READY"
    with Session(engine) as session:
        session.get(ResourceIndex, request["resourceId"]).embedding_model = "different-space"
        session.commit()
    assert search(client, [request["resourceId"]]).status_code == 409
    assert not query.calls


@pytest.mark.parametrize("during", ["search", "answer"])
def test_deletion_during_external_call_rejects_stale_response(rag_app, during):
    client, _, _, query, generator = rag_app
    resource = ready(client)
    provider = query if during == "search" else generator
    provider.gate.clear()
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(search if during == "search" else answer, client, [resource])
        try:
            assert provider.started.wait(2)
            assert delete(client, resource).status_code == 204
        finally:
            provider.gate.set()
        response = future.result(3)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "RESOURCE_SCOPE_CHANGED"
    assert search(client, [resource]).status_code == 404


@pytest.mark.parametrize("draft", [
    lambda p: GeneratedAnswer("ANSWERED", "거짓 출처.[1]", [EvidenceCitation(str(uuid4()), "발췌")]),
    lambda p: GeneratedAnswer("ANSWERED", "거짓 발췌.[1]", [EvidenceCitation(p.evidence[0].chunk_id, "원문에 없는 텍스트")]),
    lambda p: GeneratedAnswer("ANSWERED", "인용 누락.", [EvidenceCitation(p.evidence[0].chunk_id, p.evidence[0].content[:5])]),
    lambda p: GeneratedAnswer("ANSWERED", "출처 누락.[1]", []),
    lambda p: GeneratedAnswer("REFUSED", "거절.[1]", []),
    lambda p: GeneratedAnswer("ANSWERED", "잘못된 번호.[01]", [EvidenceCitation(p.evidence[0].chunk_id, p.evidence[0].content[:5])]),
])
def test_invalid_provider_citations_are_errors_without_retry(rag_app, draft):
    client, _, _, _, generator = rag_app
    resource = ready(client)
    generator.draft = draft
    response = answer(client, [resource])
    assert response.status_code == 502 and response.json()["error"]["code"] == "AI_PROVIDER_ERROR"
    assert len(generator.calls) == 1


@pytest.mark.parametrize("status", ["INSUFFICIENT_EVIDENCE", "REFUSED"])
def test_non_answers_are_successful_results_with_no_citations(rag_app, status):
    client, _, _, _, generator = rag_app
    resource = ready(client)
    generator.draft = GeneratedAnswer(status, "답변을 제공할 수 없습니다.", [])
    response = answer(client, [resource])
    assert response.status_code == 200
    assert response.json()["status"] == status and response.json()["citations"] == []


def test_budget_drops_oldest_complete_history_pairs(rag_app):
    client, _, _, _, generator = rag_app
    client.app.state.settings.answer_context_budget_bytes = 8192
    history = [{"role": role, "content": text} for role, text in (
        ("USER", "old" * 700), ("ASSISTANT", "old" * 700), ("USER", "recent"), ("ASSISTANT", "recent answer"))]
    response = answer(client, history=history)
    assert response.status_code == 200
    assert response.json()["context"] == {"historyMessagesUsed": 2, "historyTruncated": True}
    assert generator.calls[0].history == [("USER", "recent"), ("ASSISTANT", "recent answer")]


def test_question_exceeding_budget_is_not_truncated_or_sent(rag_app):
    client, _, _, _, generator = rag_app
    client.app.state.settings.answer_context_budget_bytes = 8192
    response = answer(client, message="가" * 3000)
    assert response.status_code == 400 and response.json()["error"]["code"] == "CONTEXT_LIMIT_EXCEEDED"
    assert not generator.calls


def test_oversized_answer_is_truncated_and_unused_citations_are_removed(rag_app):
    client, state, _, _, generator = rag_app
    state["markdown"]["markdown"] = "서로 다른 근거를 포함한 문서 문장입니다.\n" * 40
    resource = ready(client)

    def draft(prompt):
        first, second = prompt.evidence[:2]
        content = "첫 근거입니다.[1] " + "설명 문장입니다. " * 2000 + "마지막 근거.[2]"
        return GeneratedAnswer("ANSWERED", content, [EvidenceCitation(first.chunk_id, first.content[:10]),
                                                    EvidenceCitation(second.chunk_id, second.content[:10])])
    generator.draft = draft
    output = answer(client, [resource]).json()
    assert output["status"] == "ANSWERED" and len(output["content"]) <= 16000
    assert "[1]" in output["content"] and "[2]" not in output["content"]
    assert len(output["citations"]) == 1 and output["citations"][0]["citationId"] == "1"


def test_duplicate_chunks_cannot_get_multiple_citation_ids(rag_app):
    client, _, _, _, generator = rag_app
    resource = ready(client)
    def draft(prompt):
        citation = EvidenceCitation(prompt.evidence[0].chunk_id, prompt.evidence[0].content[:5])
        return GeneratedAnswer("ANSWERED", "내용.[1] 내용.[2]", [citation, citation])
    generator.draft = draft
    assert answer(client, [resource]).status_code == 502


def test_empty_retrieval_is_insufficient_without_calling_generator(rag_app, monkeypatch):
    client, _, _, _, generator = rag_app
    resource = ready(client)
    monkeypatch.setattr(client.app.state.retrieval.store, "search", lambda *args: [])
    output = answer(client, [resource]).json()
    assert output["status"] == "INSUFFICIENT_EVIDENCE" and not generator.calls


def test_general_answers_cannot_inherit_prior_citations(rag_app):
    client, _, _, query, generator = rag_app
    generator.draft = GeneratedAnswer("ANSWERED", "과거 출처를 인용.[1]", [])
    assert answer(client).status_code == 502
    assert not query.calls


def test_failed_physical_deletion_still_excludes_resource(rag_app, monkeypatch):
    client, _, _, query, _ = rag_app
    resource = ready(client)
    def fail(*args):
        raise StorageError("private information")
    monkeypatch.setattr(client.app.state.ingestions.store, "delete", fail)
    assert delete(client, resource).status_code == 503
    assert search(client, [resource]).status_code == 404
    assert not query.calls


def test_answer_does_not_start_generation_after_request_deadline(rag_app, monkeypatch):
    from app.adapters.inbound.http import rag
    client, _, _, query, generator = rag_app
    resource = ready(client)
    done = threading.Event()
    original = client.app.state.answers.execute

    def execute(*args):
        try:
            return original(*args)
        finally:
            done.set()

    monkeypatch.setattr(client.app.state.answers, "execute", execute)
    query.gate.clear()
    monkeypatch.setattr(rag, "ANSWER_TIMEOUT_SECONDS", 0.02)
    try:
        assert answer(client, [resource]).status_code == 504
    finally:
        query.gate.set()
    assert done.wait(1)
    assert query.started.is_set() and not generator.calls


def test_provider_and_storage_failures_are_not_insufficient_evidence(rag_app, monkeypatch):
    client, _, _, query, generator = rag_app
    resource = ready(client)
    query.failure = EmbeddingError("Embedding provider request failed", True)
    response = answer(client, [resource])
    assert response.status_code == 502 and not generator.calls
    query.failure = None
    def fail(*args):
        raise StorageError("private database information")
    monkeypatch.setattr(client.app.state.retrieval.store, "search", fail)
    response = search(client, [resource])
    assert response.status_code == 503 and "private" not in response.text


def test_runtime_api_and_provider_injection_survive_restart(rag_app):
    from fastapi.testclient import TestClient
    from app.main import create_app
    client, _, engine, query, generator = rag_app
    resource = ready(client)
    with TestClient(create_app(client.app.state.settings, engine=engine,
                              notion_client=client.app.state.notion_client,
                              embedding_client=query, answer_generator=generator)) as restarted:
        assert search(restarted, [resource]).status_code == 200
        assert answer(restarted, [resource]).status_code == 200
        paths = restarted.get("/openapi.json").json()["paths"]
        assert SEARCH in paths and ANSWERS in paths


@pytest.mark.parametrize("path,payload", [
    (SEARCH, {"userId": USER_ID, "query": " " , "resourceIds": []}),
    (SEARCH, {"userId": USER_ID, "query": "q"}),
    (SEARCH, {"userId": USER_ID, "query": "q", "resourceIds": [], "topK": 21}),
    (SEARCH, {"userId": USER_ID, "query": "q", "resourceIds": [USER_ID, USER_ID.upper()]}),
    (ANSWERS, {"userId": USER_ID, "mode": "GENERAL", "message": "q", "resourceIds": []}),
    (ANSWERS, {"userId": USER_ID, "mode": "RESOURCE", "message": "q"}),
    (ANSWERS, {"userId": USER_ID, "mode": "GENERAL", "message": "q", "history": [{"role": "SYSTEM", "content": "x"}]}),
    (ANSWERS, {"userId": USER_ID, "mode": "GENERAL", "message": "q", "history": [{"role": "USER", "content": "x"}]}),
])
def test_rag_request_validation_uses_internal_error_envelope(rag_app, path, payload):
    client, _, _, _, _ = rag_app
    response = client.post(path, headers=HEADERS, json=payload)
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_REQUEST" and "requestId" in response.json()


def test_auth_and_internal_request_rules_cover_new_routes(rag_app):
    client, _, _, _, _ = rag_app
    for path, payload in [(SEARCH, {"userId": USER_ID, "query": "q", "resourceIds": []}),
                          (ANSWERS, {"userId": USER_ID, "mode": "GENERAL", "message": "q"})]:
        assert client.post(path, json=payload).status_code == 401
        assert client.post(path + "?userId=" + USER_ID, headers=HEADERS, json=payload).status_code == 400
        assert client.post(path, headers={**HEADERS, "X-Request-Id": "invalid"}, json=payload).status_code == 400


@pytest.mark.parametrize("route", ["search", "answer"])
def test_http_deadline_returns_timeout_without_retry(rag_app, monkeypatch, route):
    from app.adapters.inbound.http import rag
    client, _, _, query, generator = rag_app
    resource = ready(client)
    provider = query if route == "search" else generator
    provider.gate.clear()
    monkeypatch.setattr(rag, "SEARCH_TIMEOUT_SECONDS" if route == "search" else "ANSWER_TIMEOUT_SECONDS", 0.02)
    try:
        response = search(client, [resource]) if route == "search" else answer(client, [resource])
        assert response.status_code == 504
    finally:
        provider.gate.set()
