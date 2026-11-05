"""
자료(Resources) API. 프론트 명세 v2.2 [3.1].

Backend 는 자료 기본 정보·처리 상태·최근 작업을 관리하고,
노션 본문 수집·색인은 AI 서비스에 비동기 작업으로 맡긴다 (services/ingestion.py).
"""

import logging
import uuid
from typing import Optional
from datetime import datetime, timezone


from fastapi import APIRouter, Depends, Response, status
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.core.errors import AppError
from app.db.session import get_db
from app.models.ingestion import IngestionJob
from app.models.resources import Resources
from app.models.users import User
from app.schemas.resource import (
    ResourceCreate,
    ResourceError,
    ResourceJob,
    ResourceListResponse,
    ResourceResponse,
    ResourceSource,
)
from app.services import ingestion


router = APIRouter(
    prefix="/api/v1/resources",
    tags=["Resources"]
)

logger = logging.getLogger(__name__)


# AI 접수 오류 → 명세의 오류 코드
_CREATE_ERRORS = {
    "CONNECTION_NOT_FOUND": (status.HTTP_404_NOT_FOUND, "NOTION_CONNECTION_NOT_FOUND", "노션 연결을 찾을 수 없습니다."),
    "RESOURCE_NOT_FOUND": (status.HTTP_404_NOT_FOUND, "RESOURCE_NOT_FOUND", "부모 자료를 찾을 수 없습니다."),
    "INVALID_PARENT_REFERENCE": (
        status.HTTP_409_CONFLICT,
        "INVALID_PARENT_REFERENCE",
        "부모 페이지가 참조하는 페이지가 아닙니다.",
    ),
}

# AI 가 알려 주는 자료 상태 중 Backend 가 그대로 받는 값 (references.md 1장 작업 조회 표)
_RESOURCE_STATUSES = {"PROCESSING", "COLLECTED", "READY", "FAILED"}
_FINISHED_JOB_STATUSES = {"SUCCEEDED", "FAILED", "CANCELLED"}


def _get_owned(db: Session, user: User, resource_id: str) -> Resources:
    """내 자료만. 없거나, 다른 사용자 것이거나, 삭제한 자료는 모두 같은 404 (존재 여부를 알려주지 않는다)."""
    resource = db.scalar(
        select(Resources).where(
            Resources.id == resource_id,
            Resources.user_id == user.id,
            Resources.status != "DELETED",
        )
    )
    if resource is None:
        raise AppError(status.HTTP_404_NOT_FOUND, "RESOURCE_NOT_FOUND", "요청한 자료를 찾을 수 없습니다.")
    return resource

def _refresh_from_ai(db: Session, resource: Resources, job: IngestionJob, user_id: str) -> None:
    """처리 중인 자료의 최근 작업 상태를 AI 에 물어 DB 에 반영한다."""
    now = datetime.now(timezone.utc)
    try:
        data = ingestion.get_job(job.id, user_id)
    except ingestion.AiError as exc:
        if exc.status == 404 and exc.code == "JOB_NOT_FOUND":
            # AI 재시작 등으로 작업이 사라짐. 자동으로 다시 접수하지 않고 실패로 기록한다 (계약 1장)
            job.status = "FAILED"
            job.error_code = "JOB_LOST"
            job.error_message = "처리 작업이 사라졌습니다. 다시 등록해주세요."
            job.retryable = True
            job.completed_at = now
            resource.status = "FAILED"
            db.commit()
        else:
            # 일시적으로 AI 에 연결할 수 없으면 저장된 상태를 그대로 돌려준다 (명세 3.1.3)
            logger.warning("ingestion status check failed: %s", exc)
        return

    job.status = data["status"]
    if job.status in _FINISHED_JOB_STATUSES and job.completed_at is None:
        job.completed_at = now

    error = data.get("error")
    if error:
        job.error_code = error.get("code")
        job.error_message = error.get("message")
        job.retryable = error.get("retryable", False)

    result = data.get("result") or {}
    if result.get("title"):
        resource.title = result["title"]
    if result.get("canonicalUrl"):
        # JSON 칼럼은 안의 값만 바꾸면 변경으로 인식되지 않아서, 새 dict 로 통째로 바꾼다
        resource.source = {"url": result["canonicalUrl"]}

    if data.get("resourceStatus") in _RESOURCE_STATUSES:
        resource.status = data["resourceStatus"]

    db.commit()

