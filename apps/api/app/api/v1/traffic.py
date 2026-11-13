"""Simulated traffic incidents on a route option."""

import uuid

from fastapi import APIRouter, Response, status

from app.auth.deps import CurrentOperator
from app.db import DbConn
from app.domain import traffic
from app.schemas.traffic import TrafficIncidentCreate, TrafficIncidentOut

router = APIRouter(tags=["traffic"])


@router.post(
    "/route-templates/{template_id}/traffic-incidents",
    response_model=TrafficIncidentOut,
    status_code=status.HTTP_201_CREATED,
)
def create_incident(
    template_id: uuid.UUID, data: TrafficIncidentCreate, ctx: CurrentOperator, conn: DbConn
):
    return traffic.create_incident(conn, ctx, template_id, data)


@router.get(
    "/route-templates/{template_id}/traffic-incidents", response_model=list[TrafficIncidentOut]
)
def list_incidents(
    template_id: uuid.UUID, ctx: CurrentOperator, conn: DbConn, active_only: bool = True
):
    return traffic.list_incidents(conn, ctx, template_id, active_only)


@router.delete("/traffic-incidents/{incident_id}", status_code=status.HTTP_204_NO_CONTENT)
def end_incident(incident_id: uuid.UUID, ctx: CurrentOperator, conn: DbConn):
    traffic.end_incident(conn, ctx, incident_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
