from datetime import datetime
from typing import List, Optional

from app.schemas.message import CamelModel


# 노션 연결 시작 응답
class NotionAuthorizeResponse(CamelModel):
    authorization_url: str


# 노션 연결 1개 (AI 서비스의 connection 객체, 토큰은 포함하지 않음)
class NotionConnectionResponse(CamelModel):
    connection_id: str
    workspace_id: str
    workspace_name: Optional[str] = None
    bot_id: str
    created_at: datetime
    status: str


# 노션 연결 목록 응답
class NotionConnectionListResponse(CamelModel):
    connections: List[NotionConnectionResponse]
