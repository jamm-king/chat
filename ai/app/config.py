from cryptography.fernet import Fernet
from typing import Literal
from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", hide_input_in_errors=True)

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
    ingestion_timeout_seconds: float = Field(default=600, gt=0, le=600)
    indexing_enabled: bool = False
    rag_enabled: bool = False
    answer_model: str = Field(default="gpt-6-luna", min_length=1)
    answer_provider_timeout_seconds: float = Field(default=40, gt=0, le=55)
    answer_max_output_tokens: int = Field(default=4096, ge=1024, le=8192)
    answer_context_budget_bytes: int = Field(default=64000, ge=8192, le=256000)
    openai_api_key: SecretStr | None = None
    embedding_model: Literal["text-embedding-3-small", "text-embedding-3-large"] = "text-embedding-3-small"
    embedding_dimensions: int = Field(default=1536, ge=1, le=3072)
    embedding_batch_size: int = Field(default=32, ge=1, le=32)
    embedding_timeout_seconds: float = Field(default=30, gt=0, le=60)
    chunk_size: int = Field(default=1000, ge=64, le=2000)
    chunk_overlap: int = Field(default=150, ge=0)

    @field_validator("openai_api_key", mode="before")
    @classmethod
    def empty_key_is_none(cls, value):
        return None if value == "" else value

    @model_validator(mode="after")
    def validate_indexing_settings(self):
        if self.chunk_overlap >= self.chunk_size:
            raise ValueError("CHUNK_OVERLAP must be smaller than CHUNK_SIZE")
        if self.embedding_model == "text-embedding-3-small" and self.embedding_dimensions > 1536:
            raise ValueError("text-embedding-3-small supports at most 1536 dimensions")
        if (self.indexing_enabled or self.rag_enabled) and (not self.openai_api_key or not self.openai_api_key.get_secret_value().strip()):
            raise ValueError("OPENAI_API_KEY is required when INDEXING_ENABLED or RAG_ENABLED is true")
        return self

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
