import psycopg
import pytest
from dotenv import dotenv_values
from psycopg.types.json import Jsonb

from app.domain import reroute
from app.domain.routing import get_routing_provider
from app.main import app
from app.optimizer import geo
from app.providers.routing.base import RoutingUnavailable
from app.providers.routing.fake import FakeRoutingProvider

from .conftest import ENV_FILE
from .live_fixtures import BEED, PARBHANI, build_live_journey

pytestmark = pytest.mark.db

# Middle of the Beed-Parbhani stretch of the approved road, and an approved bypass ~4 km north.
MID = ((BEED[0] + PARBHANI[0]) / 2, (BEED[1] + PARBHANI[1]) / 2)
BYPASS_POINT = {"lng": MID[0], "lat": MID[1] + 0.038}
BYPASS = [{"name": "Northern bypass", "points": [BYPASS_POINT]}]
A = (MID[0] - 0.03, MID[1] - 0.008)  # ~3 km before the middle, on the road
B = (MID[0] + 0.03, MID[1] + 0.008)  # ~3 km after it


@pytest.fixture
def provider():
    fake = FakeRoutingProvider()
    app.dependency_overrides[get_routing_provider] = lambda: fake
    yield fake
    app.dependency_overrides.pop(get_routing_provider, None)


@pytest.fixture
def live(api, conn, tenants):
    w = build_live_journey(conn, tenants)
    conn.execute(
        "update public.route_templates set variants = %s where id = %s",
        (Jsonb(BYPASS), w["template"]),
    )
    return w


def incident(conn, w, kind="slow", multiplier=20.0, a=A, b=B):
    conn.execute(
        "insert into public.traffic_incidents (operator_id, route_template_id, kind, multiplier, "
        "from_point, to_point, from_km, to_km, starts_at) values (%s, %s, %s, %s, "
        "%s::extensions.geography, %s::extensions.geography, 1, 2, clock_timestamp() - interval '1 minute')",
        (
            w["op"],
            w["template"],
            kind,
            multiplier,
            f"POINT({a[0]} {a[1]})",
            f"POINT({b[0]} {b[1]})",
        ),
    )


def run(conn, w, provider, **kwargs):
    kwargs.setdefault("force", True)
    return reroute.evaluate(conn, w["op"], w["journey"], provider, **kwargs)


def versions(conn, w):
    return conn.execute(
        "select version, source, reason, details, id from public.route_versions "
        "where journey_id = %s order by version",
        (w["journey"],),
    ).fetchall()


def decisions(conn, w):
    return conn.execute(
        "select outcome, reason_code from public.route_decisions where journey_id = %s order by id",
        (w["journey"],),
    ).fetchall()


def open_alerts(conn, w):
    rows = conn.execute(
        "select type, severity, is_public from public.journey_alerts "
        "where journey_id = %s and resolved_at is null",
        (w["journey"],),
    ).fetchall()
    return {r[0]: r for r in rows}


def current_route(conn, w):
    row = conn.execute(
        "select extensions.st_asgeojson(v.geometry::extensions.geometry)::jsonb -> 'coordinates' "
        "from public.journeys j join public.route_versions v on v.id = j.current_route_version_id "
        "where j.id = %s",
        (w["journey"],),
    ).fetchone()[0]
    return [(c[0], c[1]) for c in row]


# ------------------------------------------------------------------ keep the route


def test_journey_running_normally_keeps_its_route_and_spends_no_quota(conn, live, provider):
    result = run(conn, live, provider)
    assert result == {"action": "keep", "reason_code": "no_disruption", "logged": False}
    assert provider.calls == [] and decisions(conn, live) == []
    assert len(versions(conn, live)) == 1


def test_marginal_slowdown_does_not_change_the_route(conn, live, provider):
    incident(conn, live, multiplier=1.3)
    for _ in range(3):
        result = run(conn, live, provider)
    assert result["action"] == "keep" and result["reason_code"] == "below_threshold"
    assert len(versions(conn, live)) == 1
    assert set(decisions(conn, live)) == {("keep", "below_threshold")}


def test_evaluations_are_throttled(conn, live, provider):
    incident(conn, live)
    assert run(conn, live, provider, force=False) is not None
    assert run(conn, live, provider, force=False) is None
    assert len(decisions(conn, live)) == 1


def test_stale_position_blocks_a_change(conn, live, provider):
    incident(conn, live)
    conn.execute(
        "update public.journeys set last_position_at = now() - interval '10 minutes' where id = %s",
        (live["journey"],),
    )
    for _ in range(3):
        result = run(conn, live, provider)
    assert result["action"] == "keep" and result["reason_code"] == "gps_stale"
    assert len(versions(conn, live)) == 1


def test_routing_provider_down_keeps_the_current_route(conn, live, provider):
    incident(conn, live)
    provider.fail_with = RoutingUnavailable("simulated")
    for _ in range(3):
        result = run(conn, live, provider)
    assert result["action"] == "keep"
    assert len(versions(conn, live)) == 1


# ------------------------------------------------------------------ meaningful change


