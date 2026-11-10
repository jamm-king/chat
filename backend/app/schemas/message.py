from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic.alias_generators import to_camel


ConversationMode = Literal["GENERAL","RESOURCE"]
RequestMode = Literal["GENERAL","RESOURCE","AUTO"]


# API 명세가 camelCase 이므로 alias 를 camelCase 로 지정
class CamelModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True
    )


# 메시지 전송 요청
class MessageCreate(CamelModel):
    mode: RequestMode = "AUTO"
    message: str = Field(min_length=1, max_length=4000)
    resource_ids: List[str] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def check_resource_ids(self):
        if not self.message.strip():
            raise ValueError("message는 공백일 수 없습니다.")

        if self.mode == "RESOURCE" and not self.resource_ids:
            raise ValueError("RESOURCE 모드에서는 resourceIds가 1개 이상 필요합니다.")

        # 중복 제거 (순서 유지)
        self.resource_ids = list(dict.fromkeys(self.resource_ids))
        return self


# 답변 출처
class CitationResponse(CamelModel):
    citation_id: str
    resource_id: str
    title: Optional[str] = None
    excerpt: str
    locator: Optional[Dict[str, Any]] = None


# 메시지 전송 응답 (POST)
class MessageAnswerResponse(CamelModel):
    answer_id: str
    mode: ConversationMode
    status: Literal["ANSWERED", "INSUFFICIENT_EVIDENCE", "REFUSED"] = "ANSWERED"
    content: str
    citations: List[CitationResponse]


# 대화 기록의 메시지 1개 (GET)
class MessageResponse(CamelModel):
    message_id: str
    role: Literal["USER", "ASSISTANT"]
    mode: ConversationMode
    content: str
    citations: List[CitationResponse]
    created_at: datetime


# 대화 기록 조회 응답 (GET)
class MessageListResponse(CamelModel):
    messages: List[MessageResponse]
