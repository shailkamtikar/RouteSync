"""Journey alerts. At most one open alert of each type exists per journey."""

import uuid

import psycopg

from app.auth.deps import OperatorContext
from app.domain.audit import record_event
from app.eta import commitment as cm

DELAY_ALERT = "delay"
# Alerts about lateness only make sense once the journey has been published to passengers.
ALERTING_STATUSES = ("published", "boarding", "in_progress", "disrupted")


def sync_delay_alert(
    conn: psycopg.Connection,
    ctx: OperatorContext,
    journey_id: uuid.UUID,
    journey_status: str,
    result: cm.Commitment,
    config: cm.CommitmentConfig,
) -> str:
    """Open, refresh or resolve the journey's delay alert. Returns the action taken."""
    if journey_status not in ALERTING_STATUSES:
        return "none"
    open_alert = conn.execute(
        "select id from public.journey_alerts "
        "where journey_id = %s and operator_id = %s and type = %s and resolved_at is null "
        "for update",
        (journey_id, ctx.operator_id, DELAY_ALERT),
    ).fetchone()
    action = cm.alert_action(result.delay_minutes, open_alert is not None, config)
    message = cm.alert_message(result.delay_minutes)
    level = cm.severity(result.delay_minutes, config)

    if action == "open":
        conn.execute(
            "insert into public.journey_alerts (operator_id, journey_id, type, severity, message, "
            "is_public) values (%s, %s, %s, %s, %s, true) "
            "on conflict (journey_id, type) where resolved_at is null do nothing",
            (ctx.operator_id, journey_id, DELAY_ALERT, level, message),
        )
        record_event(
            conn,
            operator_id=ctx.operator_id,
            actor_id=None,
            journey_id=journey_id,
            event_type="delay_alert_opened",
            payload={"delay_minutes": round(result.delay_minutes, 1), "severity": level},
        )
    elif action == "update":
        conn.execute(
            "update public.journey_alerts set severity = %s, message = %s where id = %s",
            (level, message, open_alert[0]),
        )
    elif action == "resolve":
        conn.execute(
            "update public.journey_alerts set resolved_at = now() where id = %s", (open_alert[0],)
        )
        record_event(
            conn,
            operator_id=ctx.operator_id,
            actor_id=None,
            journey_id=journey_id,
            event_type="delay_alert_resolved",
            payload={"delay_minutes": round(result.delay_minutes, 1)},
        )
    return action
