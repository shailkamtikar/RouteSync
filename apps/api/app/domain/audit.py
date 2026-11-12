"""Append-only audit trail.

`record_event` runs on the caller's connection so the audit row commits or rolls back
together with the change it describes.
"""

import uuid
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

PAYLOAD_SCHEMA_VERSION = 1

# Passenger personal data must never be copied into audit payloads.
FORBIDDEN_PAYLOAD_KEYS = frozenset(
    {
        "passenger_name",
        "passenger_names",
        "contact_name",
        "phone",
        "phone_number",
        "seat_number",
        "seat_numbers",
        "email",
        "password",
        "token",
    }
)


class AuditPayloadError(ValueError):
    """The payload contains a field that must not be stored in the audit trail."""


def _check_payload(value: Any, path: str = "payload") -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if str(key).lower() in FORBIDDEN_PAYLOAD_KEYS:
                raise AuditPayloadError(f"{path}.{key} is not allowed in audit payloads")
            _check_payload(item, f"{path}.{key}")
    elif isinstance(value, list | tuple):
        for index, item in enumerate(value):
            _check_payload(item, f"{path}[{index}]")


def record_event(
    conn: psycopg.Connection,
    *,
    operator_id: uuid.UUID,
    event_type: str,
    actor_id: uuid.UUID | None = None,
    journey_id: uuid.UUID | None = None,
    entity_type: str | None = None,
    entity_id: uuid.UUID | None = None,
    payload: dict[str, Any] | None = None,
) -> int:
    """Insert one audit event and return its id."""
    body = dict(payload or {})
    _check_payload(body)
    body["schema_version"] = PAYLOAD_SCHEMA_VERSION
    row = conn.execute(
        "insert into public.journey_events "
        "(operator_id, journey_id, actor_id, event_type, entity_type, entity_id, payload) "
        "values (%s, %s, %s, %s, %s, %s, %s) returning id",
        (operator_id, journey_id, actor_id, event_type, entity_type, entity_id, Jsonb(body)),
    ).fetchone()
    return row[0]
