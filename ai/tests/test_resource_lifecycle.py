import asyncio
import threading
from concurrent.futures import ThreadPoolExecutor
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.adapters.outbound.persistence.models import NotionResource
from app.main import create_app
from test_ingestions import HEADERS, body, finished, ingestion_app, poll, submit
from test_notion_pages import CONNECTION_ID, PAGE_ID, USER_ID


def delete(client, resource_id, user_id=USER_ID, **kwargs):
    return client.delete(f"/internal/v1/resources/{resource_id}",
                         params={"userId": user_id}, headers=HEADERS, **kwargs)


def read(client, resource_id, user_id=USER_ID):
    return client.get(f"/integrations/notion/resources/{resource_id}",
                      params={"userId": user_id}, headers=HEADERS)


def listing(client):
    return client.get(f"/integrations/notion/connections/{CONNECTION_ID}/resources",
                      params={"userId": USER_ID}, headers=HEADERS)


def collect(client, request=None):
    request = request or body()
    assert submit(client, request).status_code == 202
    assert finished(client, request)["status"] == "SUCCEEDED"
    return request


def test_delete_removes_snapshot_and_is_idempotent(ingestion_app):
    client, _, calls, _, _, engine = ingestion_app
    request = collect(client)
    assert len(listing(client).json()) == 1
    before = poll(client, request).json()
    response = delete(client, request["resourceId"])
    assert response.status_code == 204 and response.content == b""
    assert response.headers["Cache-Control"] == "no-store"
    assert UUID(response.headers["X-Request-Id"])
    assert read(client, request["resourceId"]).status_code == 404
    assert listing(client).json() == []
    assert delete(client, request["resourceId"]).status_code == 204
    assert delete(client, str(uuid4())).status_code == 204
    with Session(engine) as session:
        assert session.get(NotionResource, request["resourceId"]) is None
    # Completed job results are historical, not a way to revive the resource.
    assert poll(client, request).json() == before
    assert submit(client, request).json()["error"]["code"] == "RESOURCE_DELETED"
    assert submit(client, {**request, "jobId": str(uuid4())}).json()["error"]["code"] == "RESOURCE_DELETED"
    # Explicitly registering the source again needs a new Backend resource ID.
    replacement = collect(client)
    assert replacement["resourceId"] != request["resourceId"]
    assert len(calls) == 4


def test_foreign_delete_does_not_change_owner_data_or_job(ingestion_app):
    client, _, calls, gate, started, _ = ingestion_app
    gate.clear()
    request = body()
    submit(client, request)
    assert started.wait(1)
    assert delete(client, request["resourceId"], str(uuid4())).status_code == 204
    assert poll(client, request).json()["status"] == "EXTRACTING"
    gate.set()
    assert finished(client, request)["status"] == "SUCCEEDED"
    assert delete(client, request["resourceId"], str(uuid4())).status_code == 204
    assert read(client, request["resourceId"]).status_code == 200
    assert len(calls) == 2


@pytest.mark.parametrize("provider_status", [200, 500])
def test_delete_during_fetch_cancels_and_prevents_late_save(ingestion_app, monkeypatch, provider_status):
    client, state, _, gate, started, engine = ingestion_app
    import app.adapters.outbound.notion.source as ingestion
    load_done = threading.Event()
    original = ingestion.load_page

    def load(*args):
        try:
            return original(*args)
        finally:
            load_done.set()

    monkeypatch.setattr(ingestion, "load_page", load)
    gate.clear()
    request = body()
    submit(client, request)
    assert started.wait(1)
    state["status"] = provider_status
    assert delete(client, request["resourceId"]).status_code == 204
    job = poll(client, request).json()
    assert job["status"] == "CANCELLED" and job["resourceStatus"] == "DELETED"
    assert job["error"]["code"] == "RESOURCE_DELETED" and not job["error"]["retryable"]
    assert job["result"] is None
    gate.set()
    assert load_done.wait(2)
    with Session(engine) as session:
        assert session.get(NotionResource, request["resourceId"]) is None
    assert poll(client, request).json() == job
    assert submit(client, request).json()["status"] == "CANCELLED"


