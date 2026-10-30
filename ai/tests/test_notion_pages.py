import json
from uuid import UUID, uuid4

import httpx
import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.config import Settings
from app.db import NotionConnection
from app.loader import load_page
from app.main import create_app
from app.notion_auth import encrypt_token
from app.notion_client import NotionApiError, NotionClient

USER_ID, CONNECTION_ID, PAGE_ID = str(uuid4()), str(uuid4()), str(uuid4())
UNKNOWN_ID = str(uuid4())
HEADERS = {"Authorization": "Bearer test-service-token-long-enough"}
BASE = f"/integrations/notion/connections/{CONNECTION_ID}/pages"
MARKDOWN = "# 회의록\n\n| 항목 | 값 |\n| --- | --- |\n| 출시 | 11월 |\n\n<details><summary>상세</summary>중첩 본문</details>"


def page_data(**updates):
    return {
        "object": "page", "id": PAGE_ID, "url": "https://www.notion.so/example",
        "properties": {"이름": {"type": "title", "title": [{"plain_text": "회의록"}]}},
        "last_edited_time": "2026-10-30T01:00:00Z", **updates,
    }


def markdown_data(**updates):
    return {"object": "page_markdown", "id": PAGE_ID, "markdown": MARKDOWN,
            "truncated": False, "unknown_block_ids": [], **updates}


@pytest.fixture
def page_app():
    settings = Settings(
        _env_file=None, database_url="sqlite://", ai_service_token="test-service-token-long-enough",
        notion_client_id="test-client", notion_client_secret="secret",
        notion_redirect_uri="http://localhost:8001/integrations/notion/callback",
        token_encryption_key=Fernet.generate_key().decode(),
    )
    calls = []
    state = {"page": page_data(), "markdown": markdown_data(), "status": 200}

    def handler(request):
        calls.append(request)
        assert request.headers["Authorization"] == "Bearer private-notion-token"
        assert request.headers["Notion-Version"] == "2026-03-11"
        if state.get("timeout"):
            raise httpx.ReadTimeout("private-notion-token", request=request)
        if state["status"] != 200:
            return httpx.Response(state["status"], json={"message": "private-notion-token"},
                                  headers={"Retry-After": "5"})
        if state.get("invalid_json"):
            return httpx.Response(200, text="private-notion-token")
        if request.url.path.endswith("/search"):
            payload = {"object": "list", "results": [state["page"]],
                       "has_more": False, "next_cursor": None}
            payload.update(state.get("search", {}))
        elif request.url.path.endswith("/markdown"):
            payload = state["markdown"]
        else:
            payload = state["page"]
        return httpx.Response(200, json=payload)

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    with httpx.Client(transport=httpx.MockTransport(handler)) as upstream:
        app = create_app(settings, engine=engine, notion_client=upstream)
        with TestClient(app) as client:
            with Session(engine) as session:
                session.add(NotionConnection(
                    id=CONNECTION_ID, user_id=USER_ID, workspace_id=str(uuid4()), bot_id=str(uuid4()),
                    access_token_encrypted=encrypt_token("private-notion-token", settings.token_encryption_key.get_secret_value()),
                ))
                session.commit()
            yield client, state, calls
    engine.dispose()


def fetch(client, path=None, **params):
    return client.get(path or f"{BASE}/{PAGE_ID}", headers=HEADERS,
                      params={"userId": USER_ID, **params})


def test_title_search_and_cursor_pagination(page_app):
    client, state, calls = page_app
    state["search"] = {"has_more": True, "next_cursor": "next-page"}
    response = fetch(client, BASE, query="회의", pageSize=1)
    assert response.status_code == 200
    assert response.json()["results"][0]["title"] == "회의록"
    assert response.json()["next_cursor"] == "next-page"
    payload = json.loads(calls[0].content)
    assert payload["filter"] == {"property": "object", "value": "page"}
    assert payload["query"] == "회의" and payload["page_size"] == 1
    state["search"] = {"has_more": False, "next_cursor": None, "results": []}
    response = fetch(client, BASE, startCursor="next-page")
    assert response.json()["results"] == []
    assert json.loads(calls[1].content)["start_cursor"] == "next-page"
    assert "private-notion-token" not in response.text


def test_selected_page_preserves_markdown_and_metadata(page_app):
    client, _, calls = page_app
    response = fetch(client)
    assert response.status_code == 200
    assert response.json() == {
        "id": PAGE_ID, "title": "회의록", "url": "https://www.notion.so/example",
        "last_edited_time": "2026-10-30T01:00:00Z", "content": MARKDOWN,
        "content_status": "complete", "truncated": False, "unknown_block_ids": [], "warnings": [],
    }
    assert response.headers["Cache-Control"] == "no-store"
    assert [request.method for request in calls] == ["GET", "GET"]


