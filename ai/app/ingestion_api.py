from collections.abc import Callable
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError
from starlette.background import BackgroundTask
from starlette.concurrency import run_in_threadpool

from app.ingestion import IngestionError, TERMINAL
from app.ingestion_schemas import IngestionJob, IngestionRequest


def error_response(request: Request, status: int, code: str, message: str,
                   retryable: bool = False, details: list | None = None) -> JSONResponse:
    request_id = getattr(request.state, "request_id", str(uuid4()))
    return JSONResponse(
        {"error": {"code": code, "message": message, "retryable": retryable, "details": details or []},
         "requestId": request_id}, status_code=status,
        headers={"X-Request-Id": request_id, "Cache-Control": "no-store"},
    )


def is_internal_request(request: Request) -> bool:
    return any(request.url.path == prefix or request.url.path.startswith(prefix + "/")
               for prefix in ("/internal/v1/ingestions", "/internal/v1/resources"))


async def internal_headers(request: Request, call_next):
    if not is_internal_request(request):
        return await call_next(request)
    request.state.request_id = str(uuid4())
    if supplied := request.headers.get("X-Request-Id"):
        try:
            request.state.request_id = str(UUID(supplied))
        except ValueError:
            return error_response(request, 400, "INVALID_REQUEST", "X-Request-Id must be a UUID")
    if request.method == "POST":
        # Bound the body before FastAPI parses it. This API only accepts small metadata requests.
        try:
            declared = int(request.headers.get("Content-Length", "0"))
        except ValueError:
            return error_response(request, 400, "INVALID_REQUEST", "Invalid Content-Length")
        if declared > 256 * 1024 or len(await request.body()) > 256 * 1024:
            return error_response(request, 413, "REQUEST_TOO_LARGE", "Request body exceeds 256 KiB")
        if request.headers.get("Content-Type", "").split(";", 1)[0].strip().lower() != "application/json":
            return error_response(request, 415, "UNSUPPORTED_MEDIA_TYPE", "Content-Type must be application/json")
        if request.query_params:
            return error_response(request, 400, "INVALID_REQUEST", "POST inputs must be in the JSON body")
    elif request.method in {"GET", "DELETE"}:
        if any(key != "userId" for key in request.query_params) or len(request.query_params.getlist("userId")) > 1:
            return error_response(request, 400, "INVALID_REQUEST", "Only one userId query parameter is allowed")
        if await request.body():
            return error_response(request, 400, "INVALID_REQUEST", "GET/DELETE do not accept a body")
    try:
        response = await call_next(request)
    except Exception:
        return error_response(request, 500, "INTERNAL_ERROR", "Request could not be processed")
    response.headers["X-Request-Id"] = request.state.request_id
    response.headers["Cache-Control"] = "no-store"
    return response


def create_ingestion_router(require_service_token: Callable) -> APIRouter:
    router = APIRouter(prefix="/internal/v1/ingestions", tags=["Ingestions"],
                       dependencies=[Depends(require_service_token)])

    @router.post("", response_model=IngestionJob, status_code=202)
    async def create_ingestion(request: Request, body: IngestionRequest):
        try:
            job, created = await run_in_threadpool(request.app.state.ingestions.submit, body)
        except IngestionError as exc:
            return error_response(request, exc.status, exc.code, str(exc), exc.retryable)
        except SQLAlchemyError:
            return error_response(request, 503, "AI_SERVICE_UNAVAILABLE", "Resource storage is unavailable", True)
        headers = {"Location": f"/internal/v1/ingestions/{job.jobId}?userId={job.userId}"}
        if job.status not in TERMINAL:
            headers["Retry-After"] = "2"
        return JSONResponse(
            job.model_dump(mode="json"), status_code=202 if created else 200, headers=headers,
            background=BackgroundTask(request.app.state.ingestions.start, job.jobId) if created else None,
        )

    @router.get("/{job_id}", response_model=IngestionJob)
    async def get_ingestion(request: Request, job_id: UUID, userId: UUID = Query()):
        try:
            job = await run_in_threadpool(request.app.state.ingestions.get, job_id, userId)
        except IngestionError as exc:
            return error_response(request, exc.status, exc.code, str(exc), exc.retryable)
        return JSONResponse(job.model_dump(mode="json"),
                            headers={"Retry-After": "2"} if job.status not in TERMINAL else {})

    return router
