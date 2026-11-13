from datetime import UTC, datetime, timedelta

import pytest

from app.api.v1 import ingest as ingest_api
from app.auth.rate_limit import RateLimiter

from . import factories as f

pytestmark = pytest.mark.db

NOW = datetime.now(UTC).replace(microsecond=0)


def ts(seconds: float) -> str:
    return (NOW + timedelta(seconds=seconds)).isoformat()


def point(seconds=-60, lat=18.60, lng=73.90, **extra):
    return {"device_ts": ts(seconds), "lat": lat, "lng": lng, **extra}


@pytest.fixture
def world(api, conn, tenants):
    """A journey in progress with an assigned route, and its device token."""
    w = f.make_world(conn, tenants["op1"])
    version = f.make_route_version(conn, tenants["op1"], w["journey"], 2, 450_000, 21_600)
    conn.execute(
        "update public.journeys set status = 'in_progress', current_route_version_id = %s "
        "where id = %s",
        (version, w["journey"]),
    )
    conn.execute("delete from public.gps_positions where journey_id = %s", (w["journey"],))
    r = api.post(f"/journeys/{w['journey']}/ingest-token")
    assert r.status_code == 200, r.text
    w["token"] = r.json()["token"]
    return w


def send(api, token, points, **kwargs):
    headers = {"Authorization": f"Bearer {token}"} if token is not None else {}
    return api.client.post("/api/v1/ingest/gps", json={"points": points}, headers=headers, **kwargs)


def latest(conn, journey):
    return conn.execute(
        "select extensions.st_y(last_position::extensions.geometry), last_device_ts "
        "from public.journeys where id = %s",
        (journey,),
    ).fetchone()


def stored(conn, journey):
    return conn.execute(
        "select count(*) from public.gps_positions where journey_id = %s", (journey,)
    ).fetchone()[0]


# ------------------------------------------------------------------ tokens


def test_token_is_shown_once_and_only_its_hash_is_stored(api, world, conn):
    assert len(world["token"]) >= 43
    hashes = conn.execute(
        "select token_hash from public.journey_ingest_tokens where journey_id = %s "
        "and revoked_at is null",
        (world["journey"],),
    ).fetchall()
    assert len(hashes) == 1 and hashes[0][0] != world["token"] and len(hashes[0][0]) == 64
    # The stored hash is useless as a token.
    assert send(api, hashes[0][0], [point()]).status_code == 401


def test_reissuing_revokes_the_previous_token(api, world):
    new = api.post(f"/journeys/{world['journey']}/ingest-token").json()["token"]
    assert new != world["token"]
    assert send(api, world["token"], [point()]).status_code == 401
    assert send(api, new, [point()]).status_code == 202


def test_revoked_token_stops_working(api, world):
    assert api.delete(f"/journeys/{world['journey']}/ingest-token").status_code == 204
    assert send(api, world["token"], [point()]).status_code == 401


def test_token_management_is_operator_scoped(api, world, conn):
    j = world["journey"]
    assert api.post(f"/journeys/{j}/ingest-token", who="owner2").status_code == 404
    assert api.delete(f"/journeys/{j}/ingest-token", who="owner2").status_code == 404
    assert api.call("POST", f"/journeys/{j}/ingest-token", who=None).status_code == 401
    assert send(api, world["token"], [point()]).status_code == 202  # still valid
    conn.execute("update public.journeys set status = 'draft' where id = %s", (j,))
    assert api.post(f"/journeys/{j}/ingest-token").status_code == 409


@pytest.mark.parametrize("token", [None, "", "wrong-token", "x" * 500])
def test_missing_or_wrong_token_is_401(api, world, conn, token):
    assert send(api, token, [point()]).status_code == 401
    assert stored(conn, world["journey"]) == 0


# ------------------------------------------------------------------ ingestion


def test_valid_point_is_stored_and_becomes_the_latest_position(api, world, conn):
    r = send(api, world["token"], [point(-30, accuracy_m=8, speed_mps=16.5, source="sim-1")])
    assert r.status_code == 202
    assert r.json() == {"accepted": 1, "duplicates": 0, "rejected": []}
    lat, device_ts = latest(conn, world["journey"])
    assert lat == pytest.approx(18.60) and device_ts == NOW - timedelta(seconds=30)


def test_token_decides_the_journey_and_body_cannot_name_one(api, world, conn, tenants):
    other = f.make_world(conn, tenants["op1"])
    r = send(api, world["token"], [{**point(), "journey_id": str(other["journey"])}])
    assert r.status_code == 422
    r = api.client.post(
        "/api/v1/ingest/gps",
        json={"points": [point()], "journey_id": str(other["journey"])},
        headers={"Authorization": f"Bearer {world['token']}"},
    )
    assert r.status_code == 422
    before = stored(conn, other["journey"])
    send(api, world["token"], [point()])
    assert stored(conn, world["journey"]) == 1
    assert stored(conn, other["journey"]) == before


def test_duplicate_point_is_stored_once(api, world, conn):
    first = send(api, world["token"], [point(-30)])
    again = send(api, world["token"], [point(-30)])
    assert first.status_code == again.status_code == 202
    assert again.json() == {"accepted": 0, "duplicates": 1, "rejected": []}
    assert stored(conn, world["journey"]) == 1


