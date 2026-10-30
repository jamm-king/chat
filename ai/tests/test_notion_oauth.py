import time
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import httpx
import pytest
from cryptography.fernet import Fernet, InvalidToken
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.config import Settings
from app.db import NotionConnection, get_connection
from app.main import COOKIE_NAME, create_app
from app.notion_auth import (
    NotionOAuthError, OAuthStateStore, consume_state, create_authorization_url,
    decrypt_token, encrypt_token,
)

SERVICE_TOKEN = "test-service-token-long-enough"
HEADERS = {"Authorization": f"Bearer {SERVICE_TOKEN}"}
USER_ID = "11111111-1111-4111-8111-111111111111"
WORKSPACE_ID = str(uuid4())
BOT_ID = str(uuid4())


@pytest.fixture
def settings():
    return Settings(
        _env_file=None, database_url="sqlite://", ai_service_token=SERVICE_TOKEN,
        notion_client_id="test-client",
        notion_client_secret="test-client-secret",
        notion_redirect_uri="http://localhost:8001/integrations/notion/callback",
        token_encryption_key=Fernet.generate_key().decode(),
    )


@pytest.fixture
def setup_app(settings):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json={
            "access_token": "secret-access", "refresh_token": "secret-refresh",
            "workspace_id": WORKSPACE_ID, "bot_id": BOT_ID, "workspace_name": "Test workspace",
        })

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    with httpx.Client(transport=httpx.MockTransport(handler)) as upstream:
        app = create_app(settings, engine=engine, notion_client=upstream)
        with TestClient(app) as client:
            yield client, engine, calls
    engine.dispose()


def begin(client):
    response = client.get("/integrations/notion/authorize", params={"userId": USER_ID}, headers=HEADERS)
    assert response.status_code == 200
    url = response.json()["authorization_url"]
    query = parse_qs(urlsplit(url).query)
    assert query["redirect_uri"] == ["http://localhost:8001/integrations/notion/callback"]
    assert query["owner"] == ["user"]
    assert "httponly" in response.headers["set-cookie"].lower()
    return query["state"][0]


def test_success_persists_encrypted_tokens_without_exposing_them(setup_app, settings):
    client, engine, calls = setup_app
    state = begin(client)
    response = client.get("/integrations/notion/callback", params={"state": state, "code": "temporary"})
    assert response.status_code == 200
    assert "secret-access" not in response.text and "secret-refresh" not in response.text
    assert "token" not in response.text
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert COOKIE_NAME not in client.cookies
    with Session(engine) as session:
        connection = session.scalar(select(NotionConnection))
        assert connection.user_id == USER_ID
        assert connection.access_token_encrypted != "secret-access"
        key = settings.token_encryption_key.get_secret_value()
        assert decrypt_token(connection.access_token_encrypted, key) == "secret-access"
        assert decrypt_token(connection.refresh_token_encrypted, key) == "secret-refresh"
        assert get_connection(session, str(uuid4()), connection.id) is None
    assert len(calls) == 1
    assert calls[0].url == "https://api.notion.com/v1/oauth/token"
    assert calls[0].headers["authorization"].startswith("Basic ")
    assert b'"grant_type":"authorization_code"' in calls[0].content
    listing = client.get("/integrations/notion/connections", params={"userId": USER_ID}, headers=HEADERS)
    assert listing.status_code == 200 and len(listing.json()) == 1
    assert "secret-access" not in listing.text


def test_service_auth_is_required(setup_app):
    client, _, calls = setup_app
    for path in ["/integrations/notion/authorize", "/integrations/notion/connections"]:
        assert client.get(path).status_code == 401
        assert client.get(path, headers={"Authorization": "Bearer wrong"}).status_code == 401
    assert not calls


def test_user_id_is_required_and_validated(setup_app):
    client, _, calls = setup_app
    for path in ["/integrations/notion/authorize", "/integrations/notion/connections"]:
        assert client.get(path, headers=HEADERS).status_code == 422
        assert client.get(path, params={"userId": "invalid"}, headers=HEADERS).status_code == 422
    assert not calls


