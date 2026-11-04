import threading
import time
from concurrent.futures import ThreadPoolExecutor
from uuid import UUID, uuid4

import httpx
import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.config import Settings
from app.db import NotionConnection, NotionResource
from app.main import create_app
from app.notion_auth import encrypt_token
from test_notion_pages import CONNECTION_ID, MARKDOWN, PAGE_ID, USER_ID, markdown_data, page_data

HEADERS = {"Authorization": "Bearer test-service-token-long-enough"}
PATH = "/internal/v1/ingestions"


@pytest.fixture
def ingestion_app(tmp_path):
    settings = Settings(
        _env_file=None, database_url="sqlite://", ai_service_token="test-service-token-long-enough",
        notion_client_id="client", notion_client_secret="secret",
        notion_redirect_uri="http://localhost:8001/integrations/notion/callback",
        token_encryption_key=Fernet.generate_key().decode(), ingestion_timeout_seconds=2,
    )
    engine = create_engine(f"sqlite:///{(tmp_path / 'resources.db').as_posix()}",
                           connect_args={"check_same_thread": False})
    gate, started = threading.Event(), threading.Event()
    gate.set()
    state = {"status": 200, "markdown": markdown_data(), "page": page_data()}
    calls = []

    def handler(request):
        calls.append(request)
        started.set()
        assert gate.wait(3), "Test did not release its simulated upstream"
        if state.get("timeout"):
            raise httpx.ReadTimeout("private-notion-token", request=request)
        if state["status"] != 200:
            return httpx.Response(state["status"], json={"message": "private-notion-token"})
        return httpx.Response(200, json=state["markdown"] if request.url.path.endswith("/markdown") else state["page"])

    with httpx.Client(transport=httpx.MockTransport(handler)) as upstream:
        app = create_app(settings, engine=engine, notion_client=upstream)
        with TestClient(app) as client:
            with Session(engine) as session:
                session.add(NotionConnection(
                    id=CONNECTION_ID, user_id=USER_ID, workspace_id=str(uuid4()), bot_id=str(uuid4()),
                    access_token_encrypted=encrypt_token("private-notion-token", settings.token_encryption_key.get_secret_value()),
                ))
                session.commit()
            try:
                yield client, state, calls, gate, started, engine
            finally:
                gate.set()
    engine.dispose()


def body(**updates):
    return {"jobId": str(uuid4()), "userId": USER_ID, "resourceId": str(uuid4()),
            "connectionId": CONNECTION_ID, "pageId": PAGE_ID, "operation": "COLLECT", **updates}


def submit(client, request, **kwargs):
    return client.post(PATH, headers=HEADERS, json=request, **kwargs)


def poll(client, request):
    return client.get(f'{PATH}/{request["jobId"]}', params={"userId": request["userId"]}, headers=HEADERS)


def finished(client, request):
    deadline = time.monotonic() + 4
    while time.monotonic() < deadline:
        response = poll(client, request)
        assert response.status_code == 200
        if response.json()["status"] in {"SUCCEEDED", "FAILED", "CANCELLED"}:
            return response.json()
        time.sleep(0.01)
    pytest.fail("Job failed to terminate")


def test_acceptance_returns_before_upstream_finishes(ingestion_app):
    client, _, calls, gate, started, engine = ingestion_app
    gate.clear()
    request = body()
    response = submit(client, request)
    assert response.status_code == 202
    assert response.json()["status"] == "QUEUED"
    assert response.json()["resourceStatus"] == "PROCESSING"
    assert response.headers["Retry-After"] == "2"
    assert response.headers["Location"].startswith(f'{PATH}/{request["jobId"]}')
    assert started.wait(1)
    assert poll(client, request).json()["status"] == "EXTRACTING"
    with Session(engine) as session:
        assert session.scalar(select(NotionResource)) is None
    gate.set()
    result = finished(client, request)
    assert result["status"] == "SUCCEEDED" and result["resourceStatus"] == "COLLECTED"
    assert result["result"]["ready"] is False and result["result"]["chunkCount"] == 0
    assert result["result"]["indexedAt"] is None
    assert result["startedAt"] and result["completedAt"] and result["error"] is None
    with Session(engine) as session:
        resource = session.get(NotionResource, request["resourceId"])
        assert resource.raw_content == MARKDOWN
    assert len(calls) == 2
    stored = client.get(f'/integrations/notion/resources/{request["resourceId"]}',
                        params={"userId": USER_ID}, headers=HEADERS)
    assert stored.status_code == 200
    assert stored.json()["id"] == request["resourceId"]
    assert "Retry-After" not in poll(client, request).headers


