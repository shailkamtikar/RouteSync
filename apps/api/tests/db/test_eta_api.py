from datetime import UTC, datetime, timedelta

import pytest

from app.auth.deps import OperatorContext
from app.eta import service

from . import factories as f

pytestmark = pytest.mark.db


@pytest.fixture
def world(api, conn, tenants):
    """One journey with an assigned route version, one active stop and a recent position."""
    w = f.make_world(conn, tenants["op1"])
    conn.execute("delete from public.journey_eta_snapshots where journey_id = %s", (w["journey"],))
    w["route_version"] = f.make_route_version(
        conn, tenants["op1"], w["journey"], version=2, distance_m=450000, duration_s=21600
    )
    conn.execute(
        "update public.journeys set current_route_version_id = %s, "
        "last_position = 'POINT(74.2 18.8)'::extensions.geography, "
        "last_position_at = now() - interval '10 seconds' where id = %s",
        (w["route_version"], w["journey"]),
    )
    w["ctx"] = OperatorContext(
        user_id=tenants["owner1"],
        email=None,
        operator_id=tenants["op1"],
        operator_name="Test Operator One",
        role="owner",
    )
    return w


def eta(api, world, who="owner1"):
    return api.get(f"/journeys/{world['journey']}/eta", who=who)


def snapshot_count(conn, journey):
    return conn.execute(
        "select count(*) from public.journey_eta_snapshots where journey_id = %s", (journey,)
    ).fetchone()[0]


def test_eta_has_next_stop_destination_and_progress(api, world):
    r = eta(api, world)
    assert r.status_code == 200
    body = r.json()
    assert body["schema_version"] == 1
    assert body["next_stop"]["name"] == "Ahmednagar"
    assert body["destination"]["name"] == "Nanded"
    assert body["next_stop"]["eta"] < body["destination"]["eta"]
    assert body["flags"]["stale"] is False and body["flags"]["plan_based"] is False
    assert 0 < body["progress_pct"] < 100
    assert body["travelled_distance_m"] + body["remaining_distance_m"] == pytest.approx(
        450_000, abs=2
    )
    assert body["route_version_id"] == str(world["route_version"])


def test_every_read_comes_from_one_stored_snapshot(api, world, conn):
    first = eta(api, world).json()
    second = eta(api, world).json()
    assert first == second
    assert snapshot_count(conn, world["journey"]) == 1
    stored = conn.execute(
        "select payload from public.journey_eta_snapshots where journey_id = %s",
        (world["journey"],),
    ).fetchone()[0]
    assert stored == first


def test_old_snapshot_is_replaced_by_a_new_one(world, conn):
    start = datetime.now(UTC)
    one = service.current_snapshot(conn, world["ctx"], world["journey"], now=start)
    again = service.current_snapshot(
        conn, world["ctx"], world["journey"], now=start + timedelta(seconds=2)
    )
    later = service.current_snapshot(
        conn, world["ctx"], world["journey"], now=start + timedelta(seconds=30)
    )
    assert one == again and later["computed_at"] != one["computed_at"]
    assert snapshot_count(conn, world["journey"]) == 2


def test_snapshot_is_recomputed_when_the_route_version_changes(world, conn, tenants):
    start = datetime.now(UTC)
    service.current_snapshot(conn, world["ctx"], world["journey"], now=start)
    v2 = f.make_route_version(
        conn, tenants["op1"], world["journey"], version=3, distance_m=400000, duration_s=19000
    )
    conn.execute(
        "update public.journeys set current_route_version_id = %s where id = %s",
        (v2, world["journey"]),
    )
    changed = service.current_snapshot(
        conn, world["ctx"], world["journey"], now=start + timedelta(seconds=1)
    )
    assert changed["route_version_id"] == str(v2)
    assert snapshot_count(conn, world["journey"]) == 2


def test_stale_gps_is_flagged(api, world, conn):
    conn.execute(
        "update public.journeys set last_position_at = now() - interval '10 minutes' where id = %s",
        (world["journey"],),
    )
    body = eta(api, world).json()
    assert body["flags"]["stale"] is True and body["gps_age_s"] >= 600
    assert any(w["code"] == "GPS_STALE" for w in body["warnings"])


def test_no_gps_gives_a_plan_based_eta(api, world, conn):
    conn.execute(
        "update public.journeys set last_position = null, last_position_at = null where id = %s",
        (world["journey"],),
    )
    body = eta(api, world).json()
    assert body["flags"]["plan_based"] is True and body["gps_age_s"] is None
    assert body["progress_pct"] == 0


def test_completed_stop_is_skipped(api, world, conn):
    conn.execute(
        "update public.journey_stops set status = 'departed' where journey_id = %s",
        (world["journey"],),
    )
    body = eta(api, world).json()
    assert body["stops"][0]["status"] == "completed" and body["stops"][0]["eta"] is None
    assert body["flags"]["next_is_destination"] is True
    assert body["next_stop"]["name"] == "Nanded"


def test_journey_without_a_route_is_a_conflict(api, world, conn):
    conn.execute(
        "update public.journeys set current_route_version_id = null where id = %s",
        (world["journey"],),
    )
    r = eta(api, world)
    assert r.status_code == 409 and "route" in r.json()["detail"]


def test_eta_is_operator_scoped_and_authenticated(api, world):
    assert eta(api, world, who="owner2").status_code == 404
    assert api.call("GET", f"/journeys/{world['journey']}/eta", who=None).status_code == 401
    assert eta(api, world, who="outsider").status_code == 403
    assert eta(api, world, who="dispatcher1").status_code == 200


def test_two_journeys_have_independent_snapshots(api, world, conn, tenants):
    other = f.make_world(conn, tenants["op1"])
    conn.execute(
        "delete from public.journey_eta_snapshots where journey_id = %s", (other["journey"],)
    )
    other["route_version"] = f.make_route_version(
        conn, tenants["op1"], other["journey"], version=2, distance_m=300000, duration_s=10000
    )
    conn.execute(
        "update public.journeys set current_route_version_id = %s where id = %s",
        (other["route_version"], other["journey"]),
    )
    first = eta(api, world).json()
    second = api.get(f"/journeys/{other['journey']}/eta").json()
    assert first["route_version_id"] != second["route_version_id"]
    assert (
        first["progress_pct"] != second["progress_pct"]
        or first["destination"]["eta"] != second["destination"]["eta"]
    )
    assert (
        snapshot_count(conn, world["journey"]) == 1 and snapshot_count(conn, other["journey"]) == 1
    )
