import json

import pytest

from .live_fixtures import build_live_journey

pytestmark = pytest.mark.db


@pytest.fixture
def live(api, conn, tenants):
    return build_live_journey(conn, tenants)


def monitor(api, w, who="owner1"):
    return api.get(f"/journeys/{w['journey']}/monitor", who=who)


def test_monitor_returns_one_consistent_payload(api, live):
    r = monitor(api, live)
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {
        "journey",
        "position",
        "eta",
        "route",
        "stops",
        "alerts",
        "onboard",
        "decisions",
    }
    assert body["journey"]["status"] == "in_progress"
    assert body["position"]["lat"] == pytest.approx(19.0948)
    assert body["eta"]["next_stop"]["name"] == "Beed"
    assert body["eta"]["commitment"]["status"] in ("on_time", "minor", "significant")
    assert [s["name"] for s in body["stops"]] == ["Beed", "Parbhani"]
    assert body["route"]["version"] == 1 and len(body["route"]["coordinates"]) >= 2
    assert body["onboard"]["method"] == "planned_only"
    assert body["decisions"] == []


def test_monitor_eta_equals_the_eta_endpoint(api, live):
    from_monitor = monitor(api, live).json()["eta"]
    direct = api.get(f"/journeys/{live['journey']}/eta").json()
    assert from_monitor == direct  # both read the same stored snapshot


def test_monitor_shows_stale_position_and_alerts(api, live, conn):
    conn.execute(
        "update public.journeys set last_position_at = now() - interval '10 minutes' where id = %s",
        (live["journey"],),
    )
    conn.execute(
        "insert into public.journey_alerts (operator_id, journey_id, type, severity, message) "
        "values (%s, %s, 'reroute', 'info', 'Route changed'), "
        "(%s, %s, 'no_feasible_route', 'critical', 'Blocked')",
        (live["op"], live["journey"], live["op"], live["journey"]),
    )
    body = monitor(api, live).json()
    assert body["eta"]["flags"]["stale"] is True
    assert [a["type"] for a in body["alerts"]][0] == "no_feasible_route"  # most severe first


def test_monitor_before_a_route_is_assigned(api, live, conn):
    conn.execute(
        "update public.journeys set current_route_version_id = null, status = 'draft' where id = %s",
        (live["journey"],),
    )
    body = monitor(api, live).json()
    assert body["eta"] is None and body["route"] is None


def test_monitor_without_a_position(api, live, conn):
    conn.execute(
        "update public.journeys set last_position = null, last_position_at = null where id = %s",
        (live["journey"],),
    )
    body = monitor(api, live).json()
    assert body["position"] is None and body["eta"]["flags"]["plan_based"] is True


def test_monitor_is_operator_scoped_and_authenticated(api, live):
    assert monitor(api, live, who="owner2").status_code == 404
    assert monitor(api, live, who="outsider").status_code == 403
    assert api.call("GET", f"/journeys/{live['journey']}/monitor", who=None).status_code == 401
    assert monitor(api, live, who="dispatcher1").status_code == 200


def test_monitor_never_includes_passenger_details(api, live, conn):
    booking = conn.execute(
        "insert into public.bookings (operator_id, journey_id, reference, contact_name, "
        "passenger_count, pickup_stop_name, drop_stop_name) values (%s, %s, 'REF-SECRET', "
        "'Asha Kulkarni', 1, 'Pune', 'Nanded') returning id",
        (live["op"], live["journey"]),
    ).fetchone()[0]
    conn.execute(
        "insert into public.booking_passengers (operator_id, journey_id, booking_id, name, "
        "seat_number, phone) values (%s, %s, %s, 'Asha Kulkarni', '12A', '+919800000000')",
        (live["op"], live["journey"], booking),
    )
    text = json.dumps(monitor(api, live).json())
    for secret in ("Asha", "REF-SECRET", "12A", "9800000000"):
        assert secret not in text
