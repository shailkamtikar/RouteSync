from datetime import timedelta

import pytest
from psycopg import errors, sql

from . import factories as f

pytestmark = pytest.mark.db

LATER = f.T0 + timedelta(days=30)


def expect_error(conn, error_type, query, params=()):
    with pytest.raises(error_type):
        with conn.transaction():
            conn.execute(query, params)


def count(conn, table, where="true", params=()):
    query = sql.SQL("select count(*) from public.{} where " + where).format(sql.Identifier(table))
    return conn.execute(query, params).fetchone()[0]


@pytest.fixture
def worlds(conn, actor, tenants):
    actor.admin()
    return f.make_world(conn, tenants["op1"]), f.make_world(conn, tenants["op2"])


# ------------------------------------------------------------------ tenant isolation (RLS)


@pytest.mark.parametrize("table", f.MEMBER_READABLE_TABLES)
def test_member_reads_only_own_operator_rows(conn, actor, tenants, worlds, table):
    actor.user(tenants["dispatcher1"])
    assert count(conn, table, "operator_id = %s", (tenants["op1"],)) >= 1
    assert count(conn, table, "operator_id = %s", (tenants["op2"],)) == 0
    assert count(conn, table) == count(conn, table, "operator_id = %s", (tenants["op1"],))


@pytest.mark.parametrize("table", f.MEMBER_READABLE_TABLES)
def test_user_without_membership_reads_nothing(conn, actor, tenants, worlds, table):
    actor.user(tenants["outsider"])
    assert count(conn, table) == 0


@pytest.mark.parametrize("table", f.ALL_DOMAIN_TABLES)
def test_anon_cannot_read(conn, actor, tenants, worlds, table):
    actor.anon()
    with pytest.raises(errors.InsufficientPrivilege):
        with conn.transaction():
            count(conn, table)


@pytest.mark.parametrize("table", f.ALL_DOMAIN_TABLES)
def test_members_cannot_write_directly(conn, actor, tenants, worlds, table):
    actor.user(tenants["owner1"])
    with pytest.raises(errors.InsufficientPrivilege):
        with conn.transaction():
            conn.execute(sql.SQL("delete from public.{}").format(sql.Identifier(table)))


def test_tracking_link_hashes_not_readable_by_members(conn, actor, tenants, worlds):
    actor.user(tenants["owner1"])
    with pytest.raises(errors.InsufficientPrivilege):
        with conn.transaction():
            count(conn, "public_tracking_links")


def test_rls_enabled_on_every_public_table(conn, actor):
    actor.admin()
    rows = conn.execute(
        "select c.relname from pg_class c join pg_namespace n on n.oid = c.relnamespace "
        "where n.nspname = 'public' and c.relkind = 'r' and not c.relrowsecurity"
    ).fetchall()
    assert rows == []


# ------------------------------------------------------------------ journey isolation (FKs)


def test_journey_cannot_use_another_operators_bus(conn, actor, worlds):
    w1, w2 = worlds
    expect_error(
        conn,
        errors.ForeignKeyViolation,
        "insert into public.journeys (operator_id, bus_id, service_id, departure_at, "
        "scheduled_arrival_at, booking_eta_at) values (%s, %s, %s, %s, %s, %s)",
        (w1["op"], w2["bus"], w1["service"], LATER, LATER + timedelta(hours=5), LATER),
    )


def test_journey_cannot_use_template_of_another_service(conn, actor, worlds):
    w1, _ = worlds
    other_service = f.make_service(conn, w1["op"], "Pune", "Latur")
    other_template = f.make_template(conn, w1["op"], other_service, "Via Latur")
    expect_error(
        conn,
        errors.ForeignKeyViolation,
        "update public.journeys set route_template_id = %s where id = %s",
        (other_template, w1["journey"]),
    )


