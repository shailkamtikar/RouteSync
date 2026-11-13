"""Places provider interface: named places near a route, used only as stop suggestions."""

from dataclasses import dataclass
from typing import Protocol

LngLat = tuple[float, float]


class PlacesUnavailable(Exception):
    """The places provider timed out, failed, or returned something unusable."""


@dataclass(frozen=True)
class Place:
    name: str
    lng: float
    lat: float
    place_type: str  # city, town, village, bus_station


class PlacesProvider(Protocol):
    name: str
    attribution: str

    def places_near_line(self, line: list[LngLat], radius_m: int) -> list[Place]:
        """Named places within `radius_m` of the line."""
        ...
