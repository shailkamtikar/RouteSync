"""Journey setup: stop plan, validation, lifecycle transitions and route assignment."""

import uuid
from dataclasses import asdict

from fastapi import APIRouter

from app.auth.deps import CurrentOperator
from app.db import DbConn
from app.domain import journeys, lifecycle, route_versions, stop_plan, validation
from app.domain.routing import Routing
from app.schemas.journeys import JourneyOut
from app.schemas.planning import (
    ActiveStopsIn,
    RouteVersionOut,
    StopPlanOut,
    TransitionIn,
    TransitionsOut,
    ValidationOut,
)

router = APIRouter(prefix="/journeys", tags=["planning"])


@router.get("/{journey_id}/stop-plan", response_model=StopPlanOut)
def get_stop_plan(journey_id: uuid.UUID, ctx: CurrentOperator, conn: DbConn):
    return stop_plan.get_stop_plan(conn, ctx, journey_id)


@router.put("/{journey_id}/active-stops", response_model=StopPlanOut)
def confirm_active_stops(
    journey_id: uuid.UUID, data: ActiveStopsIn, ctx: CurrentOperator, conn: DbConn
):
    return stop_plan.confirm_active_stops(conn, ctx, journey_id, data.stops)


@router.post("/{journey_id}/validate", response_model=ValidationOut)
def validate(journey_id: uuid.UUID, ctx: CurrentOperator, conn: DbConn):
    issues = stop_plan.validate_journey(conn, ctx, journey_id)
    return ValidationOut(
        valid=not validation.has_errors(issues), issues=[asdict(issue) for issue in issues]
    )


@router.get("/{journey_id}/transitions", response_model=TransitionsOut)
def transitions(journey_id: uuid.UUID, ctx: CurrentOperator, conn: DbConn):
    journey = journeys.get_journey(conn, ctx, journey_id)
    return TransitionsOut(
        status=journey["status"],
        allowed=lifecycle.allowed_transitions(journey["status"], ctx.role),
    )


@router.post("/{journey_id}/transition", response_model=JourneyOut)
def transition(journey_id: uuid.UUID, data: TransitionIn, ctx: CurrentOperator, conn: DbConn):
    return lifecycle.transition(conn, ctx, journey_id, data.to)


@router.post("/{journey_id}/assign", response_model=JourneyOut)
def assign(journey_id: uuid.UUID, ctx: CurrentOperator, conn: DbConn, provider: Routing):
    return route_versions.assign(conn, ctx, provider, journey_id)


@router.get("/{journey_id}/route-versions", response_model=list[RouteVersionOut])
def list_route_versions(journey_id: uuid.UUID, ctx: CurrentOperator, conn: DbConn):
    return route_versions.list_versions(conn, ctx, journey_id)