def test_queued_job_does_not_start_after_deletion(ingestion_app, monkeypatch):
    client, _, calls, _, _, _ = ingestion_app
    manager = client.app.state.ingestions
    start_gate, done = threading.Event(), threading.Event()
    original = manager.run

    async def delayed(job_id):
        try:
            await asyncio.to_thread(start_gate.wait, 3)
            await original(job_id)
        finally:
            done.set()

    monkeypatch.setattr(manager, "run", delayed)
    request = body()
    submit(client, request)
    try:
        assert poll(client, request).json()["status"] == "QUEUED"
        assert delete(client, request["resourceId"]).status_code == 204
    finally:
        start_gate.set()
    assert done.wait(2)
    assert poll(client, request).json()["status"] == "CANCELLED"
    assert not calls


def test_delete_after_commit_wins_without_recreating_data(ingestion_app, monkeypatch):
    client, _, _, _, _, engine = ingestion_app
    import app.adapters.outbound.persistence.resources as ingestion
    building, release, deleting = threading.Event(), threading.Event(), threading.Event()
    original_build = ingestion.build_resource
    manager = client.app.state.ingestions
    original_delete = manager.delete

    def build(*args):
        building.set()
        assert release.wait(3)
        return original_build(*args)

    def delete_started(*args):
        deleting.set()
        return original_delete(*args)

    monkeypatch.setattr(ingestion, "build_resource", build)
    monkeypatch.setattr(manager, "delete", delete_started)
    request = body()
    submit(client, request)
    assert building.wait(1)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(delete, client, request["resourceId"])
        try:
            assert deleting.wait(1)
        finally:
            release.set()
        assert future.result(timeout=3).status_code == 204
    assert read(client, request["resourceId"]).status_code == 404
    with Session(engine) as session:
        assert session.get(NotionResource, request["resourceId"]) is None


def enable_foreign_keys(engine):
    def enable(connection, _):
        connection.execute("PRAGMA foreign_keys=ON")
    event.listen(engine, "connect", enable)
    with engine.connect() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")


def test_parent_delete_detaches_existing_child_without_cascade(ingestion_app):
    client, state, _, _, _, engine = ingestion_app
    enable_foreign_keys(engine)
    child_id = str(uuid4())
    state["markdown"]["markdown"] = f'<page url="https://www.notion.so/{child_id}">Child</page>'
    parent = collect(client)
    state["page"]["id"] = state["markdown"]["id"] = child_id
    state["markdown"]["markdown"] = "Child text"
    child = collect(client, body(pageId=child_id, parentResourceId=parent["resourceId"]))
    assert delete(client, parent["resourceId"]).status_code == 204
    data = read(client, child["resourceId"]).json()
    assert data["parent_resource_id"] is None and data["content"] == "Child text"
    assert len(listing(client).json()) == 1


def test_parent_delete_detaches_inflight_child(ingestion_app):
    client, state, _, gate, started, _ = ingestion_app
    child_id = str(uuid4())
    state["markdown"]["markdown"] = f'<page url="https://www.notion.so/{child_id}">Child</page>'
    parent = collect(client)
    state["page"]["id"] = state["markdown"]["id"] = child_id
    state["markdown"]["markdown"] = "Child text"
    gate.clear()
    started.clear()
    child = body(pageId=child_id, parentResourceId=parent["resourceId"])
    submit(client, child)
    assert started.wait(1)
    assert delete(client, parent["resourceId"]).status_code == 204
    assert poll(client, child).json()["status"] == "EXTRACTING"
    gate.set()
    assert finished(client, child)["status"] == "SUCCEEDED"
    assert read(client, child["resourceId"]).json()["parent_resource_id"] is None


