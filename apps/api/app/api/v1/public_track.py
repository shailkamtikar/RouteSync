"""Public tracking: resolve a link token to a public-safe journey view."""

import threading
import time
import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel

from app.auth.deps import CurrentOperator
from app.auth.rate_limit import RateLimiter
from app.config import get_settings
from app.db import DbConn, LazyDb
from app.domain import public_view, tracking_links
from app.schemas.fleet import StrictModel
from app.schemas.journeys import JourneyOut

router = APIRouter(tags=["public"])
settings = get_settings()
by_ip = RateLimiter(limit=settings.public_rate_per_min_ip, window_s=60.0)
by_token = RateLimiter(limit=settings.public_rate_per_min_token, window_s=60.0)
GONE_MESSAGE = "This tracking link is no longer available."

# Many viewers share one link and poll every 10 s; a short cache means a burst of viewers costs
# one database pass and the others need no connection at all. Entries are small and expire fast.
_view_cache: dict[str, tuple[float, uuid.UUID, dict]] = {}
_view_lock = threading.Lock()


def _cached(token: str) -> dict | None:
    ttl = get_settings().public_view_cache_s
    with _view_lock:
        hit = _view_cache.get(token)
    if hit and time.monotonic() - hit[0] < ttl:
        return hit[2]
    return None


def _remember(token: str, journey_id: uuid.UUID, view: dict) -> None:
    ttl = get_settings().public_view_cache_s
    if ttl <= 0:
        return
    now = time.monotonic()
    with _view_lock:
        _view_cache[token] = (now, journey_id, view)
        if len(_view_cache) > 5000:
            for key in [k for k, (t, _, _) in _view_cache.items() if now - t >= ttl]:
                del _view_cache[key]


def invalidate_view(journey_id: uuid.UUID) -> None:
    """Drop the cached view after an operator action that changes what passengers see."""
    with _view_lock:
        for key in [k for k, (_, j, _) in _view_cache.items() if j == journey_id]:
            del _view_cache[key]


class PublicJourney:
    def __init__(self, journey_id: uuid.UUID, operator_id: uuid.UUID, token: str):
        self.journey_id = journey_id
        self.operator_id = operator_id
        self.token = token


def _rate_limit(request: Request, token: str) -> None:
    client = request.client.host if request.client else "unknown"
    allowed, retry = by_ip.allow(client)
    if allowed:
        allowed, retry = by_token.allow(token[:64])
    if not allowed:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "Too many requests",
            headers={"Retry-After": str(int(retry) + 1)},
        )


def _resolve(conn, token: str) -> PublicJourney:
    state, journey_id, operator_id = tracking_links.resolve_token(conn, token)
    if state == tracking_links.LinkState.UNKNOWN:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    if state == tracking_links.LinkState.GONE:
        raise HTTPException(status.HTTP_410_GONE, GONE_MESSAGE)
    return PublicJourney(journey_id, operator_id, token)


def resolve_public_journey(token: str, request: Request, conn: DbConn) -> PublicJourney:
    _rate_limit(request, token)
    return _resolve(conn, token)


Public = Annotated[PublicJourney, Depends(resolve_public_journey)]


@router.get("/public/track/{token}", response_model=dict[str, Any])
def track(token: str, request: Request, response: Response, open_conn: LazyDb):
    response.headers["Cache-Control"] = "no-store"
    _rate_limit(request, token)
    view = _cached(token)
    if view is not None:
        return view
    with open_conn() as conn:
        public = _resolve(conn, token)
        view = public_view.build_public_view(conn, public.operator_id, public.journey_id)
    _remember(token, public.journey_id, view)
    return view


# ------------------------------------------------------------------ operator side


class TrackingLinkOut(BaseModel):
    token: str
    expires_at: Any


class PublicCountsIn(StrictModel):
    enabled: bool


@router.post("/journeys/{journey_id}/tracking-link", response_model=TrackingLinkOut)
def create_link(journey_id: uuid.UUID, ctx: CurrentOperator, conn: DbConn):
    invalidate_view(journey_id)
    return tracking_links.create_link(conn, ctx, journey_id)


@router.get("/journeys/{journey_id}/tracking-link", response_model=dict[str, Any])
def link_status(journey_id: uuid.UUID, ctx: CurrentOperator, conn: DbConn):
    return tracking_links.link_status(conn, ctx, journey_id)


@router.delete("/journeys/{journey_id}/tracking-link", status_code=status.HTTP_204_NO_CONTENT)
def revoke_link(journey_id: uuid.UUID, ctx: CurrentOperator, conn: DbConn):
    tracking_links.revoke_link(conn, ctx, journey_id)
    invalidate_view(journey_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.put("/journeys/{journey_id}/public-counts", response_model=JourneyOut)
def set_public_counts(
    journey_id: uuid.UUID, data: PublicCountsIn, ctx: CurrentOperator, conn: DbConn
):
    invalidate_view(journey_id)
    return tracking_links.set_public_counts(conn, ctx, journey_id, data.enabled)
