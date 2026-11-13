"""Route options (templates) for a service, their route-specific stops, and route selection."""

import uuid

from fastapi import APIRouter, Response, status

from app.auth.deps import CurrentOperator, OwnerOperator
from app.db import DbConn
from app.domain import routes, stops
from app.domain.routing import Routing
from app.domain.stops import Places
from app.schemas.fleet import RemovalResult
from app.schemas.journeys import JourneyOut
from app.schemas.routes import (
    ResolveStopsResult,
    RouteTemplateCreate,
    RouteTemplateOut,
    RouteTemplateUpdate,
    RouteTemplateWriteResult,
    SelectRouteTemplate,
    StopCandidatesOut,
    StopCreate,
    StopOut,
    StopUpdate,
)

router = APIRouter(tags=["routes"])


@router.get("/services/{service_id}/route-templates", response_model=list[RouteTemplateOut])
def list_templates(
    service_id: uuid.UUID, ctx: CurrentOperator, conn: DbConn, include_archived: bool = False
):
    return routes.list_templates(conn, ctx, service_id, include_archived)


@router.post(
    "/services/{service_id}/route-templates",
    response_model=RouteTemplateWriteResult,
    status_code=status.HTTP_201_CREATED,
)
def create_template(
    service_id: uuid.UUID,
    data: RouteTemplateCreate,
    ctx: CurrentOperator,
    conn: DbConn,
    provider: Routing,
):
    template, error = routes.create_template(conn, ctx, provider, service_id, data)
    return RouteTemplateWriteResult(template=template, generation_error=error)


@router.get("/route-templates/{template_id}", response_model=RouteTemplateOut)
def get_template(template_id: uuid.UUID, ctx: CurrentOperator, conn: DbConn):
    return routes.get_template(conn, ctx, template_id)


@router.patch("/route-templates/{template_id}", response_model=RouteTemplateWriteResult)
def update_template(
    template_id: uuid.UUID,
    data: RouteTemplateUpdate,
    ctx: CurrentOperator,
    conn: DbConn,
    provider: Routing,
):
    template, error, warnings = routes.update_template(conn, ctx, provider, template_id, data)
    return RouteTemplateWriteResult(template=template, generation_error=error, warnings=warnings)


@router.post("/route-templates/{template_id}/generate", response_model=RouteTemplateOut)
def generate(template_id: uuid.UUID, ctx: CurrentOperator, conn: DbConn, provider: Routing):
    return routes.generate_geometry(conn, ctx, provider, template_id)


@router.delete("/route-templates/{template_id}", response_model=RemovalResult)
def remove_template(template_id: uuid.UUID, ctx: OwnerOperator, conn: DbConn):
    return RemovalResult(result=routes.remove_template(conn, ctx, template_id))


# ------------------------------------------------------------------ stops


@router.get("/route-templates/{template_id}/stops", response_model=list[StopOut])
def list_stops(template_id: uuid.UUID, ctx: CurrentOperator, conn: DbConn):
    return stops.list_stops(conn, ctx, template_id)


@router.post(
    "/route-templates/{template_id}/stops",
    response_model=StopOut,
    status_code=status.HTTP_201_CREATED,
)
def create_stop(template_id: uuid.UUID, data: StopCreate, ctx: CurrentOperator, conn: DbConn):
    return stops.create_stop(conn, ctx, template_id, data)


@router.get("/route-templates/{template_id}/stop-candidates", response_model=StopCandidatesOut)
def stop_candidates(template_id: uuid.UUID, ctx: CurrentOperator, conn: DbConn, provider: Places):
    return stops.stop_candidates(conn, ctx, provider, template_id)


@router.patch("/route-template-stops/{stop_id}", response_model=StopOut)
def update_stop(stop_id: uuid.UUID, data: StopUpdate, ctx: CurrentOperator, conn: DbConn):
    return stops.update_stop(conn, ctx, stop_id, data)


@router.delete("/route-template-stops/{stop_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_stop(stop_id: uuid.UUID, ctx: CurrentOperator, conn: DbConn):
    stops.remove_stop(conn, ctx, stop_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ------------------------------------------------------------------ journey route selection


@router.put("/journeys/{journey_id}/route-template", response_model=JourneyOut)
def select_route_template(
    journey_id: uuid.UUID, data: SelectRouteTemplate, ctx: CurrentOperator, conn: DbConn
):
    return routes.select_for_journey(conn, ctx, journey_id, data.route_template_id)


@router.post("/journeys/{journey_id}/bookings/resolve-stops", response_model=ResolveStopsResult)
def resolve_booking_stops(journey_id: uuid.UUID, ctx: CurrentOperator, conn: DbConn):
    return stops.resolve_booking_stops(conn, ctx, journey_id)
