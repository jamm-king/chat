import json
from uuid import uuid4

import httpx
import pytest

from app.adapters.outbound.langchain.answers import LangChainAnswerGenerator
from app.domain.errors import RagError
from app.domain.retrieval import GenerationInput, RetrievedChunk
from test_answer_provider import response_payload, settings


def tool_payload(args=None, name="search_resources"):
    payload = response_payload()
    payload["output"] = [{"type": "function_call", "id": "fc_test", "call_id": "call_test",
                          "name": name, "arguments": json.dumps(args if args is not None else {
                              "query": "프로젝트 준비물", "top_k": 5}), "status": "completed"}]
    return payload


def final_payload(chunk):
    return response_payload([{"type": "output_text", "annotations": [], "text": json.dumps({
        "status": "ANSWERED", "content": "준비물은 노트북입니다.[1]",
        "citations": [{"chunkId": chunk.chunk_id, "excerpt": "노트북"}],
    })}])


def evidence():
    return RetrievedChunk(str(uuid4()), str(uuid4()), "준비물", "노트북과 충전기", "https://example.com")


def test_auto_direct_answer_is_one_call_without_search():
    calls = []
    def handler(request):
        calls.append(json.loads(request.content))
        return httpx.Response(200, json=response_payload())
    def search(*args):
        pytest.fail("Direct general answers must not search")
    with httpx.Client(transport=httpx.MockTransport(handler)) as http:
        generator = LangChainAnswerGenerator(settings(), http)
        answer = generator.generate_auto(GenerationInput("AUTO", "안녕", [], []), search, lambda: None)
    assert answer.status == "ANSWERED" and answer.citations == []
    assert len(calls) == 1
    payload = calls[0]
    assert payload["parallel_tool_calls"] is False and payload["store"] is False
    assert payload["include"] == ["reasoning.encrypted_content"]
    assert len(payload["tools"]) == 1
    tool = payload["tools"][0]
    assert tool["name"] == "search_resources" and tool["strict"] is True
    assert set(tool["parameters"]["properties"]) == {"query", "top_k"}
    assert "userId" not in json.dumps(tool) and "resourceIds" not in json.dumps(tool)


def test_auto_executes_tool_once_and_passes_function_output_and_reasoning_to_final_call():
    calls, searches = [], []
    chunk = evidence()
    first = tool_payload()
    first["output"].insert(0, {"type": "reasoning", "id": "rs_test", "summary": [],
                               "encrypted_content": "opaque-encrypted-reasoning"})

    def handler(request):
        calls.append(json.loads(request.content))
        return httpx.Response(200, json=first if len(calls) == 1 else final_payload(chunk))

    def search(query, top_k, continuation_bytes):
        searches.append((query, top_k, continuation_bytes))
        return GenerationInput("RESOURCE", "그 준비물은?", [], [chunk])

    with httpx.Client(transport=httpx.MockTransport(handler)) as http:
        answer = LangChainAnswerGenerator(settings(), http).generate_auto(
            GenerationInput("AUTO", "그 준비물은?", [("USER", "프로젝트 일정"), ("ASSISTANT", "준비 중입니다")], []),
            search, lambda: None,
        )
    assert answer.citations[0].chunk_id == chunk.chunk_id
    assert len(calls) == 2 and len(searches) == 1 and searches[0][:2] == ("프로젝트 준비물", 5)
    assert searches[0][2] > 0
    assert not calls[1].get("tools") and calls[1]["store"] is False
    items = calls[1]["input"]
    assert any(item.get("type") == "function_call" and item["call_id"] == "call_test" for item in items)
    output = next(item for item in items if item.get("type") == "function_call_output")
    assert output["call_id"] == "call_test" and chunk.chunk_id in output["output"]
    assert any(item.get("encrypted_content") == "opaque-encrypted-reasoning" for item in items)


def test_auto_empty_search_does_not_make_a_second_model_call():
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(200, json=tool_payload())
    with httpx.Client(transport=httpx.MockTransport(handler)) as http:
        answer = LangChainAnswerGenerator(settings(), http).generate_auto(
            GenerationInput("AUTO", "자료 질문", [], []),
            lambda *args: GenerationInput("RESOURCE", "자료 질문", [], []), lambda: None,
        )
    assert answer.status == "INSUFFICIENT_EVIDENCE" and not answer.citations and len(calls) == 1


