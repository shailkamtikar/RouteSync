"""Public tracking links: one unguessable, revocable link per journey. Only a hash is stored."""

import uuid
from datetime import UTC, datetime, timedelta

import psycopg

from app.auth import tokens
from app.auth.deps import OperatorContext
from app.config import get_settings
from app.domain import journeys
from app.domain.audit import record_event
from app.domain.errors import Conflict

LINKABLE_STATUSES = ("ready", "published", "boarding", "in_progress", "disrupted")


def create_link(conn: psycopg.Connection, ctx: OperatorContext, journey_id: uuid.UUID) -> dict:
    """Issue the journey's public link, revoking any earlier one. The token is shown once."""
    journey = journeys.get_journey(conn, ctx, journey_id, lock=True)
    if journey["status"] not in LINKABLE_STATUSES:
        raise Conflict("A tracking link can be created once the route is assigned")
    conn.execute(
        "update public.public_tracking_links set revoked_at = now() "
        "where journey_id = %s and revoked_at is null",
        (journey_id,),
    )
    token = tokens.generate_token()
    hours = get_settings().tracking_link_hours_after_arrival
    expires = journey["scheduled_arrival_at"] + timedelta(hours=hours)
    conn.execute(
        "insert into public.public_tracking_links (operator_id, journey_id, token_hash, expires_at) "
        "values (%s, %s, %s, %s)",
        (ctx.operator_id, journey_id, tokens.hash_token(token), expires),
    )
    record_event(
        conn,
        operator_id=ctx.operator_id,
        actor_id=ctx.user_id,
        journey_id=journey_id,
        event_type="tracking_link_created",
        payload={"expires_at": expires.isoformat()},
    )
    return {"token": token, "expires_at": expires}


def link_status(conn: psycopg.Connection, ctx: OperatorContext, journey_id: uuid.UUID) -> dict:
    journeys.get_journey(conn, ctx, journey_id)
    row = conn.execute(
        "select created_at, expires_at from public.public_tracking_links "
        "where journey_id = %s and operator_id = %s and revoked_at is null",
        (journey_id, ctx.operator_id),
    ).fetchone()
    if row is None:
        return {"active": False, "created_at": None, "expires_at": None}
    return {"active": True, "created_at": row[0], "expires_at": row[1]}


def revoke_link(conn: psycopg.Connection, ctx: OperatorContext, journey_id: uuid.UUID) -> bool:
    journeys.get_journey(conn, ctx, journey_id, lock=True)
    revoked = conn.execute(
        "update public.public_tracking_links set revoked_at = now() "
        "where journey_id = %s and operator_id = %s and revoked_at is null",
        (journey_id, ctx.operator_id),
    ).rowcount
    if revoked:
        record_event(
            conn,
            operator_id=ctx.operator_id,
            actor_id=ctx.user_id,
            journey_id=journey_id,
            event_type="tracking_link_revoked",
        )
    return bool(revoked)


def set_public_counts(
    conn: psycopg.Connection, ctx: OperatorContext, journey_id: uuid.UUID, enabled: bool
) -> dict:
    journeys.get_journey(conn, ctx, journey_id, lock=True)
    conn.execute(
        "update public.journeys set public_counts_enabled = %s where id = %s and operator_id = %s",
        (enabled, journey_id, ctx.operator_id),
    )
    record_event(
        conn,
        operator_id=ctx.operator_id,
        actor_id=ctx.user_id,
        journey_id=journey_id,
        event_type="public_counts_changed",
        payload={"enabled": enabled},
    )
    return journeys.get_journey(conn, ctx, journey_id)


class LinkState:
    VALID = "valid"
    UNKNOWN = "unknown"
    GONE = "gone"  # revoked or expired


def resolve_token(conn: psycopg.Connection, token: str, now: datetime | None = None):
    """Map a public token to (state, journey_id, operator_id). Never trusts anything else."""
    if not token or len(token) > 200:
        return LinkState.UNKNOWN, None, None
    row = conn.execute(
        "select journey_id, operator_id, revoked_at, expires_at from public.public_tracking_links "
        "where token_hash = %s",
        (tokens.hash_token(token),),
    ).fetchone()
    if row is None:
        return LinkState.UNKNOWN, None, None
    clock = now or datetime.now(UTC)
    if row[2] is not None or (row[3] is not None and row[3] <= clock):
        return LinkState.GONE, None, None
    return LinkState.VALID, row[0], row[1]
