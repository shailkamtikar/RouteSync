"""Deterministic routing provider for tests and offline development. Uses no network."""

from app.providers.routing.base import (
    Leg,
    LngLat,
    RouteResult,
    RoutingError,
    alternatives_allowed,
    haversine_m,
    validate_request,
)

ROAD_FACTOR = 1.25  # roads are longer than straight lines
SPEED_MPS = 60 / 3.6
STEP_M = 5_000


class FakeRoutingProvider:
    name = "fake"
    max_waypoints = 50

    def __init__(self) -> None:
        self.calls: list[dict] = []
        self.fail_with: RoutingError | None = None

    def route(
        self, waypoints: list[LngLat], *, profile: str = "driving-car", alternatives: int = 0
    ) -> list[RouteResult]:
        validate_request(waypoints, profile, alternatives, self.max_waypoints)
        self.calls.append(
            {"waypoints": list(waypoints), "profile": profile, "alternatives": alternatives}
        )
        if self.fail_with is not None:
            raise self.fail_with
        warnings = []
        count = 1
        if alternatives:
            if alternatives_allowed(waypoints):
                count += alternatives
            else:
                warnings.append("alternatives_unavailable")
        return [self._build(waypoints, bend=index, warnings=warnings) for index in range(count)]

    def _build(self, waypoints: list[LngLat], bend: int, warnings: list[str]) -> RouteResult:
        coordinates: list[LngLat] = [waypoints[0]]
        legs: list[Leg] = []
        indices = [0]
        for start, end in zip(waypoints, waypoints[1:], strict=False):
            straight = haversine_m(start, end)
            steps = max(1, int(straight // STEP_M))
            for step in range(1, steps + 1):
                t = step / steps
                # Alternatives bow sideways so their geometry differs from the main route.
                bow = bend * 0.02 * (1 - abs(2 * t - 1))
                coordinates.append(
                    (
                        round(start[0] + (end[0] - start[0]) * t, 6),
                        round(start[1] + (end[1] - start[1]) * t + bow, 6),
                    )
                )
            indices.append(len(coordinates) - 1)
            distance = straight * ROAD_FACTOR * (1 + 0.1 * bend)
            legs.append(Leg(distance_m=distance, duration_s=distance / SPEED_MPS))
        return RouteResult(
            coordinates=coordinates,
            distance_m=sum(leg.distance_m for leg in legs),
            duration_s=sum(leg.duration_s for leg in legs),
            legs=legs,
            provider=self.name,
            metadata={"attribution": "simulated route"},
            warnings=list(warnings),
            waypoint_indices=indices,
        )