@pytest.mark.parametrize("payload", [
    tool_payload(name="delete_resource"),
    tool_payload({"query": "q", "top_k": 1, "userId": str(uuid4())}),
    tool_payload({"query": "q", "top_k": 1, "resourceIds": [str(uuid4())]}),
    tool_payload({"query": " ", "top_k": 1}),
    tool_payload({"query": "q", "top_k": 11}),
    tool_payload({"query": "q", "top_k": True}),
    tool_payload({"query": "q"}),
])
def test_invalid_tool_calls_never_reach_server_search(payload):
    def handler(request):
        return httpx.Response(200, json=payload)
    def search(*args):
        pytest.fail("Invalid or unauthorized tool arguments must never execute")
    with httpx.Client(transport=httpx.MockTransport(handler)) as http:
        with pytest.raises(RagError) as error:
            LangChainAnswerGenerator(settings(), http).generate_auto(GenerationInput("AUTO", "q", [], []), search, lambda: None)
    assert error.value.code == "AI_PROVIDER_ERROR"


def test_multiple_tool_calls_are_rejected_before_any_search():
    payload = tool_payload()
    payload["output"].append({**payload["output"][0], "id": "fc_second", "call_id": "call_second"})
    def handler(request):
        return httpx.Response(200, json=payload)
    def search(*args):
        pytest.fail("Multiple tool calls must not execute")
    with httpx.Client(transport=httpx.MockTransport(handler)) as http:
        with pytest.raises(RagError):
            LangChainAnswerGenerator(settings(), http).generate_auto(GenerationInput("AUTO", "q", [], []), search, lambda: None)


def test_final_response_cannot_request_another_tool():
    calls, searches = [], []
    chunk = evidence()
    def handler(request):
        calls.append(request)
        return httpx.Response(200, json=tool_payload())
    def search(*args):
        searches.append(args)
        return GenerationInput("RESOURCE", "q", [], [chunk])
    with httpx.Client(transport=httpx.MockTransport(handler)) as http:
        with pytest.raises(RagError):
            LangChainAnswerGenerator(settings(), http).generate_auto(GenerationInput("AUTO", "q", [], []), search, lambda: None)
    assert len(searches) == 1 and len(calls) == 2


def test_search_failures_propagate_without_general_fallback_or_second_model_call():
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(200, json=tool_payload())
    def search(*args):
        raise RagError(409, "RESOURCE_SCOPE_CHANGED", "Resource scope changed")
    with httpx.Client(transport=httpx.MockTransport(handler)) as http:
        with pytest.raises(RagError) as error:
            LangChainAnswerGenerator(settings(), http).generate_auto(GenerationInput("AUTO", "q", [], []), search, lambda: None)
    assert error.value.code == "RESOURCE_SCOPE_CHANGED" and len(calls) == 1


def test_concurrent_auto_requests_keep_tools_and_evidence_isolated():
    import threading
    from concurrent.futures import ThreadPoolExecutor
    barrier = threading.Barrier(2, timeout=3)
    chunks = {name: evidence() for name in ("question-a", "question-b")}

    def handler(request):
        payload = json.loads(request.content)
        output = next((item for item in payload["input"] if item.get("type") == "function_call_output"), None)
        if output is not None:
            name = output["call_id"].removeprefix("call-")
            assert chunks[name].chunk_id in output["output"]
            assert chunks["question-b" if name == "question-a" else "question-a"].chunk_id not in output["output"]
            return httpx.Response(200, json=final_payload(chunks[name]))
        content = payload["input"][-1]["content"]
        if isinstance(content, list):
            content = "".join(item["text"] for item in content)
        name = json.loads(content)["question"]
        response = tool_payload({"query": name, "top_k": 5})
        response["output"][0].update(id="fc-" + name, call_id="call-" + name)
        barrier.wait()
        return httpx.Response(200, json=response)

    with httpx.Client(transport=httpx.MockTransport(handler)) as http:
        provider = LangChainAnswerGenerator(settings(), http)
        def invoke(name):
            def search(query, top_k, _):
                assert query == name
                return GenerationInput("RESOURCE", name, [], [chunks[name]])
            return provider.generate_auto(GenerationInput("AUTO", name, [], []), search, lambda: None)
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = {name: pool.submit(invoke, name) for name in chunks}
            for name, future in futures.items():
                assert future.result(5).citations[0].chunk_id == chunks[name].chunk_id
