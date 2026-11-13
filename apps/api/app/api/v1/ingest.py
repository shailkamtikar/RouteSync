"""Position ingestion for devices, and device-token management for operators."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.auth import tokens
from app.auth.deps import CurrentOperator
from app.auth.rate_limit import RateLimiter
from app.config import get_settings
from app.db import DbConn
from app.domain import gps, reroute
from app.domain.routing import Routing
from app.schemas.live import DeviceRouteOut, GpsBatchIn, GpsIngestResult, IngestTokenOut

router = APIRouter(tags=["ingest"])
_bearer = HTTPBearer(auto_error=False)
limiter = RateLimiter(limit=get_settings().ingest_rate_per_min, window_s=60.0)


def device_journey(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    conn: DbConn,
) -> gps.IngestJourney:
    token = credentials.credentials if credentials else ""
    journey = gps.resolve_ingest_token(conn, token)
    if journey is None:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "Invalid device token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    allowed, retry_after = limiter.allow(tokens.hash_token(token))
    if not allowed:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "Too many requests",
            headers={"Retry-After": str(int(retry_after) + 1)},
        )
    return journey


Device = Annotated[gps.IngestJourney, Depends(device_journey)]


@router.post("/ingest/gps", response_model=GpsIngestResult, status_code=status.HTTP_202_ACCEPTED)
def ingest_gps(data: GpsBatchIn, device: Device, conn: DbConn, provider: Routing):
    result = gps.ingest_points(conn, device, data.points)
    if result["accepted"]:
        reroute.after_position_update(conn, device, provider)
    return result


@router.get("/ingest/route", response_model=DeviceRouteOut)
def device_route(device: Device, conn: DbConn):
    return gps.device_route(conn, device)


@router.post("/journeys/{journey_id}/ingest-token", response_model=IngestTokenOut)
def issue_ingest_token(journey_id: uuid.UUID, ctx: CurrentOperator, conn: DbConn):
    return IngestTokenOut(token=gps.issue_ingest_token(conn, ctx, journey_id))


@router.delete("/journeys/{journey_id}/ingest-token", status_code=status.HTTP_204_NO_CONTENT)
def revoke_ingest_token(journey_id: uuid.UUID, ctx: CurrentOperator, conn: DbConn):
    gps.revoke_ingest_token(conn, ctx, journey_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
