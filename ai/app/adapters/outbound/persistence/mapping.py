from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.adapters.outbound.persistence.models import NotionResource
from app.domain.documents import TextDocument
from app.domain.errors import ResourceError
from app.domain.resources import validate_parent_reference


def get_resource(session: Session, user_id: str, resource_id: str) -> NotionResource:
    resource = session.scalar(select(NotionResource).where(
        NotionResource.id == resource_id, NotionResource.user_id == user_id,
    ))
    if resource is None:
        raise ResourceError(404, "Resource not found")
    return resource


def validate_parent(session: Session, user_id: str, connection_id: str,
                    page_id: str, parent_resource_id: str | None) -> None:
    if parent_resource_id is not None:
        parent = get_resource(session, user_id, parent_resource_id)
        validate_parent_reference(parent.connection_id, parent.references, connection_id, page_id)


def build_resource(document: TextDocument, user_id: str, connection_id: str, page_id: str,
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
