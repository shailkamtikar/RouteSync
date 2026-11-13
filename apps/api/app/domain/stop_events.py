"""Stop events recorded by the operator: what actually happened at each active stop.

Completion of a stop is never inferred from GPS proximity; it exists only as a recorded event.
"""

import uuid
from datetime import UTC, datetime, timedelta

import psycopg
from psycopg.rows import dict_row

from app.auth.deps import OperatorContext
from app.domain import journeys, lifecycle
from app.domain.audit import record_event
from app.domain.errors import Conflict, Invalid, NotFound
from app.domain.onboard import CountEvent, PlannedStop, onboard_summary
from app.schemas.live import StopEventIn

RECORDING_STATUSES = ("boarding", "in_progress", "disrupted")
EVENT_COLUMNS = "id, journey_stop_id, type, count, client_event_id, occurred_at"


def onboard(conn: psycopg.Connection, ctx: OperatorContext, journey_id: uuid.UUID) -> dict:
    journeys.get_journey(conn, ctx, journey_id)
    return _onboard(conn, ctx.operator_id, journey_id)


def _onboard(conn: psycopg.Connection, operator_id: uuid.UUID, journey_id: uuid.UUID) -> dict:
    events = [
        CountEvent(*row)
        for row in conn.execute(
            "select type, count, occurred_at from public.stop_events "
            "where journey_id = %s and operator_id = %s",
            (journey_id, operator_id),
        ).fetchall()
    ]
    planned = [
        PlannedStop(row[0], row[1], row[2] == "departed")
        for row in conn.execute(
            "select pickup_count, drop_count, status from public.journey_stops "
            "where journey_id = %s and operator_id = %s",
            (journey_id, operator_id),
        ).fetchall()
    ]
    return onboard_summary(events, planned)


def list_events(conn: psycopg.Connection, ctx: OperatorContext, journey_id: uuid.UUID) -> list:
    journeys.get_journey(conn, ctx, journey_id)
    with conn.cursor(row_factory=dict_row) as cur:
        return cur.execute(
            f"select {EVENT_COLUMNS} from public.stop_events "
            "where journey_id = %s and operator_id = %s order by occurred_at, created_at",
            (journey_id, ctx.operator_id),
        ).fetchall()


def record(
    conn: psycopg.Connection,
    ctx: OperatorContext,
    journey_id: uuid.UUID,
    data: StopEventIn,
    now: datetime | None = None,
) -> dict:
    journey = journeys.get_journey(conn, ctx, journey_id, lock=True)
    clock = now or datetime.now(UTC)

    with conn.cursor(row_factory=dict_row) as cur:
        existing = cur.execute(
            f"select {EVENT_COLUMNS} from public.stop_events "
            "where journey_id = %s and client_event_id = %s",
            (journey_id, data.client_event_id),
        ).fetchone()
    if existing:  # a retried request: same answer, no second effect
        return {
            **existing,
            "duplicate": True,
            "journey_status": journey["status"],
            "onboard": _onboard(conn, ctx.operator_id, journey_id),
        }

    if journey["status"] not in RECORDING_STATUSES:
        raise Conflict("Stop events can be recorded only while the journey is boarding or running")
    stop = conn.execute(
        "select js.status, js.sequence, s.name, s.role from public.journey_stops js "
        "join public.route_template_stops s on s.id = js.route_template_stop_id "
        "where js.id = %s and js.journey_id = %s and js.operator_id = %s",
        (data.journey_stop_id, journey_id, ctx.operator_id),
    ).fetchone()
    if stop is None:
        raise NotFound("Stop not found on this journey")
    stop_status, sequence, stop_name, role = stop

    occurred_at = data.occurred_at or clock
    if occurred_at > clock + timedelta(seconds=60):
        raise Invalid("occurred_at is in the future")

    new_journey_status = journey["status"]
    if data.type == "arrived":
        if stop_status != "pending":
            raise Conflict(f"Arrival at {stop_name} is already recorded")
        skipped = conn.execute(
            "select s.name from public.journey_stops js "
            "join public.route_template_stops s on s.id = js.route_template_stop_id "
            "where js.journey_id = %s and js.sequence < %s and js.status <> 'departed' "
            "order by js.sequence limit 1",
            (journey_id, sequence),
        ).fetchone()
        if skipped:
            raise Conflict(f"{skipped[0]} comes first and has not been completed")
        conn.execute(
            "update public.journey_stops set status = 'arrived', arrived_at = %s where id = %s",
            (occurred_at, data.journey_stop_id),
        )
    elif data.type == "departed":
        if stop_status != "arrived":
            raise Conflict(f"Record the arrival at {stop_name} before the departure")
        conn.execute(
            "update public.journey_stops set status = 'departed', departed_at = %s where id = %s",
            (occurred_at, data.journey_stop_id),
        )
        if role == "destination":
            new_journey_status = "completed"
        elif journey["status"] == "boarding":
            new_journey_status = "in_progress"
    else:  # boarded / alighted
        if stop_status != "arrived":
            raise Conflict(f"Passengers can be counted only while the bus is at {stop_name}")
        if data.count < 1:
            raise Invalid("count must be at least 1")
        if data.type == "alighted":
            current = _onboard(conn, ctx.operator_id, journey_id)
            if data.count > (current["onboard"] or 0):
                raise Invalid(
                    f"{data.count} cannot alight: only {current['onboard'] or 0} recorded on board"
                )

    with conn.cursor(row_factory=dict_row) as cur:
        event = cur.execute(
            "insert into public.stop_events (operator_id, journey_id, journey_stop_id, type, "
            f"count, client_event_id, occurred_at, recorded_by) "
            f"values (%s, %s, %s, %s, %s, %s, %s, %s) returning {EVENT_COLUMNS}",
            (
                ctx.operator_id,
                journey_id,
                data.journey_stop_id,
                data.type,
                data.count if data.type in ("boarded", "alighted") else 0,
                data.client_event_id,
                occurred_at,
                ctx.user_id,
            ),
        ).fetchone()
    record_event(
        conn,
        operator_id=ctx.operator_id,
        actor_id=ctx.user_id,
        journey_id=journey_id,
        event_type="stop_event_recorded",
        payload={"stop": stop_name, "type": data.type, "count": event["count"]},
    )
    if new_journey_status != journey["status"]:
        lifecycle.apply_status(
            conn,
            ctx,
            journey_id,
            journey["status"],
            new_journey_status,
            reason=f"{data.type} at {stop_name}",
        )
    return {
        **event,
        "duplicate": False,
        "journey_status": new_journey_status,
        "onboard": _onboard(conn, ctx.operator_id, journey_id),
    }
