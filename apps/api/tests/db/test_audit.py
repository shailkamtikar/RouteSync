import uuid

import pytest
from psycopg import errors

from app.domain.audit import AuditPayloadError, record_event

from . import factories as f

pytestmark = pytest.mark.db


@pytest.fixture
def world(conn, actor, tenants):
    actor.admin()
    return f.make_world(conn, tenants["op1"])


def test_record_event_stores_actor_type_and_utc_time(conn, world, tenants):
    event_id = record_event(
        conn,
        operator_id=world["op"],
        journey_id=world["journey"],
        actor_id=tenants["owner1"],
        event_type="journey_transition",
        payload={"from": "draft", "to": "ready"},
    )
    row = conn.execute(
        "select actor_id, event_type, payload, created_at, "
        "extract(timezone from created_at) from public.journey_events where id = %s",
        (event_id,),
    ).fetchone()
    assert row[0] == tenants["owner1"]
    assert row[1] == "journey_transition"
    assert row[2] == {"from": "draft", "to": "ready", "schema_version": 1}
    assert row[3] is not None


def test_operator_level_event_without_journey(conn, world):
    event_id = record_event(
        conn,
        operator_id=world["op"],
        event_type="bus_created",
        entity_type="bus",
        entity_id=world["bus"],
    )
    row = conn.execute(
        "select journey_id, entity_type, entity_id from public.journey_events where id = %s",
        (event_id,),
    ).fetchone()
    assert row == (None, "bus", world["bus"])


def test_unknown_journey_is_rejected(conn, world):
    with pytest.raises(errors.ForeignKeyViolation):
        with conn.transaction():
            record_event(conn, operator_id=world["op"], journey_id=uuid.uuid4(), event_type="x")


def test_journey_of_another_operator_is_rejected(conn, world, tenants):
    with pytest.raises(errors.ForeignKeyViolation):
        with conn.transaction():
            record_event(
                conn, operator_id=tenants["op2"], journey_id=world["journey"], event_type="x"
            )


def test_personal_data_never_reaches_the_table(conn, world):
    before = conn.execute("select count(*) from public.journey_events").fetchone()[0]
    with pytest.raises(AuditPayloadError):
        record_event(
            conn,
            operator_id=world["op"],
            journey_id=world["journey"],
            event_type="booking_created",
            payload={"passenger_name": "Asha Kulkarni"},
        )
    after = conn.execute("select count(*) from public.journey_events").fetchone()[0]
    assert after == before


def test_recorded_event_cannot_be_changed_or_deleted(conn, world):
    event_id = record_event(conn, operator_id=world["op"], event_type="x")
    for statement in (
        "update public.journey_events set event_type = 'y' where id = %s",
        "delete from public.journey_events where id = %s",
    ):
        with pytest.raises(errors.RestrictViolation):
            with conn.transaction():
                conn.execute(statement, (event_id,))
