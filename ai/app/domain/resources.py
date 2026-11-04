from app.domain.errors import ResourceError


def validate_parent_reference(parent_connection_id: str, references: list[dict],
                              connection_id: str, page_id: str) -> None:
    if parent_connection_id != connection_id:
        raise ResourceError(400, "Parent must use the same Notion connection")
    if not any(reference["kind"] == "page" and reference["can_register"]
               and reference["page_id"] == page_id for reference in references):
        raise ResourceError(400, "Selected page is not a registrable reference of the parent")
