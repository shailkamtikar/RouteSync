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
AHMEDNAGAR = {"name": "Ahmednagar", "lat": 19.0948, "lng": 74.7496}
BEED = {"name": "Beed", "lat": 18.9891, "lng": 75.7601}
SOLAPUR = {"name": "Solapur", "lat": 17.6599, "lng": 75.9064}
LATUR = {"name": "Latur", "lat": 18.4088, "lng": 76.5604}
NORTH = {"name": "Via Ahmednagar and Beed", "via_points": [AHMEDNAGAR, BEED]}
SOUTH = {"name": "Via Solapur and Latur", "via_points": [SOLAPUR, LATUR]}


def point(place):
    return {"lat": place["lat"], "lng": place["lng"]}


@pytest.fixture
def world(api, conn, tenants):
    routing_provider = FakeRoutingProvider()
    places_provider = FakePlacesProvider()
    app.dependency_overrides[get_routing_provider] = lambda: routing_provider
    app.dependency_overrides[get_places_provider] = lambda: places_provider
    service = api.post(
        "/services",
        {
            "origin_name": "Pune",
            "destination_name": "Nanded",
            "origin_location": PUNE,
            "destination_location": NANDED,
        },
    ).json()
    yield {"service": service["id"], "routing": routing_provider, "places": places_provider}
    app.dependency_overrides.pop(get_routing_provider, None)
    app.dependency_overrides.pop(get_places_provider, None)


def make_template(api, world, body=NORTH, who="owner1"):
    r = api.post(f"/services/{world['service']}/route-templates", body, who=who)
    assert r.status_code == 201, r.text
    return r.json()["template"]


def stop_names(api, template_id):
    return [stop["name"] for stop in api.get(f"/route-templates/{template_id}/stops").json()]


# ------------------------------------------------------------------ route options


def test_two_route_options_have_distinct_geometry(api, world):
    north = make_template(api, world, NORTH)
    south = make_template(api, world, SOUTH)
    assert north["status"] == south["status"] == "ready"
    assert north["coordinates"] != south["coordinates"]
    assert north["distance_m"] != south["distance_m"]
    assert north["provider"] == "fake" and north["attribution"]
    listed = api.get(f"/services/{world['service']}/route-templates").json()
    assert [t["name"] for t in listed] == [NORTH["name"], SOUTH["name"]]
    # The provider received origin, the via-points in order, then the destination.
    assert world["routing"].calls[0]["waypoints"] == [
        (PUNE["lng"], PUNE["lat"]),
        (AHMEDNAGAR["lng"], AHMEDNAGAR["lat"]),
        (BEED["lng"], BEED["lat"]),
        (NANDED["lng"], NANDED["lat"]),
    ]


def test_generation_creates_origin_and_destination_stops_and_corridor(api, world, conn):
    template = make_template(api, world)
    stops = api.get(f"/route-templates/{template['id']}/stops").json()
    assert [(s["name"], s["role"]) for s in stops] == [
        ("Pune", "origin"),
        ("Nanded", "destination"),
    ]
    assert stops[0]["chainage_m"] == 0
    assert stops[1]["chainage_m"] == pytest.approx(template["distance_m"])
    inside, width = conn.execute(
        "select extensions.st_covers(corridor, geometry), "
        "(provider_metadata ->> 'corridor_width_m')::int "
        "from public.route_templates where id = %s",
        (template["id"],),
    ).fetchone()
    assert inside is True and width == 5000


def test_duplicate_option_name_is_conflict(api, world):
    make_template(api, world)
    r = api.post(
        f"/services/{world['service']}/route-templates",
        {**NORTH, "name": "via ahmednagar and BEED"},
    )
    assert r.status_code == 409


@pytest.mark.parametrize(
    "body",
    [
        {"name": ""},
        {"name": "X", "via_points": [{"lat": 123, "lng": 75}]},
        {"name": "X", "via_points": [BEED] * 21},
        {"name": "X", "profile": "walking"},
        {"name": "X", "geometry": "LINESTRING(0 0, 1 1)"},
    ],
)
def test_invalid_route_option_is_rejected(api, world, body):
    assert api.post(f"/services/{world['service']}/route-templates", body).status_code == 422
    assert api.get(f"/services/{world['service']}/route-templates").json() == []


def test_provider_failure_leaves_option_unresolved_with_clear_error(api, world):
    world["routing"].fail_with = RoutingUnavailable("simulated")
    r = api.post(f"/services/{world['service']}/route-templates", NORTH)
    assert r.status_code == 201
    body = r.json()
    assert body["template"]["status"] == "unresolved"
    assert body["template"]["coordinates"] == []
    assert body["generation_error"]
    # Retrying once the provider is back works.
    world["routing"].fail_with = None
    regenerated = api.post(f"/route-templates/{body['template']['id']}/generate")
    assert regenerated.status_code == 200 and regenerated.json()["status"] == "ready"


