"""Journey lifecycle: which status changes are allowed, by whom, and under what conditions."""

import uuid

import psycopg

from app.auth.deps import OperatorContext
from app.domain import journeys, stop_plan, validation
from app.domain.audit import record_event
from app.domain.errors import Conflict, Forbidden

ANY = frozenset({"owner", "dispatcher"})
OWNER = frozenset({"owner"})

# from status -> {to status: roles allowed to trigger it}
TRANSITIONS: dict[str, dict[str, frozenset[str]]] = {
    "draft": {"awaiting_confirmation": ANY, "cancelled": OWNER},
    "awaiting_confirmation": {"draft": ANY, "ready": ANY, "cancelled": OWNER},
    "ready": {"draft": ANY, "published": ANY, "cancelled": OWNER},
    "published": {"boarding": ANY, "cancelled": OWNER},
    "boarding": {"in_progress": ANY, "cancelled": OWNER},
    "in_progress": {"completed": ANY, "disrupted": ANY, "cancelled": OWNER},
    "disrupted": {"in_progress": ANY, "completed": ANY, "cancelled": OWNER},
    "completed": {},
    "cancelled": {},
}
STATUSES = tuple(TRANSITIONS)

# These changes have their own endpoint because they do more than change the status.
DEDICATED = {
    ("awaiting_confirmation", "ready"): "Assign the route to make the journey ready.",
}


def allowed_transitions(status: str, role: str) -> list[str]:
    return [to for to, roles in TRANSITIONS.get(status, {}).items() if role in roles]


def check_transition(current: str, to: str, role: str) -> None:
    """Raise if `role` may not move a journey from `current` to `to`."""
    options = TRANSITIONS.get(current, {})
    if to not in options:
        allowed = ", ".join(options) or "none"
        raise Conflict(
            f"A journey that is {current.replace('_', ' ')} cannot become "
            f"{to.replace('_', ' ')}. Allowed: {allowed}.",
            details={"allowed": list(options)},
        )
    if role not in options[to]:
        raise Forbidden("Only an owner can do that")


def apply_status(
    conn: psycopg.Connection,
    ctx: OperatorContext,
    journey_id: uuid.UUID,
    current: str,
    to: str,
    *,
    reason: str | None = None,
) -> None:
    """Write the new status and its audit event. Callers must have checked the transition."""
    conn.execute(
        "update public.journeys set status = %s where id = %s and operator_id = %s",
        (to, journey_id, ctx.operator_id),
    )
    record_event(
        conn,
        operator_id=ctx.operator_id,
        actor_id=ctx.user_id,
        journey_id=journey_id,
        event_type="journey_transition",
        payload={"from": current, "to": to, **({"reason": reason} if reason else {})},
    )


def transition(
    conn: psycopg.Connection, ctx: OperatorContext, journey_id: uuid.UUID, to: str
) -> dict:
    journey = journeys.get_journey(conn, ctx, journey_id, lock=True)
    current = journey["status"]
    check_transition(current, to, ctx.role)
    if (current, to) in DEDICATED:
        raise Conflict(DEDICATED[(current, to)])
    if to == "awaiting_confirmation":
        issues = stop_plan.validate_journey(conn, ctx, journey_id)
        if validation.has_errors(issues):
            raise Conflict(
                "The journey plan has problems that must be fixed first.",
                details={
                    "issues": [
                        {"code": i.code, "message": i.message}
                        for i in issues
                        if i.severity == "error"
                    ]
                },
            )
    apply_status(conn, ctx, journey_id, current, to)
    return journeys.get_journey(conn, ctx, journey_id)
