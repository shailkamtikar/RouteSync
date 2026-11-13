"""Operator live monitor."""

import uuid
from typing import Any

from fastapi import APIRouter

from app.auth.deps import CurrentOperator
from app.db import DbConn
from app.domain import monitor

router = APIRouter(prefix="/journeys", tags=["monitor"])


@router.get("/{journey_id}/monitor", response_model=dict[str, Any])
def get_monitor(journey_id: uuid.UUID, ctx: CurrentOperator, conn: DbConn):
    return monitor.get_monitor(conn, ctx, journey_id)
