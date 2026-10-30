from collections.abc import Iterator
from datetime import datetime
from typing import Any, Literal, TypeVar
from uuid import UUID

import httpx
from pydantic import BaseModel, Field, StrictBool, ValidationError, model_validator

from app.schemas import NotionContentWarning


class NotionApiError(Exception):
    def __init__(self, status_code: int, code: str, message: str,
                 retry_after: str | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.retry_after = retry_after


def invalid_response() -> NotionApiError:
    return NotionApiError(502, "NOTION_INVALID_RESPONSE", "Notion returned an invalid response")


class NotionPage(BaseModel):
    object: Literal["page"]
    id: UUID
    url: str
    properties: dict[str, Any]
    last_edited_time: datetime
    archived: bool = False
    in_trash: bool = False


class NotionMarkdown(BaseModel):
    object: Literal["page_markdown"]
    id: UUID
    markdown: str
    truncated: StrictBool
    unknown_block_ids: list[UUID]
    warnings: list[NotionContentWarning] = Field(default_factory=list)


class PaginatedResponse(BaseModel):
    object: Literal["list"]
    has_more: StrictBool
    next_cursor: str | None

    @model_validator(mode="after")
    def validate_cursor(self):
        if self.has_more and not self.next_cursor:
            raise ValueError("Missing pagination cursor")
        return self


class NotionPageList(PaginatedResponse):
    results: list[NotionPage]


class NotionBlockList(PaginatedResponse):
    results: list[dict[str, Any]]


T = TypeVar("T", bound=BaseModel)


class NotionClient:
    """Read operations only; the shared HTTP client owns timeouts and disables retries."""

    def __init__(self, client: httpx.Client, token: str, api_version: str) -> None:
        self._client = client
        self._token = token
        self._api_version = api_version

    def _request(self, method: str, path: str, model: type[T], **kwargs) -> T:
        try:
            response = self._client.request(
                method, f"https://api.notion.com/v1/{path}",
                headers={"Authorization": f"Bearer {self._token}",
                         "Notion-Version": self._api_version},
                follow_redirects=False, **kwargs,
            )
        except httpx.TimeoutException:
            raise NotionApiError(504, "NOTION_TIMEOUT", "Notion request timed out") from None
        except httpx.RequestError:
            raise NotionApiError(502, "NOTION_UNAVAILABLE", "Notion request failed") from None

        errors = {
            400: (400, "NOTION_INVALID_REQUEST", "Notion rejected the request"),
            401: (409, "NOTION_REAUTHORIZATION_REQUIRED", "Reconnect your Notion account"),
            403: (403, "NOTION_ACCESS_DENIED", "Notion connection does not have read access"),
            404: (404, "NOTION_PAGE_NOT_FOUND", "Page does not exist or is not shared with this connection"),
            429: (429, "NOTION_RATE_LIMITED", "Notion request limit exceeded"),
            529: (503, "NOTION_OVERLOADED", "Notion is temporarily overloaded"),
        }
        if response.status_code in errors:
            wait = response.headers.get("Retry-After", "")
            wait = wait if wait.isascii() and wait.isdigit() else None
            raise NotionApiError(*errors[response.status_code], retry_after=wait)
        if not response.is_success:
            raise NotionApiError(502, "NOTION_UNAVAILABLE", "Notion request failed")
        try:
            return model.model_validate(response.json())
        except (ValidationError, ValueError):
            raise invalid_response() from None

    def search_pages(self, *, query: str | None = None, start_cursor: str | None = None,
                     page_size: int = 50) -> NotionPageList:
        payload: dict[str, Any] = {
            "filter": {"property": "object", "value": "page"}, "page_size": page_size,
            "sort": {"direction": "descending", "timestamp": "last_edited_time"},
        }
        if query:
            payload["query"] = query
        if start_cursor:
            payload["start_cursor"] = start_cursor
        return self._request("POST", "search", NotionPageList, json=payload)

    def retrieve_page(self, page_id: UUID) -> NotionPage:
        page = self._request("GET", f"pages/{page_id}", NotionPage)
        if page.id != page_id:
            raise invalid_response()
        if page.archived or page.in_trash:
            raise NotionApiError(404, "NOTION_PAGE_NOT_FOUND", "Page is archived or in trash")
        return page

    def retrieve_markdown(self, page_id: UUID) -> NotionMarkdown:
        content = self._request("GET", f"pages/{page_id}/markdown", NotionMarkdown)
        if content.id != page_id:
            raise invalid_response()
        return content

    def iter_block_children(self, block_id: UUID) -> Iterator[dict[str, Any]]:
        cursor = None
        seen: set[str] = set()
        while True:
            params: dict[str, Any] = {"page_size": 100}
            if cursor:
                params["start_cursor"] = cursor
            page = self._request("GET", f"blocks/{block_id}/children", NotionBlockList, params=params)
            yield from page.results
            if not page.has_more:
                return
            cursor = page.next_cursor
            if cursor in seen:
                raise invalid_response()
            seen.add(cursor)
