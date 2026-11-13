"""Scripted model for tests: answers come from a script, never from a network."""

from collections.abc import Callable

from app.providers.llm.base import LLMError, Message, Reply, ToolCall, ToolSpec


class FakeLLM:
    """Each `generate` call pops the next scripted reply. A script entry is a Reply, an
    exception to raise, or a function of (system, messages, tools) returning a Reply."""

    name = "fake"
    model = "fake-model"

    def __init__(self, script: list | None = None):
        self.script = list(script or [])
        self.calls: list[dict] = []

    def generate(self, system, messages, tools, *, max_output_tokens=400) -> Reply:
        self.calls.append(
            {
                "system": system,
                "messages": list(messages),
                "tools": [t.name for t in tools],
                "max_output_tokens": max_output_tokens,
            }
        )
        if not self.script:
            return Reply(text="I do not have more to add.")
        item = self.script.pop(0)
        if isinstance(item, LLMError):
            raise item
        if callable(item):
            return item(system, messages, tools)
        return item


def say(text: str) -> Reply:
    return Reply(text=text)


def call(name: str, **arguments) -> Reply:
    return Reply(text="", tool_calls=(ToolCall(name, arguments),))


def answer_from_tool(template: Callable[[dict], str]) -> Callable:
    """Reply built from the most recent tool result in the conversation."""

    def build(system: str, messages: list[Message], tools: list[ToolSpec]) -> Reply:
        last = next((m for m in reversed(messages) if m.role == "tool"), None)
        return Reply(text=template(last.tool_result if last else {}))

    return build
