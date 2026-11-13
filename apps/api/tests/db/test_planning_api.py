import uuid

import pytest

from app.domain.routing import get_routing_provider
from app.domain.stops import get_places_provider
from app.main import app
from app.providers.places.fake import FakePlacesProvider
from app.providers.routing.base import RoutingUnavailable
from app.providers.routing.fake import FakeRoutingProvider

from . import factories as f

pytestmark = pytest.mark.db

PUNE = {"lat": 18.5204, "lng": 73.8567}
NANDED = {"lat": 19.1383, "lng": 77.321}
AHMEDNAGAR = {"lat": 19.0948, "lng": 74.7496}
BEED = {"lat": 18.9891, "lng": 75.7601}
LATUR = {"lat": 18.4088, "lng": 76.5604}


@pytest.fixture
def world(api, conn, tenants):
    """A draft journey on the northern route option with stops and three bookings."""
    routing_provider = FakeRoutingProvider()
    app.dependency_overrides[get_routing_provider] = lambda: routing_provider
    app.dependency_overrides[get_places_provider] = lambda: FakePlacesProvider()
    service = api.post(
        "/services",
        {
            "origin_name": "Pune",
            "destination_name": "Nanded",
            "origin_location": PUNE,
            "destination_location": NANDED,
        },
    ).json()["id"]
    north = api.post(
        f"/services/{service}/route-templates",
        {
            "name": "North",
            "via_points": [{"name": "Ahmednagar", **AHMEDNAGAR}, {"name": "Beed", **BEED}],
        },
    ).json()["template"]["id"]
    south = api.post(
        f"/services/{service}/route-templates",
        {"name": "South", "via_points": [{"name": "Latur", **LATUR}]},
    ).json()["template"]["id"]
    for name, location in (("Ahmednagar", AHMEDNAGAR), ("Beed", BEED)):
        api.post(f"/route-templates/{north}/stops", {"name": name, "location": location})
    api.post(
        f"/route-templates/{north}/stops",
        {"name": "Majalgaon", "location": {"lat": 19.03, "lng": 76.2}, "kind": "pass_through"},
    )
    latur = api.post(
        f"/route-templates/{south}/stops", {"name": "Latur", "location": LATUR}
    ).json()["id"]
    bus = str(f.make_bus(conn, tenants["op1"], capacity=40))
    journey = api.post(
        "/journeys",
        {
            "bus_id": bus,
            "service_id": service,
            "departure_at": "2031-03-01T16:30:00Z",
            "scheduled_arrival_at": "2031-03-02T02:00:00Z",
        },
    ).json()["id"]
    for reference, count, pickup, drop in (
        ("B1", 3, "Pune", "Beed"),
        ("B2", 2, "Pune", "Nanded"),
        ("B3", 2, "Beed", "Nanded"),
    ):
        api.post(
            f"/journeys/{journey}/bookings",
            {
                "reference": reference,
                "passenger_count": count,
                "pickup_stop_name": pickup,
                "drop_stop_name": drop,
            },
        )
    api.put(f"/journeys/{journey}/route-template", {"route_template_id": north})
    stops = {s["name"]: s for s in api.get(f"/journeys/{journey}/stop-plan").json()["stops"]}
    yield {
        "service": service,
        "north": north,
        "south": south,
        "latur": latur,
        "journey": journey,
        "bus": bus,
        "stops": {name: s["route_template_stop_id"] for name, s in stops.items()},
        "routing": routing_provider,
    }
    app.dependency_overrides.pop(get_routing_provider, None)
    app.dependency_overrides.pop(get_places_provider, None)


def selection(world, **overrides):
    """The correct active stops for the three bookings, optionally altered."""
    plan = {
        "Pune": {"pickup_count": 5, "drop_count": 0},
        "Beed": {"pickup_count": 2, "drop_count": 3},
        "Nanded": {"pickup_count": 0, "drop_count": 4},
    }
    plan.update(overrides)
    return {
        "stops": [
            {"route_template_stop_id": world["stops"][name], **counts}
            for name, counts in plan.items()
            if counts is not None
        ]
    }