def test_option_needs_service_coordinates(api, world):
    bare = api.post("/services", {"origin_name": "Pune", "destination_name": "Latur"}).json()
    r = api.post(f"/services/{bare['id']}/route-templates", {"name": "Direct"})
    assert r.status_code == 201
    assert r.json()["template"]["status"] == "unresolved"
    assert "coordinates" in r.json()["generation_error"]


def test_cross_operator_route_option_access_is_404(api, world):
    template = make_template(api, world)
    tid = template["id"]
    assert api.get(f"/route-templates/{tid}", who="owner2").status_code == 404
    assert api.patch(f"/route-templates/{tid}", {"name": "Mine"}, who="owner2").status_code == 404
    assert api.delete(f"/route-templates/{tid}", who="owner2").status_code == 404
    assert api.post(f"/route-templates/{tid}/generate", who="owner2").status_code == 404
    assert api.get(f"/route-templates/{tid}/stops", who="owner2").status_code == 404
    assert api.get(f"/route-templates/{tid}/stop-candidates", who="owner2").status_code == 404
    assert (
        api.post(
            f"/route-templates/{tid}/stops", {"name": "Beed", "location": point(BEED)}, who="owner2"
        ).status_code
        == 404
    )
    assert api.get(f"/services/{world['service']}/route-templates", who="owner2").status_code == 404
    assert api.get(f"/route-templates/{tid}").json()["name"] == NORTH["name"]


def test_route_endpoints_require_authentication(api, world):
    template = make_template(api, world)
    for method, path in [
        ("GET", f"/services/{world['service']}/route-templates"),
        ("POST", f"/services/{world['service']}/route-templates"),
        ("GET", f"/route-templates/{template['id']}/stops"),
        ("GET", f"/route-templates/{template['id']}/stop-candidates"),
    ]:
        assert api.call(method, path, who=None, json=NORTH).status_code == 401


def test_rename_keeps_geometry_and_version(api, world):
    template = make_template(api, world)
    calls = len(world["routing"].calls)
    r = api.patch(f"/route-templates/{template['id']}", {"name": "Northern corridor"})
    assert r.status_code == 200
    updated = r.json()["template"]
    assert updated["id"] == template["id"] and updated["version"] == 1
    assert updated["coordinates"] == template["coordinates"]
    assert len(world["routing"].calls) == calls


def test_editing_road_of_unused_option_regenerates_in_place(api, world):
    template = make_template(api, world)
    r = api.patch(f"/route-templates/{template['id']}", {"via_points": [BEED]})
    updated = r.json()["template"]
    assert updated["id"] == template["id"] and updated["version"] == 1
    assert updated["distance_m"] != template["distance_m"]


def test_editing_road_of_option_in_use_creates_new_version(api, world, conn, tenants):
    template = make_template(api, world)
    api.post(f"/route-templates/{template['id']}/stops", {"name": "Beed", "location": point(BEED)})
    bus = f.make_bus(conn, tenants["op1"])
    journey = f.make_journey(conn, tenants["op1"], bus, world["service"], template["id"])

    r = api.patch(f"/route-templates/{template['id']}", {"via_points": [BEED]})
    assert r.status_code == 200
    body = r.json()
    new = body["template"]
    assert "new_version_created" in body["warnings"]
    assert new["id"] != template["id"] and new["version"] == 2

    # The journey still points at the original option, whose geometry is untouched.
    old = api.get(f"/route-templates/{template['id']}").json()
    assert old["status"] == "archived" and old["coordinates"] == template["coordinates"]
    assert (
        str(
            conn.execute(
                "select route_template_id from public.journeys where id = %s", (journey,)
            ).fetchone()[0]
        )
        == template["id"]
    )
    assert "Beed" in stop_names(api, new["id"])
    listed = api.get(f"/services/{world['service']}/route-templates").json()
    assert [t["id"] for t in listed] == [new["id"]]


def test_remove_option_deletes_or_archives(api, world, conn, tenants):
    unused = make_template(api, world, SOUTH)
    assert api.delete(f"/route-templates/{unused['id']}", who="dispatcher1").status_code == 403
    assert api.delete(f"/route-templates/{unused['id']}").json() == {"result": "deleted"}
    used = make_template(api, world, NORTH)
    bus = f.make_bus(conn, tenants["op1"])
    f.make_journey(conn, tenants["op1"], bus, world["service"], used["id"])
    assert api.delete(f"/route-templates/{used['id']}").json() == {"result": "archived"}


# ------------------------------------------------------------------ route-specific stops


