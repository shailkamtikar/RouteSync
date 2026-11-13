"""Everything the operator's live monitor shows, in one payload from one moment."""

import uuid
from typing import Any

import psycopg
from psycopg.rows import dict_row

from app.auth.deps import OperatorContext
from app.domain import journeys, reroute, stop_events
from app.domain.errors import Conflict
from app.eta import service as eta_service


def get_monitor(
    conn: psycopg.Connection, ctx: OperatorContext, journey_id: uuid.UUID
) -> dict[str, Any]:
    journey = journeys.get_journey(conn, ctx, journey_id)
    try:
        eta = eta_service.current_snapshot(conn, ctx, journey_id)
    except Conflict:
        eta = None  # no route assigned yet

    with conn.cursor(row_factory=dict_row) as cur:
        position = cur.execute(
            "select extensions.st_x(last_position::extensions.geometry) as lng, "
            "       extensions.st_y(last_position::extensions.geometry) as lat, "
            "       last_position_at as at "
            "from public.journeys where id = %s and operator_id = %s",
            (journey_id, ctx.operator_id),
        ).fetchone()
        route = cur.execute(
            "select v.version, v.source, v.reason, v.created_at, "
            "  extensions.st_asgeojson(extensions.st_simplify("
            "    v.geometry::extensions.geometry, 0.0005))::jsonb -> 'coordinates' as coordinates "
            "from public.route_versions v "
            "where v.id = %s and v.journey_id = %s and v.operator_id = %s",
            (journey["current_route_version_id"], journey_id, ctx.operator_id),
        ).fetchone()
        stops = cur.execute(
            "select js.id as journey_stop_id, s.name, s.role, js.sequence, js.status, "
            "       js.pickup_count, js.drop_count, js.dwell_minutes, js.arrived_at, js.departed_at, "
            "       extensions.st_x(s.location::extensions.geometry) as lng, "
            "       extensions.st_y(s.location::extensions.geometry) as lat "
            "from public.journey_stops js "
            "join public.route_template_stops s on s.id = js.route_template_stop_id "
            "where js.journey_id = %s and js.operator_id = %s order by js.sequence",
            (journey_id, ctx.operator_id),
        ).fetchall()
        alerts = cur.execute(
            "select id, type, severity, message, is_public, created_at from public.journey_alerts "
            "where journey_id = %s and operator_id = %s and resolved_at is null "
            "order by case severity when 'critical' then 0 when 'warning' then 1 else 2 end, "
            "created_at desc",
            (journey_id, ctx.operator_id),
        ).fetchall()

    return {
        "journey": {
            "id": journey["id"],
            "status": journey["status"],
            "origin_name": journey["origin_name"],
            "destination_name": journey["destination_name"],
            "bus_registration": journey["bus_registration"],
            "timezone": journey["timezone"],
            "departure_at": journey["departure_at"],
            "booking_eta_at": journey["booking_eta_at"],
            "manual_mode": journey["manual_mode"],
            "route_template_id": journey["route_template_id"],
        },
        "position": position if position and position["lng"] is not None else None,
        "eta": eta,
        "route": route,
        "stops": stops,
        "alerts": alerts,
        "onboard": stop_events.onboard(conn, ctx, journey_id),
        "decisions": reroute.list_decisions(conn, ctx, journey_id, limit=10),
    }