def test_out_of_order_point_is_kept_but_does_not_move_latest_back(api, world, conn):
    send(api, world["token"], [point(-30, lat=18.62)])
    r = send(api, world["token"], [point(-90, lat=18.58)])
    assert r.json()["accepted"] == 1
    assert stored(conn, world["journey"]) == 2
    lat, device_ts = latest(conn, world["journey"])
    assert lat == pytest.approx(18.62) and device_ts == NOW - timedelta(seconds=30)


def test_impossible_jump_is_rejected(api, world, conn):
    send(api, world["token"], [point(-30, lat=18.60, lng=73.90)])
    r = send(api, world["token"], [point(-20, lat=19.14, lng=77.32)])  # ~370 km in 10 s
    assert r.status_code == 202
    assert r.json() == {
        "accepted": 0,
        "duplicates": 0,
        "rejected": [{"index": 0, "reason": "impossible_jump"}],
    }
    assert latest(conn, world["journey"])[0] == pytest.approx(18.60)
    assert stored(conn, world["journey"]) == 1


def test_plausible_movement_is_accepted(api, world):
    send(api, world["token"], [point(-60, lat=18.600)])
    r = send(api, world["token"], [point(0, lat=18.609)])  # ~1 km in 60 s
    assert r.json()["accepted"] == 1


def test_future_timestamp_is_rejected(api, world, conn):
    r = send(api, world["token"], [point(600)])
    assert r.json()["rejected"] == [{"index": 0, "reason": "timestamp_in_future"}]
    assert stored(conn, world["journey"]) == 0
    assert send(api, world["token"], [point(20)]).json()["accepted"] == 1  # small clock skew


@pytest.mark.parametrize(
    "bad",
    [
        {"lat": 200, "lng": 73.9},
        {"lat": 18.6, "lng": -500},
        {"lat": "north", "lng": 73.9},
        {"lat": 18.6, "lng": 73.9, "speed_mps": -1},
        {"lat": 18.6, "lng": 73.9, "source": "bad source!"},
        {"lat": 18.6},
    ],
)
def test_invalid_point_is_422(api, world, conn, bad):
    assert send(api, world["token"], [{"device_ts": ts(-10), **bad}]).status_code == 422
    assert stored(conn, world["journey"]) == 0


def test_naive_timestamp_and_empty_or_oversized_batches_are_422(api, world):
    naive = {"device_ts": "2031-03-01T10:00:00", "lat": 18.6, "lng": 73.9}
    assert send(api, world["token"], [naive]).status_code == 422
    assert send(api, world["token"], []).status_code == 422
    assert send(api, world["token"], [point(-i) for i in range(51)]).status_code == 422


def test_reconnect_batch_is_stored_in_time_order(api, world, conn):
    batch = [point(-300 + i * 10, lat=18.60 + i * 0.001) for i in range(30)]
    batch.reverse()  # arrival order must not matter
    r = send(api, world["token"], batch)
    assert r.json() == {"accepted": 30, "duplicates": 0, "rejected": []}
    lat, device_ts = latest(conn, world["journey"])
    assert lat == pytest.approx(18.629) and device_ts == NOW - timedelta(seconds=10)


def test_batch_with_one_bad_point_keeps_the_good_ones(api, world, conn):
    batch = [point(-60, lat=18.600), point(-50, lat=19.9), point(-40, lat=18.602)]
    r = send(api, world["token"], batch)
    assert r.json()["accepted"] == 2
    assert r.json()["rejected"] == [{"index": 1, "reason": "impossible_jump"}]


@pytest.mark.parametrize("status", ["completed", "cancelled", "draft", "ready"])
def test_journey_not_running_refuses_positions(api, world, conn, status):
    conn.execute("update public.journeys set status = %s where id = %s", (status, world["journey"]))
    assert send(api, world["token"], [point()]).status_code == 409
    assert stored(conn, world["journey"]) == 0


def test_rate_limit_returns_429(api, world, monkeypatch):
    monkeypatch.setattr(ingest_api, "limiter", RateLimiter(limit=3, window_s=60))
    codes = [send(api, world["token"], [point(-100 + i)]).status_code for i in range(5)]
    assert codes == [202, 202, 202, 429, 429]


def test_device_can_read_only_its_own_route(api, world):
    r = api.client.get(
        "/api/v1/ingest/route", headers={"Authorization": f"Bearer {world['token']}"}
    )
    assert r.status_code == 200
    assert r.json()["distance_m"] == 450_000 and len(r.json()["coordinates"]) >= 2
    assert api.client.get("/api/v1/ingest/route").status_code == 401


def test_positions_of_two_journeys_stay_separate(api, world, conn, tenants):
    other = f.make_world(conn, tenants["op1"])
    conn.execute(
        "update public.journeys set status = 'in_progress' where id = %s", (other["journey"],)
    )
    other_token = api.post(f"/journeys/{other['journey']}/ingest-token").json()["token"]
    send(api, world["token"], [point(-30, lat=18.61)])
    send(api, other_token, [point(-20, lat=18.99)])
    assert latest(conn, world["journey"])[0] == pytest.approx(18.61)
    assert latest(conn, other["journey"])[0] == pytest.approx(18.99)


def test_token_table_is_not_readable_through_the_data_api(conn, actor, tenants, world):
    import psycopg

    actor.user(tenants["owner1"])
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        with conn.transaction():
            conn.execute("select count(*) from public.journey_ingest_tokens")
    actor.admin()
