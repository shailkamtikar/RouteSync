"""Builds ETA snapshots from the database, stores them, and serves the latest one."""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from app.auth.deps import OperatorContext
from app.config import get_settings
from app.domain import alerts, journeys
from app.domain.errors import Conflict
from app.eta import commitment as cm
from app.eta.engine import EtaConfig, EtaInput, EtaSnapshot, EtaStop, compute_snapshot

# A snapshot younger than this is reused, so polling screens do not create a row per request.
DEFAULT_MAX_AGE_S = 5.0


def load_input(
    conn: psycopg.Connection,
    ctx: OperatorContext,
    journey_id: uuid.UUID,
    now: datetime | None = None,
) -> EtaInput:
    """Read everything the engine needs for one journey. All queries are operator-scoped."""
    journey = journeys.get_journey(conn, ctx, journey_id)
    version_id = journey["current_route_version_id"]
    if version_id is None:
        raise Conflict("No route has been assigned to this journey yet")

    with conn.cursor(row_factory=dict_row) as cur:
        version = cur.execute(
            "select distance_m, duration_s, "
            "  extensions.st_asgeojson(geometry::extensions.geometry)::jsonb -> 'coordinates' "
            "    as coordinates "
            "from public.route_versions where id = %s and journey_id = %s and operator_id = %s",
            (version_id, journey_id, ctx.operator_id),
        ).fetchone()
        position = cur.execute(
            "select extensions.st_x(last_position::extensions.geometry) as lng, "
            "       extensions.st_y(last_position::extensions.geometry) as lat, last_position_at "
            "from public.journeys where id = %s and operator_id = %s",
            (journey_id, ctx.operator_id),
        ).fetchone()
        stop_rows = cur.execute(
            "select s.id::text as stop_id, s.name, js.dwell_minutes, js.status, js.arrived_at, "
            "       extensions.st_x(s.location::extensions.geometry) as lng, "
            "       extensions.st_y(s.location::extensions.geometry) as lat "
            "from public.journey_stops js "
            "join public.route_template_stops s on s.id = js.route_template_stop_id "
            "where js.journey_id = %s and js.operator_id = %s order by js.sequence",
            (journey_id, ctx.operator_id),
        ).fetchall()

    route = tuple((c[0], c[1]) for c in version["coordinates"])
    settings = get_settings()
    has_position = position["lng"] is not None
    return EtaInput(
        now=now or datetime.now(UTC),
        route=route,
        route_distance_m=float(version["distance_m"]),
        route_duration_s=float(version["duration_s"]),
        stops=tuple(
            EtaStop(
                stop_id=row["stop_id"],
                name=row["name"],
                lng=row["lng"],
                lat=row["lat"],
                dwell_minutes=row["dwell_minutes"],
                status=row["status"],
                arrived_at=row["arrived_at"],
            )
            for row in stop_rows
        ),
        destination_name=journey["destination_name"],
        destination=route[-1],
        planned_departure=journey["departure_at"],
        position=(position["lng"], position["lat"]) if has_position else None,
        position_at=position["last_position_at"] if has_position else None,
        route_version_id=str(version_id),
        config=EtaConfig(
            stale_after_s=settings.gps_stale_after_s, off_route_m=settings.off_route_m
        ),
    )


def persist_snapshot(
    conn: psycopg.Connection,
    ctx: OperatorContext,
    journey_id: uuid.UUID,
    snapshot: EtaSnapshot,
    payload: dict[str, Any] | None = None,
) -> uuid.UUID:
    return conn.execute(
        "insert into public.journey_eta_snapshots (operator_id, journey_id, route_version_id, "
        "calculated_at, next_stop_eta, destination_eta, payload) "
        "values (%s, %s, %s, %s, %s, %s, %s) returning id",
        (
            ctx.operator_id,
            journey_id,
            snapshot.route_version_id,
            snapshot.computed_at,
            snapshot.next_stop.eta,
            snapshot.destination.eta,
            Jsonb(payload if payload is not None else snapshot.to_payload()),
        ),
    ).fetchone()[0]


def latest_snapshot(
    conn: psycopg.Connection, ctx: OperatorContext, journey_id: uuid.UUID
) -> dict[str, Any] | None:
    row = conn.execute(
        "select calculated_at, route_version_id, payload from public.journey_eta_snapshots "
        "where journey_id = %s and operator_id = %s order by calculated_at desc, id desc limit 1",
        (journey_id, ctx.operator_id),
    ).fetchone()
    if row is None:
        return None
    return {"calculated_at": row[0], "route_version_id": row[1], "payload": row[2]}


def current_snapshot(
    conn: psycopg.Connection,
    ctx: OperatorContext,
    journey_id: uuid.UUID,
    *,
    now: datetime | None = None,
    max_age_s: float = DEFAULT_MAX_AGE_S,
) -> dict[str, Any]:
    """The journey's ETA payload: a recent stored snapshot, or a freshly computed and stored one.

    Every screen reads this one payload, so the numbers on them can never disagree.
    """
    clock = now or datetime.now(UTC)
    data = load_input(conn, ctx, journey_id, clock)
    latest = latest_snapshot(conn, ctx, journey_id)
    if (
        latest is not None
        and str(latest["route_version_id"]) == data.route_version_id
        and timedelta(0) <= clock - latest["calculated_at"] < timedelta(seconds=max_age_s)
    ):
        return latest["payload"]
    snapshot = compute_snapshot(data)
    journey = journeys.get_journey(conn, ctx, journey_id)
    config = get_settings().commitment_config()
    result = cm.assess(journey["booking_eta_at"], snapshot.destination.eta, config)
    payload = snapshot.to_payload()
    payload["commitment"] = result.to_payload()
    persist_snapshot(conn, ctx, journey_id, snapshot, payload)
    alerts.sync_delay_alert(conn, ctx, journey_id, journey["status"], result, config)
    return payload
