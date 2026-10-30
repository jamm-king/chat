from datetime import datetime

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

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
) -> NotionResourceResponse:
    if request.parent_resource_id is not None:
        parent = get_resource(session, user_id, str(request.parent_resource_id))
        if parent.connection_id != connection_id:
            raise HTTPException(400, "Parent must use the same Notion connection")
        if not any(
            reference["kind"] == "page" and reference["can_register"]
            and reference["page_id"] == str(request.page_id)
            for reference in parent.references
        ):
            raise HTTPException(400, "Selected page is not a registrable reference of the parent")

    existing = session.scalar(select(NotionResource.id).where(
        NotionResource.connection_id == connection_id,
        NotionResource.page_id == str(request.page_id),
    ))
    if existing is not None:
        raise HTTPException(409, "Page is already registered for this connection")

    # Fetch exactly this page. References are recorded but never followed here.
    document = load_page(client, request.page_id)[0]
    metadata = document.metadata
    resource = NotionResource(
        user_id=user_id, connection_id=connection_id, page_id=str(request.page_id),
        parent_resource_id=str(request.parent_resource_id) if request.parent_resource_id else None,
        title=metadata["title"], url=metadata["source"],
        raw_content=metadata["raw_content"], content=document.page_content,
        content_status=metadata["content_status"], references=metadata["references"],
        truncated=metadata["truncated"], unknown_block_ids=metadata["unknown_block_ids"],
        warnings=metadata["warnings"],
        source_updated_at=datetime.fromisoformat(metadata["last_edited_time"]),
        collected_at=datetime.fromisoformat(metadata["collected_at"]),
    )
    session.add(resource)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        raise HTTPException(409, "Resource conflicts with an existing registration") from None
    session.refresh(resource)
    return NotionResourceResponse.model_validate(resource)
