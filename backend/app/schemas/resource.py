"""
자료(Resources) API 요청·응답 형식. 프론트 명세 v2.2 [3.1] Resource 객체.
"""
from datetime import datetime
from typing import List, Literal, Optional
from uuid import UUID

from app.schemas.message import CamelModel


# 자료 등록 요청 (POST /api/v1/resources)
class ResourceCreate(CamelModel):
    connection_id: UUID
    page_id: UUID
    parent_resource_id: Optional[UUID] = None

class ResourceSource(CamelModel):
    type: Literal["NOTION_PAGE"] = "NOTION_PAGE"
    connection_id: Optional[str]
    page_id: Optional[str]
    url: Optional[str] = None

class ResourceJob(CamelModel):
    job_id: str
    operation: str
    status: str


class ResourceError(CamelModel):
    code: str
    message: str
    retryable: bool


# 등록.목록.상세 응답에 공통으로 쓰는 Resource 객체
class ResourceResponse(CamelModel):
    resource_id: str
    title: Optional[str]
    source: ResourceSource
    parent_resource_id: Optional[str]
    status: Literal["PROCESSING", "COLLECTED", "READY", "FAILED"]
    job: Optional[ResourceJob]
    error: Optional[ResourceError]
    created_at: datetime
    updated_at: datetime


class ResourceListResponse(CamelModel):
    resources: List[ResourceResponse]