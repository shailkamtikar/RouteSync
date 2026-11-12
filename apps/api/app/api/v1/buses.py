"""Operator-scoped bus management."""

import uuid

from fastapi import APIRouter, status

from app.auth.deps import CurrentOperator, OwnerOperator
from app.db import DbConn
from app.domain import fleet
from app.schemas.fleet import BusCreate, BusOut, BusUpdate, RemovalResult

router = APIRouter(prefix="/buses", tags=["buses"])


@router.get("", response_model=list[BusOut])
def list_buses(ctx: CurrentOperator, conn: DbConn, include_archived: bool = False):
    return fleet.list_buses(conn, ctx, include_archived)


@router.post("", response_model=BusOut, status_code=status.HTTP_201_CREATED)
def create_bus(data: BusCreate, ctx: CurrentOperator, conn: DbConn):
    return fleet.create_bus(conn, ctx, data)


@router.get("/{bus_id}", response_model=BusOut)
def get_bus(bus_id: uuid.UUID, ctx: CurrentOperator, conn: DbConn):
    return fleet.get_bus(conn, ctx, bus_id)


@router.patch("/{bus_id}", response_model=BusOut)
def update_bus(bus_id: uuid.UUID, data: BusUpdate, ctx: CurrentOperator, conn: DbConn):
    return fleet.update_bus(conn, ctx, bus_id, data)


@router.delete("/{bus_id}", response_model=RemovalResult)
def remove_bus(bus_id: uuid.UUID, ctx: OwnerOperator, conn: DbConn):
    return RemovalResult(result=fleet.remove_bus(conn, ctx, bus_id))
