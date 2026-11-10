import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import uuid4

from app.application.ports.retrieval import AnswerGenerator, AutoAnswerGenerator, RetrievalOptions
from app.application.rag_dto import (
    AnswerContext, AnswerRequest, AnswerResponse, AutoAnswerRequest, Citation, ResourceAnswerRequest, SearchRequest,
)
from app.application.use_cases.retrieval import ScopeSnapshot, SearchResources, locator
from app.domain.errors import RagError
from app.domain.retrieval import GeneratedAnswer, GenerationInput
from app.domain.retrieval import INSUFFICIENT_EVIDENCE_TEXT as INSUFFICIENT

REFERENCES = re.compile(r"\[([0-9]+)\]")


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
    def __init__(self, options: RetrievalOptions, search: SearchResources, generator: AnswerGenerator | None,
                 auto_generator: AutoAnswerGenerator | None = None):
        self.options, self.search, self.generator = options, search, generator
        self.auto_generator = auto_generator
        self.access = search.access

    def _response(self, mode, status, content, citations, used=0, truncated=False):
        return AnswerResponse(answerId=uuid4(), mode=mode, status=status, content=content, citations=citations,
                              context=AnswerContext(historyMessagesUsed=used, historyTruncated=truncated),
                              createdAt=datetime.now(timezone.utc))

    def _plan(self, request, chunks, extra_bytes=0):
        # A conservative UTF-8 byte budget also bounds token count. Reserve room for instructions/schema.
        budget = self.options.answer_context_budget_bytes - 4096 - extra_bytes
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
        if isinstance(request, AutoAnswerRequest):
            return self._execute_auto(request, check_active)
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

    def _execute_auto(self, request: AutoAnswerRequest, check_active) -> AnswerExecution:
        if self.auto_generator is None:
            raise RagError(409, "OPERATION_NOT_AVAILABLE", "Automatic answer generation is not configured")
        ids = [str(value) for value in request.resourceIds]
        scope = self.search.capture_scope(str(request.userId), ids) if ids else None
        initial_plan = self._plan(request, [])
        final_plan, searched = initial_plan, False

        def search(query: str, top_k: int, continuation_bytes: int) -> GenerationInput:
            nonlocal final_plan, searched
            check_active()
            if searched or type(top_k) is not int or not 1 <= top_k <= 10:
                raise invalid_output()
            if not isinstance(query, str) or not query.strip() or len(query) > 8000:
                raise invalid_output()
            if type(continuation_bytes) is not int or continuation_bytes < 0:
                raise invalid_output()
            searched = True
            self.access.finalize(scope, lambda: None)
            # Check the continuation budget before paying for another provider call.
            self._plan(request, [], extra_bytes=continuation_bytes)
            try:
                result = self.search.execute(SearchRequest(userId=request.userId, query=query,
                                                           resourceIds=request.resourceIds, topK=top_k), check_active)
            except RagError as exc:
                if scope is not None and exc.code in {"RESOURCE_NOT_FOUND", "RESOURCE_NOT_READY"}:
                    raise RagError(409, "RESOURCE_SCOPE_CHANGED", "Resource scope changed") from None
                raise
            self.access.finalize(scope, lambda: None)
            final_plan = self._plan(request, result.chunks, extra_bytes=continuation_bytes)
            return GenerationInput("RESOURCE", final_plan.message, final_plan.history, final_plan.evidence)

        check_active()
        draft = self.auto_generator.generate_auto(initial_plan, search, check_active)
        check_active()
        mode = "RESOURCE" if searched else "GENERAL"
        status, content, citations = self._validate(mode, draft, final_plan.evidence)
        # AUTO reports unique history messages seen by either call and any pair truncation.
        used = max(len(initial_plan.history), len(final_plan.history))
        truncated = min(len(initial_plan.history), len(final_plan.history)) < len(request.history)
        response = self._response(mode, status, content, citations, used, truncated)
        self.access.finalize(scope, lambda: None)
        return AnswerExecution(response, scope)