def test_latur_exists_only_on_the_route_that_passes_it(api, world):
    north = make_template(api, world, NORTH)
    south = make_template(api, world, SOUTH)

    on_south = api.post(
        f"/route-templates/{south['id']}/stops", {"name": "Latur", "location": point(LATUR)}
    )
    assert on_south.status_code == 201
    on_north = api.post(
        f"/route-templates/{north['id']}/stops", {"name": "Latur", "location": point(LATUR)}
    )
    assert on_north.status_code == 422
    assert "cannot be a stop" in on_north.json()["detail"]

    assert "Latur" in stop_names(api, south["id"])
    assert "Latur" not in stop_names(api, north["id"])

    north_candidates = api.get(f"/route-templates/{north['id']}/stop-candidates").json()
    south_candidates = api.get(f"/route-templates/{south['id']}/stop-candidates").json()
    north_names = [c["name"] for c in north_candidates["candidates"]]
    south_names = [c["name"] for c in south_candidates["candidates"]]
    assert "Latur" not in north_names and "Solapur" not in north_names
    assert {"Ahmednagar", "Beed"} <= set(north_names)
    assert "Solapur" in south_names and "Ahmednagar" not in south_names
    assert "Latur" not in south_names  # already a stop on that option


def test_stops_are_ordered_by_distance_along_the_route(api, world):
    template = make_template(api, world)
    for place in (BEED, AHMEDNAGAR):
        r = api.post(
            f"/route-templates/{template['id']}/stops",
            {"name": place["name"], "location": point(place)},
        )
        assert r.status_code == 201
    stops = api.get(f"/route-templates/{template['id']}/stops").json()
    assert [s["name"] for s in stops] == ["Pune", "Ahmednagar", "Beed", "Nanded"]
    chainages = [s["chainage_m"] for s in stops]
    assert chainages == sorted(chainages)


def test_candidates_are_on_corridor_sorted_and_cached(api, world):
    template = make_template(api, world)
    first = api.get(f"/route-templates/{template['id']}/stop-candidates").json()
    assert first["available"] is True and first["attribution"]
    chainages = [c["chainage_m"] for c in first["candidates"]]
    assert chainages == sorted(chainages)
    api.get(f"/route-templates/{template['id']}/stop-candidates")
    assert world["places"].calls == 1


def test_promoting_a_candidate_makes_it_a_stop(api, world):
    template = make_template(api, world)
    candidate = api.get(f"/route-templates/{template['id']}/stop-candidates").json()["candidates"][
        0
    ]
    r = api.post(
        f"/route-templates/{template['id']}/stops",
        {"name": candidate["name"], "location": candidate["location"], "source": "osm"},
    )
    assert r.status_code == 201 and r.json()["source"] == "osm"
    remaining = api.get(f"/route-templates/{template['id']}/stop-candidates").json()["candidates"]
    assert candidate["name"] not in [c["name"] for c in remaining]


def test_places_provider_down_falls_back_gracefully(api, world):
    template = make_template(api, world)
    world["places"].fail = True
    r = api.get(f"/route-templates/{template['id']}/stop-candidates")
    assert r.status_code == 200
    assert r.json()["available"] is False and r.json()["candidates"] == []
    assert stop_names(api, template["id"]) == ["Pune", "Nanded"]


def test_pass_through_place_and_stop_rules(api, world, conn, tenants):
    template = make_template(api, world)
    tid = template["id"]
    town = api.post(
        f"/route-templates/{tid}/stops",
        {"name": "Majalgaon", "location": {"lat": 19.02, "lng": 76.2}, "kind": "pass_through"},
    )
    assert town.status_code == 201 and town.json()["kind"] == "pass_through"
    assert (
        api.post(
            f"/route-templates/{tid}/stops",
            {"name": "majalgaon", "location": {"lat": 19.02, "lng": 76.2}},
        ).status_code
        == 409
    )

    stops = api.get(f"/route-templates/{tid}/stops").json()
    origin = next(s for s in stops if s["role"] == "origin")
    assert api.patch(f"/route-template-stops/{origin['id']}", {"name": "X"}).status_code == 409
    assert api.delete(f"/route-template-stops/{origin['id']}").status_code == 409

    beed = api.post(
        f"/route-templates/{tid}/stops", {"name": "Beed", "location": point(BEED)}
    ).json()
    bus = f.make_bus(conn, tenants["op1"])
    journey = f.make_journey(conn, tenants["op1"], bus, world["service"], tid)
    f.make_journey_stop(conn, tenants["op1"], journey, tid, beed["id"])
    assert api.delete(f"/route-template-stops/{beed['id']}").status_code == 409
    assert (
        api.patch(f"/route-template-stops/{beed['id']}", {"kind": "pass_through"}).status_code
        == 409
    )
    assert api.delete(f"/route-template-stops/{town.json()['id']}").status_code == 204
    assert api.delete(f"/route-template-stops/{town.json()['id']}").status_code == 404


