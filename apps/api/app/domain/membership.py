"""Operator membership lookups."""

import uuid
from dataclasses import dataclass

import psycopg


@dataclass(frozen=True)
class Membership:
    operator_id: uuid.UUID
    operator_name: str
    operator_status: str
    role: str


def fetch_membership(conn: psycopg.Connection, user_id: uuid.UUID) -> Membership | None:
    row = conn.execute(
        "select o.id, o.name, o.status, m.role "
        "from public.operator_members m "
        "join public.operators o on o.id = m.operator_id "
        "where m.user_id = %s",
        (user_id,),
    ).fetchone()
    return Membership(*row) if row else None
