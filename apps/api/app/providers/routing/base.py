"""Routing provider interface. The rest of the app never talks to a routing vendor directly."""

import math
from dataclasses import dataclass, field
from typing import Protocol

LngLat = tuple[float, float]

MIN_WAYPOINTS = 2
ALTERNATIVES_MAX_DISTANCE_M = 100_000
ALTERNATIVES_MAX_COUNT = 3
ALLOWED_PROFILES = ("driving-car", "driving-hgv")


class RoutingError(Exception):
    """Base class for routing failures."""


class RoutingInvalidRequest(RoutingError):
    """The request can never succeed (bad coordinates, too many waypoints, unroutable point)."""


class RoutingQuotaExceeded(RoutingError):
    """The provider refused the request because the quota or rate limit is exhausted."""


class RoutingUnavailable(RoutingError):
    """The provider timed out, failed, or returned something unusable."""


@dataclass(frozen=True)
class Leg:
    distance_m: float
    duration_s: float


@dataclass(frozen=True)
class RouteResult:
    coordinates: list[LngLat]
    distance_m: float
    duration_s: float
    legs: list[Leg]
    provider: str
    metadata: dict = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    # Index into `coordinates` of each requested waypoint, in order (first is 0).
    waypoint_indices: list[int] = field(default_factory=list)


class RoutingProvider(Protocol):
    name: str
    max_waypoints: int

    def route(
        self, waypoints: list[LngLat], *, profile: str = "driving-car", alternatives: int = 0
    ) -> list[RouteResult]:
        """Return the main route first, then up to `alternatives` alternative routes."""
        ...


def haversine_m(a: LngLat, b: LngLat) -> float:
    lng1, lat1, lng2, lat2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = (
        math.sin((lat2 - lat1) / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin((lng2 - lng1) / 2) ** 2
    )
    return 2 * 6_371_008.8 * math.asin(math.sqrt(h))


def validate_request(
    waypoints: list[LngLat], profile: str, alternatives: int, max_waypoints: int
) -> None:
    """Reject requests that cannot succeed, before any provider quota is spent."""
    if profile not in ALLOWED_PROFILES:
        raise RoutingInvalidRequest(f"profile must be one of {', '.join(ALLOWED_PROFILES)}")
    if not MIN_WAYPOINTS <= len(waypoints) <= max_waypoints:
        raise RoutingInvalidRequest(
            f"a route needs between {MIN_WAYPOINTS} and {max_waypoints} waypoints"
        )
    if not 0 <= alternatives <= ALTERNATIVES_MAX_COUNT:
        raise RoutingInvalidRequest(f"alternatives must be 0 to {ALTERNATIVES_MAX_COUNT}")
    for lng, lat in waypoints:
        if not (
            math.isfinite(lng) and math.isfinite(lat) and -180 <= lng <= 180 and -90 <= lat <= 90
        ):
            raise RoutingInvalidRequest("waypoint coordinates are out of range")
    for previous, current in zip(waypoints, waypoints[1:], strict=False):
        if haversine_m(previous, current) < 1:
            raise RoutingInvalidRequest("consecutive waypoints must be different places")


def alternatives_allowed(waypoints: list[LngLat]) -> bool:
    """Providers only compute alternatives for a single short leg."""
    return (
        len(waypoints) == 2
        and haversine_m(waypoints[0], waypoints[1]) <= ALTERNATIVES_MAX_DISTANCE_M
    )
