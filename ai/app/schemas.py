from datetime import datetime
from uuid import UUID
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr


class AuthorizationResponse(BaseModel):
    authorization_url: str


class NotionTokenResponse(BaseModel):
    access_token: SecretStr = Field(min_length=1)
    refresh_token: SecretStr | None = None
    bot_id: UUID
    workspace_id: UUID
    workspace_name: str | None = None


class ConnectionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    workspace_id: UUID
    workspace_name: str | None
    bot_id: UUID
    created_at: datetime
    status: str = "connected"


class NotionPageSummary(BaseModel):
    id: UUID
    title: str | None
    url: str
    last_edited_time: datetime


class NotionPageListResponse(BaseModel):
    results: list[NotionPageSummary]
    has_more: bool
    next_cursor: str | None


class NotionContentWarning(BaseModel):
    code: str
    message: str


class NotionPageResponse(NotionPageSummary):
    content: str
    content_status: Literal["complete", "partial"]
    truncated: bool
    unknown_block_ids: list[UUID]
    warnings: list[NotionContentWarning]
