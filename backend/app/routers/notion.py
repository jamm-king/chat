"""
노션 OAuth 연동 중계 라우터.

연동 계약: ai/docs/api/notion-oauth.md
Frontend 명세: frontend_api_reference_v2.0.md [3.2] 노션 연결
OAuth 처리(state 발급·검증, 토큰 교환, 토큰 암호화 저장)는 AI 서비스가 맡고,
Backend 는 로그인 사용자 확인 + AI 호출 + 쿠키/콜백 중계만 한다.

흐름
1. Frontend → POST /api/v1/integrations/notion/authorize (로그인 토큰)
   Backend 가 AI 에 userId 를 넘기고, 받은 authorizationUrl 과 Set-Cookie 를 그대로 돌려준다.
2. Frontend 는 같은 브라우저에서 authorizationUrl 로 이동해 노션 권한을 허용한다.
3. Notion → 브라우저 → GET /integrations/notion/callback (Backend)
   Backend 는 state/code/error 와 notion_oauth_browser 쿠키만 AI 로 전달하고,
   결과에 따라 Frontend 화면(/notion/callback?status=...)으로 이동시킨다.
4. Frontend → GET /api/v1/integrations/notion/connections 로 연결 상태를 확인한다.
"""
import logging
import os
from typing import Optional
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, Query, Request, status
from fastapi.responses import JSONResponse, RedirectResponse

from app.core.deps import get_current_user
from app.core.errors import AppError
from app.models.users import User
from app.schemas.notion import (
    NotionAuthorizeResponse,
    NotionConnectionListResponse,
    NotionConnectionResponse,
)
from app.services import ai_client


logger = logging.getLogger(__name__)

# AI 서비스가 발급하는 브라우저 바인딩 쿠키 (계약 문서 기준, 변경 시 AI 와 함께 맞춘다)
OAUTH_COOKIE_NAME = "notion_oauth_browser"
OAUTH_COOKIE_PATH = "/integrations/notion/callback"

# 콜백 처리 후 브라우저를 보낼 Frontend 주소
NOTION_CONNECT_RESULT_URL = os.getenv(
    "NOTION_CONNECT_RESULT_URL",
    "http://localhost:5173/notion/callback"
)

NO_STORE = {"Cache-Control": "no-store"}


api_router = APIRouter(
    prefix="/api/v1/integrations/notion",
    tags=["Notion"]
)

# 노션에 등록된 redirect URI 와 쿠키 path 가 /integrations/notion/callback 이므로 /api/v1 을 붙이지 않는다.
callback_router = APIRouter(
    prefix="/integrations/notion",
    tags=["Notion"]
)


def _call_ai(method: str, path: str, **kwargs) -> httpx.Response:
    try:
        return ai_client.request(method, path, **kwargs)
    except ai_client.AiServiceUnavailable:
        raise AppError(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "AI_SERVICE_UNAVAILABLE",
            "AI 서비스에 연결할 수 없습니다. 잠시 후 다시 시도해주세요.",
            retryable=True,
        )


def _raise_ai_error(upstream: httpx.Response):
    # 401 은 Backend 의 AI_SERVICE_TOKEN 설정 오류이므로 사용자 인증 오류와 구분해 502 로 응답한다.
    logger.warning("AI service %s returned %s", upstream.request.url.path, upstream.status_code)
    raise AppError(
        status.HTTP_502_BAD_GATEWAY,
        "AI_SERVICE_ERROR",
        "AI 서비스 처리 중 오류가 발생했습니다.",
        retryable=upstream.status_code >= 500,
    )


def _relay_set_cookies(upstream: httpx.Response, response) -> bool:
    # Set-Cookie 는 하나씩 별도 헤더로 전달한다. (콤마로 합치면 안 됨)
    cookies = upstream.headers.get_list("set-cookie")
    for cookie in cookies:
        response.headers.append("set-cookie", cookie)
    return bool(cookies)


# 1. 노션 연결 시작 (권한 허용 주소 발급)
# 호출할 때마다 새 OAuth state 와 쿠키가 발급되므로 POST 로 받는다. (AI 호출은 계약대로 GET)
@api_router.post("/authorize", response_model=NotionAuthorizeResponse)
def authorize_notion(current_user: User = Depends(get_current_user)):
    upstream = _call_ai(
        "GET",
        "/integrations/notion/authorize",
        params={"userId": current_user.id},
    )
    if upstream.status_code != 200:
        _raise_ai_error(upstream)

    body = NotionAuthorizeResponse(
        authorization_url=upstream.json()["authorization_url"]
    )
    response = JSONResponse(
        body.model_dump(by_alias=True),
        headers=NO_STORE,
    )
    _relay_set_cookies(upstream, response)
    return response


