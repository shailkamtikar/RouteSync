from datetime import UTC, datetime, timedelta

import psycopg
import pytest

from app.auth.deps import OperatorContext
from app.eta import service

from . import factories as f

pytestmark = pytest.mark.db


def build(conn, tenants, *, status="in_progress", promise_in_min=30, duration_s=21600):
    """A journey on its way whose booking promise is `promise_in_min` minutes from now."""
    op = tenants["op1"]
    now = datetime.now(UTC)
    bus, svc = f.make_bus(conn, op), f.make_service(conn, op)
    template = f.make_template(conn, op, svc)
    stop = f.make_template_stop(conn, op, template, "Ahmednagar", 74.74, 19.09)
    start = now - timedelta(hours=1)
    hours = 1 + promise_in_min / 60
    journey = f.make_journey(conn, op, bus, svc, template, start=start, hours=hours, status=status)
    f.make_journey_stop(conn, op, journey, template, stop)
    version = f.make_route_version(conn, op, journey, 1, distance_m=450_000, duration_s=duration_s)
    conn.execute(
        "update public.journeys set current_route_version_id = %s, "
        "last_position = 'POINT(74.2 18.8)'::extensions.geography, "
        "last_position_at = now() - interval '5 seconds' where id = %s",
        (version, journey),
    )
    ctx = OperatorContext(tenants["owner1"], None, op, "Test Operator One", "owner")
    return {"journey": journey, "ctx": ctx, "op": op}


def refresh(conn, w):
    return service.current_snapshot(conn, w["ctx"], w["journey"], max_age_s=0)


def open_alerts(conn, w):
    return conn.execute(
        "select severity, message, is_public from public.journey_alerts "
        "where journey_id = %s and type = 'delay' and resolved_at is null",
        (w["journey"],),
    ).fetchall()


def event_types(conn, w):
    rows = conn.execute(
        "select event_type from public.journey_events where journey_id = %s "
        "and event_type like 'delay_alert%%' order by id",
        (w["journey"],),
    ).fetchall()
    return [r[0] for r in rows]


@pytest.fixture
def late(conn, actor, tenants):
    actor.admin()
    return build(conn, tenants)  # ~6 h route, promise in 30 min: hours late


def test_snapshot_carries_original_predicted_and_delay(conn, late):
    payload = refresh(conn, late)
    promise = conn.execute(
        "select booking_eta_at from public.journeys where id = %s", (late["journey"],)
    ).fetchone()[0]
    c = payload["commitment"]
    assert c["original_eta"] == promise.isoformat()
    assert c["predicted_eta"] == payload["destination"]["eta"]
    assert c["delay_minutes"] > 60 and c["status"] == "significant" and c["is_early"] is False


def test_late_journey_opens_exactly_one_public_alert(conn, late):
    for _ in range(3):
        refresh(conn, late)
    alerts = open_alerts(conn, late)
    assert len(alerts) == 1
    severity, message, is_public = alerts[0]
    assert severity == "critical" and is_public is True
    assert "later than promised at booking" in message
    assert event_types(conn, late) == ["delay_alert_opened"]


def test_alert_resolves_when_the_journey_recovers(conn, late):
    refresh(conn, late)
    assert len(open_alerts(conn, late)) == 1
    quick = f.make_route_version(conn, late["op"], late["journey"], 2, 450_000, 600)
    conn.execute(
        "update public.journeys set current_route_version_id = %s where id = %s",
        (quick, late["journey"]),
    )
    payload = refresh(conn, late)
    assert payload["commitment"]["status"] == "on_time"
    assert open_alerts(conn, late) == []
    assert event_types(conn, late) == ["delay_alert_opened", "delay_alert_resolved"]
    resolved = conn.execute(
        "select count(*) from public.journey_alerts where journey_id = %s "
        "and resolved_at is not null",
        (late["journey"],),
    ).fetchone()[0]
    assert resolved == 1


def test_on_time_journey_raises_no_alert(conn, actor, tenants):
    actor.admin()
    w = build(conn, tenants, promise_in_min=60 * 24)
    payload = refresh(conn, w)
    assert payload["commitment"]["status"] == "on_time" and payload["commitment"]["is_early"]
    assert payload["commitment"]["delay_minutes"] < 0
    assert open_alerts(conn, w) == [] and event_types(conn, w) == []


@pytest.mark.parametrize("status", ["draft", "ready"])
def test_unpublished_journeys_never_alert(conn, actor, tenants, status):
    actor.admin()
    w = build(conn, tenants, status=status)
    assert refresh(conn, w)["commitment"]["status"] == "significant"
    assert open_alerts(conn, w) == []


def test_alert_is_scoped_to_its_own_journey(conn, actor, tenants):
    actor.admin()
    a, b = build(conn, tenants), build(conn, tenants, promise_in_min=60 * 24)
    refresh(conn, a)
    refresh(conn, b)
    assert len(open_alerts(conn, a)) == 1 and open_alerts(conn, b) == []


def test_the_promise_cannot_be_changed_in_the_database(conn, late):
    with pytest.raises(psycopg.errors.RestrictViolation):
        with conn.transaction():
            conn.execute(
                "update public.journeys set booking_eta_at = booking_eta_at + interval '2 hours' "
                "where id = %s",
                (late["journey"],),
            )


def test_api_snapshot_includes_the_commitment(api, conn, tenants, late):
    r = api.get(f"/journeys/{late['journey']}/eta")
    assert r.status_code == 200
    assert r.json()["commitment"]["status"] == "significant"
