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


class NotionReference(BaseModel):
    kind: Literal["page", "database", "video", "image", "audio", "file"]
    title: str | None
    url: str
    page_id: UUID | None = None
    can_register: bool = False


class NotionPageResponse(NotionPageSummary):
    raw_content: str
    content: str
    content_status: Literal["complete", "partial"]
    truncated: bool
    unknown_block_ids: list[UUID]
    warnings: list[NotionContentWarning]
    references: list[NotionReference]


class RegisterNotionResourceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    page_id: UUID
    parent_resource_id: UUID | None = None


class NotionResourceSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    connection_id: UUID
    page_id: UUID
    parent_resource_id: UUID | None
    title: str | None
    url: str
    content_status: Literal["complete", "partial"]
    created_at: datetime


class NotionResourceResponse(NotionResourceSummary):
    raw_content: str
    content: str
    references: list[NotionReference]
    source_updated_at: datetime
    collected_at: datetime
    truncated: bool
    unknown_block_ids: list[UUID]
    warnings: list[NotionContentWarning]