# 2. 노션 연결 상태 조회
@api_router.get("/connections", response_model=NotionConnectionListResponse)
def list_notion_connections(current_user: User = Depends(get_current_user)):
    upstream = _call_ai(
        "GET",
        "/integrations/notion/connections",
        params={"userId": current_user.id},
    )
    if upstream.status_code != 200:
        _raise_ai_error(upstream)

    body = NotionConnectionListResponse(
        connections=[
            NotionConnectionResponse(
                connection_id=item["id"],
                workspace_name=item.get("workspace_name"),
                status="CONNECTED",
                created_at=item["created_at"],
            )
            for item in upstream.json()
        ]
    )
    return JSONResponse(
        body.model_dump(mode="json", by_alias=True),
        headers=NO_STORE,
    )


# AI 콜백 결과 → Frontend 에 전달할 reason
# denied  : 사용자가 노션 화면에서 취소
# expired : state 만료·재사용·다른 브라우저 (AI 는 이 경우 state 검증 실패로 400 을 준다)
# failed  : 토큰 발급·저장 실패, AI 연결 실패 등 그 외
def _failure_reason(upstream: Optional[httpx.Response], has_error_param: bool) -> str:
    if upstream is None or upstream.status_code != 400:
        return "failed"

    try:
        detail = str(upstream.json().get("detail", ""))
    except ValueError:
        detail = ""

    # AI 는 state 를 먼저 검증하므로, 취소했더라도 state 가 잘못됐으면 expired 로 본다.
    if "state" in detail.lower():
        return "expired"
    if has_error_param:
        return "denied"
    return "failed"


def _redirect_to_frontend(upstream: Optional[httpx.Response], params: dict) -> RedirectResponse:
    separator = "&" if "?" in NOTION_CONNECT_RESULT_URL else "?"
    response = RedirectResponse(
        f"{NOTION_CONNECT_RESULT_URL}{separator}{urlencode(params)}",
        status_code=status.HTTP_303_SEE_OTHER,
        headers={**NO_STORE, "Referrer-Policy": "no-referrer"},
    )

    # AI 의 쿠키 삭제 헤더를 전달하고, AI 가 처리하지 못한 경우(422, 연결 실패)는 직접 삭제한다.
    relayed = upstream is not None and _relay_set_cookies(upstream, response)
    if not relayed:
        response.delete_cookie(OAUTH_COOKIE_NAME, path=OAUTH_COOKIE_PATH)

    return response


# 3. 노션 OAuth 콜백 (브라우저가 노션에서 리다이렉트되어 들어오는 주소)
# 로그인 토큰이 필요 없다. 사용자는 AI 가 state 로 복원하고, 쿠키로 같은 브라우저인지 확인한다.
@callback_router.get("/callback")
def notion_callback(
    request: Request,
    state: Optional[str] = Query(default=None),
    code: Optional[str] = Query(default=None),
    error: Optional[str] = Query(default=None),
):
    params = {
        key: value
        for key, value in (("state", state), ("code", code), ("error", error))
        if value is not None
    }
    # Chat 로그인 쿠키 등 다른 쿠키는 넘기지 않는다.
    browser_cookie = request.cookies.get(OAUTH_COOKIE_NAME)
    cookies = {OAUTH_COOKIE_NAME: browser_cookie} if browser_cookie else None

    try:
        upstream = ai_client.request(
            "GET",
            "/integrations/notion/callback",
            params=params,
            cookies=cookies,
            with_service_token=False,
        )
    except ai_client.AiServiceUnavailable:
        logger.warning("Notion OAuth callback failed: AI service unavailable")
        return _redirect_to_frontend(None, {"status": "failed", "reason": "failed"})

    if upstream.status_code == 200:
        return _redirect_to_frontend(upstream, {"status": "connected"})

    reason = _failure_reason(upstream, error is not None)
    logger.warning("Notion OAuth callback failed with AI status %s (%s)", upstream.status_code, reason)
    return _redirect_to_frontend(upstream, {"status": "failed", "reason": reason})
