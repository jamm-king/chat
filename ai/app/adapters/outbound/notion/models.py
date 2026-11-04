from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, SecretStr


class NotionTokenResponse(BaseModel):
    access_token: SecretStr = Field(min_length=1)
    refresh_token: SecretStr | None = None
    bot_id: UUID
    workspace_id: UUID
    workspace_name: str | None = None


class NotionPageSummary(BaseModel):
    id: UUID
    title: str | None
    url: str
    last_edited_time: datetime


class NotionContentWarning(BaseModel):
    code: str
    message: str


class NotionReference(BaseModel):
    kind: Literal["page", "database", "video", "image", "audio", "file"]
    title: str | None
    url: str
    page_id: UUID | None = None
    can_register: bool = False