def confirm(api, world, who="owner1", **overrides):
    return api.put(
        f"/journeys/{world['journey']}/active-stops", selection(world, **overrides), who=who
    )


def issue_codes(api, world):
    return [i["code"] for i in api.post(f"/journeys/{world['journey']}/validate").json()["issues"]]


def to_ready(api, world):
    assert confirm(api, world).status_code == 200
    r = api.post(f"/journeys/{world['journey']}/transition", {"to": "awaiting_confirmation"})
    assert r.status_code == 200, r.text
    r = api.post(f"/journeys/{world['journey']}/assign")
    assert r.status_code == 200, r.text
    return r.json()


# ------------------------------------------------------------------ stop plan


def test_bookings_give_hints_but_never_activate_stops(api, world):
    plan = api.get(f"/journeys/{world['journey']}/stop-plan").json()
    by_name = {s["name"]: s for s in plan["stops"]}
    assert [s["name"] for s in plan["stops"]] == [
        "Pune",
        "Ahmednagar",
        "Beed",
        "Majalgaon",
        "Nanded",
    ]
    assert by_name["Beed"]["booked_pickups"] == 2 and by_name["Beed"]["booked_drops"] == 3
    assert by_name["Pune"]["booked_pickups"] == 5
    assert all(s["active"] is False for s in plan["stops"])
    assert plan["editable"] is True and plan["unresolved_bookings"] == []


def test_confirm_active_stops_orders_them_along_the_road(api, world, conn):
    body = selection(world)
    body["stops"].reverse()  # client order must not matter
    r = api.put(f"/journeys/{world['journey']}/active-stops", body)
    assert r.status_code == 200
    active = [(s["name"], s["sequence"]) for s in r.json()["stops"] if s["active"]]
    assert active == [("Pune", 1), ("Beed", 2), ("Nanded", 3)]
    event = conn.execute(
        "select payload from public.journey_events where journey_id = %s "
        "and event_type = 'active_stops_confirmed'",
        (world["journey"],),
    ).fetchone()[0]
    assert [s["name"] for s in event["stops"]] == ["Pune", "Beed", "Nanded"]


def test_stop_from_another_route_option_is_rejected(api, world):
    body = selection(world)
    body["stops"].append(
        {"route_template_stop_id": world["latur"], "pickup_count": 1, "drop_count": 0}
    )
    r = api.put(f"/journeys/{world['journey']}/active-stops", body)
    assert r.status_code == 422
    assert "route option" in r.json()["detail"]
    plan = api.get(f"/journeys/{world['journey']}/stop-plan").json()
    assert not any(s["active"] for s in plan["stops"])
    assert "Latur" not in [s["name"] for s in plan["stops"]]


@pytest.mark.parametrize(
    "bad",
    [
        {"pickup_count": 0, "drop_count": 0},
        {"pickup_count": -1, "drop_count": 1},
        {"pickup_count": 1, "drop_count": 1, "dwell_minutes": 500},
        {"pickup_count": 1, "drop_count": 1, "sequence": 1},
    ],
)
def test_invalid_active_stop_is_rejected(api, world, bad):
    assert confirm(api, world, Ahmednagar=bad).status_code == 422


def test_pass_through_place_cannot_be_active(api, world):
    r = confirm(api, world, Majalgaon={"pickup_count": 1, "drop_count": 0})
    assert r.status_code == 422
    assert "no passenger stop" in r.json()["detail"]


def test_duplicate_and_unknown_stops_are_rejected(api, world):
    body = selection(world)
    body["stops"].append(body["stops"][0])
    assert api.put(f"/journeys/{world['journey']}/active-stops", body).status_code == 422
    body = selection(world)
    body["stops"][0]["route_template_stop_id"] = str(uuid.uuid4())
    assert api.put(f"/journeys/{world['journey']}/active-stops", body).status_code == 422


