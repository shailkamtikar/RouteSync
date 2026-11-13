import uuid
from datetime import UTC, datetime, timedelta

import pytest

from . import factories as f

pytestmark = pytest.mark.db


@pytest.fixture
def world(api, conn, tenants):
    """A boarding journey with three active stops: Pune (origin), Beed, Nanded (destination)."""
    op = tenants["op1"]
    bus, svc = f.make_bus(conn, op), f.make_service(conn, op)
    template = f.make_template(conn, op, svc)
    stops = {}
    for name, lng, lat, role in (
        ("Pune", 73.8567, 18.5204, "origin"),
        ("Beed", 75.76, 18.99, "intermediate"),
        ("Nanded", 77.321, 19.1383, "destination"),
    ):
        stop = f.make_template_stop(conn, op, template, name, lng, lat)
        conn.execute("update public.route_template_stops set role = %s where id = %s", (role, stop))
        stops[name] = stop
    journey = f.make_journey(conn, op, bus, svc, template, status="boarding")
    ids = {}
    for sequence, (name, pickup, drop) in enumerate(
        (("Pune", 5, 0), ("Beed", 2, 3), ("Nanded", 0, 4)), start=1
    ):
        ids[name] = str(
            conn.execute(
                "insert into public.journey_stops (operator_id, journey_id, route_template_id, "
                "route_template_stop_id, sequence, pickup_count, drop_count) "
                "values (%s, %s, %s, %s, %s, %s, %s) returning id",
                (op, journey, template, stops[name], sequence, pickup, drop),
            ).fetchone()[0]
        )
    return {"journey": journey, "stops": ids, "op": op, "template": template}


def post(api, world, stop, kind, count=0, who="owner1", event_id=None, **extra):
    body = {
        "journey_stop_id": world["stops"][stop] if stop in world["stops"] else stop,
        "type": kind,
        "count": count,
        "client_event_id": event_id or uuid.uuid4().hex,
        **extra,
    }
    return api.post(f"/journeys/{world['journey']}/stop-events", body, who=who)


def stop_status(conn, world, stop):
    return conn.execute(
        "select status from public.journey_stops where id = %s", (world["stops"][stop],)
    ).fetchone()[0]


def journey_status(conn, world):
    return conn.execute(
        "select status from public.journeys where id = %s", (world["journey"],)
    ).fetchone()[0]


def test_arrive_board_depart_completes_the_stop_and_starts_the_journey(api, world, conn):
    assert post(api, world, "Pune", "arrived").status_code == 200
    assert stop_status(conn, world, "Pune") == "arrived"
    boarded = post(api, world, "Pune", "boarded", 5)
    assert boarded.json()["onboard"]["onboard"] == 5
    assert journey_status(conn, world) == "boarding"
    departed = post(api, world, "Pune", "departed")
    assert departed.json()["journey_status"] == "in_progress"
    assert stop_status(conn, world, "Pune") == "departed"
    assert journey_status(conn, world) == "in_progress"


def test_departure_without_arrival_is_refused(api, world, conn):
    r = post(api, world, "Pune", "departed")
    assert r.status_code == 409 and "arrival" in r.json()["detail"]
    assert stop_status(conn, world, "Pune") == "pending"


def test_repeated_request_has_one_effect(api, world, conn):
    post(api, world, "Pune", "arrived")
    first = post(api, world, "Pune", "boarded", 5, event_id="evt-1")
    again = post(api, world, "Pune", "boarded", 5, event_id="evt-1")
    assert first.status_code == again.status_code == 200
    assert first.json()["duplicate"] is False and again.json()["duplicate"] is True
    assert again.json()["id"] == first.json()["id"]
    assert again.json()["onboard"]["onboard"] == 5
    count = conn.execute(
        "select count(*) from public.stop_events where journey_id = %s and type = 'boarded'",
        (world["journey"],),
    ).fetchone()[0]
    assert count == 1


def test_cannot_alight_more_than_are_on_board(api, world):
    post(api, world, "Pune", "arrived")
    post(api, world, "Pune", "boarded", 5)
    post(api, world, "Pune", "departed")
    post(api, world, "Beed", "arrived")
    r = post(api, world, "Beed", "alighted", 8)
    assert r.status_code == 422 and "only 5" in r.json()["detail"]
    assert post(api, world, "Beed", "alighted", 3).json()["onboard"]["onboard"] == 2
    assert post(api, world, "Beed", "boarded", 2).json()["onboard"]["onboard"] == 4


def test_counts_only_while_the_bus_is_at_the_stop(api, world):
    assert post(api, world, "Pune", "boarded", 5).status_code == 409  # not arrived yet
    post(api, world, "Pune", "arrived")
    assert post(api, world, "Pune", "boarded", 0).status_code == 422
    assert post(api, world, "Pune", "boarded", -2).status_code == 422
    post(api, world, "Pune", "departed")
    assert post(api, world, "Pune", "boarded", 1).status_code == 409  # already left


