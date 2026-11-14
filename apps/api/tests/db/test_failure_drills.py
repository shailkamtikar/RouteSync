"""Failure drills: every edge case from the knowledge document, with the expected behaviour."""

import pytest

from app.domain import reroute
from app.domain.routing import get_routing_provider
from app.domain.stops import get_places_provider
from app.eta import service
from app.main import app
from app.providers.places.fake import FakePlacesProvider
from app.providers.routing.base import RoutingQuotaExceeded, RoutingUnavailable
from app.providers.routing.fake import FakeRoutingProvider

from .live_fixtures import PARBHANI, build_live_journey

pytestmark = pytest.mark.db


@pytest.fixture
def providers():
    routing, places = FakeRoutingProvider(), FakePlacesProvider()
    app.dependency_overrides[get_routing_provider] = lambda: routing
    app.dependency_overrides[get_places_provider] = lambda: places
    yield routing, places
    app.dependency_overrides.pop(get_routing_provider, None)
    app.dependency_overrides.pop(get_places_provider, None)


@pytest.fixture
def live(api, conn, tenants, providers):
    w = build_live_journey(conn, tenants)
    w["token"] = api.post(f"/journeys/{w['journey']}/tracking-link").json()["token"]
    return w


def public(api, w):
    return api.client.get(f"/api/v1/public/track/{w['token']}").json()


def test_gps_loss_is_shown_as_not_live_everywhere(api, conn, live):
    conn.execute(
        "update public.journeys set last_position_at = now() - interval '15 minutes' where id = %s",
        (live["journey"],),
    )
    conn.execute(
        "delete from public.journey_eta_snapshots where journey_id = %s", (live["journey"],)
    )
    assert public(api, live)["bus"]["stale"] is True
    assert api.get(f"/journeys/{live['journey']}/monitor").json()["eta"]["flags"]["stale"] is True


def test_routing_quota_exhausted_keeps_journeys_running(api, conn, live, providers):
    routing, _ = providers
    routing.fail_with = RoutingQuotaExceeded("quota")
    conn.execute(
        "insert into public.traffic_incidents (operator_id, route_template_id, kind, multiplier, "
        "from_point, to_point, from_km, to_km, starts_at) values (%s, %s, 'closure', 1, "
        "'POINT(76.2 19.12)'::extensions.geography, 'POINT(76.5 19.2)'::extensions.geography, 250, 290, clock_timestamp())",
        (live["op"], live["template"]),
    )
    result = reroute.evaluate(conn, live["op"], live["journey"], routing, force=True)
    assert result["action"] in ("keep", "no_feasible_route")
    assert public(api, live)["eta"]["flags"]["closure_ahead"] is True
    assert api.get(f"/journeys/{live['journey']}/eta").status_code == 200


def test_routing_outage_during_assignment_falls_back_to_the_template(api, conn, live, providers):
    routing, _ = providers
    routing.fail_with = RoutingUnavailable("down")
    r = api.post(f"/journeys/{live['journey']}/reroute/evaluate", {})
    assert r.status_code == 200 and r.json()["action"] == "keep"


def test_places_outage_degrades_to_manual_stops(api, live, providers):
    _, places = providers
    places.fail = True
    r = api.get(f"/route-templates/{live['template']}/stop-candidates")
    assert r.status_code == 200 and r.json()["available"] is False


def test_revoked_link_mid_journey(api, live):
    assert api.client.get(f"/api/v1/public/track/{live['token']}").status_code == 200
    api.delete(f"/journeys/{live['journey']}/tracking-link")
    r = api.client.get(f"/api/v1/public/track/{live['token']}")
    assert r.status_code == 410 and "Pune" not in r.text


def test_booking_change_after_confirmation_flags_review_without_rewriting_the_plan(api, conn, live):
    conn.execute("update public.journeys set status = 'draft' where id = %s", (live["journey"],))
    r = api.post(
        f"/journeys/{live['journey']}/bookings",
        {"passenger_count": 1, "pickup_stop_name": "Pune", "drop_stop_name": "Beed"},
    )
    assert r.status_code == 201
    journey = api.get(f"/journeys/{live['journey']}").json()
    assert journey["plan_needs_review"] is True
    stops = conn.execute(
        "select count(*) from public.journey_stops where journey_id = %s", (live["journey"],)
    ).fetchone()[0]
    assert stops == 2


def test_delay_beyond_the_promise_is_reported_and_the_promise_is_kept(api, conn, live, tenants):
    late = build_live_journey(conn, tenants, promise_in_hours=0.5)
    token = api.post(f"/journeys/{late['journey']}/tracking-link").json()["token"]
    view = api.client.get(f"/api/v1/public/track/{token}").json()
    c = view["eta"]["commitment"]
    assert c["status"] == "significant" and c["delay_minutes"] > 60
    assert c["original_eta"] == view["journey"]["booking_eta_at"]
    assert [a["type"] for a in view["alerts"]] == ["delay"]


def test_two_journeys_same_route_same_time_never_share_state(api, conn, live, tenants):
    other = build_live_journey(
        conn, tenants, position=PARBHANI, template=live["template"], service=live["service"]
    )
    conn.execute(
        "update public.journey_stops set status = 'departed' where journey_id = %s",
        (other["journey"],),
    )
    other_token = api.post(f"/journeys/{other['journey']}/tracking-link").json()["token"]
    a = public(api, live)
    b = api.client.get(f"/api/v1/public/track/{other_token}").json()
    assert a["eta"]["next_stop"]["name"] == "Beed" and b["eta"]["next_stop"]["name"] == "Nanded"
    assert (
        service.latest_snapshot(conn, live["ctx"], live["journey"])["payload"]
        != service.latest_snapshot(conn, other["ctx"], other["journey"])["payload"]
    )


def test_operator_cannot_touch_another_operators_journey(api, live):
    j = live["journey"]
    for method, path in [
        ("GET", f"/journeys/{j}"),
        ("GET", f"/journeys/{j}/monitor"),
        ("POST", f"/journeys/{j}/tracking-link"),
    ]:
        assert api.call(method, path, who="owner2").status_code == 404


def test_journey_without_intermediate_stops(api, conn, live):
    conn.execute("delete from public.journey_stops where journey_id = %s", (live["journey"],))
    conn.execute(
        "delete from public.journey_eta_snapshots where journey_id = %s", (live["journey"],)
    )
    view = public(api, live)
    assert view["stops"] == [] and view["eta"]["flags"]["next_is_destination"] is True
    assert view["eta"]["next_stop"]["name"] == "Nanded"


def test_cancelled_journey_is_shown_as_cancelled(api, conn, live):
    conn.execute(
        "update public.journeys set status = 'cancelled' where id = %s", (live["journey"],)
    )
    assert public(api, live)["journey"]["status"] == "cancelled"