def test_idempotency_and_active_claims(ingestion_app):
    client, _, calls, gate, _, _ = ingestion_app
    gate.clear()
    request = body()
    assert submit(client, request).status_code == 202
    equivalent = {**request, "parentResourceId": None, "jobId": request["jobId"].upper()}
    assert submit(client, equivalent).status_code == 200
    conflicting = {**request, "resourceId": str(uuid4())}
    assert submit(client, conflicting).json()["error"]["code"] == "JOB_ID_CONFLICT"
    for change in [{"jobId": str(uuid4())}, {"jobId": str(uuid4()), "resourceId": str(uuid4())}]:
        response = submit(client, {**request, **change})
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "INGESTION_IN_PROGRESS"
    gate.set()
    assert finished(client, request)["status"] == "SUCCEEDED"
    assert submit(client, request).status_code == 200
    assert submit(client, {**request, "jobId": str(uuid4())}).json()["error"]["code"] == "RESOURCE_ALREADY_COLLECTED"
    assert len(calls) == 2


def test_concurrent_admission_reserves_resource_once(ingestion_app):
    client, _, calls, gate, _, _ = ingestion_app
    gate.clear()
    request = body()
    other = {**request, "jobId": str(uuid4())}
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda data: submit(client, data), [request, other]))
    assert sorted(response.status_code for response in responses) == [202, 409]
    accepted = next(response.json() for response in responses if response.status_code == 202)
    gate.set()
    assert finished(client, {**request, "jobId": accepted["jobId"]})["status"] == "SUCCEEDED"
    assert len(calls) == 2


@pytest.mark.parametrize("provider,code", [(401, "NOTION_REAUTHORIZATION_REQUIRED"),
    (403, "NOTION_ACCESS_DENIED"), (404, "NOTION_PAGE_NOT_FOUND"),
    (429, "NOTION_RATE_LIMITED"), (500, "NOTION_UNAVAILABLE")])
def test_provider_errors_become_failed_jobs(ingestion_app, provider, code):
    client, state, calls, _, _, engine = ingestion_app
    state["status"] = provider
    request = body()
    assert submit(client, request).status_code == 202
    job = finished(client, request)
    assert job["status"] == "FAILED" and job["resourceStatus"] == "FAILED"
    assert job["error"]["code"] == code and job["result"] is None
    assert "private-notion-token" not in str(job)
    assert len(calls) == 1
    with Session(engine) as session:
        assert session.scalar(select(NotionResource)) is None


def test_retry_uses_new_job_and_preserves_source_identity(ingestion_app):
    client, state, _, _, _, _ = ingestion_app
    state["timeout"] = True
    request = body()
    submit(client, request)
    assert finished(client, request)["error"]["code"] == "NOTION_TIMEOUT"
    invalid = {**request, "jobId": str(uuid4()), "pageId": str(uuid4())}
    assert submit(client, invalid).json()["error"]["code"] == "RESOURCE_ID_CONFLICT"
    state["timeout"] = False
    retry = {**request, "jobId": str(uuid4())}
    assert submit(client, retry).status_code == 202
    assert finished(client, retry)["status"] == "SUCCEEDED"


def test_deadline_prevents_late_fetch_from_saving(ingestion_app, monkeypatch):
    client, _, _, gate, started, engine = ingestion_app
    import app.ingestion as ingestion
    done = threading.Event()
    original = ingestion.load_page

    def load(*args):
        try:
            return original(*args)
        finally:
            done.set()

    monkeypatch.setattr(ingestion, "load_page", load)
    client.app.state.settings.ingestion_timeout_seconds = 0.05
    gate.clear()
    request = body()
    assert submit(client, request).status_code == 202
    assert started.wait(1)
    assert finished(client, request)["error"]["code"] == "INGESTION_TIMEOUT"
    gate.set()
    assert done.wait(2)
    with Session(engine) as session:
        assert session.scalar(select(NotionResource)) is None
    assert poll(client, request).json()["status"] == "FAILED"


