"""
RAG 시스템 연동 지점.

현재는 RAG 시스템과의 연동 방식(URL, 요청 형식)이 정해지지 않아 임시 답변을 반환한다.
연동 방식이 정해지면 generate_answer() 내부만 실제 호출로 교체하면 된다.
라우터는 이 함수의 입력/출력 형식에만 의존한다.
"""
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from app.models.resources import Resources


# RAG 호출 실패 시 발생 (라우터에서 502 로 변환)
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
    citations: List[RagCitation] = field(default_factory=list)


def generate_answer(
    mode: str,
    message: str,
    resources: List[Resources],
    history: List[HistoryTurn]
) -> RagAnswer:
    """
    사용자 메시지에 대한 AI 답변을 생성한다.

    mode      : GENERAL 또는 RESOURCE
    message   : 사용자 메시지
    resources : RESOURCE 모드에서 검색 대상 자료 (GENERAL 모드에서는 빈 리스트)
    history   : 이전 대화 기록 (오래된 순)

    TODO: RAG 시스템 연동 후 실제 호출로 교체
    """
    if mode == "GENERAL":
        return RagAnswer(
            content=f"[임시 답변] '{message}'에 대한 답변입니다. (RAG 시스템 연동 전)"
        )

    citations = [
        RagCitation(
            resource_id=resource.id,
            excerpt="[임시 발췌] RAG 시스템 연동 후 실제 발췌 텍스트가 표시됩니다.",
            locator=_locator_from_source(resource.source)
        )
        for resource in resources
    ]

    markers = "".join(f"[{i}]" for i in range(1, len(citations) + 1))

    return RagAnswer(
        content=f"[임시 답변] 등록된 자료를 기반으로 한 답변입니다. (RAG 시스템 연동 전){markers}",
        citations=citations
    )


def _locator_from_source(source: Dict[str, Any] | None) -> Optional[Dict[str, Any]]:
    if not source or not source.get("url"):
        return None

    return {"type": "URL", "url": source["url"]}
