import threading
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest

from app.domain.retrieval import EvidenceCitation, GeneratedAnswer, INSUFFICIENT_EVIDENCE_TEXT
from test_ingestions import HEADERS, ingestion_app
from test_indexing import indexed_app
from test_notion_pages import USER_ID
from test_rag import ANSWERS, FakeGenerator, rag_app, ready
from test_resource_lifecycle import delete


class FakeAutoGenerator:
    def __init__(self):
        self.route = "GENERAL"
        self.query = "독립적인 검색 질문"
        self.continuation_bytes = 0
        self.calls = []
        self.gate, self.started = threading.Event(), threading.Event()
        self.gate.set()
        self.final = FakeGenerator()
        self.repeat = False

    def generate_auto(self, prompt, search, check_active):
        self.calls.append(prompt)
        self.started.set()
        assert self.gate.wait(3)
        check_active()
        if self.route == "GENERAL":
            return self.final.generate(prompt)
        prepared = search(self.query, 5, self.continuation_bytes)
        if self.repeat:
            search(self.query, 5, self.continuation_bytes)
        if not prepared.evidence:
            return GeneratedAnswer("INSUFFICIENT_EVIDENCE", INSUFFICIENT_EVIDENCE_TEXT, [])
        check_active()
        return self.final.generate(prepared)


@pytest.fixture
def auto_app(rag_app):
    client, state, engine, query, _ = rag_app
    auto = FakeAutoGenerator()
    # The no-search decision returns a GENERAL draft even though the request was AUTO.
    auto.final.draft = GeneratedAnswer("ANSWERED", "안녕하세요.", [])
    client.app.state.answers.auto_generator = auto
    try:
        yield client, state, engine, query, auto
    finally:
        auto.gate.set()
        auto.final.gate.set()


def answer_auto(client, resources, **updates):
    return client.post(ANSWERS, headers=HEADERS, json={"userId": USER_ID, "mode": "AUTO", "message": "질문",
                                                     "history": [], "resourceIds": resources, **updates})


def use_search(auto):
    auto.route = "RESOURCE"
    auto.final.draft = None


def test_auto_direct_answer_returns_general_without_embedding(auto_app):
    client, _, _, query, auto = auto_app
    resource = ready(client)
    response = answer_auto(client, [resource], message="안녕")
    assert response.status_code == 200
    output = response.json()
    assert output["mode"] == "GENERAL" and output["status"] == "ANSWERED" and output["citations"] == []
    assert not query.calls and len(auto.calls) == 1
    assert set(output) == {"answerId", "mode", "status", "content", "citations", "context", "createdAt"}


def test_auto_search_returns_resource_and_uses_rewritten_query(auto_app):
    client, _, _, query, auto = auto_app
    resource = ready(client)
    use_search(auto)
    response = answer_auto(client, [resource], message="그 준비물은?", history=[
        {"role": "USER", "content": "프로젝트 일정이 궁금해"}, {"role": "ASSISTANT", "content": "어떤 일정인가요?"}])
    assert response.status_code == 200
    output = response.json()
    assert output["mode"] == "RESOURCE" and output["status"] == "ANSWERED"
    assert output["citations"][0]["resourceId"] == resource and "[1]" in output["content"]
    assert query.calls == [["독립적인 검색 질문"]]
    assert auto.calls[0].history[0] == ("USER", "프로젝트 일정이 궁금해")
    assert len(auto.final.calls) == 1


@pytest.mark.parametrize("route,expected", [("GENERAL", "GENERAL"), ("RESOURCE", "RESOURCE")])
def test_auto_empty_scope_still_routes_without_global_search(auto_app, route, expected):
    client, _, _, query, auto = auto_app
    if route == "RESOURCE":
        use_search(auto)
    response = answer_auto(client, [])
    assert response.status_code == 200 and response.json()["mode"] == expected
    assert not query.calls and response.json()["citations"] == []
    if route == "RESOURCE":
        assert response.json()["status"] == "INSUFFICIENT_EVIDENCE" and not auto.final.calls


