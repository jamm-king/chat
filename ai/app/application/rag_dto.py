from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator, model_validator

Text = Annotated[str, StringConstraints(min_length=1, max_length=8000, pattern=r"\S")]
ResourceIds = Annotated[list[UUID], Field(max_length=100)]


class InputModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


def unique_ids(values):
    if len(values) != len(set(values)):
        raise ValueError("resourceIds must be unique")
    return values


class SearchRequest(InputModel):
    userId: UUID
    query: Text
    resourceIds: ResourceIds
    topK: int = Field(default=5, ge=1, le=20, strict=True)

    _unique = field_validator("resourceIds")(unique_ids)


class HistoryMessage(InputModel):
    role: Literal["USER", "ASSISTANT"]
    content: Text


class AnswerInput(InputModel):
    userId: UUID
    message: Text
    history: list[HistoryMessage] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def validate_history(self):
        if len(self.history) % 2 or any(
            item.role != ("USER" if index % 2 == 0 else "ASSISTANT")
            for index, item in enumerate(self.history)
        ):
            raise ValueError("history must contain completed USER/ASSISTANT pairs")
        if len(self.message) + sum(len(item.content) for item in self.history) > 32000:
            raise ValueError("message and history exceed 32000 characters")
        return self


class GeneralAnswerRequest(AnswerInput):
    mode: Literal["GENERAL"]


class ResourceAnswerRequest(AnswerInput):
    mode: Literal["RESOURCE"]
    resourceIds: ResourceIds

    _unique = field_validator("resourceIds")(unique_ids)


class AutoAnswerRequest(AnswerInput):
    mode: Literal["AUTO"]
    resourceIds: ResourceIds

    _unique = field_validator("resourceIds")(unique_ids)


AnswerRequest = Annotated[GeneralAnswerRequest | ResourceAnswerRequest | AutoAnswerRequest, Field(discriminator="mode")]


class SourceLocator(InputModel):
    type: Literal["URL"]
    url: str = Field(max_length=2048, json_schema_extra={"format": "uri"})
    section: str | None = Field(min_length=1, max_length=500)


class SearchResult(InputModel):
    resourceId: UUID
    chunkId: UUID
    title: str | None = Field(min_length=1, max_length=500)
    content: str = Field(min_length=1, max_length=8000)
    rank: int = Field(ge=1, le=20)
    locator: SourceLocator


class SearchResponse(InputModel):
    results: list[SearchResult] = Field(max_length=20)


class Citation(InputModel):
    citationId: str = Field(pattern=r"^[1-9][0-9]*$")
    resourceId: UUID
    chunkId: UUID
    title: str | None = Field(min_length=1, max_length=500)
    excerpt: str = Field(min_length=1, max_length=1000)
    locator: SourceLocator


class AnswerContext(InputModel):
    historyMessagesUsed: int = Field(ge=0, le=20)
    historyTruncated: bool


class AnswerResponse(InputModel):
    answerId: UUID
    mode: Literal["GENERAL", "RESOURCE"]
    status: Literal["ANSWERED", "INSUFFICIENT_EVIDENCE", "REFUSED"]
    content: str = Field(min_length=1, max_length=16000)
    citations: list[Citation] = Field(max_length=10)
    context: AnswerContext
    createdAt: datetime
