from datetime import datetime
from collections.abc import Callable

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from langchain_core.documents import Document

from app.db import NotionResource
from app.loader import load_page
from app.notion_client import NotionClient
from app.schemas import NotionResourceResponse, RegisterNotionResourceRequest


def get_resource(session: Session, user_id: str, resource_id: str) -> NotionResource:
    resource = session.scalar(select(NotionResource).where(
        NotionResource.id == resource_id, NotionResource.user_id == user_id,
    ))
    if resource is None:
        raise HTTPException(404, "Resource not found")
    return resource


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
        raise HTTPException(409, "Page is already registered for this connection")

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
        raise HTTPException(409, "Resource conflicts with an existing registration") from None
    session.refresh(resource)
    return NotionResourceResponse.model_validate(resource)


def validate_parent(session: Session, user_id: str, connection_id: str,
                    page_id: str, parent_resource_id: str | None) -> None:
    if parent_resource_id is not None:
        parent = get_resource(session, user_id, parent_resource_id)
        if parent.connection_id != connection_id:
            raise HTTPException(400, "Parent must use the same Notion connection")
        if not any(
            reference["kind"] == "page" and reference["can_register"]
            and reference["page_id"] == page_id
            for reference in parent.references
        ):
            raise HTTPException(400, "Selected page is not a registrable reference of the parent")


def build_resource(document: Document, user_id: str, connection_id: str, page_id: str,
                   parent_resource_id: str | None, resource_id: str | None = None) -> NotionResource:
    metadata = document.metadata
    resource = NotionResource(
        user_id=user_id, connection_id=connection_id, page_id=page_id,
        parent_resource_id=parent_resource_id,
        title=metadata["title"], url=metadata["source"],
        raw_content=metadata["raw_content"], content=document.page_content,
        content_status=metadata["content_status"], references=metadata["references"],
        truncated=metadata["truncated"], unknown_block_ids=metadata["unknown_block_ids"],
        warnings=metadata["warnings"],
        source_updated_at=datetime.fromisoformat(metadata["last_edited_time"]),
        collected_at=datetime.fromisoformat(metadata["collected_at"]),
    )
    if resource_id is not None:
        resource.id = resource_id
    return resource