def test_big_slowdown_reroutes_after_two_confirming_evaluations(conn, live, provider):
    incident(conn, live)
    first = run(conn, live, provider)
    assert first["action"] == "keep" and first["reason_code"] == "awaiting_confirmation"
    assert len(versions(conn, live)) == 1

    second = run(conn, live, provider)
    assert second["action"] == "reroute" and second["chosen_name"] == "Northern bypass"
    assert second["saving_minutes"] > 60

    rows = versions(conn, live)
    assert [(r[0], r[1]) for r in rows] == [(1, "operator_initial"), (2, "auto_reroute")]
    v2 = rows[1]
    assert "Northern bypass" in v2[2] and "serves every remaining stop" in v2[2]
    assert v2[3]["previous_version"] == 1 and v2[3]["reason_code"] == "meaningful_saving"
    assert v2[3]["chosen"]["breakdown"]["travel_time"]["minutes"] > 0
    assert str(v2[4]) == str(second["route_version_id"])
    assert decisions(conn, live) == [
        ("keep", "awaiting_confirmation"),
        ("reroute", "meaningful_saving"),
    ]
    alert = open_alerts(conn, live)["reroute"]
    assert alert[2] is False  # the operator is told; it is not a public message
    event = conn.execute(
        "select payload from public.journey_events where journey_id = %s "
        "and event_type = 'route_rerouted'",
        (live["journey"],),
    ).fetchone()[0]
    assert event["from_version"] == 1 and event["to_version"] == 2 and event["automatic"] is True


def test_the_new_route_still_serves_every_active_stop_and_stays_in_the_corridor(
    conn, live, provider
):
    incident(conn, live)
    run(conn, live, provider)
    run(conn, live, provider)
    route = current_route(conn, live)
    assert geo.distance_to_line_m(route, BEED) < 1000
    assert geo.distance_to_line_m(route, PARBHANI) < 1000
    assert geo.chainage_m(route, BEED) < geo.chainage_m(route, PARBHANI)
    corridor = conn.execute(
        "select extensions.st_asgeojson(geometry::extensions.geometry)::jsonb -> 'coordinates' "
        "from public.route_templates where id = %s",
        (live["template"],),
    ).fetchone()[0]
    assert geo.max_distance_from_line_m(route, [(c[0], c[1]) for c in corridor]) <= 5000


def test_no_flapping_after_a_reroute(conn, live, provider):
    incident(conn, live)
    for _ in range(8):
        run(conn, live, provider)
    assert len(versions(conn, live)) == 2  # exactly one change, however often it is evaluated


def test_closure_on_the_current_route_reroutes_immediately(conn, live, provider):
    incident(conn, live, kind="closure", multiplier=1.0)
    result = run(conn, live, provider)
    assert result["action"] == "reroute" and result["reason_code"] == "current_route_blocked"
    assert [r[1] for r in versions(conn, live)] == ["operator_initial", "auto_reroute"]


def test_closure_with_no_approved_alternative_marks_the_journey_disrupted(conn, live, provider):
    conn.execute(
        "update public.route_templates set variants = '[]' where id = %s", (live["template"],)
    )
    incident(conn, live, kind="closure", multiplier=1.0)
    result = run(conn, live, provider)
    assert result["action"] == "no_feasible_route"
    assert len(versions(conn, live)) == 1
    status = conn.execute(
        "select status from public.journeys where id = %s", (live["journey"],)
    ).fetchone()[0]
    assert status == "disrupted"
    assert open_alerts(conn, live)["no_feasible_route"][1] == "critical"


# ------------------------------------------------------------------ manual mode


def test_manual_mode_only_recommends_until_the_operator_approves(api, conn, live, provider):
    r = api.put(f"/journeys/{live['journey']}/manual-mode", {"enabled": True})
    assert r.status_code == 200 and r.json()["manual_mode"] is True
    incident(conn, live)
    run(conn, live, provider)
    second = run(conn, live, provider)
    assert second["action"] == "recommend"
    assert len(versions(conn, live)) == 1
    assert "reroute_recommended" in open_alerts(conn, live)

    approved = api.post(f"/journeys/{live['journey']}/reroute/evaluate", {"apply": True})
    assert approved.status_code == 200 and approved.json()["action"] == "reroute"
    rows = versions(conn, live)
    assert [(r[0], r[1]) for r in rows] == [(1, "operator_initial"), (2, "operator_reroute")]
    assert "reroute_recommended" not in open_alerts(conn, live)


def test_manual_mode_toggle_is_audited(api, conn, live):
    api.put(f"/journeys/{live['journey']}/manual-mode", {"enabled": True})
    api.put(f"/journeys/{live['journey']}/manual-mode", {"enabled": True})  # no change
    api.put(f"/journeys/{live['journey']}/manual-mode", {"enabled": False})
    rows = conn.execute(
        "select payload ->> 'enabled' from public.journey_events where journey_id = %s "
        "and event_type = 'manual_mode_changed' order by id",
        (live["journey"],),
    ).fetchall()
    assert rows == [("true",), ("false",)]


# ------------------------------------------------------------------ isolation and concurrency


