"""Fixtures for tests that run against the real dev database.

Every test runs inside one transaction that is rolled back, so no rows are left behind.
Run with: pytest -m db
"""

import json
import uuid
from pathlib import Path

import psycopg
import pytest
from dotenv import dotenv_values

ENV_FILE = Path(__file__).resolve().parents[2] / ".env"


@pytest.fixture(scope="session")
def _connection():
    url = dotenv_values(ENV_FILE).get("DATABASE_URL")
    if not url:
        pytest.skip("DATABASE_URL not configured in apps/api/.env")
    connection = psycopg.connect(url, connect_timeout=15)
    try:
        yield connection
    finally:
        connection.rollback()
        connection.close()


@pytest.fixture
def conn(_connection):
    """One shared connection; each test runs in a savepoint that is always rolled back."""
    with _connection.transaction(force_rollback=True):
        yield _connection


class Actor:
    """Switches the session between privileged, authenticated-user and anonymous roles."""

    def __init__(self, connection: psycopg.Connection):
        self.c = connection

    def admin(self) -> None:
        self.c.execute("reset role")
        self.c.execute("select set_config('request.jwt.claims', '', true)")

    def user(self, user_id: uuid.UUID) -> None:
        self.admin()
        claims = json.dumps({"sub": str(user_id), "role": "authenticated"})
        self.c.execute("select set_config('request.jwt.claims', %s, true)", (claims,))
        self.c.execute("set local role authenticated")

    def anon(self) -> None:
        self.admin()
        self.c.execute("set local role anon")


@pytest.fixture
def actor(conn) -> Actor:
    return Actor(conn)


def make_user(c: psycopg.Connection) -> uuid.UUID:
    user_id = uuid.uuid4()
    c.execute(
        "insert into auth.users (id, instance_id, aud, role, email) "
        "values (%s, '00000000-0000-0000-0000-000000000000', 'authenticated', 'authenticated', %s)",
        (user_id, f"test-{user_id.hex}@routesync.test"),
    )
    return user_id


def make_operator(c: psycopg.Connection, name: str) -> uuid.UUID:
    return c.execute(
        "insert into public.operators (name) values (%s) returning id", (name,)
    ).fetchone()[0]


def add_member(c: psycopg.Connection, operator_id, user_id, role: str) -> None:
    c.execute(
        "insert into public.operator_members (operator_id, user_id, role) values (%s, %s, %s)",
        (operator_id, user_id, role),
    )


@pytest.fixture
def tenants(conn, actor):
    """Two operators: Op1 has an owner and a dispatcher, Op2 has an owner."""
    actor.admin()
    data = {
        "op1": make_operator(conn, "Test Operator One"),
        "op2": make_operator(conn, "Test Operator Two"),
        "owner1": make_user(conn),
        "dispatcher1": make_user(conn),
        "owner2": make_user(conn),
        "outsider": make_user(conn),
    }
    add_member(conn, data["op1"], data["owner1"], "owner")
    add_member(conn, data["op1"], data["dispatcher1"], "dispatcher")
    add_member(conn, data["op2"], data["owner2"], "owner")
    return data