def _to_response(resource: Resources, job: Optional[IngestionJob]) -> ResourceResponse:
    """DB 의 자료·최근 작업 → 명세의 Resource 객체. error 는 FAILED 일 때만 채운다."""
    error = None
    if resource.status == "FAILED" and job is not None and job.error_code:
        error = ResourceError(
            code=job.error_code,
            message=job.error_message or "",
            retryable=bool(job.retryable),
        )

    return ResourceResponse(
        resource_id=resource.id,
        title=resource.title,
        source=ResourceSource(
            connection_id=resource.connection_id,
            page_id=resource.page_id,
            url=(resource.source or {}).get("url"),
        ),
        parent_resource_id=resource.parent_resource_id,
        status=resource.status,
        job=ResourceJob(job_id=job.id, operation=job.operation, status=job.status) if job else None,
        error=error,
        created_at=resource.created_at,
        updated_at=resource.updated_at,
    )


# 1. 자료 등록 (노션 페이지 1개)
@router.post("", response_model=ResourceResponse, status_code=status.HTTP_202_ACCEPTED)
def create_resource(
    body: ResourceCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    connection_id = str(body.connection_id)
    page_id = str(body.page_id)
    parent_id = str(body.parent_resource_id) if body.parent_resource_id else None

    # ① 같은 연결에서 같은 페이지를 이미 등록했는지 (삭제한 자료는 다시 등록 가능)
    existing = db.scalar(
        select(Resources).where(
            Resources.user_id == current_user.id,
            Resources.connection_id == connection_id,
            Resources.page_id == page_id,
            Resources.status != "DELETED",
        )
    )
    if existing:
        raise AppError(
            status.HTTP_409_CONFLICT,
            "RESOURCE_ALREADY_EXISTS",
            "이미 등록한 노션 페이지입니다.",
            details=[{"field": "pageId", "message": existing.id}],
        )

    # 부모 자료: 내 자료이고, 같은 연결이어야 한다 (실제 참조 관계는 AI 가 확인)
    if parent_id:
        parent = db.scalar(
            select(Resources).where(
                Resources.id == parent_id,
                Resources.user_id == current_user.id,
                Resources.status != "DELETED",
            )
        )
        if parent is None:
            raise AppError(status.HTTP_404_NOT_FOUND, "RESOURCE_NOT_FOUND", "부모 자료를 찾을 수 없습니다.")
        if parent.connection_id != connection_id:
            raise AppError(
                status.HTTP_409_CONFLICT,
                "INVALID_PARENT_REFERENCE",
                "부모 자료와 다른 노션 연결입니다.",
            )

    # ② ID 발급
    resource_id = str(uuid.uuid4())
    job_id = str(uuid.uuid4())

    # ③ AI 에 작업 접수. 색인이 꺼져 있으면 수집만이라도 한다
    operation = "COLLECT_AND_INDEX"
    try:
        try:
            job = _create_job(job_id, current_user.id, resource_id, connection_id, page_id, parent_id, operation)
        except ingestion.AiError as exc:
            if exc.code != "OPERATION_NOT_AVAILABLE":
                raise
            operation = "COLLECT"
            job = _create_job(job_id, current_user.id, resource_id, connection_id, page_id, parent_id, operation)
    except ingestion.AiError as exc:
        if exc.code in _CREATE_ERRORS:
            code_status, code, message = _CREATE_ERRORS[exc.code]
            raise AppError(code_status, code, message)
        logger.warning("ingestion create failed: %s", exc)
        raise AppError(
            status.HTTP_502_BAD_GATEWAY,
            "RAG_SERVICE_UNAVAILABLE",
            "자료 처리 요청에 실패했습니다. 잠시 후 다시 시도해주세요.",
            retryable=True,
        )

    # ④ 저장: 자료는 PROCESSING, 작업은 AI 가 준 상태(QUEUED)
    resource = Resources(
        id=resource_id,
        user_id=current_user.id,
        title=None,
        type="NOTION_PAGE",
        source={"url": None},
        status="PROCESSING",
        connection_id=connection_id,
        page_id=page_id,
        parent_resource_id=parent_id,
        latest_job_id=job_id,
    )
    job_row = IngestionJob(
        id=job_id,
        resource_id=resource_id,
        operation=operation,
        status=job.get("status", "QUEUED"),
    )
    db.add_all([resource, job_row])
    db.commit()

    # ⑤ 202 + Resource 객체
    return _to_response(resource, job_row)


# 2. 자료 목록 (최근 등록 순, 삭제한 자료 제외)
@router.get("", response_model=ResourceListResponse)
def list_resources(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    resources = db.scalars(
        select(Resources)
        .where(Resources.user_id == current_user.id, Resources.status != "DELETED")
        .order_by(Resources.created_at.desc())
    ).all()

    # 자료마다 작업을 따로 조회하지 않고 한 번에 가져온다
    job_ids = [r.latest_job_id for r in resources if r.latest_job_id]
    jobs = {}
    if job_ids:
        jobs = {j.id: j for j in db.scalars(select(IngestionJob).where(IngestionJob.id.in_(job_ids)))}

    return ResourceListResponse(
        resources=[_to_response(r, jobs.get(r.latest_job_id)) for r in resources]
    )


# 3. 자료 상세 (처리 중이면 AI 에 물어 최신 상태로 갱신)
@router.get("/{resource_id}", response_model=ResourceResponse)
def get_resource(
    resource_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    resource = _get_owned(db, current_user, resource_id)
    job = db.get(IngestionJob, resource.latest_job_id) if resource.latest_job_id else None

    if resource.status == "PROCESSING" and job is not None:
        _refresh_from_ai(db, resource, job, current_user.id)
    return _to_response(resource, job)

# 4. 자료 삭제
@router.delete("/{resource_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_resource(
    resource_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    resource = _get_owned(db, current_user, resource_id)

    # ② Backend 에서 먼저 삭제 표시: 바로 목록·상세·대화 검색 대상에서 빠진다 (계약 4장)
    resource.status = "DELETED"

    # 이 자료를 부모로 둔 자식은 지우지 않고 부모 연결만 끊는다
    db.execute(
        update(Resources)
        .where(Resources.parent_resource_id == resource.id)
        .values(parent_resource_id=None)
    )

    # 진행 중이던 작업은 취소로 기록 (AI 도 삭제 요청을 받으면 작업을 취소한다)
    job = db.get(IngestionJob, resource.latest_job_id) if resource.latest_job_id else None
    if job is not None and job.status not in _FINISHED_JOB_STATUSES:
        job.status = "CANCELLED"
        job.completed_at = datetime.now(timezone.utc)

    db.commit()

    # ③ AI 데이터 삭제. 실패해도 Backend 의 DELETED 는 유지한다 (사용자에게는 이미 삭제된 자료)
    try:
        ingestion.delete_resource(resource.id, current_user.id)
    except ingestion.AiError as exc:
        logger.warning("AI resource delete failed (resource=%s): %s", resource.id, exc)

    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _create_job(job_id, user_id, resource_id, connection_id, page_id, parent_id, operation):
    return ingestion.create_job(
        job_id=job_id,
        user_id=user_id,
        resource_id=resource_id,
        connection_id=connection_id,
        page_id=page_id,
        parent_resource_id=parent_id,
        operation=operation,
    )