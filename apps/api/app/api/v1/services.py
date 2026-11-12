"""Operator-scoped service (origin to destination offering) management."""

import uuid

from fastapi import APIRouter, status

from app.auth.deps import CurrentOperator, OwnerOperator
from app.db import DbConn
from app.domain import fleet
from app.schemas.fleet import RemovalResult, ServiceCreate, ServiceOut, ServiceUpdate

router = APIRouter(prefix="/services", tags=["services"])


@router.get("", response_model=list[ServiceOut])
def list_services(ctx: CurrentOperator, conn: DbConn, include_archived: bool = False):
    return fleet.list_services(conn, ctx, include_archived)


@router.post("", response_model=ServiceOut, status_code=status.HTTP_201_CREATED)
def create_service(data: ServiceCreate, ctx: CurrentOperator, conn: DbConn):
    return fleet.create_service(conn, ctx, data)


@router.get("/{service_id}", response_model=ServiceOut)
def get_service(service_id: uuid.UUID, ctx: CurrentOperator, conn: DbConn):
    return fleet.get_service(conn, ctx, service_id)


@router.patch("/{service_id}", response_model=ServiceOut)
def update_service(service_id: uuid.UUID, data: ServiceUpdate, ctx: CurrentOperator, conn: DbConn):
    return fleet.update_service(conn, ctx, service_id, data)


@router.delete("/{service_id}", response_model=RemovalResult)
def remove_service(service_id: uuid.UUID, ctx: OwnerOperator, conn: DbConn):
    return RemovalResult(result=fleet.remove_service(conn, ctx, service_id))
