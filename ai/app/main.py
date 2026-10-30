import secrets
from contextlib import asynccontextmanager
from typing import Annotated
from urllib.parse import urlsplit
from uuid import UUID

import httpx
from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import create_engine, select
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import sessionmaker
from starlette.concurrency import run_in_threadpool

from app.config import Settings
from app.db import NotionConnection, init_db, save_connection
from app.notion_auth import (
    NotionOAuthError, OAuthStateStore, consume_state, create_authorization_url,
    encrypt_token, exchange_code,
)
from app.schemas import AuthorizationResponse, ConnectionResponse

COOKIE_NAME = "notion_oauth_browser"
COOKIE_PATH = "/integrations/notion/callback"
bearer = HTTPBearer(auto_error=False)


def create_app(settings: Settings | None = None, *, engine: Engine | None = None,
               notion_client: httpx.Client | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        config = settings or Settings()
        db_engine = engine if engine is not None else create_engine(
            config.database_url.get_secret_value(), hide_parameters=True
        )
        client = notion_client if notion_client is not None else httpx.Client(
            timeout=config.notion_timeout_seconds, follow_redirects=False,
            transport=httpx.HTTPTransport(retries=0),
        )
        app.state.settings = config
        app.state.sessions = sessionmaker(db_engine, expire_on_commit=False)
        app.state.oauth_states = OAuthStateStore()
        app.state.notion_client = client
        try:
            await run_in_threadpool(init_db, db_engine)
            yield
        finally:
            if notion_client is None:
                client.close()
            if engine is None:
                db_engine.dispose()

    app = FastAPI(title="찾", lifespan=lifespan)

    def require_service_token(
        request: Request,
        credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
    ) -> None:
        config = request.app.state.settings
        if credentials is None or not secrets.compare_digest(
            credentials.credentials.encode(), config.ai_service_token.get_secret_value().encode()
        ):
            raise HTTPException(401, "Invalid service token", headers={"WWW-Authenticate": "Bearer"})

    @app.get("/integrations/notion/authorize", response_model=AuthorizationResponse,
             dependencies=[Depends(require_service_token)])
    def authorize_notion(request: Request, user_id: Annotated[UUID, Query(alias="userId")]):
        config = request.app.state.settings
        url, browser_token = create_authorization_url(config, request.app.state.oauth_states, str(user_id))
        response = JSONResponse({"authorization_url": url}, headers={"Cache-Control": "no-store"})
        response.set_cookie(
            COOKIE_NAME, browser_token, max_age=config.oauth_state_ttl_seconds,
            httponly=True, samesite="lax", path=COOKIE_PATH,
            secure=config.oauth_cookie_secure or urlsplit(config.notion_redirect_uri).scheme == "https",
        )
        return response

    @app.get("/integrations/notion/callback", response_model=ConnectionResponse)
    def notion_callback(
        request: Request, state: Annotated[str, Query(min_length=1, max_length=256)],
        code: Annotated[str | None, Query(max_length=4096)] = None,
        error: Annotated[str | None, Query(max_length=256)] = None,
    ):
        headers = {"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"}

        def result(data, status_code=200):
            response = JSONResponse(data, status_code=status_code, headers=headers)
            response.delete_cookie(COOKIE_NAME, path=COOKIE_PATH)
            return response

        try:
            user_id = consume_state(request.app.state.oauth_states, state, request.cookies.get(COOKIE_NAME))
        except NotionOAuthError:
            return result({"detail": "Invalid, expired or mismatched OAuth state"}, 400)
        if error is not None:
            return result({"detail": "Notion authorization was denied or cancelled"}, 400)
        if not code:
            return result({"detail": "Authorization code is required"}, 400)
        config = request.app.state.settings
        try:
            token = exchange_code(config, request.app.state.notion_client, code)
        except NotionOAuthError as exc:
            return result({"detail": str(exc)}, 502)
        key = config.token_encryption_key.get_secret_value()
        try:
            with request.app.state.sessions() as session:
                connection = save_connection(
                    session, user_id, token,
                    encrypt_token(token.access_token.get_secret_value(), key),
                    encrypt_token(token.refresh_token.get_secret_value(), key) if token.refresh_token else None,
                )
                output = ConnectionResponse.model_validate(connection).model_dump(mode="json")
        except SQLAlchemyError:
            return result({"detail": "Connection could not be saved; start authorization again"}, 503)
        return result(output)

    @app.get("/integrations/notion/connections", response_model=list[ConnectionResponse],
             dependencies=[Depends(require_service_token)])
    def list_connections(request: Request, user_id: Annotated[UUID, Query(alias="userId")]):
        with request.app.state.sessions() as session:
            connections = session.scalars(select(NotionConnection).where(NotionConnection.user_id == str(user_id))).all()
            return JSONResponse(
                [ConnectionResponse.model_validate(item).model_dump(mode="json") for item in connections],
                headers={"Cache-Control": "no-store"},
            )

    return app


app = create_app()