def test_auto_checks_entire_scope_before_model_decision(auto_app):
    client, _, _, query, auto = auto_app
    resource = ready(client)
    assert answer_auto(client, [resource, str(uuid4())]).status_code == 404
    assert answer_auto(client, [resource], userId=str(uuid4())).status_code == 404
    # Same page already exists; use a collected resource from the original ready snapshot by removing its marker.
    from sqlalchemy.orm import Session
    from app.adapters.outbound.persistence.models import ResourceIndex
    with Session(auto_app[2]) as session:
        session.delete(session.get(ResourceIndex, resource))
        session.commit()
    response = answer_auto(client, [resource])
    assert response.status_code == 409 and response.json()["error"]["code"] == "RESOURCE_NOT_READY"
    assert not auto.calls and not query.calls


@pytest.mark.parametrize("route", ["GENERAL", "RESOURCE"])
def test_deletion_during_first_model_call_blocks_auto_response(auto_app, route):
    client, _, _, query, auto = auto_app
    resource = ready(client)
    if route == "RESOURCE":
        use_search(auto)
    auto.gate.clear()
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(answer_auto, client, [resource])
        try:
            assert auto.started.wait(2)
            assert delete(client, resource).status_code == 204
        finally:
            auto.gate.set()
        response = future.result(3)
    assert response.status_code == 409 and response.json()["error"]["code"] == "RESOURCE_SCOPE_CHANGED"
    assert not query.calls


def test_deletion_during_final_generation_blocks_auto_answer(auto_app):
    client, _, _, _, auto = auto_app
    resource = ready(client)
    use_search(auto)
    auto.final.gate.clear()
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(answer_auto, client, [resource])
        try:
            assert auto.final.started.wait(2)
            assert delete(client, resource).status_code == 204
        finally:
            auto.final.gate.set()
        response = future.result(3)
    assert response.status_code == 409 and response.json()["error"]["code"] == "RESOURCE_SCOPE_CHANGED"


def test_auto_rejects_second_search_attempt(auto_app):
    client, _, _, query, auto = auto_app
    resource = ready(client)
    use_search(auto)
    auto.repeat = True
    response = answer_auto(client, [resource])
    assert response.status_code == 502 and response.json()["error"]["code"] == "AI_PROVIDER_ERROR"
    assert len(query.calls) == 1 and not auto.final.calls


def test_auto_continuation_budget_is_checked_before_embedding(auto_app):
    client, _, _, query, auto = auto_app
    resource = ready(client)
    use_search(auto)
    auto.continuation_bytes = 64000
    response = answer_auto(client, [resource])
    assert response.status_code == 400 and response.json()["error"]["code"] == "CONTEXT_LIMIT_EXCEEDED"
    assert not query.calls and not auto.final.calls


def test_auto_applies_existing_citation_validation(auto_app):
    client, _, _, _, auto = auto_app
    resource = ready(client)
    use_search(auto)
    auto.final.draft = GeneratedAnswer("ANSWERED", "출처.[1]", [EvidenceCitation(str(uuid4()), "가짜")])
    assert answer_auto(client, [resource]).status_code == 502


def test_auto_cannot_cite_history_without_search(auto_app):
    client, _, _, query, auto = auto_app
    auto.final.draft = GeneratedAnswer("ANSWERED", "과거 출처.[1]", [])
    assert answer_auto(client, []).status_code == 502 and not query.calls


def test_auto_disabled_provider_is_explicit(auto_app):
    client, _, _, query, auto = auto_app
    client.app.state.answers.auto_generator = None
    response = answer_auto(client, [])
    assert response.status_code == 409 and response.json()["error"]["code"] == "OPERATION_NOT_AVAILABLE"
    assert not auto.calls and not query.calls


