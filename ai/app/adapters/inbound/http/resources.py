import asyncio
from collections.abc import Callable
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import Response
from app.domain.errors import StorageError

from app.adapters.inbound.http.ingestions import error_response

DELETE_TIMEOUT_SECONDS = 10


def create_resource_router(require_service_token: Callable) -> APIRouter:
    router = APIRouter(prefix="/internal/v1/resources", tags=["Resources"],
                       dependencies=[Depends(require_service_token)])

    @router.delete("/{resource_id}", status_code=204, response_class=Response)
    async def delete_resource(request: Request, resource_id: UUID, userId: UUID = Query()):
        try:
            await asyncio.wait_for(
                asyncio.to_thread(request.app.state.ingestions.delete, resource_id, userId),
                timeout=DELETE_TIMEOUT_SECONDS,
            )
        except TimeoutError:
            return error_response(request, 504, "RESOURCE_DELETE_TIMEOUT", "Resource deletion timed out", True)
        except StorageError:
            return error_response(request, 503, "RESOURCE_DELETE_FAILED", "Resource deletion could not be completed", True)
        return Response(status_code=204)

    return router