def test_stop_with_both_pickup_and_drop_is_accepted(api, world):
    r = confirm(api, world)
    beed = next(s for s in r.json()["stops"] if s["name"] == "Beed")
    assert beed["pickup_count"] == 2 and beed["drop_count"] == 3


def test_stop_plan_cross_operator_and_auth(api, world):
    j = world["journey"]
    assert api.get(f"/journeys/{j}/stop-plan", who="owner2").status_code == 404
    assert api.put(f"/journeys/{j}/active-stops", selection(world), who="owner2").status_code == 404
    assert api.post(f"/journeys/{j}/validate", who="owner2").status_code == 404
    assert api.post(f"/journeys/{j}/assign", who="owner2").status_code == 404
    assert (
        api.post(f"/journeys/{j}/transition", {"to": "cancelled"}, who="owner2").status_code == 404
    )
    assert api.get(f"/journeys/{j}/route-versions", who="owner2").status_code == 404
    assert api.call("GET", f"/journeys/{j}/stop-plan", who=None).status_code == 401
    assert api.call("POST", f"/journeys/{j}/assign", who=None).status_code == 401


# ------------------------------------------------------------------ validation through the API


def test_valid_plan_validates_clean(api, world):
    confirm(api, world)
    result = api.post(f"/journeys/{world['journey']}/validate").json()
    assert result == {"valid": True, "issues": []}


def test_validation_reports_missing_active_stop(api, world):
    confirm(api, world, Beed=None, Pune={"pickup_count": 5, "drop_count": 0})
    found = issue_codes(api, world)
    assert "BOOKING_DROP_NOT_ACTIVE" in found and "BOOKING_PICKUP_NOT_ACTIVE" in found


def test_validation_reports_count_mismatch_and_capacity(api, world, conn):
    confirm(api, world, Pune={"pickup_count": 6, "drop_count": 0})
    assert "COUNT_MISMATCH" in issue_codes(api, world)
    confirm(api, world)
    conn.execute("update public.buses set capacity = 4 where id = %s", (world["bus"],))
    assert "CAPACITY_EXCEEDED" in issue_codes(api, world)


def test_booking_to_a_place_not_on_this_route_is_reported(api, world):
    api.post(
        f"/journeys/{world['journey']}/bookings",
        {
            "reference": "B9",
            "passenger_count": 1,
            "pickup_stop_name": "Pune",
            "drop_stop_name": "Latur",
        },
    )
    confirm(api, world, Pune={"pickup_count": 6, "drop_count": 0})
    result = api.post(f"/journeys/{world['journey']}/validate").json()
    unresolved = [i for i in result["issues"] if i["code"] == "BOOKING_STOP_UNRESOLVED"]
    assert len(unresolved) == 1 and unresolved[0]["details"]["stop"] == "Latur"
    assert result["valid"] is False


def test_booking_change_after_confirmation_requires_review(api, world):
    confirm(api, world)
    api.post(
        f"/journeys/{world['journey']}/bookings",
        {
            "reference": "B4",
            "passenger_count": 1,
            "pickup_stop_name": "Pune",
            "drop_stop_name": "Nanded",
        },
    )
    assert "PLAN_NEEDS_REVIEW" in issue_codes(api, world)
    # The confirmed stops were not rewritten behind the operator's back.
    plan = api.get(f"/journeys/{world['journey']}/stop-plan").json()
    pune = next(s for s in plan["stops"] if s["name"] == "Pune")
    assert pune["pickup_count"] == 5 and pune["booked_pickups"] == 6
    # Re-confirming with the right numbers clears the flag.
    confirm(
        api,
        world,
        Pune={"pickup_count": 6, "drop_count": 0},
        Nanded={"pickup_count": 0, "drop_count": 5},
    )
    assert issue_codes(api, world) == []


