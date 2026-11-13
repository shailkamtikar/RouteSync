import json
import re
from datetime import timedelta

import pytest

from app.api.v1 import public_track as public_api
from app.auth.rate_limit import RateLimiter

from .live_fixtures import build_live_journey

pytestmark = pytest.mark.db

PRIVATE = ["Asha Kulkarni", "Ravi", "REF-SECRET", "12A", "9800000000", "asha@example.com"]


@pytest.fixture
def live(api, conn, tenants):
    w = build_live_journey(conn, tenants)
    booking = conn.execute(
        "insert into public.bookings (operator_id, journey_id, reference, contact_name, "
        "passenger_count, pickup_stop_name, drop_stop_name) values (%s, %s, 'REF-SECRET', "
        "'Asha Kulkarni', 2, 'Pune', 'Nanded') returning id",
        (w["op"], w["journey"]),
    ).fetchone()[0]
    conn.execute(
        "insert into public.booking_passengers (operator_id, journey_id, booking_id, name, "
        "seat_number, phone) values (%s, %s, %s, 'Ravi Kulkarni', '12A', '+919800000000')",
        (w["op"], w["journey"], booking),
    )
    conn.execute(
        "insert into public.journey_alerts (operator_id, journey_id, type, severity, message, is_public) "
        "values (%s, %s, 'reroute', 'info', 'Route changed because of asha@example.com', false), "
        "(%s, %s, 'traffic', 'info', 'Simulated slow traffic ahead on the route.', true)",
        (w["op"], w["journey"], w["op"], w["journey"]),
    )
    r = api.post(f"/journeys/{w['journey']}/tracking-link")
    assert r.status_code == 200, r.text
    w["token"] = r.json()["token"]
    return w


def track(api, token):
    return api.client.get(f"/api/v1/public/track/{token}")


# ------------------------------------------------------------------ links


def test_link_is_long_shown_once_and_stored_hashed(api, live, conn):
    assert len(live["token"]) >= 43
    row = conn.execute(
        "select token_hash, expires_at from public.public_tracking_links "
        "where journey_id = %s and revoked_at is null",
        (live["journey"],),
    ).fetchone()
    assert row[0] != live["token"] and len(row[0]) == 64
    assert row[1] is not None
    status = api.get(f"/journeys/{live['journey']}/tracking-link").json()
    assert status["active"] is True and "token" not in status
    assert track(api, row[0]).status_code == 404  # the hash is not a usable link


def test_links_are_unique_and_a_new_one_revokes_the_old(api, live):
    made = [
        api.post(f"/journeys/{live['journey']}/tracking-link").json()["token"] for _ in range(5)
    ]
    assert len(set(made)) == 5
    assert track(api, live["token"]).status_code == 410
    for old in made[:-1]:
        assert track(api, old).status_code == 410
    assert track(api, made[-1]).status_code == 200


def test_revoked_and_expired_links_are_gone(api, live, conn):
    api.delete(f"/journeys/{live['journey']}/tracking-link")
    r = track(api, live["token"])
    assert (
        r.status_code == 410 and r.json()["detail"] == "This tracking link is no longer available."
    )
    fresh = api.post(f"/journeys/{live['journey']}/tracking-link").json()["token"]
    conn.execute(
        "update public.public_tracking_links set expires_at = now() - interval '1 minute' "
        "where journey_id = %s and revoked_at is null",
        (live["journey"],),
    )
    assert track(api, fresh).status_code == 410


@pytest.mark.parametrize("token", ["", "nope", "' OR 1=1--", "../../etc/passwd", "x" * 400])
def test_unknown_tokens_are_404_without_detail(api, live, token):
    r = api.client.get(f"/api/v1/public/track/{token}")
    assert r.status_code in (404, 422)
    assert "Traceback" not in r.text and "journey" not in r.text.lower()


def test_link_management_is_operator_scoped(api, live, conn):
    j = live["journey"]
    assert api.post(f"/journeys/{j}/tracking-link", who="owner2").status_code == 404
    assert api.delete(f"/journeys/{j}/tracking-link", who="owner2").status_code == 404
    assert api.call("POST", f"/journeys/{j}/tracking-link", who=None).status_code == 401
    conn.execute("update public.journeys set status = 'draft' where id = %s", (j,))
    assert api.post(f"/journeys/{j}/tracking-link").status_code == 409


# ------------------------------------------------------------------ the public view


def test_public_view_has_what_the_page_needs(api, live):
    r = track(api, live["token"])
    assert r.status_code == 200
    assert r.headers["cache-control"] == "no-store"
    body = r.json()
    assert body["journey"]["status"] == "in_progress"
    assert (
        body["journey"]["origin_name"] == "Pune" and body["journey"]["destination_name"] == "Nanded"
    )
    assert body["eta"]["next_stop"]["name"] == "Beed"
    assert body["eta"]["destination"]["name"] == "Nanded"
    assert body["eta"]["commitment"]["original_eta"] == body["journey"]["booking_eta_at"]
    assert [s["name"] for s in body["stops"]] == ["Beed", "Parbhani"]
    assert body["bus"]["stale"] is False and body["route"]["version"] == 1
    assert [a["type"] for a in body["alerts"]] == ["traffic"]
    assert body["counts_enabled"] is False and "onboard" not in body


