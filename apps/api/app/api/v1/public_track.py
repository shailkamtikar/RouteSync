"""Public tracking: resolve a link token to a public-safe journey view."""

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel

from app.auth.deps import CurrentOperator
from app.auth.rate_limit import RateLimiter
from app.config import get_settings
from app.db import DbConn
from app.domain import public_view, tracking_links
from app.schemas.fleet import StrictModel
from app.schemas.journeys import JourneyOut

router = APIRouter(tags=["public"])
settings = get_settings()
by_ip = RateLimiter(limit=settings.public_rate_per_min_ip, window_s=60.0)
by_token = RateLimiter(limit=settings.public_rate_per_min_token, window_s=60.0)
GONE_MESSAGE = "This tracking link is no longer available."


class PublicJourney:
    def __init__(self, journey_id: uuid.UUID, operator_id: uuid.UUID, token: str):
        self.journey_id = journey_id
        self.operator_id = operator_id
        self.token = token


def resolve_public_journey(token: str, request: Request, conn: DbConn) -> PublicJourney:
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
    state, journey_id, operator_id = tracking_links.resolve_token(conn, token)
    if state == tracking_links.LinkState.UNKNOWN:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    if state == tracking_links.LinkState.GONE:
        raise HTTPException(status.HTTP_410_GONE, GONE_MESSAGE)
    return PublicJourney(journey_id, operator_id, token)


Public = Annotated[PublicJourney, Depends(resolve_public_journey)]


@router.get("/public/track/{token}", response_model=dict[str, Any])
def track(public: Public, conn: DbConn, response: Response):
    response.headers["Cache-Control"] = "no-store"
    return public_view.build_public_view(conn, public.operator_id, public.journey_id)


# ------------------------------------------------------------------ operator side


class TrackingLinkOut(BaseModel):
    token: str
    expires_at: Any


class PublicCountsIn(StrictModel):
    enabled: bool


@router.post("/journeys/{journey_id}/tracking-link", response_model=TrackingLinkOut)
def create_link(journey_id: uuid.UUID, ctx: CurrentOperator, conn: DbConn):
    return tracking_links.create_link(conn, ctx, journey_id)


@router.get("/journeys/{journey_id}/tracking-link", response_model=dict[str, Any])
def link_status(journey_id: uuid.UUID, ctx: CurrentOperator, conn: DbConn):
    return tracking_links.link_status(conn, ctx, journey_id)


@router.delete("/journeys/{journey_id}/tracking-link", status_code=status.HTTP_204_NO_CONTENT)
def revoke_link(journey_id: uuid.UUID, ctx: CurrentOperator, conn: DbConn):
    tracking_links.revoke_link(conn, ctx, journey_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.put("/journeys/{journey_id}/public-counts", response_model=JourneyOut)
def set_public_counts(
    journey_id: uuid.UUID, data: PublicCountsIn, ctx: CurrentOperator, conn: DbConn
):
    return tracking_links.set_public_counts(conn, ctx, journey_id, data.enabled)
