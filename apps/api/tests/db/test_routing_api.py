import pytest

from app.domain import routing
from app.domain.routing import get_routing_provider
from app.main import app
from app.providers.routing.base import RoutingQuotaExceeded, RoutingUnavailable
from app.providers.routing.fake import FakeRoutingProvider

pytestmark = pytest.mark.db

PUNE = {"lat": 18.5204, "lng": 73.8567}
BEED = {"lat": 18.9891, "lng": 75.7601}
NANDED = {"lat": 19.1383, "lng": 77.321}


@pytest.fixture
def fake_routing(api):
    provider = FakeRoutingProvider()
    app.dependency_overrides[get_routing_provider] = lambda: provider
    yield provider
    app.dependency_overrides.pop(get_routing_provider, None)


def test_preview_returns_route_through_ordered_waypoints(api, fake_routing):
    r = api.post("/routing/preview", {"waypoints": [PUNE, BEED, NANDED]})
    assert r.status_code == 200
    route = r.json()[0]
    assert len(route["legs"]) == 2
    assert route["coordinates"][0] == [PUNE["lng"], PUNE["lat"]]
    assert route["distance_m"] > 300_000
    assert fake_routing.calls[0]["waypoints"] == [
        (PUNE["lng"], PUNE["lat"]),
        (BEED["lng"], BEED["lat"]),
        (NANDED["lng"], NANDED["lat"]),
    ]


def test_second_identical_request_is_served_from_cache(api, fake_routing):
    body = {"waypoints": [PUNE, NANDED]}
    first = api.post("/routing/preview", body).json()
    second = api.post("/routing/preview", body, who="owner2").json()
    assert first == second
    assert len(fake_routing.calls) == 1
    api.post("/routing/preview", {"waypoints": [PUNE, BEED]})
    assert len(fake_routing.calls) == 2


def test_long_route_alternatives_return_single_route_with_warning(api, fake_routing):
    r = api.post("/routing/preview", {"waypoints": [PUNE, NANDED], "alternatives": 2})
    assert r.status_code == 200
    assert len(r.json()) == 1
    assert r.json()[0]["warnings"] == ["alternatives_unavailable"]


@pytest.mark.parametrize(
    "body",
    [
        {"waypoints": [PUNE]},
        {"waypoints": [PUNE, {"lat": 123, "lng": 77}]},
        {"waypoints": [PUNE, NANDED] * 26},
        {"waypoints": [PUNE, NANDED], "profile": "walking"},
        {"waypoints": [PUNE, NANDED], "alternatives": 9},
        {"waypoints": [PUNE, PUNE]},
        {},
    ],
)
def test_invalid_preview_is_422_without_provider_call(api, fake_routing, body):
    assert api.post("/routing/preview", body).status_code == 422
    assert fake_routing.calls == []


def test_preview_requires_authentication(api, fake_routing):
    body = {"waypoints": [PUNE, NANDED]}
    assert api.call("POST", "/routing/preview", who=None, json=body).status_code == 401
    assert api.post("/routing/preview", body, who="outsider").status_code == 403
    assert fake_routing.calls == []


def test_quota_exhausted_is_503_with_clear_code(api, fake_routing):
    fake_routing.fail_with = RoutingQuotaExceeded("simulated")
    r = api.post("/routing/preview", {"waypoints": [PUNE, NANDED]})
    assert r.status_code == 503
    assert r.json()["code"] == "routing_quota_exceeded"


def test_provider_down_is_503_and_nothing_is_cached(api, fake_routing, conn):
    fake_routing.fail_with = RoutingUnavailable("simulated")
    r = api.post("/routing/preview", {"waypoints": [PUNE, NANDED]})
    assert r.status_code == 503
    assert r.json()["code"] == "routing_unavailable"
    assert "Traceback" not in r.text
    fake_routing.fail_with = None
    assert api.post("/routing/preview", {"waypoints": [PUNE, NANDED]}).status_code == 200
    assert len(fake_routing.calls) == 2


def test_unreadable_cache_entry_falls_back_to_provider(api, fake_routing, conn):
    waypoints = [(PUNE["lng"], PUNE["lat"]), (NANDED["lng"], NANDED["lat"])]
    key = routing.cache_key("fake", waypoints, "driving-car", 0)
    conn.execute(
        "insert into public.routing_cache (key, provider, response) values (%s, 'fake', %s)",
        (key, '[{"broken": true}]'),
    )
    r = api.post("/routing/preview", {"waypoints": [PUNE, NANDED]})
    assert r.status_code == 200
    assert len(fake_routing.calls) == 1


def test_cache_table_is_not_readable_through_the_data_api(conn, actor, tenants):
    import psycopg

    for role in ("user", "anon"):
        actor.user(tenants["owner1"]) if role == "user" else actor.anon()
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            with conn.transaction():
                conn.execute("select count(*) from public.routing_cache")
    actor.admin()
