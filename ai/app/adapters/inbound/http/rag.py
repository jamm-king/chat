import asyncio
import threading
import time
from collections.abc import Callable

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from app.adapters.inbound.http.ingestions import error_response
from app.application.rag_dto import AnswerRequest, AnswerResponse, SearchRequest, SearchResponse
from app.domain.errors import EmbeddingError, RagError, StorageError

SEARCH_TIMEOUT_SECONDS = 15
ANSWER_TIMEOUT_SECONDS = 60


async def execute(request, service, body, timeout):
    cancelled = threading.Event()
    deadline = time.monotonic() + timeout

    def check_active():
        if cancelled.is_set() or time.monotonic() >= deadline:
            raise RagError(504, "AI_SERVICE_TIMEOUT", "AI request exceeded its deadline", True)

    def run():
        outcome = service.execute(body, check_active)
        check_active()
        return service.access.finalize(outcome.scope, lambda: JSONResponse(outcome.response.model_dump(mode="json")))

    try:
        return await asyncio.wait_for(asyncio.to_thread(run), timeout=timeout)
    except TimeoutError:
        cancelled.set()
        return error_response(request, 504, "AI_SERVICE_TIMEOUT", "AI request exceeded its deadline", True)
    except asyncio.CancelledError:
        cancelled.set()
        raise
    except RagError as exc:
        return error_response(request, exc.status, exc.code, str(exc), exc.retryable)
    except EmbeddingError as exc:
        return error_response(request, 502, "AI_PROVIDER_ERROR", str(exc), exc.retryable)
    except StorageError:
        return error_response(request, 503, "AI_SERVICE_UNAVAILABLE", "Resource storage is unavailable", True)


def create_rag_router(require_service_token: Callable) -> APIRouter:
    router = APIRouter(prefix="/internal/v1", dependencies=[Depends(require_service_token)])

    @router.post("/retrieval/search", response_model=SearchResponse, tags=["Retrieval"])
    async def search(request: Request, body: SearchRequest):
        return await execute(request, request.app.state.retrieval, body, SEARCH_TIMEOUT_SECONDS)

    @router.post("/answers", response_model=AnswerResponse, tags=["Answers"])
    async def answer(request: Request, body: AnswerRequest):
        return await execute(request, request.app.state.answers, body, ANSWER_TIMEOUT_SECONDS)

    return router
