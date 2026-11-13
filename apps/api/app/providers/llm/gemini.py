"""Gemini adapter (google-genai SDK). Called only from the backend with a server-side key."""

import logging

from google import genai
from google.genai import errors as genai_errors
from google.genai import types

from app.providers.llm.base import (
    LLMBlocked,
    LLMQuotaExceeded,
    LLMUnavailable,
    Message,
    Reply,
    ToolCall,
)

logger = logging.getLogger(__name__)


class GeminiProvider:
    name = "gemini"

    def __init__(self, api_key: str, model: str, *, timeout_s: float = 15.0):
        if not api_key or not model:
            raise LLMUnavailable("the assistant is not configured")
        self.model = model
        self._client = genai.Client(
            api_key=api_key, http_options=types.HttpOptions(timeout=int(timeout_s * 1000))
        )

    @staticmethod
    def _contents(messages: list[Message]) -> list[types.Content]:
        contents: list[types.Content] = []
        for message in messages:
            if message.role == "user":
                contents.append(types.Content(role="user", parts=[types.Part(text=message.text)]))
            elif message.role == "assistant":
                parts = [types.Part(text=message.text)] if message.text else []
                parts += [
                    types.Part(
                        function_call=types.FunctionCall(name=c.name, args=c.arguments),
                        thought_signature=c.signature,
                    )
                    for c in message.tool_calls
                ]
                contents.append(types.Content(role="model", parts=parts))
            elif message.role == "tool":
                contents.append(
                    types.Content(
                        role="user",
                        parts=[
                            types.Part(
                                function_response=types.FunctionResponse(
                                    name=message.tool_name or "", response=message.tool_result or {}
                                )
                            )
                        ],
                    )
                )
        return contents

    def generate(self, system, messages, tools, *, max_output_tokens=400) -> Reply:
        declarations = [
            types.FunctionDeclaration(
                name=t.name, description=t.description, parameters=t.parameters or None
            )
            for t in tools
        ]
        config = types.GenerateContentConfig(
            system_instruction=system,
            temperature=0.2,
            max_output_tokens=max_output_tokens,
            tools=[types.Tool(function_declarations=declarations)] if declarations else None,
        )
        try:
            response = self._client.models.generate_content(
                model=self.model, contents=self._contents(messages), config=config
            )
        except genai_errors.APIError as exc:
            if exc.code == 429 or "quota" in str(exc).lower():
                raise LLMQuotaExceeded("assistant quota exhausted") from None
            logger.warning("gemini request failed: %s", exc.code)
            raise LLMUnavailable("assistant unavailable") from None
        except Exception as exc:  # network, timeout, SDK errors
            logger.warning("gemini request failed: %s", type(exc).__name__)
            raise LLMUnavailable("assistant unavailable") from None

        if response.prompt_feedback and response.prompt_feedback.block_reason:
            raise LLMBlocked("the assistant cannot answer that")
        candidate = (response.candidates or [None])[0]
        if candidate is None or candidate.content is None:
            raise LLMUnavailable("assistant returned no answer")
        texts, calls = [], []
        for part in candidate.content.parts or []:
            if part.function_call:
                calls.append(
                    ToolCall(
                        part.function_call.name or "",
                        dict(part.function_call.args or {}),
                        signature=part.thought_signature,
                    )
                )
            elif part.text:
                texts.append(part.text)
        usage = response.usage_metadata
        return Reply(
            text="".join(texts).strip(),
            tool_calls=tuple(calls),
            usage={
                "input": (usage.prompt_token_count or 0) if usage else 0,
                "output": (usage.candidates_token_count or 0) if usage else 0,
            },
        )
