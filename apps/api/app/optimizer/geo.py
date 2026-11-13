"""Small geometry helpers in metres. Pure functions, no I/O.

Coordinates are (lng, lat). Points are projected with an equirectangular projection around
the geometry's own mean latitude, which is accurate to well under 1% over a bus route.
"""

import math
from collections.abc import Sequence

from shapely.geometry import LineString, Point

LngLat = tuple[float, float]
EARTH_RADIUS_M = 6_371_008.8


class Projector:
    def __init__(self, reference_lat: float):
        self._cos = math.cos(math.radians(reference_lat))

    def xy(self, point: LngLat) -> tuple[float, float]:
        return (
            EARTH_RADIUS_M * math.radians(point[0]) * self._cos,
            EARTH_RADIUS_M * math.radians(point[1]),
        )

    def inverse(self, x: float, y: float) -> LngLat:
        return (math.degrees(x / (EARTH_RADIUS_M * self._cos)), math.degrees(y / EARTH_RADIUS_M))

    def line(self, coordinates: Sequence[LngLat]) -> LineString:
        return LineString([self.xy(c) for c in coordinates])


def mean_lat(*groups: Sequence[LngLat]) -> float:
    lats = [point[1] for group in groups for point in group]
    return sum(lats) / len(lats) if lats else 0.0


def line_length_m(coordinates: Sequence[LngLat]) -> float:
    if len(coordinates) < 2:
        return 0.0
    return Projector(mean_lat(coordinates)).line(coordinates).length


def chainage_m(coordinates: Sequence[LngLat], point: LngLat) -> float:
    """Distance along the line to the point on it that is closest to `point`."""
    projector = Projector(mean_lat(coordinates))
    return projector.line(coordinates).project(Point(projector.xy(point)))


def distance_to_line_m(coordinates: Sequence[LngLat], point: LngLat) -> float:
    projector = Projector(mean_lat(coordinates))
    return projector.line(coordinates).distance(Point(projector.xy(point)))


def distance_m(a: LngLat, b: LngLat) -> float:
    projector = Projector((a[1] + b[1]) / 2)
    return math.dist(projector.xy(a), projector.xy(b))


def max_distance_from_line_m(
    coordinates: Sequence[LngLat], corridor_centreline: Sequence[LngLat]
) -> float:
    """Largest distance from any vertex of `coordinates` to the corridor centreline."""
    projector = Projector(mean_lat(coordinates, corridor_centreline))
    centreline = projector.line(corridor_centreline)
    return max(centreline.distance(Point(projector.xy(c))) for c in coordinates)


def slice_from(coordinates: Sequence[LngLat], point: LngLat) -> list[LngLat]:
    """The part of the line from the point nearest `point` to the end."""
    projector = Projector(mean_lat(coordinates))
    line = projector.line(coordinates)
    start = line.project(Point(projector.xy(point)))
    remaining = [projector.inverse(*line.interpolate(start).coords[0])]
    cumulative = 0.0
    xy = [projector.xy(c) for c in coordinates]
    for index, current in enumerate(coordinates):
        if index and cumulative > start:
            remaining.append(current)
        if index + 1 < len(coordinates):
            cumulative += math.dist(xy[index], xy[index + 1])
    if len(remaining) < 2:
        remaining.append(coordinates[-1])
    return remaining
