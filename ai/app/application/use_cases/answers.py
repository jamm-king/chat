import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import uuid4

from app.application.ports.retrieval import AnswerGenerator, RetrievalOptions
from app.application.rag_dto import (
    AnswerContext, AnswerRequest, AnswerResponse, Citation, ResourceAnswerRequest, SearchRequest,
)
from app.application.use_cases.retrieval import ScopeSnapshot, SearchResources, locator
from app.domain.errors import RagError
from app.domain.retrieval import GeneratedAnswer, GenerationInput

REFERENCES = re.compile(r"\[([0-9]+)\]")
INSUFFICIENT = "선택한 자료에서 질문에 답할 충분한 근거를 찾지 못했습니다."


@dataclass(frozen=True)
class AnswerExecution:
    response: AnswerResponse
    scope: ScopeSnapshot | None


def invalid_output():
    return RagError(502, "AI_PROVIDER_ERROR", "Answer provider returned an invalid response")


def truncate_content(content: str) -> str:
    if len(content) <= 16000:
        return content
    prefix = content[:16000]
    boundaries = list(re.finditer(r"[.!?。](?:\[[1-9][0-9]*\])*(?=\s|$)|\n", prefix))
    end = boundaries[-1].end() if boundaries else max(prefix.rfind(" "), 0)
    prefix = prefix[:end] if end else prefix
    return re.sub(r"\[[0-9]*$", "", prefix).rstrip()


class GenerateAnswer:
    def __init__(self, options: RetrievalOptions, search: SearchResources, generator: AnswerGenerator | None):
        self.options, self.search, self.generator = options, search, generator
        self.access = search.access

    def _response(self, mode, status, content, citations, used=0, truncated=False):
        return AnswerResponse(answerId=uuid4(), mode=mode, status=status, content=content, citations=citations,
                              context=AnswerContext(historyMessagesUsed=used, historyTruncated=truncated),
                              createdAt=datetime.now(timezone.utc))

    def _plan(self, request, chunks):
        # A conservative UTF-8 byte budget also bounds token count. Reserve room for instructions/schema.
        budget = self.options.answer_context_budget_bytes - 4096
        history = [(item.role, item.content) for item in request.history]

        def size(evidence, messages):
            data = {"message": request.message, "history": messages,
                    "evidence": [{"chunkId": item.chunk_id, "content": item.content} for item in evidence]}
            return len(json.dumps(data, ensure_ascii=False).encode("utf-8"))

        if size([], []) > budget:
            raise RagError(400, "CONTEXT_LIMIT_EXCEEDED", "Question exceeds the context budget")
        evidence = []
        for chunk in chunks:
            if size([*evidence, chunk], []) <= budget:
                evidence.append(chunk)
        while history and size(evidence, history) > budget:
            history = history[2:]
        return GenerationInput(request.mode, request.message, history, evidence)

    def _validate(self, mode, draft: GeneratedAnswer, evidence):
        if draft.status not in {"ANSWERED", "REFUSED", "INSUFFICIENT_EVIDENCE"} or not draft.content.strip():
            raise invalid_output()
        if mode == "GENERAL" and draft.status == "INSUFFICIENT_EVIDENCE":
            raise invalid_output()
        citations = []
        if mode != "RESOURCE" or draft.status != "ANSWERED":
            if draft.citations or REFERENCES.search(draft.content):
                raise invalid_output()
        else:
            if not 1 <= len(draft.citations) <= 10:
                raise invalid_output()
            by_id = {chunk.chunk_id: chunk for chunk in evidence}
            seen = set()
            for number, citation in enumerate(draft.citations, 1):
                chunk = by_id.get(citation.chunk_id)
                if chunk is None or citation.chunk_id in seen or not 1 <= len(citation.excerpt) <= 1000:
                    raise invalid_output()
                if not citation.excerpt.strip() or citation.excerpt not in chunk.content:
                    raise invalid_output()
                seen.add(citation.chunk_id)
                citations.append(Citation(citationId=str(number), resourceId=chunk.resource_id, chunkId=chunk.chunk_id,
                                          title=chunk.title[:500] if chunk.title else None,
                                          excerpt=citation.excerpt, locator=locator(chunk)))
            if set(REFERENCES.findall(draft.content)) != {str(i) for i in range(1, len(citations) + 1)}:
                raise invalid_output()
        content = truncate_content(draft.content)
        if not content.strip():
            raise invalid_output()
        used = set(REFERENCES.findall(content))
        citations = [citation for citation in citations if citation.citationId in used]
        mapping = {citation.citationId: str(index) for index, citation in enumerate(citations, 1)}
        content = REFERENCES.sub(lambda match: "[" + mapping[match[1]] + "]", content) if citations else content
        citations = [citation.model_copy(update={"citationId": mapping[citation.citationId]}) for citation in citations]
        if mode == "RESOURCE" and draft.status == "ANSWERED" and not citations:
            return "INSUFFICIENT_EVIDENCE", INSUFFICIENT, []
        return draft.status, content, citations

    def execute(self, request: AnswerRequest, check_active=lambda: None) -> AnswerExecution:
        check_active()
        scope, chunks = None, []
        if isinstance(request, ResourceAnswerRequest):
            if not request.resourceIds:
                return AnswerExecution(self._response(request.mode, "INSUFFICIENT_EVIDENCE", INSUFFICIENT, []), None)
            result = self.search.execute(SearchRequest(userId=request.userId, query=request.message,
                                                       resourceIds=request.resourceIds, topK=10), check_active)
            scope, chunks = result.scope, result.chunks
        plan = self._plan(request, chunks)
        if request.mode == "RESOURCE" and not plan.evidence:
            return AnswerExecution(self._response(request.mode, "INSUFFICIENT_EVIDENCE", INSUFFICIENT, []), scope)
        if self.generator is None:
            raise RagError(409, "OPERATION_NOT_AVAILABLE", "Answer generation is not configured")
        self.access.finalize(scope, lambda: None)
        check_active()
        draft = self.generator.generate(plan)
        check_active()
        status, content, citations = self._validate(request.mode, draft, plan.evidence)
        response = self._response(request.mode, status, content, citations, len(plan.history),
                                  len(plan.history) < len(request.history))
        self.access.finalize(scope, lambda: None)
        return AnswerExecution(response, scope)
