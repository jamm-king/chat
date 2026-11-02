from datetime import datetime
from typing import List, Literal, Optional

from app.schemas.message import CamelModel


# 노션 연결 시작 응답
class NotionAuthorizeResponse(CamelModel):
    authorization_url: str


# 노션 연결 1개 (노션 토큰은 포함하지 않음)
class NotionConnectionResponse(CamelModel):
    connection_id: str
    workspace_name: Optional[str] = None
    # 저장된 연결이라는 뜻이며, 노션 권한이 지금도 유효한지는 확인하지 않는다.
    status: Literal["CONNECTED"] = "CONNECTED"
    created_at: datetime


# 노션 연결 상태 조회 응답
class NotionConnectionListResponse(CamelModel):
    connections: List[NotionConnectionResponse]
