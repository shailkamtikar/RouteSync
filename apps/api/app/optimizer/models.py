"""Data the optimizer works with. Plain dataclasses, no database or HTTP types."""

from dataclasses import dataclass, field

LngLat = tuple[float, float]


@dataclass(frozen=True)
class Tolerances:
    """All distances in metres. These are configuration, not product rules."""

    # A route must pass this close to an active stop to count as serving it.
    stop_m: float = 1000.0
    # The route calculation starts from a road point this close to the bus.
    position_m: float = 2000.0
    # The route must end this close to the destination.
    destination_m: float = 1000.0
    # Half-width of the approved corridor around the selected route option.
    corridor_m: float = 5000.0


@dataclass(frozen=True)
class ActiveStop:
    """An operator-confirmed stop that is still to be served."""

    stop_id: str
    name: str
    lng: float
    lat: float
    dwell_minutes: int = 5

    @property
    def point(self) -> LngLat:
        return (self.lng, self.lat)


@dataclass(frozen=True)
class CorridorVariant:
    """An approved alternative road between two waypoints, expressed as extra via-points.

    `insert_before` is the index in the waypoint list (position, remaining stops in order,
    destination) before which the detour points are inserted. 1 means between the bus position
    and the first remaining stop.
    """

    name: str
    detour_points: tuple[LngLat, ...]
    insert_before: int = 1


@dataclass(frozen=True)
class JourneyState:
    position: LngLat
    remaining_stops: tuple[ActiveStop, ...]
    destination: LngLat
    destination_name: str
    # Centreline of the selected route option. The corridor is this line widened by
    # `Tolerances.corridor_m`; no plan may leave it.
    corridor_centreline: tuple[LngLat, ...]
    current_route: tuple[LngLat, ...]
    current_route_distance_m: float
    current_route_duration_s: float
    variants: tuple[CorridorVariant, ...] = ()
    profile: str = "driving-car"

    def waypoints(self) -> list[LngLat]:
        return [self.position, *(stop.point for stop in self.remaining_stops), self.destination]


@dataclass(frozen=True)
class Candidate:
    """One whole-journey way of completing the remaining trip."""

    name: str
    source: str  # current_route | current_route_resolved | variant | provider_alternative
    coordinates: tuple[LngLat, ...]
    distance_m: float
    duration_s: float
    # Extra waypoints the route was forced through, beyond the active stops.
    extra_waypoints: tuple[LngLat, ...] = ()
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class Violation:
    code: str
    message: str
    details: dict = field(default_factory=dict)


@dataclass(frozen=True)
class CandidateSet:
    candidates: tuple[Candidate, ...]
    degraded: bool = False
    notes: tuple[str, ...] = ()
