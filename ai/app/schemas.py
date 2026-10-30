from datetime import datetime
from uuid import UUID

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
