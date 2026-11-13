from types import SimpleNamespace

import pytest
from google.genai import errors as genai_errors

from app.providers.llm import gemini as gemini_module
from app.providers.llm.base import (
    LLMBlocked,
    LLMQuotaExceeded,
    LLMUnavailable,
    Message,
    ToolCall,
    ToolSpec,
)
from app.providers.llm.fake import FakeLLM, answer_from_tool, call, say
from app.providers.llm.gemini import GeminiProvider

TOOL = ToolSpec("get_remaining_stops", "stops left", {"type": "object", "properties": {}})


def provider(monkeypatch, response=None, error=None) -> GeminiProvider:
    p = GeminiProvider("test-key", "gemini-test")

    def generate_content(**kwargs):
        if error:
            raise error
        return response

    monkeypatch.setattr(p._client.models, "generate_content", generate_content)
    return p


def response(parts, block=None, usage=(10, 5)):
    return SimpleNamespace(
        prompt_feedback=SimpleNamespace(block_reason=block) if block else None,
        candidates=[SimpleNamespace(content=SimpleNamespace(parts=parts))],
        usage_metadata=SimpleNamespace(
            prompt_token_count=usage[0], candidates_token_count=usage[1]
        ),
    )


def text_part(text):
    return SimpleNamespace(function_call=None, text=text, thought_signature=None)


def call_part(name, args, signature=b"sig"):
    return SimpleNamespace(
        function_call=SimpleNamespace(name=name, args=args), text=None, thought_signature=signature
    )


def test_text_reply_and_usage(monkeypatch):
    p = provider(monkeypatch, response([text_part("Two stops "), text_part("left.")]))
    reply = p.generate("sys", [Message("user", "hi")], [TOOL])
    assert reply.text == "Two stops left." and reply.tool_calls == ()
    assert reply.usage == {"input": 10, "output": 5}


def test_tool_call_keeps_the_signature(monkeypatch):
    p = provider(monkeypatch, response([call_part("get_remaining_stops", {"after": "Beed"})]))
    reply = p.generate("sys", [Message("user", "hi")], [TOOL])
    assert reply.tool_calls == (ToolCall("get_remaining_stops", {"after": "Beed"}, b"sig"),)


def test_conversation_is_converted_with_signatures_and_results(monkeypatch):
    p = provider(monkeypatch, response([text_part("ok")]))
    contents = p._contents(
        [
            Message("user", "q"),
            Message("assistant", "", (ToolCall("t", {"a": 1}, b"sig"),)),
            Message("tool", tool_name="t", tool_result={"count": 2}),
        ]
    )
    assert [c.role for c in contents] == ["user", "model", "user"]
    assert contents[1].parts[0].thought_signature == b"sig"
    assert contents[2].parts[0].function_response.response == {"count": 2}


def api_error(code, message):
    return genai_errors.APIError(code, {"error": {"message": message, "status": "x"}})


def test_quota_errors(monkeypatch):
    with pytest.raises(LLMQuotaExceeded):
        provider(monkeypatch, error=api_error(429, "Resource exhausted")).generate("s", [], [])
    with pytest.raises(LLMQuotaExceeded):
        provider(monkeypatch, error=api_error(403, "Quota exceeded")).generate("s", [], [])


def test_other_failures_are_unavailable(monkeypatch):
    with pytest.raises(LLMUnavailable):
        provider(monkeypatch, error=api_error(500, "boom")).generate("s", [], [])
    with pytest.raises(LLMUnavailable):
        provider(monkeypatch, error=TimeoutError()).generate("s", [], [])
    assert provider(monkeypatch, response(parts=[])).generate("s", [], []).text == ""
    empty = SimpleNamespace(prompt_feedback=None, candidates=[], usage_metadata=None)
    with pytest.raises(LLMUnavailable):
        provider(monkeypatch, empty).generate("s", [], [])


def test_blocked_content(monkeypatch):
    with pytest.raises(LLMBlocked):
        provider(monkeypatch, response([], block="SAFETY")).generate("s", [], [])


def test_missing_key_or_model_is_unavailable():
    with pytest.raises(LLMUnavailable):
        GeminiProvider("", "model")
    with pytest.raises(LLMUnavailable):
        GeminiProvider("key", "")


def test_output_cap_is_passed_through(monkeypatch):
    seen = {}
    p = GeminiProvider("k", "m")

    def generate_content(**kwargs):
        seen["cfg"] = kwargs["config"]
        return response([text_part("x")])

    monkeypatch.setattr(p._client.models, "generate_content", generate_content)
    p.generate("s", [Message("user", "q")], [TOOL], max_output_tokens=77)
    assert seen["cfg"].max_output_tokens == 77 and seen["cfg"].system_instruction == "s"
    assert gemini_module.GeminiProvider.name == "gemini"


def test_fake_llm_scripts_and_records():
    fake = FakeLLM([call("get_remaining_stops"), answer_from_tool(lambda r: f"{r['count']} left")])
    first = fake.generate("s", [Message("user", "q")], [TOOL])
    assert first.tool_calls[0].name == "get_remaining_stops"
    second = fake.generate(
        "s", [Message("tool", tool_name="get_remaining_stops", tool_result={"count": 2})], [TOOL]
    )
    assert second.text == "2 left"
    assert fake.generate("s", [], []).text  # script exhausted: a harmless default
    assert len(fake.calls) == 3 and fake.calls[0]["tools"] == ["get_remaining_stops"]
    assert say("hi").text == "hi"
    with pytest.raises(LLMQuotaExceeded):
        FakeLLM([LLMQuotaExceeded("q")]).generate("s", [], [])


@pytest.mark.live
def test_live_gemini_tool_round_trip():
    from dotenv import dotenv_values

    env = dotenv_values(".env")
    p = GeminiProvider(env["GEMINI_API_KEY"], env["GEMINI_MODEL"])
    reply = p.generate(
        "Use tools for live facts.", [Message("user", "How many stops are left?")], [TOOL]
    )
    assert reply.tool_calls and reply.tool_calls[0].signature
    final = p.generate(
        "Use tools for live facts. Be brief.",
        [
            Message("user", "How many stops are left?"),
            Message("assistant", "", reply.tool_calls),
            Message("tool", tool_name="get_remaining_stops", tool_result={"count": 2}),
        ],
        [TOOL],
    )
    assert "2" in final.text or "two" in final.text.lower()
