"""Current ETA snapshot for a journey (operator view)."""

import uuid
from typing import Any

from fastapi import APIRouter

from app.auth.deps import CurrentOperator
from app.db import DbConn
from app.eta import service

router = APIRouter(prefix="/journeys", tags=["eta"])


@router.get("/{journey_id}/eta", response_model=dict[str, Any])
def get_eta(journey_id: uuid.UUID, ctx: CurrentOperator, conn: DbConn):
    return service.current_snapshot(conn, ctx, journey_id)
