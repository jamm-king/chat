import secrets
import threading
import time
from dataclasses import dataclass
from urllib.parse import urlencode

import httpx
from cryptography.fernet import Fernet
from pydantic import ValidationError

from app.config import Settings
from app.schemas import NotionTokenResponse


@dataclass(frozen=True)
class PendingAuthorization:
    user_id: str
    browser_token: str
    expires_at: float


class OAuthStateStore:
    """Single-process, short-lived state. Restarting invalidates pending authorizations."""

    def __init__(self) -> None:
        self.pending: dict[str, PendingAuthorization] = {}
        self.lock = threading.Lock()


class NotionOAuthError(Exception):
    pass


def create_authorization_url(
    settings: Settings, store: OAuthStateStore, user_id: str,
) -> tuple[str, str]:
    state, browser_token = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    now = time.monotonic()
    with store.lock:
        store.pending = {key: item for key, item in store.pending.items() if item.expires_at > now}
        store.pending[state] = PendingAuthorization(
            user_id, browser_token, now + settings.oauth_state_ttl_seconds
        )
    query = urlencode({
        "client_id": settings.notion_client_id,
        "redirect_uri": settings.notion_redirect_uri,
        "response_type": "code", "owner": "user", "state": state,
    })
    return f"https://api.notion.com/v1/oauth/authorize?{query}", browser_token


def consume_state(store: OAuthStateStore, state: str, browser_token: str | None) -> str:
    with store.lock:
        pending = store.pending.get(state)
        if pending is None:
            raise NotionOAuthError("Invalid or already used OAuth state")
        if pending.expires_at <= time.monotonic():
            store.pending.pop(state)
            raise NotionOAuthError("OAuth state expired")
        if not browser_token or not secrets.compare_digest(pending.browser_token, browser_token):
            raise NotionOAuthError("OAuth browser session does not match")
        store.pending.pop(state)
        return pending.user_id


def exchange_code(settings: Settings, client: httpx.Client, code: str) -> NotionTokenResponse:
    try:
        response = client.post(
            "https://api.notion.com/v1/oauth/token",
            auth=httpx.BasicAuth(settings.notion_client_id, settings.notion_client_secret.get_secret_value()),
            json={"grant_type": "authorization_code", "code": code,
                  "redirect_uri": settings.notion_redirect_uri},
        )
        response.raise_for_status()
        return NotionTokenResponse.model_validate(response.json())
    except (httpx.HTTPError, ValidationError, ValueError):
        # Do not propagate provider response bodies, credentials or authorization codes.
        raise NotionOAuthError("Notion token exchange failed; start authorization again") from None


def encrypt_token(token: str, key: str) -> str:
    return Fernet(key.encode()).encrypt(token.encode()).decode()


def decrypt_token(ciphertext: str, key: str) -> str:
    return Fernet(key.encode()).decrypt(ciphertext.encode()).decode()
