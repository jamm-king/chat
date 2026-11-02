"""
AI 서비스(ai/) 호출 클라이언트.

연동 계약: ai/docs/api/notion-oauth.md
- Backend → AI 호출은 AI_SERVICE_TOKEN 으로 인증한다. (노션 토큰이 아님, 프론트에 노출 금지)
- userId 는 항상 Backend 가 로그인 세션에서 꺼낸 값만 넘긴다.
- 요청마다 새 클라이언트를 만들어 사용자 간 쿠키가 공유되지 않게 한다.
- code, state, 쿠키, authorization_url 은 로그에 남기지 않는다.
"""
import os
from typing import Any, Dict, Optional

import httpx
from dotenv import load_dotenv


load_dotenv()

AI_SERVICE_URL = os.getenv("AI_SERVICE_URL", "http://localhost:8001").rstrip("/")
AI_SERVICE_TOKEN = os.getenv("AI_SERVICE_TOKEN", "")
AI_TIMEOUT_SECONDS = float(os.getenv("AI_TIMEOUT_SECONDS", "20"))


# AI 서비스에 연결하지 못했을 때 (네트워크 오류, 타임아웃)
class AiServiceUnavailable(Exception):
    pass


def request(
    method: str,
    path: str,
    *,
    params: Optional[Dict[str, Any]] = None,
    cookies: Optional[Dict[str, str]] = None,
    with_service_token: bool = True,
) -> httpx.Response:
    headers = {}
    if with_service_token:
        headers["Authorization"] = f"Bearer {AI_SERVICE_TOKEN}"

    # 쿠키는 클라이언트 쿠키 저장소를 거치지 않고 이번 요청 헤더에만 싣는다.
    if cookies:
        headers["Cookie"] = "; ".join(f"{k}={v}" for k, v in cookies.items())

    try:
        with httpx.Client(
            base_url=AI_SERVICE_URL,
            timeout=AI_TIMEOUT_SECONDS,
            follow_redirects=False,
        ) as client:
            return client.request(method, path, params=params, headers=headers)
    except httpx.HTTPError as exc:
        raise AiServiceUnavailable() from exc
