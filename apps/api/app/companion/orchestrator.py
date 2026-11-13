"""The conversation loop: question -> tools -> grounded answer, with every guardrail enforced here."""

import logging
import time
from dataclasses import dataclass, field
from typing import Any

import psycopg

from app.companion import validators
from app.companion.context import build_context
from app.companion.prompt import build_system
from app.companion.tools import Binding, UnknownTool, run_tool, specs
from app.providers.llm.base import LLMBlocked, LLMError, LLMProvider, Message

logger = logging.getLogger(__name__)

MAX_TOOL_ROUNDS = 4
TIME_BUDGET_S = 25.0
MAX_OUTPUT_TOKENS = 350

FALLBACK_QUOTA = (
    "The assistant is busy right now; please try again in a minute. "
    "The tracking page above still shows live arrival times."
)
FALLBACK_DOWN = "The assistant is not available right now. The tracking page above still shows live arrival times."
FALLBACK_BLOCKED = "I can't help with that one. I can answer questions about this journey."
FALLBACK_LOOP = "I could not finish answering that. Please try a shorter or more specific question."


@dataclass
class ChatResult:
    answer: str
    sources: list[dict[str, Any]] = field(default_factory=list)
    fallback: str | None = None  # quota | unavailable | blocked | loop | scrubbed
    tool_rounds: int = 0
    usage: dict[str, int] = field(default_factory=lambda: {"input": 0, "output": 0})


def chat(
    conn: psycopg.Connection,
    provider: LLMProvider,
    binding: Binding,
    question: str,
    history: list[dict] | None = None,
) -> ChatResult:
    question = question.strip()[: validators.MAX_QUESTION_CHARS]
    private = validators.private_strings(conn, binding.journey_id)
    system = build_system(build_context(conn, binding))
    messages = [
        Message(turn["role"], turn["text"]) for turn in validators.clean_history(history or [])
    ]
    messages.append(Message("user", question))
    tools = specs()
    sources: list[dict[str, Any]] = []
    usage = {"input": 0, "output": 0}
    started = time.monotonic()

    try:
        for round_number in range(MAX_TOOL_ROUNDS + 1):
            if time.monotonic() - started > TIME_BUDGET_S:
                return ChatResult(FALLBACK_LOOP, sources, "loop", round_number, usage)
            reply = provider.generate(system, messages, tools, max_output_tokens=MAX_OUTPUT_TOKENS)
            usage["input"] += reply.usage.get("input", 0)
            usage["output"] += reply.usage.get("output", 0)
            if not reply.tool_calls:
                answer, replaced = validators.clean_answer(reply.text, private)
                if replaced:
                    logger.warning("assistant answer replaced: private data detected")
                if not answer:
                    answer = "I don't have an answer for that. Could you ask it another way?"
                return ChatResult(
                    answer, sources, "scrubbed" if replaced else None, round_number, usage
                )
            if round_number == MAX_TOOL_ROUNDS:
                break
            messages.append(Message("assistant", reply.text, reply.tool_calls))
            for call in reply.tool_calls:
                try:
                    result = run_tool(conn, binding, call.name, call.arguments)
                except UnknownTool:
                    result = {
                        "data": {},
                        "availability": "unknown",
                        "note": "That tool does not exist.",
                    }
                sources.append(
                    {
                        "tool": call.name,
                        "as_of": result.get("as_of"),
                        "availability": result.get("availability"),
                    }
                )
                messages.append(Message("tool", tool_name=call.name, tool_result=result))
        return ChatResult(FALLBACK_LOOP, sources, "loop", MAX_TOOL_ROUNDS, usage)
    except LLMBlocked:
        return ChatResult(FALLBACK_BLOCKED, sources, "blocked", 0, usage)
    except LLMError as exc:
        kind = "quota" if exc.__class__.__name__ == "LLMQuotaExceeded" else "unavailable"
        logger.warning("assistant fallback: %s", kind)
        return ChatResult(
            FALLBACK_QUOTA if kind == "quota" else FALLBACK_DOWN, sources, kind, 0, usage
        )
