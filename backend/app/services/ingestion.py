"""
AI 수집 작업 호출 (자료 등록·상태 조회·삭제).

연동 계약: ai/docs/api/references.md 1장(수집 접수·작업 조회), 4장(자료 삭제)
- resourceId, jobId 는 Backend 가 발급하고 AI 도 같은 ID 를 쓴다.
- 접수는 202(신규) 또는 200(같은 작업 재요청). 실행 결과는 작업 조회로 확인한다.
- AI 오류 형식: { "error": { "code", "message", "retryable" }, "requestId" }
"""

from dataclasses import dataclass
from typing import Any, Dict, Optional

from app.services import ai_client


# AI 계약의 권장 읽기 타임아웃
JOB_TIMEOUT_SECONDS = 10
DELETE_TIMEOUT_SECONDS = 15


@dataclass
class AiError(Exception):
    """AI 가 HTTP 오류로 응답했을 때. status 가 None 이면 연결 자체가 안 된 것."""
    status: Optional[int]
    code: str
    message: str = ""
    retryable: bool = True


def create_job(
        *,
        job_id: str,
        user_id: str,
        resource_id: str,
        connection_id: str,
        page_id: str,
        parent_resource_id: Optional[str],
        operation: str,
) -> Dict[str,Any]:
    """수집 작업을 접수한다. 성공하면 AI 의 작업 객체(status=QUEUED 등)를 돌려준다."""
    payload = {
        "jobId": job_id,
        "userId": user_id,
        "resourceId":resource_id,
        "connectionId":connection_id,
        "pageId":page_id,
        "parentResourceId": parent_resource_id,
        "operation": operation,
    }
    response = _call("POST","/internal/v1/ingestions", json=payload, timeout=JOB_TIMEOUT_SECONDS)
    if response.status_code not in (200, 202):
        raise _error(response)
    return response.json()

def get_job(job_id: str, user_id: str) -> Dict[str, Any]:
    """작업 상태를 조회한다. 작업이 사라졌으면(AI 재시작) AiError(404, "JOB_NOT_FOUND")."""
    response = _call(
        "GET", f"/internal/v1/ingestions/{job_id}", params={"userId": user_id}, timeout=JOB_TIMEOUT_SECONDS
    )
    if response.status_code != 200:
        raise _error(response)
    return response.json()

def delete_resource(resource_id: str, user_id: str) -> None:
    """AI 쪽 자료(본문·청크·벡터)를 지우고 진행 중인 작업을 취소한다. 없는 자료도 204 로 성공."""
    response = _call(
        "DELETE", f"/internal/v1/resources/{resource_id}", params={"userId": user_id}, timeout=DELETE_TIMEOUT_SECONDS
    )
    if response.status_code != 204:
        raise _error(response)

def _call(method: str, path: str, **kwargs):
    try:
        return ai_client.request(method, path, **kwargs)
    except ai_client.AiServiceUnavailable as exc:
        raise AiError(None, "AI_UNAVAILABLE", "AI 서비스에 연결하지 못했습니다.") from exc

def _error(response) -> AiError:
    try:
        body = response.json()["error"]
        return AiError(response.status_code, body.get("code", ""), body.get("message", ""), body.get("retryable", False))
    except Exception:
        return AiError(response.status_code, f"HTTP_{response.status_code}")
