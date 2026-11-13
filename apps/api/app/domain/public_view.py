"""The public tracking view: what anyone holding a tracking link may see.

Built with an explicit allowlist. No passenger names, seats, phone numbers, booking references
or manifests ever reach this payload. Aggregate counts appear only when the operator enabled
them for the journey.
"""

import uuid
from datetime import UTC, datetime
from typing import Any

import psycopg
from psycopg.rows import dict_row

from app.auth.deps import OperatorContext
from app.domain import stop_events
from app.domain.errors import Conflict
from app.eta import service as eta_service

SCHEMA_VERSION = 1
PUBLIC_STATUS = {
    "ready": "not_started",
    "published": "not_started",
    "boarding": "boarding",
    "in_progress": "in_progress",
    "disrupted": "in_progress",
    "completed": "completed",
    "cancelled": "cancelled",
}
# Alert types that may be shown to passengers (operator-only ones are never listed).
PUBLIC_ALERT_TYPES = ("delay", "traffic", "road_closure")


def _public_stop(item: dict | None) -> dict | None:
    """An ETA stop entry without internal identifiers."""
    if item is None:
        return None
    return {k: v for k, v in item.items() if k != "stop_id"}


def _system_ctx(operator_id: uuid.UUID) -> OperatorContext:
    return OperatorContext(None, None, operator_id, "", "owner")


def build_public_view(
    conn: psycopg.Connection, operator_id: uuid.UUID, journey_id: uuid.UUID
) -> dict[str, Any]:
    ctx = _system_ctx(operator_id)
    with conn.cursor(row_factory=dict_row) as cur:
        journey = cur.execute(
            "select j.status, j.timezone, j.departure_at, j.booking_eta_at, j.public_counts_enabled, "
            "       j.current_route_version_id, j.route_template_id, "
            "       s.origin_name, s.destination_name, "
            "       extensions.st_x(j.last_position::extensions.geometry) as lng, "
            "       extensions.st_y(j.last_position::extensions.geometry) as lat, "
            "       j.last_position_at "
            "from public.journeys j join public.services s on s.id = j.service_id "
            "where j.id = %s and j.operator_id = %s",
            (journey_id, operator_id),
        ).fetchone()
        route = (
            cur.execute(
                "select extensions.st_asgeojson(extensions.st_simplify("
                "  geometry::extensions.geometry, 0.0005))::jsonb -> 'coordinates' as coordinates, "
                "  version from public.route_versions where id = %s",
                (journey["current_route_version_id"],),
            ).fetchone()
            if journey["current_route_version_id"]
            else None
        )
        active = cur.execute(
            "select s.id::text as stop_id, s.name, s.role, js.status, js.sequence, "
            "       js.pickup_count, js.drop_count, "
            "       extensions.st_x(s.location::extensions.geometry) as lng, "
            "       extensions.st_y(s.location::extensions.geometry) as lat "
            "from public.journey_stops js "
            "join public.route_template_stops s on s.id = js.route_template_stop_id "
            "where js.journey_id = %s order by js.sequence",
            (journey_id,),
        ).fetchall()
        pass_through = (
            cur.execute(
                "select s.name, extensions.st_x(s.location::extensions.geometry) as lng, "
                "       extensions.st_y(s.location::extensions.geometry) as lat "
                "from public.route_template_stops s "
                "where s.route_template_id = %s and s.kind = 'pass_through' order by s.chainage_m",
                (journey["route_template_id"],),
            ).fetchall()
            if journey["route_template_id"]
            else []
        )
        alerts = cur.execute(
            "select type, severity, message from public.journey_alerts "
            "where journey_id = %s and is_public and resolved_at is null and type = any(%s) "
            "order by created_at",
            (journey_id, list(PUBLIC_ALERT_TYPES)),
        ).fetchall()

    try:
        eta = eta_service.current_snapshot(conn, ctx, journey_id)
    except Conflict:
        eta = None
    eta_by_id = {s["stop_id"]: s for s in (eta["stops"] if eta else [])}
    counts_enabled = journey["public_counts_enabled"]

    timeline = []
    for stop in active:
        item = eta_by_id.get(stop["stop_id"])
        entry: dict[str, Any] = {
            "name": stop["name"],
            "role": stop["role"],
            "status": item["status"]
            if item
            else ("completed" if stop["status"] == "departed" else "upcoming"),
            "eta": item["eta"] if item else None,
            "departure_eta": item["departure_eta"] if item else None,
            "remaining_m": item["remaining_m"] if item else None,
            "lng": stop["lng"],
            "lat": stop["lat"],
        }
        if counts_enabled:
            entry["boarding_count"] = stop["pickup_count"]
            entry["alighting_count"] = stop["drop_count"]
        timeline.append(entry)

    view: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "computed_at": datetime.now(UTC).isoformat(),
        "journey": {
            "status": PUBLIC_STATUS.get(journey["status"], "in_progress"),
            "origin_name": journey["origin_name"],
            "destination_name": journey["destination_name"],
            "timezone": journey["timezone"],
            "departure_at": journey["departure_at"].isoformat(),
            "booking_eta_at": journey["booking_eta_at"].isoformat(),
        },
        "route": {"version": route["version"], "coordinates": route["coordinates"]}
        if route
        else None,
        "bus": (
            {
                "lng": journey["lng"],
                "lat": journey["lat"],
                "at": journey["last_position_at"].isoformat(),
                "stale": bool(eta and eta["flags"].get("stale")),
            }
            if journey["lng"] is not None
            else None
        ),
        "eta": (
            {
                "next_stop": _public_stop(eta["next_stop"]),
                "destination": _public_stop(eta["destination"]),
                "remaining_distance_m": eta["remaining_distance_m"],
                "travelled_distance_m": eta["travelled_distance_m"],
                "progress_pct": eta["progress_pct"],
                "gps_age_s": eta["gps_age_s"],
                "flags": eta["flags"],
                "warnings": eta["warnings"],
                "commitment": eta.get("commitment"),
            }
            if eta
            else None
        ),
        "stops": timeline,
        "pass_through": [dict(p) for p in pass_through],
        "alerts": [dict(a) for a in alerts],
        "counts_enabled": counts_enabled,
    }
    if counts_enabled:
        summary = stop_events.onboard(conn, ctx, journey_id)
        view["onboard"] = {"method": summary["method"], "onboard": summary["onboard"]}
    return view
