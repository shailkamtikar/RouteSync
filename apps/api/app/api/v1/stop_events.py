"""Operator-recorded stop events and the onboard count."""

import uuid
from typing import Any

from fastapi import APIRouter

from app.auth.deps import CurrentOperator
from app.db import DbConn
from app.domain import stop_events
from app.schemas.live import StopEventIn, StopEventOut

router = APIRouter(prefix="/journeys", tags=["stop-events"])


@router.post("/{journey_id}/stop-events", response_model=StopEventOut)
def record_stop_event(journey_id: uuid.UUID, data: StopEventIn, ctx: CurrentOperator, conn: DbConn):
    return stop_events.record(conn, ctx, journey_id, data)


@router.get("/{journey_id}/stop-events", response_model=list[dict[str, Any]])
def list_stop_events(journey_id: uuid.UUID, ctx: CurrentOperator, conn: DbConn):
    return stop_events.list_events(conn, ctx, journey_id)


@router.get("/{journey_id}/onboard", response_model=dict[str, Any])
def onboard(journey_id: uuid.UUID, ctx: CurrentOperator, conn: DbConn):
    return stop_events.onboard(conn, ctx, journey_id)