def test_storage_failure_keeps_data_excluded_and_can_retry(ingestion_app, monkeypatch):
    client, _, _, _, _, engine = ingestion_app
    request = collect(client)
    commit = Session.commit

    def fail(_):
        raise SQLAlchemyError("private database information")

    monkeypatch.setattr(Session, "commit", fail)
    response = delete(client, request["resourceId"])
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "RESOURCE_DELETE_FAILED"
    assert "private" not in response.text
    monkeypatch.setattr(Session, "commit", commit)
    with Session(engine) as session:
        assert session.get(NotionResource, request["resourceId"]) is not None
    assert read(client, request["resourceId"]).status_code == 404
    assert listing(client).json() == []
    assert submit(client, {**request, "jobId": str(uuid4())}).json()["error"]["code"] == "RESOURCE_DELETED"
    assert delete(client, request["resourceId"]).status_code == 204
    with Session(engine) as session:
        assert session.get(NotionResource, request["resourceId"]) is None


def test_legacy_child_registration_does_not_restore_deleted_parent(ingestion_app):
    client, state, calls, gate, started, _ = ingestion_app
    child_id = str(uuid4())
    state["markdown"]["markdown"] = f'<page url="https://www.notion.so/{child_id}">Child</page>'
    parent = collect(client)
    state["page"]["id"] = state["markdown"]["id"] = child_id
    state["markdown"]["markdown"] = "Child text"
    gate.clear()
    started.clear()
    path = f"/integrations/notion/connections/{CONNECTION_ID}/resources"
    payload = {"page_id": child_id, "parent_resource_id": parent["resourceId"]}
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(client.post, path, params={"userId": USER_ID}, headers=HEADERS, json=payload)
        try:
            assert started.wait(1)
            assert delete(client, parent["resourceId"]).status_code == 204
        finally:
            gate.set()
        response = future.result(timeout=3)
    assert response.status_code == 201
    assert response.json()["parent_resource_id"] is None
    assert read(client, parent["resourceId"]).status_code == 404
    previous_calls = len(calls)
    response = client.post(path, params={"userId": USER_ID}, headers=HEADERS, json=payload)
    assert response.status_code == 409
    assert len(calls) == previous_calls


def test_delete_timeout_does_not_report_success(ingestion_app, monkeypatch):
    client, _, _, _, _, _ = ingestion_app
    import app.adapters.inbound.http.resources as resource_api
    request = collect(client)
    release, done = threading.Event(), threading.Event()
    original = client.app.state.ingestions.delete

    def slow(*args):
        try:
            assert release.wait(3)
            original(*args)
        finally:
            done.set()

    monkeypatch.setattr(resource_api, "DELETE_TIMEOUT_SECONDS", 0.02)
    monkeypatch.setattr(client.app.state.ingestions, "delete", slow)
    try:
        response = delete(client, request["resourceId"])
        assert response.status_code == 504
        assert response.json()["error"]["code"] == "RESOURCE_DELETE_TIMEOUT"
    finally:
        release.set()
    assert done.wait(2)
    assert read(client, request["resourceId"]).status_code == 404


def test_deleted_document_remains_absent_after_restart(ingestion_app):
    client, _, _, _, _, engine = ingestion_app
    request = collect(client)
    delete(client, request["resourceId"])
    with TestClient(create_app(client.app.state.settings, engine=engine,
                               notion_client=client.app.state.notion_client)) as restarted:
        assert read(restarted, request["resourceId"]).status_code == 404


def test_delete_auth_validation_and_request_headers(ingestion_app):
    client, _, _, _, _, _ = ingestion_app
    path = f"/internal/v1/resources/{uuid4()}"
    assert client.delete(path, params={"userId": USER_ID}).status_code == 401
    assert client.delete(path, headers=HEADERS).status_code == 400
    assert client.delete("/internal/v1/resources/bad", params={"userId": USER_ID}, headers=HEADERS).status_code == 400
    assert client.request("DELETE", path, params={"userId": USER_ID}, headers=HEADERS, json={}).status_code == 400
    assert client.delete(path, params={"userId": USER_ID, "extra": "bad"}, headers=HEADERS).status_code == 400
    request_id = str(uuid4())
    response = client.delete(path, params={"userId": USER_ID}, headers={**HEADERS, "X-Request-Id": request_id})
    assert response.status_code == 204 and response.headers["X-Request-Id"] == request_id
