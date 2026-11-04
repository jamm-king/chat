from datetime import datetime
from uuid import UUID
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from app.adapters.outbound.notion.models import NotionPageSummary, NotionContentWarning, NotionReference


class AuthorizationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: UUID = Field(alias="userId")


class AuthorizationResponse(BaseModel):
    authorization_url: str


class ConnectionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    workspace_id: UUID
    workspace_name: str | None
    bot_id: UUID
    created_at: datetime
    status: str = "connected"


class NotionPageListResponse(BaseModel):
    results: list[NotionPageSummary]
    has_more: bool
    next_cursor: str | None


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
    resource_status: Literal["COLLECTED", "READY"] = "COLLECTED"
    chunk_count: int = 0
    indexed_at: datetime | None = None
    embedding_model: str | None = None
    embedding_dimensions: int | None = None


class NotionResourceResponse(NotionResourceSummary):
    raw_content: str
    content: str
    references: list[NotionReference]
    source_updated_at: datetime
    collected_at: datetime
    truncated: bool
    unknown_block_ids: list[UUID]
    warnings: list[NotionContentWarning]
