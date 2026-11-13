"""Language-model provider interface. Only the backend ever talks to the model."""

from dataclasses import dataclass, field
from typing import Any, Protocol


class LLMError(Exception):
    """Base class for model failures."""


class LLMQuotaExceeded(LLMError):
    """The provider refused the request because the quota or rate limit is exhausted."""


class LLMUnavailable(LLMError):
    """The provider timed out, failed, or returned something unusable."""


class LLMBlocked(LLMError):
    """The provider refused to answer this content."""


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    parameters: dict[str, Any]  # JSON schema for the arguments


@dataclass(frozen=True)
class ToolCall:
    name: str
    arguments: dict[str, Any]
    # Opaque provider data that must be sent back with the call (Gemini thought signature).
    signature: bytes | None = None


@dataclass(frozen=True)
class Message:
    role: str  # user | assistant | tool
    text: str = ""
    tool_calls: tuple[ToolCall, ...] = ()
    # For role "tool": the call this result answers, and the result itself.
    tool_name: str | None = None
    tool_result: dict[str, Any] | None = None


@dataclass(frozen=True)
class Reply:
    text: str
    tool_calls: tuple[ToolCall, ...] = ()
    usage: dict[str, int] = field(default_factory=dict)


class LLMProvider(Protocol):
    name: str
    model: str

    def generate(
        self,
        system: str,
        messages: list[Message],
        tools: list[ToolSpec],
        *,
        max_output_tokens: int = 400,
    ) -> Reply:
        """One model turn: text, or tool calls the caller must run and feed back."""
        ...
