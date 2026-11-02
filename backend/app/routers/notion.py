"""
노션 OAuth 연동 중계 라우터.

연동 계약: ai/docs/api/notion-oauth.md
OAuth 처리(state 발급·검증, 토큰 교환, 토큰 암호화 저장)는 AI 서비스가 맡고,
Backend 는 로그인 사용자 확인 + AI 호출 + 쿠키/콜백 중계만 한다.

흐름
1. Frontend → POST /api/v1/integrations/notion/authorize (로그인 토큰)
   Backend 가 AI 에 userId 를 넘기고, 받은 authorizationUrl 과 Set-Cookie 를 그대로 돌려준다.
2. Frontend 는 같은 브라우저에서 authorizationUrl 로 이동해 노션 권한을 허용한다.
3. Notion → 브라우저 → GET /integrations/notion/callback (Backend)
   Backend 는 state/code/error 와 notion_oauth_browser 쿠키만 AI 로 전달한다.
4. Frontend → GET /api/v1/integrations/notion/connections 로 연결 상태를 확인한다.
"""
import logging
import os
from typing import Optional
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, Query, Request, status
from fastapi.responses import JSONResponse, RedirectResponse, Response

from app.core.deps import get_current_user
from app.core.errors import AppError, error_response
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

# 콜백 처리 후 브라우저를 보낼 Frontend 주소 (선택)
# 설정하지 않으면 콜백 결과를 JSON 으로 응답한다.
NOTION_CONNECT_RESULT_URL = os.getenv("NOTION_CONNECT_RESULT_URL", "")

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


def _connection_response(data: dict) -> NotionConnectionResponse:
    return NotionConnectionResponse(
        connection_id=data["id"],
        workspace_id=data["workspace_id"],
        workspace_name=data.get("workspace_name"),
        bot_id=data["bot_id"],
        created_at=data["created_at"],
        status=data.get("status", "connected"),
    )


def _relay_set_cookies(upstream: httpx.Response, response: Response) -> bool:
    # Set-Cookie 는 하나씩 별도 헤더로 전달한다. (콤마로 합치면 안 됨)
    cookies = upstream.headers.get_list("set-cookie")
    for cookie in cookies:
        response.headers.append("set-cookie", cookie)
    return bool(cookies)


# 1. 노션 연결 시작
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


# 2. 노션 연결 목록 조회
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
        connections=[_connection_response(item) for item in upstream.json()]
    )
    return JSONResponse(
        body.model_dump(mode="json", by_alias=True),
        headers=NO_STORE,
    )


# 콜백 실패 시 AI 상태 코드별 에러 코드
_CALLBACK_ERRORS = {
    400: ("NOTION_AUTHORIZATION_FAILED", "노션 연결이 취소되었거나 만료되었습니다. 다시 연결해주세요.", False),
    422: ("NOTION_AUTHORIZATION_FAILED", "노션 연결 요청이 올바르지 않습니다. 다시 연결해주세요.", False),
    502: ("NOTION_TOKEN_EXCHANGE_FAILED", "노션 인증 처리에 실패했습니다. 다시 연결해주세요.", True),
    503: ("NOTION_CONNECTION_SAVE_FAILED", "노션 연결 정보를 저장하지 못했습니다. 다시 연결해주세요.", True),
}


def _callback_result(
    upstream: Optional[httpx.Response],
    status_code: int,
    content: dict,
    result_params: dict,
) -> Response:
    headers = {**NO_STORE, "Referrer-Policy": "no-referrer"}

    if NOTION_CONNECT_RESULT_URL:
        separator = "&" if "?" in NOTION_CONNECT_RESULT_URL else "?"
        response: Response = RedirectResponse(
            f"{NOTION_CONNECT_RESULT_URL}{separator}{urlencode(result_params)}",
            status_code=status.HTTP_303_SEE_OTHER,
            headers=headers,
        )
    else:
        response = JSONResponse(content, status_code=status_code, headers=headers)

    # AI 의 쿠키 삭제 헤더를 전달하고, AI 가 처리하지 못한 경우(422, 연결 실패)는 직접 삭제한다.
    relayed = upstream is not None and _relay_set_cookies(upstream, response)
    if not relayed:
        response.delete_cookie(OAUTH_COOKIE_NAME, path=OAUTH_COOKIE_PATH)

    return response


# 3. 노션 OAuth 콜백 (브라우저가 노션에서 리다이렉트되어 들어오는 주소)
# 로그인 토큰이 필요 없다. 사용자는 AI 가 state 로 복원하고, 쿠키로 같은 브라우저인지 확인한다.
@callback_router.get("/callback", include_in_schema=True)
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
        return _callback_result(
            None,
            status.HTTP_503_SERVICE_UNAVAILABLE,
            error_response(
                "AI_SERVICE_UNAVAILABLE",
                "AI 서비스에 연결할 수 없습니다. 잠시 후 다시 연결해주세요.",
                retryable=True,
            ),
            {"status": "failed", "code": "AI_SERVICE_UNAVAILABLE"},
        )

    if upstream.status_code == 200:
        connection = _connection_response(upstream.json())
        return _callback_result(
            upstream,
            status.HTTP_200_OK,
            connection.model_dump(mode="json", by_alias=True),
            {"status": "connected", "connectionId": connection.connection_id},
        )

    code_name, message, retryable = _CALLBACK_ERRORS.get(
        upstream.status_code,
        ("AI_SERVICE_ERROR", "노션 연결 처리 중 오류가 발생했습니다. 다시 연결해주세요.", True),
    )
    logger.warning("Notion OAuth callback failed with AI status %s", upstream.status_code)
    return _callback_result(
        upstream,
        upstream.status_code if upstream.status_code in _CALLBACK_ERRORS else status.HTTP_502_BAD_GATEWAY,
        error_response(code_name, message, retryable=retryable),
        {"status": "failed", "code": code_name},
    )
