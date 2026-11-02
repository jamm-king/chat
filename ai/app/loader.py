from datetime import datetime, timezone
import re
from uuid import UUID

from langchain_core.documents import Document

from app.notion_client import NotionClient, NotionPage, invalid_response
from app.schemas import NotionPageSummary
from app.references import extract_references


def extract_title(page: NotionPage) -> str | None:
    for prop in page.properties.values():
        if not isinstance(prop, dict) or prop.get("type") != "title":
            continue
        try:
            return "".join(
                part["plain_text"] if "plain_text" in part else part["text"]["content"]
                for part in prop["title"]
            ) or None
        except (KeyError, TypeError):
            raise invalid_response() from None
    return None


def summarize_page(page: NotionPage) -> NotionPageSummary:
    return NotionPageSummary(
        id=page.id, title=extract_title(page), url=page.url,
        last_edited_time=page.last_edited_time,
    )


def load_page(client: NotionClient, page_id: UUID) -> list[Document]:
    page = client.retrieve_page(page_id)
    content = client.retrieve_markdown(page_id)
    # Keep Markdown intact, including tables and toggles; report gaps rather than hide them.
    partial = bool(
        content.truncated or content.unknown_block_ids or content.warnings
        or re.search(r"<unknown(?:\s|/?>)", content.markdown)
    )
    return [Document(page_content=content.markdown, metadata={
        "page_id": str(page.id), "title": extract_title(page), "source": page.url,
        "last_edited_time": page.last_edited_time.isoformat(),
        "collected_at": datetime.now(timezone.utc).isoformat(),
        "sequence": 0, "content_status": "partial" if partial else "complete",
        "truncated": content.truncated,
        "unknown_block_ids": [str(item) for item in content.unknown_block_ids],
        "warnings": [item.model_dump() for item in content.warnings],
        "raw_content": content.markdown,
        "references": [item.model_dump(mode="json") for item in extract_references(content.markdown)],
    })]
