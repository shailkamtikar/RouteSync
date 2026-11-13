import json

import httpx
import pytest

from app.providers.routing.base import (
    RoutingInvalidRequest,
    RoutingQuotaExceeded,
    RoutingUnavailable,
    haversine_m,
    validate_request,
)
from app.providers.routing.fake import FakeRoutingProvider
from app.providers.routing.ors import ALTERNATIVES_WARNING, OrsRoutingProvider

PUNE = (73.8567, 18.5204)
BEED = (75.7601, 18.9891)
NANDED = (77.321, 19.1383)
NEAR_PUNE = (73.95, 18.56)


def feature(distance=1000.0, duration=100.0, segments=1):
    """Shape of a real openrouteservice GeoJSON feature (instructions enabled)."""
    points = [[73.85 + 0.01 * i, 18.52] for i in range(segments + 1)]
    return {
        "type": "Feature",
        "geometry": {"type": "LineString", "coordinates": points},
        "properties": {
            "way_points": list(range(segments + 1)),
            "summary": {"distance": distance, "duration": duration},
            "segments": [
                {"distance": distance / segments, "duration": duration / segments}
                for _ in range(segments)
            ],
        },
    }


def ors(handler, **kwargs) -> OrsRoutingProvider:
    return OrsRoutingProvider(
        "test-key", transport=httpx.MockTransport(handler), backoff_s=0, **kwargs
    )


# ------------------------------------------------------------------ request validation


def test_haversine_pune_to_nanded_is_about_370_km():
    assert 360_000 < haversine_m(PUNE, NANDED) < 380_000


@pytest.mark.parametrize(
    ("waypoints", "profile", "alternatives"),
    [
        ([PUNE], "driving-car", 0),
        ([], "driving-car", 0),
        ([PUNE, NANDED] * 26, "driving-car", 0),
        ([PUNE, (77.3, 123.0)], "driving-car", 0),
        ([PUNE, (190.0, 19.0)], "driving-car", 0),
        ([PUNE, (float("nan"), 19.0)], "driving-car", 0),
        ([PUNE, PUNE], "driving-car", 0),
        ([PUNE, NANDED], "flying-carpet", 0),
        ([PUNE, NANDED], "driving-car", 4),
        ([PUNE, NANDED], "driving-car", -1),
    ],
)
def test_invalid_requests_are_rejected(waypoints, profile, alternatives):
    with pytest.raises(RoutingInvalidRequest):
        validate_request(waypoints, profile, alternatives, max_waypoints=50)


def test_invalid_request_never_reaches_the_provider():
    calls = []
    provider = ors(lambda request: calls.append(request) or httpx.Response(200, json={}))
    with pytest.raises(RoutingInvalidRequest):
        provider.route([PUNE, NANDED] * 30)
    with pytest.raises(RoutingInvalidRequest):
        provider.route([PUNE, (77.3, 123.0)])
    assert calls == []


# ------------------------------------------------------------------ openrouteservice adapter


def test_ors_parses_route_and_sends_ordered_waypoints():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers["authorization"]
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"features": [feature(431000, 18300, segments=2)]})

    results = ors(handler).route([PUNE, BEED, NANDED], profile="driving-hgv")
    assert seen["url"].endswith("/v2/directions/driving-hgv/geojson")
    assert seen["auth"] == "test-key"
    assert seen["body"]["coordinates"] == [list(PUNE), list(BEED), list(NANDED)]
    assert "alternative_routes" not in seen["body"]
    route = results[0]
    assert route.distance_m == 431000 and route.duration_s == 18300
    assert len(route.legs) == 2
    assert route.waypoint_indices == [0, 1, 2]
    assert seen["body"]["instructions"] is True
    assert route.provider == "openrouteservice"
    assert "OpenStreetMap" in route.metadata["attribution"]


def test_ors_requests_alternatives_only_for_one_short_leg():
    bodies = []

    def handler(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content))
        return httpx.Response(200, json={"features": [feature(), feature(1200, 130)]})

    short = ors(handler).route([PUNE, NEAR_PUNE], alternatives=2)
    assert bodies[0]["alternative_routes"]["target_count"] == 3
    assert len(short) == 2 and short[0].warnings == []

    long = ors(handler).route([PUNE, NANDED], alternatives=2)
    assert "alternative_routes" not in bodies[1]
    assert long[0].warnings == [ALTERNATIVES_WARNING]

    two_legs = lambda request: httpx.Response(200, json={"features": [feature(segments=2)]})  # noqa: E731
    bodies.append(None)
    multi = ors(two_legs).route([PUNE, NEAR_PUNE, (74.0, 18.6)], alternatives=1)
    assert multi[0].warnings == [ALTERNATIVES_WARNING]


