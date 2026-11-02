from cryptography.fernet import Fernet
from typing import Literal
from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: SecretStr
    ai_service_token: SecretStr = Field(min_length=16)
    notion_client_id: str = Field(min_length=1)
    notion_client_secret: SecretStr = Field(min_length=1)
    notion_redirect_uri: str
    token_encryption_key: SecretStr
    oauth_state_ttl_seconds: int = Field(default=600, ge=1, le=3600)
    oauth_cookie_secure: bool = False
    notion_timeout_seconds: float = Field(default=15, gt=0, le=60)
    notion_api_version: Literal["2026-03-11"] = "2026-03-11"

    @field_validator("token_encryption_key")
    @classmethod
    def valid_encryption_key(cls, value: SecretStr) -> SecretStr:
        try:
            Fernet(value.get_secret_value().encode())
        except (ValueError, TypeError):
            raise ValueError("A valid Fernet key is required") from None
        return value

    @field_validator("notion_redirect_uri")
    @classmethod
    def valid_redirect_uri(cls, value: str) -> str:
        from urllib.parse import urlsplit

        url = urlsplit(value)
        local = url.hostname in {"localhost", "127.0.0.1", "::1"}
        if (
            not url.hostname or url.username or url.password or url.query or url.fragment
            or (url.scheme != "https" and not (local and url.scheme == "http"))
            or url.path != "/integrations/notion/callback"
        ):
            raise ValueError("Use HTTPS (HTTP for localhost) and /integrations/notion/callback")
        return value
