from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.domain.jobs import JobStatus, Operation, ResourceStatus


class IngestionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    job_id: UUID = Field(alias="jobId")
    user_id: UUID = Field(alias="userId")
    resource_id: UUID = Field(alias="resourceId")
    connection_id: UUID = Field(alias="connectionId")
    page_id: UUID = Field(alias="pageId")
    parent_resource_id: UUID | None = Field(default=None, alias="parentResourceId")
    operation: Operation


class JobError(BaseModel):
    code: str
    message: str
    retryable: bool


class IngestionResult(BaseModel):
    title: str | None
    canonicalUrl: str
    contentStatus: Literal["complete", "partial"]
    referenceCount: int
    ready: bool = False
    chunkCount: int = Field(default=0, ge=0)
    indexedAt: datetime | None = None


class IngestionJob(BaseModel):
    jobId: UUID
    userId: UUID
    resourceId: UUID
    operation: Operation
    status: JobStatus
    resourceStatus: ResourceStatus
    createdAt: datetime
    startedAt: datetime | None = None
    completedAt: datetime | None = None
    result: IngestionResult | None = None
    error: JobError | None = None
