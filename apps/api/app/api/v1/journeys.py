"""Operator-scoped journeys and their bookings."""

import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Body, status

from app.auth.deps import CurrentOperator
from app.db import DbConn
from app.domain import bookings, journeys
from app.schemas.journeys import (
    BookingCreate,
    BookingOut,
    BookingUpdate,
    BookingWriteResult,
    ImportResult,
    JourneyCreate,
    JourneyOut,
    JourneyUpdate,
)

router = APIRouter(prefix="/journeys", tags=["journeys"])

JourneyStatus = Literal[
    "draft",
    "awaiting_confirmation",
    "ready",
    "published",
    "boarding",
    "in_progress",
    "completed",
    "cancelled",
    "disrupted",
]


@router.get("", response_model=list[JourneyOut])
def list_journeys(ctx: CurrentOperator, conn: DbConn, status: JourneyStatus | None = None):
    return journeys.list_journeys(conn, ctx, status)


@router.post("", response_model=JourneyOut, status_code=status.HTTP_201_CREATED)
def create_journey(data: JourneyCreate, ctx: CurrentOperator, conn: DbConn):
    return journeys.create_journey(conn, ctx, data)


@router.get("/{journey_id}", response_model=JourneyOut)
def get_journey(journey_id: uuid.UUID, ctx: CurrentOperator, conn: DbConn):
    return journeys.get_journey(conn, ctx, journey_id)


@router.patch("/{journey_id}", response_model=JourneyOut)
def update_journey(journey_id: uuid.UUID, data: JourneyUpdate, ctx: CurrentOperator, conn: DbConn):
    return journeys.update_journey(conn, ctx, journey_id, data)


# ------------------------------------------------------------------ bookings


@router.get("/{journey_id}/bookings", response_model=list[BookingOut])
def list_bookings(journey_id: uuid.UUID, ctx: CurrentOperator, conn: DbConn):
    return bookings.list_bookings(conn, ctx, journey_id)


@router.post(
    "/{journey_id}/bookings",
    response_model=BookingWriteResult,
    status_code=status.HTTP_201_CREATED,
)
def create_booking(journey_id: uuid.UUID, data: BookingCreate, ctx: CurrentOperator, conn: DbConn):
    booking, warning = bookings.create_booking(conn, ctx, journey_id, data)
    return BookingWriteResult(booking=booking, capacity_warning=warning)


@router.post("/{journey_id}/bookings/import", response_model=ImportResult)
def import_bookings(
    journey_id: uuid.UUID,
    ctx: CurrentOperator,
    conn: DbConn,
    body: Annotated[bytes, Body(media_type="text/csv")],
):
    created, warning = bookings.import_bookings(conn, ctx, journey_id, body)
    return ImportResult(created=created, capacity_warning=warning)


@router.get("/{journey_id}/bookings/{booking_id}", response_model=BookingOut)
def get_booking(journey_id: uuid.UUID, booking_id: uuid.UUID, ctx: CurrentOperator, conn: DbConn):
    journeys.get_journey(conn, ctx, journey_id)
    return bookings.get_booking(conn, ctx, journey_id, booking_id)


@router.patch("/{journey_id}/bookings/{booking_id}", response_model=BookingWriteResult)
def update_booking(
    journey_id: uuid.UUID,
    booking_id: uuid.UUID,
    data: BookingUpdate,
    ctx: CurrentOperator,
    conn: DbConn,
):
    booking, warning = bookings.update_booking(conn, ctx, journey_id, booking_id, data)
    return BookingWriteResult(booking=booking, capacity_warning=warning)


@router.delete("/{journey_id}/bookings/{booking_id}", response_model=BookingOut)
def cancel_booking(
    journey_id: uuid.UUID, booking_id: uuid.UUID, ctx: CurrentOperator, conn: DbConn
):
    return bookings.cancel_booking(conn, ctx, journey_id, booking_id)
