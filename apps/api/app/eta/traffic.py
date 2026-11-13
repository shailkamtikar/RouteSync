"""Turns traffic incidents into slowdowns along one journey's route. Pure functions.

An incident is stored as two points on the road. Each journey projects them onto its own
route, so the same incident affects every journey that still has that stretch ahead, and
none that does not use it.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from app.eta.engine import TrafficSegment
from app.optimizer import geo

LngLat = tuple[float, float]


@dataclass(frozen=True)
class Incident:
    incident_id: str
    kind: str  # slow | closure
    multiplier: float
    from_point: LngLat
    to_point: LngLat
    starts_at: datetime
    ends_at: datetime | None
    simulated: bool = True
    description: str | None = None

    def active_at(self, now: datetime) -> bool:
        return self.starts_at <= now and (self.ends_at is None or now < self.ends_at)


@dataclass(frozen=True)
class RouteTraffic:
    segments: tuple[TrafficSegment, ...]
    # (from_m, to_m) of closures on this route, in route chainage.
    closures: tuple[tuple[float, float], ...]
    incident_ids: tuple[str, ...]


def traffic_on_route(
    route: Sequence[LngLat],
    incidents: Sequence[Incident],
    now: datetime,
    *,
    max_offset_m: float = 2000.0,
) -> RouteTraffic:
    """Slowdowns and closures that lie on this route and are active now."""
    line = list(route)
    segments: list[TrafficSegment] = []
    closures: list[tuple[float, float]] = []
    used: list[str] = []
    for incident in incidents:
        if not incident.active_at(now):
            continue
        # An incident on a road this route does not use is ignored.
        if any(
            geo.distance_to_line_m(line, p) > max_offset_m
            for p in (incident.from_point, incident.to_point)
        ):
            continue
        start, end = sorted(
            (geo.chainage_m(line, incident.from_point), geo.chainage_m(line, incident.to_point))
        )
        if end - start < 1.0:
            continue
        used.append(incident.incident_id)
        if incident.kind == "closure":
            closures.append((start, end))
        else:
            segments.append(TrafficSegment(start, end, incident.multiplier, incident.simulated))
    return RouteTraffic(tuple(segments), tuple(closures), tuple(used))