def test_journey_without_bookings_only_warns(api, world, conn, tenants):
    bus = str(f.make_bus(conn, tenants["op1"]))
    empty = api.post(
        "/journeys",
        {
            "bus_id": bus,
            "service_id": world["service"],
            "departure_at": "2031-03-01T16:30:00Z",
            "scheduled_arrival_at": "2031-03-02T02:00:00Z",
        },
    ).json()["id"]
    api.put(f"/journeys/{empty}/route-template", {"route_template_id": world["north"]})
    result = api.post(f"/journeys/{empty}/validate").json()
    assert result["valid"] is True
    assert [i["code"] for i in result["issues"]] == ["NO_BOOKINGS"]
    assert (
        api.post(f"/journeys/{empty}/transition", {"to": "awaiting_confirmation"}).status_code
        == 200
    )
    assert api.post(f"/journeys/{empty}/assign").json()["status"] == "ready"


# ------------------------------------------------------------------ lifecycle


def test_legal_path_to_ready_and_beyond(api, world, conn):
    journey = to_ready(api, world)
    assert journey["status"] == "ready"
    for to in ("published", "boarding", "in_progress", "completed"):
        r = api.post(f"/journeys/{world['journey']}/transition", {"to": to}, who="dispatcher1")
        assert r.status_code == 200 and r.json()["status"] == to
    events = conn.execute(
        "select payload ->> 'from', payload ->> 'to', actor_id from public.journey_events "
        "where journey_id = %s and event_type = 'journey_transition' order by id",
        (world["journey"],),
    ).fetchall()
    assert [(a, b) for a, b, _ in events] == [
        ("draft", "awaiting_confirmation"),
        ("awaiting_confirmation", "ready"),
        ("ready", "published"),
        ("published", "boarding"),
        ("boarding", "in_progress"),
        ("in_progress", "completed"),
    ]
    assert all(actor is not None for _, _, actor in events)
    assert api.post(f"/journeys/{world['journey']}/transition", {"to": "draft"}).status_code == 409


def test_illegal_jump_lists_allowed_options(api, world):
    r = api.post(f"/journeys/{world['journey']}/transition", {"to": "in_progress"})
    assert r.status_code == 409
    assert r.json()["details"]["allowed"] == ["awaiting_confirmation", "cancelled"]
    assert api.post(f"/journeys/{world['journey']}/transition", {"to": "flying"}).status_code == 422


def test_plan_errors_block_confirmation_and_assignment(api, world):
    r = api.post(f"/journeys/{world['journey']}/transition", {"to": "awaiting_confirmation"})
    assert r.status_code == 409
    assert {i["code"] for i in r.json()["details"]["issues"]} >= {"BOOKING_PICKUP_NOT_ACTIVE"}
    assert api.post(f"/journeys/{world['journey']}/assign").status_code == 409
    assert api.get(f"/journeys/{world['journey']}").json()["status"] == "draft"


def test_ready_needs_the_assign_step(api, world):
    confirm(api, world)
    api.post(f"/journeys/{world['journey']}/transition", {"to": "awaiting_confirmation"})
    r = api.post(f"/journeys/{world['journey']}/transition", {"to": "ready"})
    assert r.status_code == 409 and "Assign" in r.json()["detail"]


def test_only_owner_can_cancel(api, world):
    j = world["journey"]
    allowed = api.get(f"/journeys/{j}/transitions", who="dispatcher1").json()
    assert allowed == {"status": "draft", "allowed": ["awaiting_confirmation"]}
    assert (
        api.post(f"/journeys/{j}/transition", {"to": "cancelled"}, who="dispatcher1").status_code
        == 403
    )
    assert (
        api.post(f"/journeys/{j}/transition", {"to": "cancelled"}).json()["status"] == "cancelled"
    )
    assert api.get(f"/journeys/{j}/transitions").json()["allowed"] == []


def test_stops_locked_outside_draft_and_reopen_allows_edits(api, world):
    to_ready(api, world)
    assert confirm(api, world).status_code == 409
    assert (
        api.put(
            f"/journeys/{world['journey']}/route-template", {"route_template_id": world["south"]}
        ).status_code
        == 409
    )
    assert api.post(f"/journeys/{world['journey']}/transition", {"to": "draft"}).status_code == 200
    assert confirm(api, world).status_code == 200


