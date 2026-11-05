"""
RAG 답변 생성. AI 서비스의 POST /internal/v1/answers 를 호출한다.

연동 계약: ai/docs/api/references.md 3장 "답변 생성"
- GENERAL 은 자료 검색 없이 답한다. resourceIds 를 보내면 AI 가 400 을 준다.
- RESOURCE 는 넘긴 자료에서만 검색해 답하고 출처(citations)를 준다.
- status: ANSWERED(답변), INSUFFICIENT_EVIDENCE(자료에 근거 부족), REFUSED(거절). 셋 다 HTTP 200 이다.
라우터는 이 함수의 입력/출력 형식에만 의존한다.
"""
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
import os
from app.models.resources import Resources
from app.services import ai_client

#AI 쪽 답변 제한 시간(60초)보다 조금 길게 기다린다
ANSWER_TIMEOUT_SECONDS = float(os.getenv("AI_ANSWER_TIMEOUT_SECONDS","65"))

#AI 가 받는 이력 1개의 최대 글자 수
HISTORY_CONTENT_LIMIT = 8000

#RAG 호출 실패 시 발생(라우터에서 502 로 변환)
class RagServiceError(Exception):
    pass


@dataclass
class HistoryTurn:
    role: str      # USER 또는 ASSISTANT
    content: str


@dataclass
class RagCitation:
    resource_id: str
    excerpt: str
    locator: Optional[Dict[str, Any]] = None


@dataclass
class RagAnswer:
    content: str
    status: str = "ANSWERED"
    citations: List[RagCitation] = field(default_factory=list)


def generate_answer(
    user_id: str,
    mode: str,
    message: str,
    resources: List[Resources],
    history: List[HistoryTurn]
) -> RagAnswer:
    """
    사용자 메시지에 대한 AI 답변을 생성한다.

    user_id   : 로그인 사용자 ID (AI 가 자료 범위를 다시 확인하는 기준)
    mode      : GENERAL 또는 RESOURCE
    message   : 사용자 메시지
    resources : RESOURCE 모드에서 검색 대상 자료 (GENERAL 모드에서는 빈 리스트)
    history   : 이전 대화 기록 (오래된 순)
    """
    payload: Dict[str, Any] = {
        "userId": user_id,
        "mode": mode,
        "message": message,
        "history": _history_payload(history),
    }
    if mode == "RESOURCE":
        payload["resourceIds"] = [resource.id for resource in resources]

    try:
        response = ai_client.request(
            "POST",
            "/internal/v1/answers",
            json=payload,
            timeout=ANSWER_TIMEOUT_SECONDS,
        )
    except ai_client.AiServiceUnavailable as exc:
        raise RagServiceError("AI 서비스에 연결하지 못했습니다.") from exc
    if response.status_code !=200:
        raise RagServiceError(f"AI 답변 생성 실패: HTTP {response.status_code} {_error_code(response)}")
    
    data= response.json()

    return RagAnswer(
        content=data["content"],
        status=data["status"],
        citations=[
            RagCitation(
                resource_id=c["resourceId"],
                excerpt=c["excerpt"],
                locator=c.get("locator"),
            )
            for c in data.get("citations",[])
        ],
    )

def _history_payload(history: List[HistoryTurn]) -> List[Dict[str, str]]:
    """
    AI 규칙에 맞는 이력만 보낸다.
    - 완료된 USER → ASSISTANT 쌍만 (짝이 안 맞는 메시지는 건너뜀)
    - 항목당 8,000자 이하 (AI 답변은 16,000자까지라 넘을 수 있다. 넘는 쌍은 통째로 뺀다)
    """    
    turns: List[Dict[str, str]] = []
    i=0
    while i + 1 < len(history):
        user, assistant = history[i], history[i + 1]
        if user.role != "USER" or assistant.role != "ASSISTANT":
            i += 1
            continue
        if len(user.content) <= HISTORY_CONTENT_LIMIT and len(assistant.content) <= HISTORY_CONTENT_LIMIT:
            turns.append({"role": "USER", "content": user.content})
            turns.append({"role": "ASSISTANT", "content": assistant.content})
        i += 2
    return turns

def _error_code(response) -> str:
    """AI 오류 응답 { "error": { "code": ... } } 에서 코드만 꺼낸다 (로그·디버깅용)."""
    try:
        return response.json()["error"]["code"]
    except Exception:
        return ""