def test_stops_cannot_be_skipped(api, world, conn):
    r = post(api, world, "Beed", "arrived")
    assert r.status_code == 409 and "Pune" in r.json()["detail"]
    assert stop_status(conn, world, "Beed") == "pending"
    post(api, world, "Pune", "arrived")
    assert post(api, world, "Beed", "arrived").status_code == 409  # Pune not departed yet
    assert post(api, world, "Pune", "arrived").status_code == 409  # already arrived


def test_finishing_at_the_destination_completes_the_journey(api, world, conn):
    for stop in ("Pune", "Beed"):
        post(api, world, stop, "arrived")
        post(api, world, stop, "departed")
    post(api, world, "Nanded", "arrived")
    assert journey_status(conn, world) == "in_progress"
    done = post(api, world, "Nanded", "departed")
    assert done.json()["journey_status"] == "completed"
    assert journey_status(conn, world) == "completed"
    assert post(api, world, "Nanded", "arrived").status_code == 409
    transitions = conn.execute(
        "select payload ->> 'to', payload ->> 'reason' from public.journey_events "
        "where journey_id = %s and event_type = 'journey_transition' order by id",
        (world["journey"],),
    ).fetchall()
    assert transitions == [
        ("in_progress", "departed at Pune"),
        ("completed", "departed at Nanded"),
    ]


def test_without_count_events_only_the_planned_figure_is_given(api, world):
    post(api, world, "Pune", "arrived")
    post(api, world, "Pune", "departed")
    summary = api.get(f"/journeys/{world['journey']}/onboard").json()
    assert summary["method"] == "planned_only" and summary["onboard"] is None
    assert summary["planned_onboard"] == 5


def test_late_reported_events_are_ordered_by_when_they_happened(api, world):
    now = datetime.now(UTC)
    post(api, world, "Pune", "arrived", occurred_at=(now - timedelta(minutes=10)).isoformat())
    post(api, world, "Pune", "boarded", 2, occurred_at=(now - timedelta(minutes=5)).isoformat())
    post(api, world, "Pune", "boarded", 3, occurred_at=(now - timedelta(minutes=8)).isoformat())
    events = api.get(f"/journeys/{world['journey']}/stop-events").json()
    assert [e["count"] for e in events if e["type"] == "boarded"] == [3, 2]
    assert api.get(f"/journeys/{world['journey']}/onboard").json()["onboard"] == 5


def test_future_event_time_is_rejected(api, world):
    future = (datetime.now(UTC) + timedelta(minutes=30)).isoformat()
    assert post(api, world, "Pune", "arrived", occurred_at=future).status_code == 422
    assert post(api, world, "Pune", "arrived", occurred_at="2031-01-01T10:00:00").status_code == 422


def test_stop_of_another_journey_is_not_found(api, world, conn, tenants):
    other = f.make_world(conn, tenants["op1"])
    r = post(api, world, str(other["journey_stop"]), "arrived")
    assert r.status_code == 404
    assert post(api, world, str(uuid.uuid4()), "arrived").status_code == 404


def test_stop_events_are_operator_scoped_and_authenticated(api, world):
    j = world["journey"]
    assert post(api, world, "Pune", "arrived", who="owner2").status_code == 404
    assert api.get(f"/journeys/{j}/stop-events", who="owner2").status_code == 404
    assert api.get(f"/journeys/{j}/onboard", who="owner2").status_code == 404
    assert api.call("POST", f"/journeys/{j}/stop-events", who=None, json={}).status_code == 401
    assert post(api, world, "Pune", "arrived", who="dispatcher1").status_code == 200


@pytest.mark.parametrize("status", ["draft", "ready", "published", "completed", "cancelled"])
def test_events_only_while_boarding_or_running(api, world, conn, status):
    conn.execute("update public.journeys set status = %s where id = %s", (status, world["journey"]))
    assert post(api, world, "Pune", "arrived").status_code == 409


@pytest.mark.parametrize(
    "bad",
    [
        {"type": "teleported"},
        {"client_event_id": ""},
        {"client_event_id": "has spaces"},
        {"count": 500},
        {"journey_id": str(uuid.uuid4())},
    ],
)
def test_invalid_event_is_422(api, world, bad):
    body = {
        "journey_stop_id": world["stops"]["Pune"],
        "type": "arrived",
        "client_event_id": "e1",
        **bad,
    }
    assert api.post(f"/journeys/{world['journey']}/stop-events", body).status_code == 422


def test_events_are_audited_without_personal_data(api, world, conn):
    post(api, world, "Pune", "arrived")
    post(api, world, "Pune", "boarded", 5)
    rows = conn.execute(
        "select payload from public.journey_events where journey_id = %s "
        "and event_type = 'stop_event_recorded' order by id",
        (world["journey"],),
    ).fetchall()
    assert [(r[0]["stop"], r[0]["type"], r[0]["count"]) for r in rows] == [
        ("Pune", "arrived", 0),
        ("Pune", "boarded", 5),
    ]