def test_journey_stop_must_come_from_the_journeys_own_template(conn, actor, worlds):
    w1, _ = worlds
    other_template = f.make_template(conn, w1["op"], w1["service"], "Via Solapur and Latur")
    latur = f.make_template_stop(conn, w1["op"], other_template, "Latur", 76.58, 18.40)
    # Claiming the journey's template with a stop of another template fails...
    expect_error(
        conn,
        errors.ForeignKeyViolation,
        "insert into public.journey_stops (operator_id, journey_id, route_template_id, "
        "route_template_stop_id, sequence, pickup_count) values (%s, %s, %s, %s, 2, 1)",
        (w1["op"], w1["journey"], w1["template"], latur),
    )
    # ...and so does claiming the other template for this journey.
    expect_error(
        conn,
        errors.ForeignKeyViolation,
        "insert into public.journey_stops (operator_id, journey_id, route_template_id, "
        "route_template_stop_id, sequence, pickup_count) values (%s, %s, %s, %s, 2, 1)",
        (w1["op"], w1["journey"], other_template, latur),
    )


def test_stop_event_cannot_reference_another_journeys_stop(conn, actor, worlds):
    w1, _ = worlds
    bus2 = f.make_bus(conn, w1["op"])
    journey2 = f.make_journey(conn, w1["op"], bus2, w1["service"], w1["template"])
    expect_error(
        conn,
        errors.ForeignKeyViolation,
        "insert into public.stop_events (operator_id, journey_id, journey_stop_id, type, "
        "client_event_id, occurred_at) values (%s, %s, %s, 'arrived', 'x1', %s)",
        (w1["op"], journey2, w1["journey_stop"], f.T0),
    )


def test_passenger_cannot_attach_to_booking_of_another_journey(conn, actor, worlds):
    w1, _ = worlds
    bus2 = f.make_bus(conn, w1["op"])
    journey2 = f.make_journey(conn, w1["op"], bus2, w1["service"], w1["template"])
    expect_error(
        conn,
        errors.ForeignKeyViolation,
        "insert into public.booking_passengers (operator_id, journey_id, booking_id, name) "
        "values (%s, %s, %s, 'X')",
        (w1["op"], journey2, w1["booking"]),
    )


def test_child_row_cannot_claim_another_operator(conn, actor, worlds):
    w1, w2 = worlds
    expect_error(
        conn,
        errors.ForeignKeyViolation,
        "insert into public.bookings (operator_id, journey_id, reference, passenger_count, "
        "pickup_stop_name, drop_stop_name) values (%s, %s, 'R1', 1, 'A', 'B')",
        (w2["op"], w1["journey"]),
    )


def test_two_journeys_on_same_template_are_independent(conn, actor, worlds):
    w1, _ = worlds
    bus2 = f.make_bus(conn, w1["op"])
    journey2 = f.make_journey(conn, w1["op"], bus2, w1["service"], w1["template"])
    f.make_gps(conn, w1["op"], journey2)
    for table in ("gps_positions", "bookings", "journey_stops", "route_versions"):
        assert count(conn, table, "journey_id = %s", (w1["journey"],)) == 1
    assert count(conn, "gps_positions", "journey_id = %s", (journey2,)) == 1
    assert count(conn, "bookings", "journey_id = %s", (journey2,)) == 0


# ------------------------------------------------------------------ integrity rules


def test_booking_eta_is_immutable(conn, actor, worlds):
    w1, _ = worlds
    expect_error(
        conn,
        errors.RestrictViolation,
        "update public.journeys set booking_eta_at = booking_eta_at + interval '1 hour' "
        "where id = %s",
        (w1["journey"],),
    )
    # Other columns can still change.
    conn.execute("update public.journeys set manual_mode = true where id = %s", (w1["journey"],))


def test_duplicate_gps_point_rejected(conn, actor, worlds):
    w1, _ = worlds
    expect_error(
        conn,
        errors.UniqueViolation,
        "insert into public.gps_positions (operator_id, journey_id, location, device_ts, source) "
        "values (%s, %s, 'POINT(74 18.7)'::extensions.geography, %s, 'simulator')",
        (w1["op"], w1["journey"], f.T0),
    )


@pytest.mark.parametrize("bad_count", [0, -1, 101])
def test_invalid_passenger_count_rejected(conn, actor, worlds, bad_count):
    w1, _ = worlds
    expect_error(
        conn,
        errors.CheckViolation,
        "insert into public.bookings (operator_id, journey_id, reference, passenger_count, "
        "pickup_stop_name, drop_stop_name) values (%s, %s, 'R2', %s, 'A', 'B')",
        (w1["op"], w1["journey"], bad_count),
    )


