"""Journeys (individual departures). Every query is filtered by the caller's operator_id."""

import uuid

import psycopg
from psycopg import errors as pg_errors
from psycopg.rows import dict_row

from app.auth.deps import OperatorContext
from app.domain.audit import record_event
from app.domain.errors import Conflict, Invalid, NotFound
from app.schemas.journeys import JourneyCreate, JourneyUpdate

JOURNEY_SELECT = """
select j.id, j.bus_id, b.registration as bus_registration, b.capacity as bus_capacity,
       j.service_id, s.origin_name, s.destination_name, j.route_template_id,
       j.departure_at, j.scheduled_arrival_at, j.booking_eta_at, j.timezone, j.status,
       j.manual_mode, j.plan_needs_review, j.public_counts_enabled,
       j.current_route_version_id, j.created_at, j.updated_at,
       coalesce((select sum(k.passenger_count) from public.bookings k
                 where k.journey_id = j.id and k.status = 'confirmed'), 0)::int
         as booked_passengers
from public.journeys j
join public.buses b on b.id = j.bus_id
join public.services s on s.id = j.service_id
"""

# Journeys can still be edited (bus, route, stops, bookings) before they depart.
PRE_DEPARTURE_STATUSES = ("draft", "awaiting_confirmation", "ready", "published", "boarding")


def list_journeys(conn: psycopg.Connection, ctx: OperatorContext, status: str | None) -> list:
    query = JOURNEY_SELECT + " where j.operator_id = %s"
    params: list = [ctx.operator_id]
    if status:
        query += " and j.status = %s"
        params.append(status)
    with conn.cursor(row_factory=dict_row) as cur:
        return cur.execute(query + " order by j.departure_at desc limit 200", params).fetchall()


def get_journey(
    conn: psycopg.Connection, ctx: OperatorContext, journey_id: uuid.UUID, lock: bool = False
) -> dict:
    if lock:
        locked = conn.execute(
            "select 1 from public.journeys where id = %s and operator_id = %s for update",
            (journey_id, ctx.operator_id),
        ).fetchone()
        if locked is None:
            raise NotFound("Journey not found")
    with conn.cursor(row_factory=dict_row) as cur:
        row = cur.execute(
            JOURNEY_SELECT + " where j.id = %s and j.operator_id = %s",
            (journey_id, ctx.operator_id),
        ).fetchone()
    if row is None:
        raise NotFound("Journey not found")
    return row


def _require_active(conn, ctx: OperatorContext, table: str, row_id: uuid.UUID, label: str) -> None:
    row = conn.execute(
        f"select status from public.{table} where id = %s and operator_id = %s",
        (row_id, ctx.operator_id),
    ).fetchone()
    if row is None:
        raise NotFound(f"{label} not found")
    if row[0] != "active":
        raise Invalid(f"{label} is archived")


def create_journey(conn: psycopg.Connection, ctx: OperatorContext, data: JourneyCreate) -> dict:
    _require_active(conn, ctx, "buses", data.bus_id, "Bus")
    _require_active(conn, ctx, "services", data.service_id, "Service")
    try:
        with conn.transaction():
            journey_id = conn.execute(
                "insert into public.journeys (operator_id, bus_id, service_id, departure_at, "
                "scheduled_arrival_at, booking_eta_at, timezone) "
                "values (%s, %s, %s, %s, %s, %s, %s) returning id",
                (
                    ctx.operator_id,
                    data.bus_id,
                    data.service_id,
                    data.departure_at,
                    data.scheduled_arrival_at,
                    data.scheduled_arrival_at,
                    data.timezone,
                ),
            ).fetchone()[0]
    except pg_errors.ExclusionViolation:
        raise Conflict("This bus already has a journey that overlaps these times") from None
    record_event(
        conn,
        operator_id=ctx.operator_id,
        actor_id=ctx.user_id,
        journey_id=journey_id,
        event_type="journey_created",
        payload={
            "bus_id": str(data.bus_id),
            "service_id": str(data.service_id),
            "departure_at": data.departure_at.isoformat(),
            "booking_eta_at": data.scheduled_arrival_at.isoformat(),
        },
    )
    return get_journey(conn, ctx, journey_id)


def update_journey(
    conn: psycopg.Connection, ctx: OperatorContext, journey_id: uuid.UUID, data: JourneyUpdate
) -> dict:
    current = get_journey(conn, ctx, journey_id, lock=True)
    changes = {k: v for k, v in data.model_dump(exclude_unset=True).items() if v is not None}
    if not changes:
        return current
    if current["status"] != "draft":
        raise Conflict("Only a draft journey can be edited")
    if "bus_id" in changes:
        _require_active(conn, ctx, "buses", changes["bus_id"], "Bus")
    assignments = ", ".join(f"{column} = %s" for column in changes)
    try:
        with conn.transaction():
            conn.execute(
                f"update public.journeys set {assignments} where id = %s and operator_id = %s",
                (*changes.values(), journey_id, ctx.operator_id),
            )
    except pg_errors.ExclusionViolation:
        raise Conflict("This bus already has a journey that overlaps these times") from None
    record_event(
        conn,
        operator_id=ctx.operator_id,
        actor_id=ctx.user_id,
        journey_id=journey_id,
        event_type="journey_updated",
        payload={"fields": sorted(changes)},
    )
    return get_journey(conn, ctx, journey_id)