def test_ors_timeout_is_retried_then_unavailable():
    attempts = []

    def handler(request: httpx.Request) -> httpx.Response:
        attempts.append(1)
        raise httpx.ReadTimeout("slow", request=request)

    with pytest.raises(RoutingUnavailable):
        ors(handler, retries=2).route([PUNE, NANDED])
    assert len(attempts) == 3


def test_ors_recovers_after_a_transient_server_error():
    responses = iter([httpx.Response(502), httpx.Response(200, json={"features": [feature()]})])
    results = ors(lambda request: next(responses)).route([PUNE, NANDED])
    assert len(results) == 1


def test_ors_rate_limit_is_quota_error_and_not_retried():
    attempts = []

    def handler(request: httpx.Request) -> httpx.Response:
        attempts.append(1)
        return httpx.Response(429, json={"error": "Rate limit exceeded"})

    with pytest.raises(RoutingQuotaExceeded):
        ors(handler).route([PUNE, NANDED])
    assert len(attempts) == 1


def test_ors_daily_quota_403_is_quota_error():
    handler = lambda request: httpx.Response(403, json={"error": "Quota exceeded"})  # noqa: E731
    with pytest.raises(RoutingQuotaExceeded):
        ors(handler).route([PUNE, NANDED])


def test_ors_bad_key_is_unavailable_without_leaking_it():
    handler = lambda request: httpx.Response(403, json={"error": "Access denied"})  # noqa: E731
    with pytest.raises(RoutingUnavailable) as exc:
        ors(handler).route([PUNE, NANDED])
    assert "test-key" not in str(exc.value)


def test_ors_unroutable_point_is_invalid_request():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            404, json={"error": {"code": 2010, "message": "Could not find routable point"}}
        )

    with pytest.raises(RoutingInvalidRequest) as exc:
        ors(handler).route([PUNE, NANDED])
    assert "routable point" in str(exc.value)


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(200, content=b"<html>not json</html>"),
        httpx.Response(200, json={"features": []}),
        httpx.Response(200, json={"unexpected": True}),
        httpx.Response(200, json={"features": [{"geometry": {"coordinates": []}}]}),
        httpx.Response(200, json={"features": [{"geometry": {"coordinates": [[1, 2]]}}]}),
        httpx.Response(200, json={"features": [feature(segments=2)]}),  # legs do not match
    ],
)
def test_ors_malformed_response_is_unavailable(response):
    with pytest.raises(RoutingUnavailable):
        ors(lambda request: response).route([PUNE, NANDED])


def test_ors_without_key_is_unavailable():
    with pytest.raises(RoutingUnavailable):
        OrsRoutingProvider("")


# ------------------------------------------------------------------ fake provider


def test_fake_provider_is_deterministic_and_ordered():
    provider = FakeRoutingProvider()
    first = provider.route([PUNE, BEED, NANDED])[0]
    second = provider.route([PUNE, BEED, NANDED])[0]
    assert first == second
    assert first.coordinates[0] == PUNE
    assert first.coordinates[-1] == pytest.approx(NANDED)
    assert len(first.legs) == 2
    assert first.waypoint_indices[0] == 0
    assert first.waypoint_indices[-1] == len(first.coordinates) - 1
    assert first.coordinates[first.waypoint_indices[1]] == pytest.approx(BEED)
    assert first.distance_m == pytest.approx(sum(leg.distance_m for leg in first.legs))
    assert len(provider.calls) == 2


def test_fake_provider_alternatives_follow_the_same_limits():
    provider = FakeRoutingProvider()
    assert len(provider.route([PUNE, NEAR_PUNE], alternatives=2)) == 3
    long = provider.route([PUNE, NANDED], alternatives=2)
    assert len(long) == 1 and long[0].warnings == ["alternatives_unavailable"]


def test_fake_provider_can_simulate_failure():
    provider = FakeRoutingProvider()
    provider.fail_with = RoutingQuotaExceeded("simulated")
    with pytest.raises(RoutingQuotaExceeded):
        provider.route([PUNE, NANDED])


# ------------------------------------------------------------------ live contract (manual)


@pytest.mark.live
def test_live_ors_pune_to_nanded():
    from pathlib import Path

    from dotenv import dotenv_values

    key = dotenv_values(Path(__file__).resolve().parents[2] / ".env").get("ORS_API_KEY")
    route = OrsRoutingProvider(key).route([PUNE, BEED, NANDED])[0]
    assert 350_000 < route.distance_m < 600_000
    assert len(route.legs) == 2
    assert len(route.waypoint_indices) == 3
    assert len(route.coordinates) > 100
