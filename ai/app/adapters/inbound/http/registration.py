"""Compatibility bridge for the deprecated synchronous registration endpoint."""
from collections.abc import Callable

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.adapters.inbound.http.schemas import NotionResourceResponse, RegisterNotionResourceRequest
from app.adapters.outbound.notion.client import NotionClient
from app.adapters.outbound.notion.loader import load_page
from app.adapters.outbound.persistence.mapping import build_resource, validate_parent
from app.adapters.outbound.persistence.models import NotionResource
from app.domain.errors import ResourceError


def persist_legacy_resource(ingestions, session, resource):
    # Share the use case publication gate; a late legacy request cannot restore deleted data.
    with ingestions.lock:
        if (resource.user_id, resource.id) in ingestions.deleted_resources:
            raise ResourceError(409, "Resource was deleted")
        if (resource.user_id, resource.parent_resource_id) in ingestions.deleted_resources:
            resource.parent_resource_id = None
        else:
            validate_parent(session, resource.user_id, resource.connection_id,
                            resource.page_id, resource.parent_resource_id)
        session.add(resource)
        session.commit()


def register_resource(
    session: Session, client: NotionClient, user_id: str, connection_id: str,
    request: RegisterNotionResourceRequest,
    persist: Callable[[Session, NotionResource], None] | None = None,
) -> NotionResourceResponse:
    validate_parent(session, user_id, connection_id, str(request.page_id),
                    str(request.parent_resource_id) if request.parent_resource_id else None)

    existing = session.scalar(select(NotionResource.id).where(
        NotionResource.connection_id == connection_id,
        NotionResource.page_id == str(request.page_id),
    ))
    if existing is not None:
        raise ResourceError(409, "Page is already registered for this connection")

    # Legacy synchronous API. New callers use /internal/v1/ingestions and supply resourceId.
    # End the read-only admission transaction before network I/O and the finalization lock.
    session.rollback()
    document = load_page(client, request.page_id)[0]
    resource = build_resource(document, user_id, connection_id, str(request.page_id),
                              str(request.parent_resource_id) if request.parent_resource_id else None)
    try:
        if persist is None:
            session.add(resource)
            session.commit()
        else:
            persist(session, resource)
    except IntegrityError:
        session.rollback()
        raise ResourceError(409, "Resource conflicts with an existing registration") from None
    session.refresh(resource)
    return NotionResourceResponse.model_validate(resource)