def test_public_view_never_contains_private_data(api, live):
    text = json.dumps(track(api, live["token"]).json())
    for secret in PRIVATE:
        assert secret not in text
    assert "booking" not in text.lower().replace("booking_eta_at", "")
    assert not re.search(r"\+?\d{10}", text)
    assert "operator_id" not in text and "journey_id" not in text and 'id"' not in text


def test_operator_only_alerts_are_never_public(api, live):
    body = track(api, live["token"]).json()
    assert all(a["type"] in ("delay", "traffic", "road_closure") for a in body["alerts"])
    assert "Route changed" not in json.dumps(body)


def test_counts_appear_only_when_the_operator_enables_them(api, live):
    body = track(api, live["token"]).json()
    assert "boarding_count" not in body["stops"][0]
    r = api.put(f"/journeys/{live['journey']}/public-counts", {"enabled": True})
    assert r.status_code == 200 and r.json()["public_counts_enabled"] is True
    body = track(api, live["token"]).json()
    assert body["stops"][0]["boarding_count"] == 2 and body["stops"][0]["alighting_count"] == 1
    assert body["onboard"] == {"method": "planned_only", "onboard": None}
    assert "Asha" not in json.dumps(body)


def test_two_journeys_on_the_same_route_option_have_separate_views(api, live, conn, tenants):
    other = build_live_journey(
        conn,
        tenants,
        position=(76.7748, 19.2608),
        template=live["template"],
        service=live["service"],
    )
    conn.execute(
        "update public.journey_stops set status = 'departed' where journey_id = %s",
        (other["journey"],),
    )
    other_token = api.post(f"/journeys/{other['journey']}/tracking-link").json()["token"]
    first, second = track(api, live["token"]).json(), track(api, other_token).json()
    assert first["eta"]["next_stop"]["name"] == "Beed"
    assert second["eta"]["next_stop"]["name"] == "Nanded"
    assert first["bus"]["lat"] != second["bus"]["lat"]


def test_stale_and_not_started_states(api, live, conn):
    conn.execute(
        "update public.journeys set last_position_at = now() - interval '10 minutes' where id = %s",
        (live["journey"],),
    )
    conn.execute(
        "delete from public.journey_eta_snapshots where journey_id = %s", (live["journey"],)
    )
    body = track(api, live["token"]).json()
    assert body["bus"]["stale"] is True and body["eta"]["flags"]["stale"] is True
    conn.execute(
        "update public.journeys set status = 'published', last_position = null, "
        "last_position_at = null where id = %s",
        (live["journey"],),
    )
    conn.execute(
        "delete from public.journey_eta_snapshots where journey_id = %s", (live["journey"],)
    )
    body = track(api, live["token"]).json()
    assert body["journey"]["status"] == "not_started" and body["bus"] is None
    assert body["eta"]["flags"]["plan_based"] is True


def test_pass_through_places_are_listed_without_an_eta(api, live, conn):
    conn.execute(
        "insert into public.route_template_stops (operator_id, route_template_id, name, location, "
        "kind, chainage_m) values (%s, %s, 'Majalgaon', 'POINT(76.208 19.151)'::extensions.geography, "
        "'pass_through', 250000)",
        (live["op"], live["template"]),
    )
    body = track(api, live["token"]).json()
    assert [p["name"] for p in body["pass_through"]] == ["Majalgaon"]
    assert "eta" not in body["pass_through"][0]
    assert "Majalgaon" not in [s["name"] for s in body["stops"]]


def test_public_view_matches_the_operator_snapshot(api, live):
    public = track(api, live["token"]).json()["eta"]
    operator = api.get(f"/journeys/{live['journey']}/eta").json()
    assert public["destination"]["eta"] == operator["destination"]["eta"]
    assert public["next_stop"]["eta"] == operator["next_stop"]["eta"]


def test_completed_and_no_intermediate_stops(api, live, conn):
    conn.execute(
        "update public.journey_stops set status = 'departed' where journey_id = %s",
        (live["journey"],),
    )
    conn.execute(
        "update public.journeys set status = 'completed' where id = %s", (live["journey"],)
    )
    body = track(api, live["token"]).json()
    assert body["journey"]["status"] == "completed"
    assert body["eta"]["flags"]["next_is_destination"] is True


def test_rate_limit(api, live, monkeypatch):
    monkeypatch.setattr(public_api, "by_token", RateLimiter(limit=3, window_s=60))
    codes = [track(api, live["token"]).status_code for _ in range(5)]
    assert codes == [200, 200, 200, 429, 429]


def test_timestamps_are_utc_iso(api, live):
    body = track(api, live["token"]).json()
    assert body["journey"]["departure_at"].endswith("+00:00")
    assert body["eta"]["next_stop"]["eta"].endswith("+00:00")


def test_link_expiry_follows_the_scheduled_arrival(api, conn, tenants):
    w = build_live_journey(conn, tenants, promise_in_hours=2)
    link = api.post(f"/journeys/{w['journey']}/tracking-link").json()
    arrival = conn.execute(
        "select scheduled_arrival_at from public.journeys where id = %s", (w["journey"],)
    ).fetchone()[0]
    from datetime import datetime

    assert datetime.fromisoformat(link["expires_at"]) == arrival + timedelta(hours=24)
