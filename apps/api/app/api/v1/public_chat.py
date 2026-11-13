"""RouteSync Companion: chat bound to a public tracking link."""

import logging
from functools import lru_cache
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.api.v1.public_track import Public
from app.auth.rate_limit import RateLimiter
from app.companion import orchestrator
from app.companion.tools import Binding
from app.config import get_settings
from app.db import DbConn
from app.providers.llm.base import LLMProvider, LLMUnavailable
from app.providers.llm.gemini import GeminiProvider
from app.schemas.fleet import StrictModel

logger = logging.getLogger(__name__)
router = APIRouter(tags=["companion"])
settings = get_settings()
per_link = RateLimiter(limit=settings.companion_rate_per_min_link, window_s=60.0)
per_day = RateLimiter(limit=settings.companion_rate_per_day_link, window_s=86_400.0)


@lru_cache
def _default_llm() -> LLMProvider | None:
    if not settings.companion_enabled or not settings.gemini_api_key:
        return None
    try:
        return GeminiProvider(settings.gemini_api_key, settings.gemini_model)
    except LLMUnavailable:
        return None


def get_llm() -> LLMProvider | None:
    return _default_llm()


LLM = Annotated[LLMProvider | None, Depends(get_llm)]


class HistoryTurn(StrictModel):
    role: str = Field(pattern=r"^(user|assistant)$")
    text: str = Field(max_length=1200)


class ChatIn(StrictModel):
    question: str = Field(min_length=1, max_length=500)
    history: list[HistoryTurn] = Field(default_factory=list, max_length=6)


class ChatOut(BaseModel):
    answer: str
    sources: list[dict[str, Any]]
    fallback: str | None
    usage: dict[str, int]


@router.get("/public/track/{token}/companion", response_model=dict[str, Any])
def companion_status(public: Public, llm: LLM):
    return {"enabled": llm is not None}


@router.post("/public/track/{token}/chat", response_model=ChatOut)
def chat(data: ChatIn, public: Public, conn: DbConn, llm: LLM):
    if llm is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "The assistant is not available.")
    key = public.token[:64]
    for limiter in (per_link, per_day):
        allowed, retry = limiter.allow(key)
        if not allowed:
            raise HTTPException(
                status.HTTP_429_TOO_MANY_REQUESTS,
                "Too many questions for now. Please try again later.",
                headers={"Retry-After": str(int(retry) + 1)},
            )
    binding = Binding(public.journey_id, public.operator_id)
    result = orchestrator.chat(
        conn, llm, binding, data.question, [turn.model_dump() for turn in data.history]
    )
    logger.info(
        "companion answer: rounds=%s fallback=%s in=%s out=%s",
        result.tool_rounds,
        result.fallback,
        result.usage["input"],
        result.usage["output"],
    )
    return ChatOut(
        answer=result.answer, sources=result.sources, fallback=result.fallback, usage=result.usage
    )
