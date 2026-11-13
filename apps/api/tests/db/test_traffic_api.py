import pytest

from app.eta import service

from .live_fixtures import PARBHANI, build_live_journey

pytestmark = pytest.mark.db

SLOW = {"kind": "slow", "from_km": 250, "to_km": 300, "multiplier": 2.0}


@pytest.fixture
def live(api, conn, tenants):
    return build_live_journey(conn, tenants)


def eta(conn, w):
    return service.current_snapshot(conn, w["ctx"], w["journey"], max_age_s=0)


def inject(api, w, body=SLOW, who="owner1"):
    return api.post(f"/route-templates/{w['template']}/traffic-incidents", body, who=who)


def open_alert_types(conn, w):
    rows = conn.execute(
        "select type, message, is_public from public.journey_alerts "
        "where journey_id = %s and resolved_at is null order by type",
        (w["journey"],),
    ).fetchall()
    return {row[0]: row for row in rows}


def test_slowdown_ahead_delays_the_journey_and_is_labelled_simulated(api, live, conn):
    before = eta(conn, live)
    r = inject(api, live)
    assert r.status_code == 201
    assert r.json()["simulated"] is True and r.json()["multiplier"] == 2.0
    after = eta(conn, live)
    assert after["destination"]["eta"] > before["destination"]["eta"]
    assert after["flags"]["traffic_ahead"] is True and after["flags"]["traffic_simulated"] is True
    assert any("Simulated" in w["message"] for w in after["warnings"])
    alert = open_alert_types(conn, live)["traffic"]
    assert "Simulated" in alert[1] and alert[2] is True


def test_ending_the_incident_restores_the_eta_and_resolves_the_alert(api, live, conn):
    before = eta(conn, live)["destination"]["eta"]
    incident = inject(api, live).json()
    assert eta(conn, live)["destination"]["eta"] > before
    assert api.delete(f"/traffic-incidents/{incident['id']}").status_code == 204
    restored = eta(conn, live)
    assert restored["flags"]["traffic_ahead"] is False
    assert "traffic" not in open_alert_types(conn, live)
    assert api.get(f"/route-templates/{live['template']}/traffic-incidents").json() == []
    history = api.get(f"/route-templates/{live['template']}/traffic-incidents?active_only=false")
    assert len(history.json()) == 1


def test_incident_with_duration_expires_by_itself(api, live, conn):
    inject(api, live, {**SLOW, "duration_minutes": 30})
    conn.execute(
        "update public.traffic_incidents set starts_at = now() - interval '2 hours', "
        "ends_at = now() - interval '90 minutes' where route_template_id = %s",
        (live["template"],),
    )
    assert eta(conn, live)["flags"]["traffic_ahead"] is False


def test_overlapping_incidents_use_the_larger_slowdown(api, live, conn):
    base = eta(conn, live)["destination"]["eta"]
    inject(api, live, {**SLOW, "multiplier": 2.0})
    two = eta(conn, live)["destination"]["eta"]
    inject(api, live, {**SLOW, "multiplier": 3.0})
    three = eta(conn, live)["destination"]["eta"]
    assert base < two < three


def test_closure_ahead_raises_a_critical_public_alert(api, live, conn):
    r = inject(api, live, {"kind": "closure", "from_km": 250, "to_km": 260})
    assert r.status_code == 201 and r.json()["multiplier"] == 1.0
    snapshot = eta(conn, live)
    assert snapshot["flags"]["closure_ahead"] is True
    alert = conn.execute(
        "select severity, message from public.journey_alerts where journey_id = %s "
        "and type = 'road_closure' and resolved_at is null",
        (live["journey"],),
    ).fetchone()
    assert alert[0] == "critical" and "Simulated road closure" in alert[1]


def test_incident_affects_only_journeys_that_still_have_it_ahead(api, live, conn, tenants):
    ahead = live
    passed = build_live_journey(
        conn, tenants, position=PARBHANI, template=live["template"], service=live["service"]
    )
    inject(api, ahead, {**SLOW, "from_km": 150, "to_km": 200})
    assert eta(conn, ahead)["flags"]["traffic_ahead"] is True
    assert eta(conn, passed)["flags"]["traffic_ahead"] is False
    assert "traffic" not in open_alert_types(conn, passed)


def test_incident_on_another_route_option_does_not_touch_this_journey(api, live, conn, tenants):
    other = build_live_journey(conn, tenants)  # its own template
    inject(api, other)
    assert eta(conn, live)["flags"]["traffic_ahead"] is False


@pytest.mark.parametrize(
    "body",
    [
        {**SLOW, "from_km": 300, "to_km": 250},
        {**SLOW, "from_km": 100, "to_km": 100},
        {**SLOW, "multiplier": 0.5},
        {**SLOW, "multiplier": 50},
        {**SLOW, "kind": "meteor"},
        {**SLOW, "to_km": 4000},
        {**SLOW, "duration_minutes": 0},
        {**SLOW, "simulated": False},
    ],
)
def test_invalid_incident_is_422(api, live, body):
    assert inject(api, live, body).status_code == 422
    assert api.get(f"/route-templates/{live['template']}/traffic-incidents").json() == []


def test_traffic_endpoints_are_operator_scoped_and_authenticated(api, live):
    incident = inject(api, live).json()
    t = live["template"]
    assert inject(api, live, who="owner2").status_code == 404
    assert api.get(f"/route-templates/{t}/traffic-incidents", who="owner2").status_code == 404
    assert api.delete(f"/traffic-incidents/{incident['id']}", who="owner2").status_code == 404
    assert (
        api.call("POST", f"/route-templates/{t}/traffic-incidents", who=None, json=SLOW).status_code
        == 401
    )
    assert len(api.get(f"/route-templates/{t}/traffic-incidents").json()) == 1


def test_database_refuses_an_incident_not_marked_simulated(live, conn):
    import psycopg

    with pytest.raises(psycopg.errors.CheckViolation):
        with conn.transaction():
            conn.execute(
                "insert into public.traffic_incidents (operator_id, route_template_id, kind, "
                "from_point, to_point, from_km, to_km, simulated) values (%s, %s, 'slow', "
                "'POINT(75 19)'::extensions.geography, 'POINT(76 19)'::extensions.geography, 1, 2, false)",
                (live["op"], live["template"]),
            )