def test_stop_needs_generated_route(api, world):
    world["routing"].fail_with = RoutingUnavailable("simulated")
    template = api.post(f"/services/{world['service']}/route-templates", NORTH).json()["template"]
    r = api.post(
        f"/route-templates/{template['id']}/stops", {"name": "Beed", "location": point(BEED)}
    )
    assert r.status_code == 422


# ------------------------------------------------------------------ journey route selection


@pytest.fixture
def journey(api, world, conn, tenants):
    bus = f.make_bus(conn, tenants["op1"])
    return api.post(
        "/journeys",
        {
            "bus_id": str(bus),
            "service_id": world["service"],
            "departure_at": "2031-03-01T16:30:00Z",
            "scheduled_arrival_at": "2031-03-02T02:00:00Z",
        },
    ).json()["id"]


def test_select_route_option_and_resolve_booking_stops(api, world, journey):
    template = make_template(api, world)
    api.post(f"/route-templates/{template['id']}/stops", {"name": "Beed", "location": point(BEED)})
    api.post(
        f"/journeys/{journey}/bookings",
        {
            "reference": "B1",
            "passenger_count": 1,
            "pickup_stop_name": "pune",
            "drop_stop_name": " BEED ",
        },
    )
    api.post(
        f"/journeys/{journey}/bookings",
        {
            "reference": "B2",
            "passenger_count": 1,
            "pickup_stop_name": "Beed",
            "drop_stop_name": "Latur",
        },
    )
    r = api.put(f"/journeys/{journey}/route-template", {"route_template_id": template["id"]})
    assert r.status_code == 200
    assert r.json()["route_template_id"] == template["id"]

    bookings = {b["reference"]: b for b in api.get(f"/journeys/{journey}/bookings").json()}
    assert bookings["B1"]["pickup_stop_id"] and bookings["B1"]["drop_stop_id"]
    assert bookings["B2"]["pickup_stop_id"] and bookings["B2"]["drop_stop_id"] is None

    report = api.post(f"/journeys/{journey}/bookings/resolve-stops").json()
    assert [u["reference"] for u in report["unresolved"]] == ["B2"]
    assert report["unresolved"][0]["drop_stop_name"] == "Latur"
    assert report["unresolved"][0]["pickup_stop_name"] is None


def test_route_option_must_belong_to_the_journeys_service(api, world, journey):
    other_service = api.post(
        "/services",
        {
            "origin_name": "Pune",
            "destination_name": "Latur",
            "origin_location": PUNE,
            "destination_location": point(LATUR),
        },
    ).json()
    foreign = api.post(
        f"/services/{other_service['id']}/route-templates", {"name": "Direct"}
    ).json()["template"]
    r = api.put(f"/journeys/{journey}/route-template", {"route_template_id": foreign["id"]})
    assert r.status_code == 422
    assert api.get(f"/journeys/{journey}").json()["route_template_id"] is None


def test_cannot_select_unresolved_or_foreign_operator_option(api, world, journey):
    world["routing"].fail_with = RoutingUnavailable("simulated")
    unresolved = api.post(f"/services/{world['service']}/route-templates", NORTH).json()["template"]
    r = api.put(f"/journeys/{journey}/route-template", {"route_template_id": unresolved["id"]})
    assert r.status_code == 422
    world["routing"].fail_with = None
    ready = make_template(api, world, SOUTH)
    assert (
        api.put(
            f"/journeys/{journey}/route-template", {"route_template_id": ready["id"]}, who="owner2"
        ).status_code
        == 404
    )


def test_changing_route_option_clears_the_old_stop_plan(api, world, journey, conn, tenants):
    north = make_template(api, world, NORTH)
    south = make_template(api, world, SOUTH)
    beed = api.post(
        f"/route-templates/{north['id']}/stops", {"name": "Beed", "location": point(BEED)}
    ).json()
    api.put(f"/journeys/{journey}/route-template", {"route_template_id": north["id"]})
    f.make_journey_stop(conn, tenants["op1"], journey, north["id"], beed["id"])

    r = api.put(f"/journeys/{journey}/route-template", {"route_template_id": south["id"]})
    assert r.status_code == 200
    assert (
        conn.execute(
            "select count(*) from public.journey_stops where journey_id = %s", (journey,)
        ).fetchone()[0]
        == 0
    )
    payload = conn.execute(
        "select payload from public.journey_events where journey_id = %s "
        "and event_type = 'journey_route_selected' order by id desc limit 1",
        (journey,),
    ).fetchone()[0]
    assert payload["active_stops_cleared"] == 1


def test_route_option_locked_after_draft(api, world, journey, conn):
    template = make_template(api, world)
    conn.execute("update public.journeys set status = 'ready' where id = %s", (journey,))
    r = api.put(f"/journeys/{journey}/route-template", {"route_template_id": template["id"]})
    assert r.status_code == 409