def test_auto_requires_explicit_scope_and_rejects_duplicates(auto_app):
    client, _, _, _, _ = auto_app
    missing = client.post(ANSWERS, headers=HEADERS, json={"userId": USER_ID, "mode": "AUTO", "message": "q"})
    assert missing.status_code == 400
    assert answer_auto(client, [USER_ID, USER_ID]).status_code == 400


def test_auto_injection_is_wired_by_bootstrap(auto_app):
    from fastapi.testclient import TestClient
    from app.main import create_app
    client, _, engine, query, auto = auto_app
    with TestClient(create_app(client.app.state.settings, engine=engine,
                              notion_client=client.app.state.notion_client, embedding_client=query,
                              auto_answer_generator=auto)) as restarted:
        assert answer_auto(restarted, []).json()["mode"] == "GENERAL"


def test_auto_http_uses_real_langchain_tool_loop_with_scoped_storage(auto_app):
    import json
    import httpx
    from fastapi.testclient import TestClient
    from pydantic import SecretStr
    from app.main import create_app
    from app.adapters.outbound.langchain.answers import LangChainAnswerGenerator
    from test_auto_provider import tool_payload
    from test_answer_provider import response_payload

    client, _, engine, query, _ = auto_app
    resource = ready(client)
    calls = []
    def handler(request):
        payload = json.loads(request.content)
        calls.append(payload)
        if len(calls) == 1:
            return httpx.Response(200, json=tool_payload())
        output = next(item for item in payload["input"] if item.get("type") == "function_call_output")
        chunk = json.loads(output["output"])["evidence"][0]
        return httpx.Response(200, json=response_payload([{"type": "output_text", "annotations": [], "text": json.dumps({
            "status": "ANSWERED", "content": "자료 근거.[1]",
            "citations": [{"chunkId": chunk["chunkId"], "excerpt": chunk["content"][:10]}],
        })}]))

    settings = client.app.state.settings.model_copy(update={"openai_api_key": SecretStr("test-key")})
    with httpx.Client(transport=httpx.MockTransport(handler)) as http:
        provider = LangChainAnswerGenerator(settings, http)
        with TestClient(create_app(settings, engine=engine, notion_client=client.app.state.notion_client,
                                  embedding_client=query, answer_generator=provider)) as restarted:
            response = answer_auto(restarted, [resource], message="내 자료 내용은?")
    assert response.status_code == 200 and response.json()["mode"] == "RESOURCE"
    assert response.json()["citations"][0]["resourceId"] == resource
    assert len(calls) == 2 and query.calls == [["프로젝트 준비물"]]


def test_auto_context_reports_history_used_by_either_call_and_final_truncation(auto_app):
    client, _, _, _, auto = auto_app
    resource = ready(client)
    use_search(auto)
    auto.continuation_bytes = 2000
    client.app.state.settings.answer_context_budget_bytes = 8192
    history = [{"role": role, "content": text} for role, text in [
        ("USER", "x" * 1000), ("ASSISTANT", "y" * 1000), ("USER", "recent"), ("ASSISTANT", "answer"),
    ]]
    response = answer_auto(client, [resource], history=history)
    assert response.status_code == 200
    assert response.json()["context"] == {"historyMessagesUsed": 4, "historyTruncated": True}
    assert len(auto.calls[0].history) == 4 and len(auto.final.calls[0].history) == 2


def test_auto_deadline_stops_search_after_first_model_call(auto_app, monkeypatch):
    from app.adapters.inbound.http import rag
    client, _, _, query, auto = auto_app
    resource = ready(client)
    use_search(auto)
    auto.gate.clear()
    done = threading.Event()
    original = client.app.state.answers.execute
    def execute(*args):
        try:
            return original(*args)
        finally:
            done.set()
    monkeypatch.setattr(client.app.state.answers, "execute", execute)
    monkeypatch.setattr(rag, "ANSWER_TIMEOUT_SECONDS", 0.02)
    try:
        assert answer_auto(client, [resource]).status_code == 504
    finally:
        auto.gate.set()
    assert done.wait(1) and not query.calls and not auto.final.calls