@pytest.mark.parametrize("updates", [
    {"truncated": True, "unknown_block_ids": [UNKNOWN_ID]},
    {"markdown": '<unknown url="https://www.notion.so/block"/>'},
    {"warnings": [{"code": "unsupported", "message": "Some content is unsupported"}]},
])
def test_incomplete_content_is_reported(page_app, updates):
    client, state, _ = page_app
    state["markdown"].update(updates)
    response = fetch(client)
    assert response.status_code == 200
    assert response.json()["content_status"] == "partial"
    for field in ["truncated", "unknown_block_ids", "warnings"]:
        if field in updates:
            assert response.json()[field] == updates[field]


def test_empty_page_is_a_valid_empty_document(page_app):
    client, state, _ = page_app
    state["markdown"]["markdown"] = ""
    response = fetch(client)
    assert response.status_code == 200
    assert response.json()["content"] == ""


@pytest.mark.parametrize("path", [BASE, f"{BASE}/{PAGE_ID}"])
def test_foreign_connection_is_not_accessible(page_app, path):
    client, _, calls = page_app
    response = fetch(client, path, userId=str(uuid4()))
    assert response.status_code == 404
    assert not calls


@pytest.mark.parametrize("path", [BASE, f"{BASE}/{PAGE_ID}"])
def test_service_auth_required(page_app, path):
    client, _, calls = page_app
    assert client.get(path, params={"userId": USER_ID}).status_code == 401
    assert not calls


@pytest.mark.parametrize("status,expected,code", [
    (401, 409, "NOTION_REAUTHORIZATION_REQUIRED"), (403, 403, "NOTION_ACCESS_DENIED"),
    (404, 404, "NOTION_PAGE_NOT_FOUND"), (429, 429, "NOTION_RATE_LIMITED"),
    (500, 502, "NOTION_UNAVAILABLE"), (529, 503, "NOTION_OVERLOADED"),
])
def test_provider_errors_are_sanitized_without_retry(page_app, status, expected, code):
    client, state, calls = page_app
    state["status"] = status
    response = fetch(client)
    assert response.status_code == expected
    assert response.json()["error"]["code"] == code
    assert "private-notion-token" not in response.text
    assert len(calls) == 1
    if status in (429, 529):
        assert response.headers["Retry-After"] == "5"


def test_timeout_is_returned_without_retry(page_app):
    client, state, calls = page_app
    state["timeout"] = True
    response = fetch(client)
    assert response.status_code == 504 and len(calls) == 1
    assert "private-notion-token" not in response.text


@pytest.mark.parametrize("mode", ["invalid_json", "missing_markdown", "wrong_id", "missing_cursor"])
def test_invalid_provider_responses_fail_explicitly(page_app, mode):
    client, state, _ = page_app
    path = None
    if mode == "invalid_json":
        state["invalid_json"] = True
    elif mode == "missing_markdown":
        del state["markdown"]["markdown"]
    elif mode == "wrong_id":
        state["markdown"]["id"] = str(uuid4())
    else:
        state["search"] = {"has_more": True, "next_cursor": None}
        path = BASE
    response = fetch(client, path)
    assert response.status_code == 502
    assert response.json()["error"]["code"] == "NOTION_INVALID_RESPONSE"


def test_archived_page_not_read(page_app):
    client, state, calls = page_app
    state["page"]["archived"] = True
    assert fetch(client).status_code == 404
    assert len(calls) == 1
    assert fetch(client, BASE).json()["results"] == []


@pytest.mark.parametrize("params", [{"pageSize": 0}, {"pageSize": 101}, {"startCursor": ""}])
def test_search_input_validation(page_app, params):
    client, _, calls = page_app
    assert fetch(client, BASE, **params).status_code == 422
    assert not calls


def test_loader_produces_langchain_document():
    def handler(request):
        return httpx.Response(200, json=markdown_data() if request.url.path.endswith("/markdown") else page_data())

    with httpx.Client(transport=httpx.MockTransport(handler)) as http:
        document = load_page(NotionClient(http, "token", "2026-03-11"), UUID(PAGE_ID))[0]
    assert document.page_content == MARKDOWN
    assert document.metadata["source"] == "https://www.notion.so/example"
    assert document.metadata["page_id"] == PAGE_ID
    assert document.metadata["collected_at"]


@pytest.mark.parametrize("repeat_cursor", [False, True])
def test_block_children_pagination(repeat_cursor):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json={
            "object": "list", "results": [{"id": str(len(calls)), "type": "paragraph"}],
            "has_more": len(calls) == 1 or repeat_cursor,
            "next_cursor": "cursor" if len(calls) == 1 or repeat_cursor else None,
        })

    with httpx.Client(transport=httpx.MockTransport(handler)) as http:
        client = NotionClient(http, "token", "2026-03-11")
        if repeat_cursor:
            with pytest.raises(NotionApiError):
                list(client.iter_block_children(UUID(PAGE_ID)))
        else:
            assert len(list(client.iter_block_children(UUID(PAGE_ID)))) == 2
    assert len(calls) == 2
    assert calls[1].url.params["start_cursor"] == "cursor"
