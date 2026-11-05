import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy import case, delete, select
from sqlalchemy.orm import Session, selectinload

from app.core.deps import get_current_user
from app.core.errors import AppError
from app.db.session import get_db
from app.models.citation import Citation
from app.models.message import Message
from app.models.resources import Resources
from app.models.users import User
from app.schemas.message import (
    CitationResponse,
    MessageAnswerResponse,
    MessageCreate,
    MessageListResponse,
    MessageResponse,
)
from app.services import rag


router = APIRouter(
    prefix="/api/v1/messages",
    tags=["Messages"]
)

logger = logging.getLogger(__name__)

# RAG 호출 시 함께 전달할 이전 대화 개수
HISTORY_LIMIT = 20


# 같은 시각(초 단위)에 저장된 메시지는 USER → ASSISTANT 순으로 정렬
_ROLE_ORDER = case((Message.role == "USER", 0), else_=1)


def _citation_response(citation: Citation) -> CitationResponse:
    return CitationResponse(
        citation_id=str(citation.position),
        resource_id=citation.resource_id,
        title=citation.resource.title if citation.resource else None,
        excerpt=citation.excerpt,
        locator=citation.locator,
    )


# 1. 대화 기록 조회
@router.get("", response_model=MessageListResponse)
def list_messages(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    messages = db.scalars(
        select(Message)
        .where(Message.user_id == current_user.id)
        .options(selectinload(Message.citations).selectinload(Citation.resource))
        .order_by(Message.created_at, _ROLE_ORDER)
    ).all()

    return MessageListResponse(
        messages=[
            MessageResponse(
                message_id=message.id,
                role=message.role,
                mode=message.mode,
                content=message.content,
                citations=[_citation_response(c) for c in message.citations],
                created_at=message.created_at,
            )
            for message in messages
        ]
    )


# 2. 메시지 전송 및 AI 답변 생성
@router.post("", response_model=MessageAnswerResponse)
def send_message(
    body: MessageCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    # RESOURCE 모드: 자료 소유 여부 및 처리 상태 확인
    resources: list[Resources] = []

    if body.mode == "RESOURCE":
        found = db.scalars(
            select(Resources).where(
                Resources.id.in_(body.resource_ids),
                Resources.user_id == current_user.id,
                Resources.status != "DELETED",
            )
        ).all()
        found_by_id = {r.id: r for r in found}

        missing = [rid for rid in body.resource_ids if rid not in found_by_id]
        if missing:
            raise AppError(
                status.HTTP_404_NOT_FOUND,
                "RESOURCE_NOT_FOUND",
                "요청한 자료를 찾을 수 없습니다.",
                details=[{"field": "resourceIds", "message": rid} for rid in missing],
            )

        not_ready = [rid for rid in body.resource_ids if found_by_id[rid].status != "READY"]
        if not_ready:
            raise AppError(
                status.HTTP_409_CONFLICT,
                "RESOURCE_NOT_READY",
                "아직 처리 중이거나 처리에 실패한 자료가 포함되어 있습니다.",
                retryable=True,
                details=[{"field": "resourceIds", "message": rid} for rid in not_ready],
            )

        resources = [found_by_id[rid] for rid in body.resource_ids]

    # 이전 대화 기록 (오래된 순)
    recent = db.scalars(
        select(Message)
        .where(Message.user_id == current_user.id)
        .order_by(Message.created_at.desc(), _ROLE_ORDER.desc())
        .limit(HISTORY_LIMIT)
    ).all()
    history = [rag.HistoryTurn(role=m.role, content=m.content) for m in reversed(recent)]

    # AI 답변 생성
    try:
        answer = rag.generate_answer(
            user_id=current_user.id,
            mode=body.mode,
            message=body.message,
            resources=resources,
            history=history,
        )
    except rag.RagServiceError as exc:
        # 원인은 서버 로그에만 남기고, 프론트에는 명세의 공통 에러 형식으로 보낸다
        logger.warning("RAG answer failed: %s", exc)
        raise AppError(
            status.HTTP_502_BAD_GATEWAY,
            "RAG_SERVICE_UNAVAILABLE",
            "AI 답변 생성에 실패했습니다. 잠시 후 다시 시도해주세요.",
            retryable=True,
        )

    # RAG 가 요청 범위 밖의 자료를 인용하면 무시
    allowed_ids = {r.id for r in resources}
    rag_citations = [c for c in answer.citations if c.resource_id in allowed_ids]

    # 사용자 메시지 + AI 답변 저장 (답변 생성에 성공했을 때만 저장)
    now = datetime.now(timezone.utc)

    user_message = Message(
        user_id=current_user.id,
        role="USER",
        content=body.message,
        mode=body.mode,
        created_at=now,
    )
    assistant_message = Message(
        user_id=current_user.id,
        role="ASSISTANT",
        content=answer.content,
        mode=body.mode,
        # 같은 시각이면 _ROLE_ORDER 로 USER → ASSISTANT 순 정렬
        created_at=now,
        citations=[
            Citation(
                resource_id=c.resource_id,
                excerpt=c.excerpt,
                locator=c.locator,
                position=i,
            )
            for i, c in enumerate(rag_citations, start=1)
        ],
    )

    db.add_all([user_message, assistant_message])

    try:
        db.commit()
    except Exception:
        db.rollback()
        raise

    titles = {r.id: r.title for r in resources}

    return MessageAnswerResponse(
        answer_id=assistant_message.id,
        mode=body.mode,
        status=answer.status,
        content=assistant_message.content,
        citations=[
            CitationResponse(
                citation_id=str(c.position),
                resource_id=c.resource_id,
                title=titles.get(c.resource_id),
                excerpt=c.excerpt,
                locator=c.locator,
            )
            for c in assistant_message.citations
        ],
    )


# 3. 대화 기록 전체 삭제
@router.delete("", status_code=status.HTTP_204_NO_CONTENT)
def clear_messages(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    # 벌크 DELETE 는 ORM cascade 를 타지 않으므로 citations 를 먼저 삭제
    db.execute(
        delete(Citation).where(
            Citation.message_id.in_(
                select(Message.id).where(Message.user_id == current_user.id)
            )
        )
    )
    db.execute(delete(Message).where(Message.user_id == current_user.id))
    db.commit()

    return Response(status_code=status.HTTP_204_NO_CONTENT)
