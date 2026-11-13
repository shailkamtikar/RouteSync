"""GPS ingestion for one journey: device tokens, validation, idempotent storage.

The device (a simulator today, real hardware later) authenticates with a per-journey token.
The journey is always taken from the token, never from the request body.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import psycopg

from app.auth import tokens
from app.auth.deps import OperatorContext
from app.config import get_settings
from app.domain import journeys
from app.domain.audit import record_event
from app.domain.errors import Conflict
from app.optimizer import geo
from app.schemas.live import GpsPointIn

# A device may be set up once the route is assigned, and reports until the journey ends.
TOKEN_STATUSES = ("ready", "published", "boarding", "in_progress", "disrupted")
INGEST_STATUSES = ("published", "boarding", "in_progress", "disrupted")


@dataclass(frozen=True)
class IngestJourney:
    journey_id: uuid.UUID
    operator_id: uuid.UUID
    status: str


def issue_ingest_token(
    conn: psycopg.Connection, ctx: OperatorContext, journey_id: uuid.UUID
) -> str:
    """Create the journey's device token (replacing any earlier one). Shown only once."""
    journey = journeys.get_journey(conn, ctx, journey_id, lock=True)
    if journey["status"] not in TOKEN_STATUSES:
        raise Conflict("A device token can be created once the route is assigned")
    conn.execute(
        "update public.journey_ingest_tokens set revoked_at = now() "
        "where journey_id = %s and revoked_at is null",
        (journey_id,),
    )
    token = tokens.generate_token()
    conn.execute(
        "insert into public.journey_ingest_tokens (operator_id, journey_id, token_hash) "
        "values (%s, %s, %s)",
        (ctx.operator_id, journey_id, tokens.hash_token(token)),
    )
    record_event(
        conn,
        operator_id=ctx.operator_id,
        actor_id=ctx.user_id,
        journey_id=journey_id,
        event_type="ingest_token_issued",
    )
    return token


def revoke_ingest_token(
    conn: psycopg.Connection, ctx: OperatorContext, journey_id: uuid.UUID
) -> bool:
    journeys.get_journey(conn, ctx, journey_id, lock=True)
    revoked = conn.execute(
        "update public.journey_ingest_tokens set revoked_at = now() "
        "where journey_id = %s and operator_id = %s and revoked_at is null",
        (journey_id, ctx.operator_id),
    ).rowcount
    if revoked:
        record_event(
            conn,
            operator_id=ctx.operator_id,
            actor_id=ctx.user_id,
            journey_id=journey_id,
            event_type="ingest_token_revoked",
        )
    return bool(revoked)


def resolve_ingest_token(conn: psycopg.Connection, token: str) -> IngestJourney | None:
    if not token or len(token) > 200:
        return None
    row = conn.execute(
        "select j.id, j.operator_id, j.status from public.journey_ingest_tokens t "
        "join public.journeys j on j.id = t.journey_id "
        "where t.token_hash = %s and t.revoked_at is null",
        (tokens.hash_token(token),),
    ).fetchone()
    return IngestJourney(*row) if row else None


def ingest_points(
    conn: psycopg.Connection,
    journey: IngestJourney,
    points: list[GpsPointIn],
    now: datetime | None = None,
) -> dict:
    """Store a batch of positions for the token's journey.

    Duplicates (same device time and source) are ignored, late points are stored without
    moving the "latest position" backwards, and physically impossible jumps are rejected.
    """
    settings = get_settings()
    clock = now or datetime.now(UTC)
    row = conn.execute(
        "select status, last_device_ts, "
        "  extensions.st_x(last_position::extensions.geometry), "
        "  extensions.st_y(last_position::extensions.geometry) "
        "from public.journeys where id = %s for update",
        (journey.journey_id,),
    ).fetchone()
    status, latest_ts, latest_lng, latest_lat = row
    if status not in INGEST_STATUSES:
        raise Conflict("This journey is not accepting positions")
    latest = (latest_lng, latest_lat) if latest_lng is not None else None

    accepted = duplicates = 0
    rejected: list[dict] = []
    max_mps = settings.gps_max_speed_kmh / 3.6
    for index, point in sorted(enumerate(points), key=lambda item: item[1].device_ts):
        if point.device_ts > clock + timedelta(seconds=settings.gps_future_tolerance_s):
            rejected.append({"index": index, "reason": "timestamp_in_future"})
            continue
        position = (point.lng, point.lat)
        is_newer = latest_ts is None or point.device_ts > latest_ts
        if is_newer and latest is not None and latest_ts is not None:
            elapsed = (point.device_ts - latest_ts).total_seconds()
            # 100 m of slack covers GPS noise while the bus stands still.
            if geo.distance_m(latest, position) > max_mps * elapsed + 100:
                rejected.append({"index": index, "reason": "impossible_jump"})
                continue
        inserted = conn.execute(
            "insert into public.gps_positions (operator_id, journey_id, location, accuracy_m, "
            "speed_mps, device_ts, source) values (%s, %s, %s::extensions.geography, %s, %s, "
            "%s, %s) on conflict (journey_id, device_ts, source) do nothing",
            (
                journey.operator_id,
                journey.journey_id,
                f"POINT({point.lng} {point.lat})",
                point.accuracy_m,
                point.speed_mps,
                point.device_ts,
                point.source,
            ),
        ).rowcount
        if not inserted:
            duplicates += 1
            continue
        accepted += 1
        if is_newer:
            latest, latest_ts = position, point.device_ts

    if accepted and latest is not None:
        conn.execute(
            "update public.journeys set last_position = %s::extensions.geography, "
            "last_position_at = %s, last_device_ts = %s "
            "where id = %s and (last_device_ts is null or last_device_ts < %s)",
            (
                f"POINT({latest[0]} {latest[1]})",
                latest_ts,
                latest_ts,
                journey.journey_id,
                latest_ts,
            ),
        )
    return {"accepted": accepted, "duplicates": duplicates, "rejected": rejected}


def device_route(conn: psycopg.Connection, journey: IngestJourney) -> dict:
    """The assigned route for the device's own journey (used by the simulator)."""
    row = conn.execute(
        "select v.distance_m, v.duration_s, "
        "  extensions.st_asgeojson(v.geometry::extensions.geometry)::jsonb -> 'coordinates' "
        "from public.journeys j join public.route_versions v on v.id = j.current_route_version_id "
        "where j.id = %s",
        (journey.journey_id,),
    ).fetchone()
    if row is None:
        raise Conflict("No route has been assigned to this journey yet")
    return {"distance_m": row[0], "duration_s": row[1], "coordinates": row[2]}