def test_same_pickup_and_drop_rejected(conn, actor, worlds):
    w1, _ = worlds
    expect_error(
        conn,
        errors.CheckViolation,
        "insert into public.bookings (operator_id, journey_id, reference, passenger_count, "
        "pickup_stop_name, drop_stop_name) values (%s, %s, 'R3', 1, 'Beed', ' beed ')",
        (w1["op"], w1["journey"]),
    )


def test_arrival_must_be_after_departure(conn, actor, worlds):
    w1, _ = worlds
    bus2 = f.make_bus(conn, w1["op"])
    with pytest.raises(errors.CheckViolation):
        with conn.transaction():
            f.make_journey(conn, w1["op"], bus2, w1["service"], hours=-1)


def test_bus_cannot_have_overlapping_journeys(conn, actor, worlds):
    w1, _ = worlds
    with pytest.raises(errors.ExclusionViolation):
        with conn.transaction():
            f.make_journey(
                conn, w1["op"], w1["bus"], w1["service"], start=f.T0 + timedelta(hours=2)
            )
    # Back-to-back is fine, and a cancelled journey does not block the slot.
    f.make_journey(conn, w1["op"], w1["bus"], w1["service"], start=f.T0 + timedelta(hours=9))
    overlapping = f.T0 + timedelta(hours=3)
    f.make_journey(conn, w1["op"], w1["bus"], w1["service"], start=overlapping, status="cancelled")


def test_duplicate_bus_registration_rejected_per_operator(conn, actor, worlds):
    w1, w2 = worlds
    f.make_bus(conn, w1["op"], "MH12AB1234")
    with pytest.raises(errors.UniqueViolation):
        with conn.transaction():
            f.make_bus(conn, w1["op"], " mh12ab1234 ")
    f.make_bus(conn, w2["op"], "MH12AB1234")  # another operator may reuse it


def test_route_version_numbers_unique_and_rows_immutable(conn, actor, worlds):
    w1, _ = worlds
    with pytest.raises(errors.UniqueViolation):
        with conn.transaction():
            f.make_route_version(conn, w1["op"], w1["journey"], version=1)
    expect_error(
        conn,
        errors.RestrictViolation,
        "update public.route_versions set reason = 'edited' where id = %s",
        (w1["route_version"],),
    )


def test_audit_events_are_append_only(conn, actor, worlds):
    w1, _ = worlds
    expect_error(
        conn,
        errors.RestrictViolation,
        "update public.journey_events set event_type = 'x' where journey_id = %s",
        (w1["journey"],),
    )
    expect_error(
        conn,
        errors.RestrictViolation,
        "delete from public.journey_events where journey_id = %s",
        (w1["journey"],),
    )


def test_journey_with_history_cannot_be_deleted(conn, actor, worlds):
    w1, _ = worlds
    expect_error(
        conn,
        (errors.ForeignKeyViolation, errors.RestrictViolation),
        "delete from public.journeys where id = %s",
        (w1["journey"],),
    )


def test_only_one_open_alert_per_type(conn, actor, worlds):
    w1, _ = worlds
    expect_error(
        conn,
        errors.UniqueViolation,
        "insert into public.journey_alerts (operator_id, journey_id, type, severity, message) "
        "values (%s, %s, 'delay', 'warning', 'again')",
        (w1["op"], w1["journey"]),
    )


def test_only_one_active_tracking_link_per_journey(conn, actor, worlds):
    w1, _ = worlds
    expect_error(
        conn,
        errors.UniqueViolation,
        "insert into public.public_tracking_links (operator_id, journey_id, token_hash) "
        "values (%s, %s, %s)",
        (w1["op"], w1["journey"], "a" * 64),
    )


def test_active_stop_needs_passenger_activity(conn, actor, worlds):
    w1, _ = worlds
    expect_error(
        conn,
        errors.CheckViolation,
        "insert into public.journey_stops (operator_id, journey_id, route_template_id, "
        "route_template_stop_id, sequence, pickup_count, drop_count) "
        "values (%s, %s, %s, %s, 2, 0, 0)",
        (w1["op"], w1["journey"], w1["template"], w1["stop_b"]),
    )

