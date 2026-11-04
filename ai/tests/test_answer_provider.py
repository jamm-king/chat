import json
from types import SimpleNamespace

import httpx
import pytest
from pydantic import SecretStr

from app.adapters.outbound.langchain.answers import LangChainAnswerGenerator
from app.domain.errors import RagError
from app.domain.retrieval import GenerationInput


def settings():
    return SimpleNamespace(openai_api_key=SecretStr("secret-key"), answer_model="gpt-6-luna",
                           answer_provider_timeout_seconds=40, answer_max_output_tokens=4096)


def response_payload(content=None):
    if content is None:
        content = [{"type": "output_text", "annotations": [], "text": json.dumps({
            "status": "ANSWERED", "content": "안녕하세요.", "citations": [],
        })}]
    return {"id": "resp_test", "object": "response", "created_at": 0, "status": "completed",
            "model": "gpt-6-luna", "error": None, "incomplete_details": None,
            "output": [{"id": "msg_test", "type": "message", "role": "assistant", "status": "completed",
                        "content": content}], "usage": {"input_tokens": 10, "output_tokens": 10, "total_tokens": 20}}


def test_langchain_chat_uses_responses_structured_output_without_storage_or_tools():
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(200, json=response_payload())
    with httpx.Client(transport=httpx.MockTransport(handler)) as http:
        generator = LangChainAnswerGenerator(settings(), http)
        output = generator.generate(GenerationInput("GENERAL", "질문", [("USER", "이전 질문"), ("ASSISTANT", "이전 답변")], []))
    assert output.status == "ANSWERED" and output.content == "안녕하세요."
    assert len(calls) == 1 and calls[0].url == "https://api.openai.com/v1/responses"
    payload = json.loads(calls[0].content)
    assert payload["store"] is False and payload["model"] == "gpt-6-luna"
    assert payload["max_output_tokens"] == 4096 and payload["reasoning"]["effort"] == "low"
    assert payload["text"]["format"]["type"] == "json_schema" and payload["text"]["format"]["strict"] is True
    assert not payload.get("tools") and not payload.get("previous_response_id")
    assert generator.model.max_retries == 0


@pytest.mark.parametrize("status,retryable", [(400, False), (401, False), (429, True), (500, True)])
def test_chat_errors_are_sanitized_and_not_retried(status, retryable):
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(status, json={"error": {"message": "secret-key private text"}})
    with httpx.Client(transport=httpx.MockTransport(handler)) as http:
        generator = LangChainAnswerGenerator(settings(), http)
        with pytest.raises(RagError) as error:
            generator.generate(GenerationInput("GENERAL", "q", [], []))
    assert error.value.code == "AI_PROVIDER_ERROR" and error.value.retryable is retryable
    assert "secret-key" not in str(error.value) and len(calls) == 1


def test_chat_native_refusal_is_a_refused_result():
    def handler(request):
        return httpx.Response(200, json=response_payload([{"type": "refusal", "refusal": "private refusal"}]))
    with httpx.Client(transport=httpx.MockTransport(handler)) as http:
        output = LangChainAnswerGenerator(settings(), http).generate(GenerationInput("GENERAL", "q", [], []))
    assert output.status == "REFUSED" and output.citations == []


@pytest.mark.parametrize("content", ["invalid JSON", '{"status":"ANSWERED","content":"x"}'])
def test_chat_malformed_output_is_not_repaired(content):
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(200, json=response_payload([{"type": "output_text", "annotations": [], "text": content}]))
    with httpx.Client(transport=httpx.MockTransport(handler)) as http:
        with pytest.raises(RagError) as error:
            LangChainAnswerGenerator(settings(), http).generate(GenerationInput("GENERAL", "q", [], []))
    assert error.value.status == 502 and len(calls) == 1


def test_incomplete_generation_is_not_published_even_with_parseable_json():
    def handler(request):
        payload = response_payload()
        payload.update(status="incomplete", incomplete_details={"reason": "max_output_tokens"})
        return httpx.Response(200, json=payload)
    with httpx.Client(transport=httpx.MockTransport(handler)) as http:
        with pytest.raises(RagError) as error:
            LangChainAnswerGenerator(settings(), http).generate(GenerationInput("GENERAL", "q", [], []))
    assert error.value.code == "AI_PROVIDER_ERROR"
