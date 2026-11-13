"""The stop plan of one journey: suggested stops, operator-confirmed active stops, validation.

Bookings only produce hints. A stop becomes active solely because the operator confirmed it.
"""

import uuid

import psycopg
from psycopg.rows import dict_row

from app.auth.deps import OperatorContext
from app.domain import journeys, stops, validation
from app.domain.audit import record_event
from app.domain.errors import Conflict, Invalid
from app.schemas.planning import ActiveStopIn

EDITABLE_STATUSES = ("draft",)


def get_stop_plan(conn: psycopg.Connection, ctx: OperatorContext, journey_id: uuid.UUID) -> dict:
    journey = journeys.get_journey(conn, ctx, journey_id)
    template_id = journey["route_template_id"]
    if template_id is None:
        return {
            "route_template_id": None,
            "editable": journey["status"] in EDITABLE_STATUSES,
            "plan_needs_review": journey["plan_needs_review"],
            "stops": [],
            "unresolved_bookings": [],
        }
    with conn.cursor(row_factory=dict_row) as cur:
        rows = cur.execute(
            """
            select s.id as route_template_stop_id, s.name, s.role, s.kind, s.chainage_m,
                   extensions.st_y(s.location::extensions.geometry) as lat,
                   extensions.st_x(s.location::extensions.geometry) as lng,
                   js.id is not null as active, js.sequence,
                   coalesce(js.pickup_count, 0) as pickup_count,
                   coalesce(js.drop_count, 0) as drop_count,
                   coalesce(js.dwell_minutes, 5) as dwell_minutes,
                   coalesce((select sum(b.passenger_count) from public.bookings b
                             where b.journey_id = %(journey)s and b.status = 'confirmed'
                               and b.pickup_stop_id = s.id), 0)::int as booked_pickups,
                   coalesce((select sum(b.passenger_count) from public.bookings b
                             where b.journey_id = %(journey)s and b.status = 'confirmed'
                               and b.drop_stop_id = s.id), 0)::int as booked_drops
            from public.route_template_stops s
            left join public.journey_stops js
              on js.route_template_stop_id = s.id and js.journey_id = %(journey)s
            where s.route_template_id = %(template)s and s.operator_id = %(operator)s
            order by s.chainage_m nulls last, s.name
            """,
            {"journey": journey_id, "template": template_id, "operator": ctx.operator_id},
        ).fetchall()
    for row in rows:
        row["location"] = {"lat": row.pop("lat"), "lng": row.pop("lng")}
    unresolved = stops.resolve_booking_stops(conn, ctx, journey_id)["unresolved"]
    return {
        "route_template_id": template_id,
        "editable": journey["status"] in EDITABLE_STATUSES,
        "plan_needs_review": journey["plan_needs_review"],
        "stops": rows,
        "unresolved_bookings": unresolved,
    }


def confirm_active_stops(
    conn: psycopg.Connection,
    ctx: OperatorContext,
    journey_id: uuid.UUID,
    items: list[ActiveStopIn],
) -> dict:
    """Replace the journey's active stops with the operator's explicit selection."""
    journey = journeys.get_journey(conn, ctx, journey_id, lock=True)
    if journey["status"] not in EDITABLE_STATUSES:
        raise Conflict("Active stops can only be changed while the journey is a draft")
    template_id = journey["route_template_id"]
    if template_id is None:
        raise Invalid("Choose a route option for this journey first")

    ids = [item.route_template_stop_id for item in items]
    if len(set(ids)) != len(ids):
        raise Invalid("A stop is listed more than once")
    known = {
        row[0]: row
        for row in conn.execute(
            "select id, name, kind, chainage_m from public.route_template_stops "
            "where route_template_id = %s and operator_id = %s",
            (template_id, ctx.operator_id),
        ).fetchall()
    }
    for item in items:
        stop = known.get(item.route_template_stop_id)
        if stop is None:
            raise Invalid("A selected stop does not belong to this journey's route option")
        if stop[2] != "passenger_stop":
            raise Invalid(f"{stop[1]} is marked as no passenger stop and cannot be active")
        if item.pickup_count + item.drop_count == 0:
            raise Invalid(f"{stop[1]} has no passengers boarding or alighting")

    # Order always follows the road, never the order the client sent.
    ordered = sorted(items, key=lambda item: known[item.route_template_stop_id][3] or 0.0)
    conn.execute("delete from public.journey_stops where journey_id = %s", (journey_id,))
    for sequence, item in enumerate(ordered, start=1):
        conn.execute(
            "insert into public.journey_stops (operator_id, journey_id, route_template_id, "
            "route_template_stop_id, sequence, pickup_count, drop_count, dwell_minutes) "
            "values (%s, %s, %s, %s, %s, %s, %s, %s)",
            (
                ctx.operator_id,
                journey_id,
                template_id,
                item.route_template_stop_id,
                sequence,
                item.pickup_count,
                item.drop_count,
                item.dwell_minutes,
            ),
        )
    conn.execute(
        "update public.journeys set plan_needs_review = false where id = %s and operator_id = %s",
        (journey_id, ctx.operator_id),
    )
    record_event(
        conn,
        operator_id=ctx.operator_id,
        actor_id=ctx.user_id,
        journey_id=journey_id,
        event_type="active_stops_confirmed",
        payload={
            "stops": [
                {
                    "name": known[item.route_template_stop_id][1],
                    "pickup_count": item.pickup_count,
                    "drop_count": item.drop_count,
                }
                for item in ordered
            ]
        },
    )
    return get_stop_plan(conn, ctx, journey_id)


def load_plan(
    conn: psycopg.Connection, ctx: OperatorContext, journey_id: uuid.UUID
) -> validation.Plan:
    """Read the journey's confirmed plan from the database in the validator's shape."""
    journey = journeys.get_journey(conn, ctx, journey_id)
    template_id = journey["route_template_id"]
    if template_id is not None:
        stops.resolve_booking_stops(conn, ctx, journey_id)
    stop_rows = conn.execute(
        "select s.id::text, s.name, js.sequence, js.pickup_count, js.drop_count, s.kind, "
        "       s.route_template_id = %s "
        "from public.journey_stops js "
        "join public.route_template_stops s on s.id = js.route_template_stop_id "
        "where js.journey_id = %s and js.operator_id = %s order by js.sequence",
        (template_id, journey_id, ctx.operator_id),
    ).fetchall()
    booking_rows = conn.execute(
        "select reference, passenger_count, pickup_stop_name, drop_stop_name, "
        "       pickup_stop_id::text, drop_stop_id::text "
        "from public.bookings where journey_id = %s and operator_id = %s "
        "and status = 'confirmed' order by reference",
        (journey_id, ctx.operator_id),
    ).fetchall()
    return validation.Plan(
        capacity=journey["bus_capacity"],
        has_route=template_id is not None,
        stops=[validation.PlanStop(*row) for row in stop_rows],
        bookings=[validation.PlanBooking(*row) for row in booking_rows],
        plan_needs_review=journey["plan_needs_review"],
    )


def validate_journey(
    conn: psycopg.Connection, ctx: OperatorContext, journey_id: uuid.UUID
) -> list[validation.Issue]:
    return validation.validate_plan(load_plan(conn, ctx, journey_id))