def test_only_the_journey_with_the_slowdown_ahead_is_rerouted(conn, live, provider, tenants):
    passed = build_live_journey(
        conn, tenants, position=PARBHANI, template=live["template"], service=live["service"]
    )
    conn.execute(
        "update public.journey_stops set status = 'departed' where journey_id = %s",
        (passed["journey"],),
    )
    incident(conn, live)
    for w in (live, passed, live, passed):
        run(conn, w, provider)
    assert len(versions(conn, live)) == 2
    assert len(versions(conn, passed)) == 1
    assert decisions(conn, passed) == []


def test_only_one_evaluation_runs_per_journey_at_a_time(conn, live, provider):
    incident(conn, live)
    url = dotenv_values(ENV_FILE)["DATABASE_URL"]
    with psycopg.connect(url, connect_timeout=15) as other:
        other.execute(
            "select pg_advisory_xact_lock(hashtextextended(%s, 0))",
            (f"reroute:{live['journey']}",),
        )
        assert run(conn, live, provider) is None  # the other evaluation holds the lock
        other.rollback()
    assert run(conn, live, provider) is not None


def test_journey_that_is_not_running_is_not_evaluated(conn, live, provider):
    incident(conn, live)
    conn.execute(
        "update public.journeys set status = 'completed' where id = %s", (live["journey"],)
    )
    assert run(conn, live, provider) is None
    assert decisions(conn, live) == []


# ------------------------------------------------------------------ API


def test_position_update_triggers_an_evaluation(api, conn, live, provider):
    incident(conn, live)
    token = api.post(f"/journeys/{live['journey']}/ingest-token").json()["token"]
    from datetime import UTC, datetime

    r = api.client.post(
        "/api/v1/ingest/gps",
        json={
            "points": [{"device_ts": datetime.now(UTC).isoformat(), "lat": 19.0948, "lng": 74.7496}]
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 202
    assert decisions(conn, live) == [("keep", "awaiting_confirmation")]


def test_decision_log_and_controls_are_operator_scoped(api, conn, live, provider):
    incident(conn, live)
    run(conn, live, provider)
    j = live["journey"]
    log = api.get(f"/journeys/{j}/reroute/decisions")
    assert log.status_code == 200 and log.json()[0]["reason_code"] == "awaiting_confirmation"
    assert log.json()[0]["details"]["current"]["name"] == "Current route"
    assert api.get(f"/journeys/{j}/reroute/decisions", who="owner2").status_code == 404
    assert api.post(f"/journeys/{j}/reroute/evaluate", {}, who="owner2").status_code == 404
    assert api.put(f"/journeys/{j}/manual-mode", {"enabled": True}, who="owner2").status_code == 404
    assert api.call("GET", f"/journeys/{j}/reroute/decisions", who=None).status_code == 401
    assert api.put(f"/journeys/{j}/manual-mode", {"enabled": "maybe"}).status_code == 422


def test_decision_log_cannot_be_edited(conn, live, provider):
    incident(conn, live)
    run(conn, live, provider)
    with pytest.raises(psycopg.errors.RestrictViolation):
        with conn.transaction():
            conn.execute(
                "update public.route_decisions set outcome = 'reroute' where journey_id = %s",
                (live["journey"],),
            )


def test_variants_must_lie_inside_the_corridor(api, conn, live):
    t = live["template"]
    ok = api.put(f"/route-templates/{t}/variants", {"variants": BYPASS})
    assert ok.status_code == 200
    far = {"variants": [{"name": "Via Latur", "points": [{"lat": 18.4088, "lng": 76.5604}]}]}
    bad = api.put(f"/route-templates/{t}/variants", far)
    assert bad.status_code == 422 and "Via Latur" in bad.json()["detail"]
    stored = conn.execute(
        "select variants from public.route_templates where id = %s", (t,)
    ).fetchone()[0]
    assert [v["name"] for v in stored] == ["Northern bypass"]
    assert (
        api.put(f"/route-templates/{t}/variants", {"variants": BYPASS}, who="owner2").status_code
        == 404
    )


def test_stop_passed_without_a_recorded_event_never_triggers_a_reroute(
    conn, live, provider, tenants
):
    ahead = build_live_journey(
        conn, tenants, position=PARBHANI, template=live["template"], service=live["service"]
    )
    incident(conn, ahead, kind="closure", multiplier=1.0)
    result = run(conn, ahead, provider)
    assert result == {"action": "keep", "reason_code": "stops_unrecorded", "logged": False}
    assert len(versions(conn, ahead)) == 1 and provider.calls == []
    alert = open_alerts(conn, ahead)["stop_events_missing"]
    assert alert[1] == "warning" and alert[2] is False
    status = conn.execute(
        "select status from public.journeys where id = %s", (ahead["journey"],)
    ).fetchone()[0]
    assert status == "in_progress"
    # Once the stops are recorded, the alert clears.
    conn.execute(
        "update public.journey_stops set status = 'departed' where journey_id = %s",
        (ahead["journey"],),
    )
    run(conn, ahead, provider)
    assert "stop_events_missing" not in open_alerts(conn, ahead)