# ------------------------------------------------------------------ route versions


def test_assign_creates_version_one_through_every_active_stop(api, world):
    to_ready(api, world)
    versions = api.get(f"/journeys/{world['journey']}/route-versions").json()
    assert len(versions) == 1
    v1 = versions[0]
    assert v1["version"] == 1 and v1["is_current"] is True
    assert v1["source"] == "operator_initial"
    assert [w["name"] for w in v1["details"]["waypoints"]] == ["Pune", "Beed", "Nanded"]
    assert len(v1["details"]["legs"]) == 2
    assert len(v1["coordinates"]) >= 2 and v1["distance_m"] > 300_000
    # The routing request went through the active stop, in order.
    last_call = world["routing"].calls[-1]["waypoints"]
    assert last_call == [
        (PUNE["lng"], PUNE["lat"]),
        (BEED["lng"], BEED["lat"]),
        (NANDED["lng"], NANDED["lat"]),
    ]


def test_reassign_after_reopen_appends_version_two(api, world):
    to_ready(api, world)
    api.post(f"/journeys/{world['journey']}/transition", {"to": "draft"})
    to_ready(api, world)
    versions = api.get(f"/journeys/{world['journey']}/route-versions").json()
    assert [(v["version"], v["is_current"]) for v in versions] == [(1, False), (2, True)]


def test_route_versions_cannot_be_modified(api, world, conn):
    import psycopg

    to_ready(api, world)
    with pytest.raises(psycopg.errors.RestrictViolation):
        with conn.transaction():
            conn.execute(
                "update public.route_versions set reason = 'x' where journey_id = %s",
                (world["journey"],),
            )


def test_assign_falls_back_to_template_geometry_when_routing_is_down(api, world):
    confirm(api, world)
    api.post(f"/journeys/{world['journey']}/transition", {"to": "awaiting_confirmation"})
    world["routing"].fail_with = RoutingUnavailable("simulated")
    r = api.post(f"/journeys/{world['journey']}/assign")
    assert r.status_code == 200 and r.json()["status"] == "ready"
    v1 = api.get(f"/journeys/{world['journey']}/route-versions").json()[0]
    assert v1["details"]["fallback"] == "template_geometry"
    assert len(v1["coordinates"]) >= 2


def test_two_journeys_on_the_same_option_have_independent_versions(api, world, conn, tenants):
    to_ready(api, world)
    bus = str(f.make_bus(conn, tenants["op1"]))
    other = api.post(
        "/journeys",
        {
            "bus_id": bus,
            "service_id": world["service"],
            "departure_at": "2031-03-01T16:30:00Z",
            "scheduled_arrival_at": "2031-03-02T02:00:00Z",
        },
    ).json()["id"]
    api.put(f"/journeys/{other}/route-template", {"route_template_id": world["north"]})
    assert api.get(f"/journeys/{other}/route-versions").json() == []
    assert not any(s["active"] for s in api.get(f"/journeys/{other}/stop-plan").json()["stops"])
    api.post(f"/journeys/{other}/transition", {"to": "awaiting_confirmation"})
    api.post(f"/journeys/{other}/assign")
    assert [v["version"] for v in api.get(f"/journeys/{other}/route-versions").json()] == [1]
    assert len(api.get(f"/journeys/{world['journey']}/route-versions").json()) == 1


def test_double_assign_creates_only_one_version(api, world):
    confirm(api, world)
    api.post(f"/journeys/{world['journey']}/transition", {"to": "awaiting_confirmation"})
    first = api.post(f"/journeys/{world['journey']}/assign")
    second = api.post(f"/journeys/{world['journey']}/assign")
    assert first.status_code == 200 and second.status_code == 409
    assert len(api.get(f"/journeys/{world['journey']}/route-versions").json()) == 1
