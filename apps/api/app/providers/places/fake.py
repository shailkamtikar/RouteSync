"""Deterministic places provider for tests. Uses no network."""

from app.providers.places.base import LngLat, Place, PlacesUnavailable
from app.providers.routing.base import haversine_m

# A few real Maharashtra towns. Latur and Solapur are far south of the northern corridor.
KNOWN_PLACES = [
    Place("Ahmednagar", 74.7496, 19.0948, "city"),
    Place("Beed", 75.7601, 18.9891, "city"),
    Place("Majalgaon", 76.2080, 19.1510, "town"),
    Place("Parbhani", 76.7748, 19.2608, "city"),
    Place("Solapur", 75.9064, 17.6599, "city"),
    Place("Latur", 76.5604, 18.4088, "city"),
]


class FakePlacesProvider:
    name = "fake"
    attribution = "simulated places"

    def __init__(self, places: list[Place] | None = None) -> None:
        self.places = list(KNOWN_PLACES if places is None else places)
        self.calls = 0
        self.fail = False

    def places_near_line(self, line: list[LngLat], radius_m: int) -> list[Place]:
        self.calls += 1
        if self.fail:
            raise PlacesUnavailable("simulated failure")
        return [
            place
            for place in self.places
            if any(haversine_m((place.lng, place.lat), point) <= radius_m for point in line)
        ]
