"""OpenStreetMap places through the public Overpass API.

Overpass is a free shared service: requests are few (one per route option, then cached),
identify the app with a User-Agent, and failures degrade to "no suggestions".
"""

import logging

import httpx

from app.providers.places.base import LngLat, Place, PlacesUnavailable

logger = logging.getLogger(__name__)

OVERPASS_URL = "https://overpass-api.de/api/interpreter"
MAX_LINE_POINTS = 120
MAX_PLACES = 200


def thin_line(line: list[LngLat], max_points: int = MAX_LINE_POINTS) -> list[LngLat]:
    """Keep at most `max_points` evenly spaced points, always including both ends."""
    if len(line) <= max_points:
        return list(line)
    step = (len(line) - 1) / (max_points - 1)
    return [line[round(i * step)] for i in range(max_points)]


def build_query(line: list[LngLat], radius_m: int) -> str:
    around = ",".join(f"{lat:.5f},{lng:.5f}" for lng, lat in thin_line(line))
    return (
        "[out:json][timeout:25];("
        f'node["place"~"^(city|town)$"]["name"](around:{radius_m},{around});'
        f'node["amenity"="bus_station"]["name"](around:{radius_m},{around});'
        ");out body;"
    )


class OverpassPlacesProvider:
    name = "overpass"
    attribution = "© OpenStreetMap contributors"

    def __init__(self, *, timeout_s: float = 30.0, transport: httpx.BaseTransport | None = None):
        self._client = httpx.Client(
            timeout=timeout_s,
            transport=transport,
            headers={"User-Agent": "RouteSync/0.1 (bus journey planning; stop suggestions)"},
        )

    def places_near_line(self, line: list[LngLat], radius_m: int) -> list[Place]:
        if len(line) < 2:
            return []
        try:
            response = self._client.post(OVERPASS_URL, data={"data": build_query(line, radius_m)})
        except httpx.HTTPError as exc:
            logger.warning("overpass request failed: %s", type(exc).__name__)
            raise PlacesUnavailable("place lookup failed") from None
        if response.status_code != 200:
            logger.warning("overpass returned HTTP %s", response.status_code)
            raise PlacesUnavailable("place lookup failed")
        try:
            elements = response.json()["elements"]
            places = []
            for element in elements:
                tags = element.get("tags", {})
                name = (tags.get("name:en") or tags.get("name") or "").strip()
                if not name or len(name) > 120:
                    continue
                places.append(
                    Place(
                        name=name,
                        lng=float(element["lon"]),
                        lat=float(element["lat"]),
                        place_type=tags.get("place") or "bus_station",
                    )
                )
            return places[:MAX_PLACES]
        except (ValueError, KeyError, TypeError):
            raise PlacesUnavailable("place lookup returned malformed data") from None
