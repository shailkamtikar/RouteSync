import httpx
import pytest

from app.providers.places.base import PlacesUnavailable
from app.providers.places.fake import FakePlacesProvider
from app.providers.places.overpass import OverpassPlacesProvider, build_query, thin_line

LINE = [(73.8567, 18.5204), (75.7601, 18.9891), (77.321, 19.1383)]


def overpass(handler, **kwargs) -> OverpassPlacesProvider:
    return OverpassPlacesProvider(transport=httpx.MockTransport(handler), backoff_s=0, **kwargs)


def element(name, lon=75.76, lat=18.99, **tags):
    return {"type": "node", "lon": lon, "lat": lat, "tags": {"name": name, **tags}}


def test_thin_line_keeps_ends_and_caps_points():
    line = [(float(i), 0.0) for i in range(1000)]
    thinned = thin_line(line, 120)
    assert len(thinned) == 120
    assert thinned[0] == line[0] and thinned[-1] == line[-1]
    assert thin_line(LINE, 120) == LINE


def test_query_uses_lat_lon_order_and_radius():
    query = build_query(LINE, 5000)
    assert "around:5000,18.52040,73.85670,18.98910,75.76010" in query
    assert "city|town" in query and "bus_station" in query


def test_overpass_parses_named_places():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["agent"] = request.headers["user-agent"]
        return httpx.Response(
            200,
            json={
                "elements": [
                    element("Beed", place="city"),
                    element("बीड", **{"name:en": "Beed East", "place": "town"}),
                    element("Central Bus Stand", amenity="bus_station"),
                    {"type": "node", "lon": 1, "lat": 2, "tags": {}},
                    element("x" * 121, place="town"),
                ]
            },
        )

    places = overpass(handler).places_near_line(LINE, 5000)
    assert [(p.name, p.place_type) for p in places] == [
        ("Beed", "city"),
        ("Beed East", "town"),
        ("Central Bus Stand", "bus_station"),
    ]
    assert "RouteSync" in seen["agent"]


def test_overpass_retries_once_then_succeeds():
    responses = iter([httpx.Response(502), httpx.Response(200, json={"elements": []})])
    assert overpass(lambda request: next(responses)).places_near_line(LINE, 5000) == []


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(504),
        httpx.Response(429),
        httpx.Response(200, content=b"<html>busy</html>"),
        httpx.Response(200, json={"remark": "runtime error"}),
        httpx.Response(200, json={"elements": [{"tags": {"name": "A"}}]}),
    ],
)
def test_overpass_failures_are_unavailable(response):
    with pytest.raises(PlacesUnavailable):
        overpass(lambda request: response).places_near_line(LINE, 5000)


def test_overpass_network_error_is_unavailable():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down", request=request)

    with pytest.raises(PlacesUnavailable):
        overpass(handler).places_near_line(LINE, 5000)


def test_short_line_makes_no_request():
    calls = []
    provider = overpass(lambda request: calls.append(1) or httpx.Response(200, json={}))
    assert provider.places_near_line([LINE[0]], 5000) == []
    assert calls == []


def test_fake_places_filters_by_distance():
    provider = FakePlacesProvider()
    names = {p.name for p in provider.places_near_line(LINE, 5000)}
    assert "Beed" in names and "Latur" not in names
    provider.fail = True
    with pytest.raises(PlacesUnavailable):
        provider.places_near_line(LINE, 5000)