def test_connections_are_scoped_to_backend_user(setup_app):
    client, _, _ = setup_app
    state = begin(client)
    assert client.get("/integrations/notion/callback", params={"state": state, "code": "temporary"}).status_code == 200
    response = client.get(
        "/integrations/notion/connections", params={"userId": str(uuid4())}, headers=HEADERS
    )
    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.parametrize("params", [{"error": "access_denied"}, {}, {"code": ""}])
def test_cancel_or_missing_code_does_not_exchange(setup_app, params):
    client, _, calls = setup_app
    state = begin(client)
    assert client.get("/integrations/notion/callback", params={"state": state, **params}).status_code == 400
    assert not calls


def test_unknown_state_is_rejected(setup_app):
    client, _, calls = setup_app
    begin(client)
    assert client.get("/integrations/notion/callback?state=unknown&code=temporary").status_code == 400
    assert not calls


def test_callback_requires_original_browser_and_state_is_single_use(setup_app):
    client, _, calls = setup_app
    state = begin(client)
    saved_cookie = client.cookies.get(COOKIE_NAME)
    client.cookies.clear()
    assert client.get("/integrations/notion/callback", params={"state": state, "code": "temporary"}).status_code == 400
    assert not calls
    client.cookies.set(COOKIE_NAME, saved_cookie)
    assert client.get("/integrations/notion/callback", params={"state": state, "code": "temporary"}).status_code == 200
    assert client.get("/integrations/notion/callback", params={"state": state, "code": "temporary"}).status_code == 400
    assert len(calls) == 1


def test_state_expiration(settings, monkeypatch):
    store = OAuthStateStore()
    monkeypatch.setattr(time, "monotonic", lambda: 100)
    url, cookie = create_authorization_url(settings, store, USER_ID)
    state = parse_qs(urlsplit(url).query)["state"][0]
    monkeypatch.setattr(time, "monotonic", lambda: 100 + settings.oauth_state_ttl_seconds)
    with pytest.raises(NotionOAuthError, match="expired"):
        consume_state(store, state, cookie)


@pytest.mark.parametrize("mode", ["error", "invalid_json", "invalid_schema", "timeout"])
def test_provider_failures_do_not_leak_credentials(setup_app, mode):
    client, engine, calls = setup_app

    def handler(request):
        calls.append(request)
        if mode == "timeout":
            raise httpx.ReadTimeout("secret-access", request=request)
        if mode == "error":
            return httpx.Response(400, json={"error": "secret-access"})
        if mode == "invalid_json":
            return httpx.Response(200, text="secret-access")
        return httpx.Response(200, json={"access_token": "secret-access"})

    with httpx.Client(transport=httpx.MockTransport(handler)) as upstream:
        client.app.state.notion_client = upstream
        state = begin(client)
        response = client.get("/integrations/notion/callback", params={"state": state, "code": "temporary"})
    assert response.status_code == 502
    assert "secret-access" not in response.text
    assert len(calls) == 1
    with Session(engine) as session:
        assert session.scalar(select(NotionConnection)) is None


def test_reauthorization_updates_existing_connection(setup_app):
    client, engine, _ = setup_app
    identifiers = []
    for _ in range(2):
        state = begin(client)
        response = client.get("/integrations/notion/callback", params={"state": state, "code": "temporary"})
        assert response.status_code == 200
        identifiers.append(response.json()["id"])
    assert identifiers[0] == identifiers[1]
    with Session(engine) as session:
        assert len(session.scalars(select(NotionConnection)).all()) == 1


def test_cipher_rejects_tampering(settings):
    key = settings.token_encryption_key.get_secret_value()
    encrypted = encrypt_token("secret", key)
    assert decrypt_token(encrypted, key) == "secret"
    with pytest.raises(InvalidToken):
        decrypt_token(encrypted[:-5] + "wrong", key)