def test_user_scope_and_admission_errors(ingestion_app):
    client, _, calls, gate, _, _ = ingestion_app
    request = body()
    assert client.post(PATH, json=request).status_code == 401
    assert submit(client, {**request, "userId": str(uuid4())}).status_code == 404
    assert submit(client, {**request, "operation": "COLLECT_AND_INDEX"}).json()["error"]["code"] == "OPERATION_NOT_AVAILABLE"
    assert not calls
    gate.clear()
    submit(client, request)
    stranger = {**request, "userId": str(uuid4())}
    assert poll(client, stranger).status_code == 404
    assert submit(client, stranger).json()["error"]["code"] == "JOB_NOT_FOUND"
    gate.set()
    finished(client, request)


def test_selected_reference_registration_and_parent_validation(ingestion_app):
    client, state, calls, _, _, engine = ingestion_app
    child_page = str(uuid4())
    state["markdown"]["markdown"] = f'<page url="https://www.notion.so/{child_page}">Child</page>'
    parent = body()
    submit(client, parent)
    assert finished(client, parent)["result"]["contentStatus"] == "complete"
    assert len(calls) == 2
    child = body(pageId=child_page, parentResourceId=parent["resourceId"])
    invalid = {**child, "pageId": str(uuid4())}
    assert submit(client, invalid).json()["error"]["code"] == "INVALID_PARENT_REFERENCE"
    assert len(calls) == 2
    state["page"]["id"] = state["markdown"]["id"] = child_page
    state["markdown"]["markdown"] = "Child content"
    assert submit(client, child).status_code == 202
    assert finished(client, child)["status"] == "SUCCEEDED"
    with Session(engine) as session:
        assert session.get(NotionResource, child["resourceId"]).parent_resource_id == parent["resourceId"]
    assert len(calls) == 4


def test_partial_body_can_be_collected(ingestion_app):
    client, state, _, _, _, _ = ingestion_app
    state["markdown"]["truncated"] = True
    request = body()
    submit(client, request)
    result = finished(client, request)
    assert result["resourceStatus"] == "COLLECTED"
    assert result["result"]["contentStatus"] == "partial"


def test_restart_loses_jobs_but_preserves_documents(ingestion_app):
    client, _, _, _, _, engine = ingestion_app
    request = body()
    submit(client, request)
    finished(client, request)
    with TestClient(create_app(client.app.state.settings, engine=engine,
                               notion_client=client.app.state.notion_client)) as restarted:
        assert poll(restarted, request).json()["error"]["code"] == "JOB_NOT_FOUND"
        response = restarted.get(f'/integrations/notion/resources/{request["resourceId"]}',
                                 params={"userId": USER_ID}, headers=HEADERS)
        assert response.status_code == 200 and response.json()["content"] == MARKDOWN


def test_request_validation_and_headers(ingestion_app):
    client, _, calls, _, _, _ = ingestion_app
    for invalid in [body(unexpected=True), body(pageId="bad"), {"userId": USER_ID}]:
        response = submit(client, invalid)
        assert response.status_code == 400
        assert response.json()["error"]["code"] == "INVALID_REQUEST"
        assert response.headers["Cache-Control"] == "no-store"
        assert UUID(response.headers["X-Request-Id"])
    request_id = str(uuid4())
    response = client.post(PATH, json=body(operation="COLLECT_AND_INDEX"),
                           headers={**HEADERS, "X-Request-Id": request_id})
    assert response.headers["X-Request-Id"] == request_id
    assert response.json()["requestId"] == request_id
    assert client.post(PATH, json=body(), headers={**HEADERS, "X-Request-Id": "bad"}).status_code == 400
    assert client.post(PATH, content=b"x" * (256 * 1024 + 1), headers=HEADERS).status_code == 413
    assert client.post(PATH, content=b"{}", headers={**HEADERS, "Content-Type": "text/plain"}).status_code == 415
    assert submit(client, body(), params={"userId": USER_ID}).status_code == 400
    assert not calls
