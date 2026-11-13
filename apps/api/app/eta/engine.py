"""ETA engine: one coherent prediction for a journey, as a single snapshot.

Pure functions. Every ETA shown anywhere (operator monitor, public page, assistant) must come
from a snapshot built here; nothing else computes arrival times.

Progress is the position of the bus projected onto the assigned route, never a straight line.
Time along the route follows the provider's total duration for the whole route, scaled by
distance, multiplied by any traffic slowdown, plus the waiting time at each active stop.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from app.optimizer import geo

LngLat = tuple[float, float]
SCHEMA_VERSION = 1


@dataclass(frozen=True)
class EtaConfig:
    stale_after_s: float = 120.0  # a position older than this is shown as not live
    off_route_m: float = 1000.0  # farther than this from the route counts as off route


@dataclass(frozen=True)
class EtaStop:
    stop_id: str
    name: str
    lng: float
    lat: float
    dwell_minutes: int = 5
    status: str = "pending"  # pending | arrived | departed
    arrived_at: datetime | None = None


@dataclass(frozen=True)
class TrafficSegment:
    """A slowdown over part of the route, in metres of route chainage."""

    from_m: float
    to_m: float
    multiplier: float  # 1.0 = free flow; 2.0 = takes twice as long
    simulated: bool = True

    def __post_init__(self) -> None:
        if not 1.0 <= self.multiplier <= 20.0:
            raise ValueError("multiplier must be between 1 and 20")
        if self.to_m < self.from_m:
            raise ValueError("segment end must not be before its start")


@dataclass(frozen=True)
class EtaInput:
    now: datetime
    route: tuple[LngLat, ...]
    route_distance_m: float
    route_duration_s: float
    stops: tuple[EtaStop, ...]
    destination_name: str
    destination: LngLat
    planned_departure: datetime
    position: LngLat | None = None
    position_at: datetime | None = None
    traffic: tuple[TrafficSegment, ...] = ()
    # Closed stretches of this route, as (from_m, to_m) in route chainage.
    closures: tuple[tuple[float, float], ...] = ()
    route_version_id: str | None = None
    config: EtaConfig = field(default_factory=EtaConfig)

    def __post_init__(self) -> None:
        for name in ("now", "planned_departure", "position_at"):
            value = getattr(self, name)
            if value is not None and value.tzinfo is None:
                raise ValueError(f"{name} must be timezone-aware")
        if len(self.route) < 2 or self.route_duration_s <= 0 or self.route_distance_m <= 0:
            raise ValueError("the route needs geometry, a distance and a duration")


@dataclass(frozen=True)
class StopEta:
    stop_id: str | None
    name: str
    status: str  # completed | current | next | upcoming
    eta: datetime | None  # arrival; None once completed
    departure_eta: datetime | None
    remaining_m: float
    is_destination: bool = False


@dataclass(frozen=True)
class EtaSnapshot:
    computed_at: datetime
    route_version_id: str | None
    next_stop: StopEta
    destination: StopEta
    stops: tuple[StopEta, ...]
    remaining_distance_m: float
    travelled_distance_m: float
    progress_pct: float
    gps_age_s: float | None
    flags: dict[str, bool]
    warnings: tuple[dict[str, str], ...]

    def to_payload(self) -> dict[str, Any]:
        def stop(item: StopEta) -> dict[str, Any]:
            return {
                "stop_id": item.stop_id,
                "name": item.name,
                "status": item.status,
                "eta": item.eta.isoformat() if item.eta else None,
                "departure_eta": item.departure_eta.isoformat() if item.departure_eta else None,
                "remaining_m": round(item.remaining_m),
                "is_destination": item.is_destination,
            }

        return {
            "schema_version": SCHEMA_VERSION,
            "computed_at": self.computed_at.isoformat(),
            "route_version_id": self.route_version_id,
            "next_stop": stop(self.next_stop),
            "destination": stop(self.destination),
            "stops": [stop(item) for item in self.stops],
            "remaining_distance_m": round(self.remaining_distance_m),
            "travelled_distance_m": round(self.travelled_distance_m),
            "progress_pct": round(self.progress_pct, 1),
            "gps_age_s": None if self.gps_age_s is None else round(self.gps_age_s),
            "flags": dict(self.flags),
            "warnings": list(self.warnings),
        }


def _travel_s(
    start_m: float, end_m: float, speed_mps: float, traffic: Sequence[TrafficSegment]
) -> float:
    """Seconds to drive from one chainage to another, honouring traffic slowdowns."""
    if end_m <= start_m:
        return 0.0
    cuts = {start_m, end_m}
    for segment in traffic:
        for edge in (segment.from_m, segment.to_m):
            if start_m < edge < end_m:
                cuts.add(edge)
    points = sorted(cuts)
    total = 0.0
    for left, right in zip(points, points[1:], strict=False):
        middle = (left + right) / 2
        multiplier = max(
            (s.multiplier for s in traffic if s.from_m <= middle <= s.to_m), default=1.0
        )
        total += (right - left) / speed_mps * multiplier
    return total


def compute_snapshot(data: EtaInput) -> EtaSnapshot:
    route = list(data.route)
    length_m = geo.line_length_m(route)
    # Chainage is in geometry metres; reported distances use the provider's road distance.
    scale = data.route_distance_m / length_m if length_m > 0 else 1.0
    speed = length_m / data.route_duration_s  # geometry metres per second at free flow

    warnings: list[dict[str, str]] = []
    flags = {
        "stale": False,
        "off_route": False,
        "plan_based": data.position is None,
        "next_is_destination": False,
        "traffic_simulated": any(segment.simulated for segment in data.traffic),
    }

    # ---- where is the bus along the route, and when does the clock start
    gps_age: float | None = None
    if data.position is None:
        position_m = 0.0
        clock = max(data.now, data.planned_departure)
    else:
        position_m = geo.chainage_m(route, data.position)
        clock = data.now
        if geo.distance_to_line_m(route, data.position) > data.config.off_route_m:
            flags["off_route"] = True
            warnings.append(
                {"code": "OFF_ROUTE", "message": "The bus is away from the assigned route."}
            )
        if data.position_at is not None:
            gps_age = max((data.now - data.position_at).total_seconds(), 0.0)
            if gps_age > data.config.stale_after_s:
                flags["stale"] = True
                warnings.append(
                    {"code": "GPS_STALE", "message": "The last known position is not recent."}
                )

    # ---- traffic still ahead of the bus
    simulated = flags["traffic_simulated"] or bool(data.closures)
    flags["traffic_ahead"] = any(segment.to_m > position_m for segment in data.traffic)
    flags["closure_ahead"] = any(end > position_m for _, end in data.closures)
    if flags["traffic_ahead"]:
        message = (
            "Simulated slow traffic ahead on the route."
            if simulated
            else "Slow traffic ahead on the route."
        )
        warnings.append({"code": "TRAFFIC_AHEAD", "message": message})
    if flags["closure_ahead"]:
        prefix = "Simulated road closure" if simulated else "Road closure"
        warnings.append(
            {
                "code": "ROAD_CLOSED_AHEAD",
                "message": f"{prefix} ahead. Arrival times are uncertain.",
            }
        )

    # ---- walk the stops in order
    chainages = []
    running = 0.0
    for stop in data.stops:
        running = max(running, geo.chainage_m(route, (stop.lng, stop.lat)))
        chainages.append(running)
    destination_m = max(length_m, running)

    results: list[StopEta] = []
    cursor_m = position_m
    first_open_found = False
    for stop, stop_m in zip(data.stops, chainages, strict=True):
        if stop.status == "departed":
            results.append(StopEta(stop.stop_id, stop.name, "completed", None, None, 0.0))
            continue
        passed = stop_m < position_m - 1.0
        if passed and stop.status == "pending" and data.position is not None:
            warnings.append(
                {
                    "code": "STOP_PASSED_WITHOUT_EVENT",
                    "message": f"The bus is past {stop.name} but no arrival was recorded.",
                }
            )
        clock += timedelta(seconds=_travel_s(cursor_m, stop_m, speed, data.traffic))
        cursor_m = max(cursor_m, stop_m)
        if stop.status == "arrived" and stop.arrived_at is not None:
            arrival = stop.arrived_at
            waited = max((data.now - stop.arrived_at).total_seconds(), 0.0)
            clock += timedelta(seconds=max(stop.dwell_minutes * 60 - waited, 0.0))
            status = "current"  # being served now; the following open stop is still "next"
        else:
            arrival = clock
            clock += timedelta(minutes=stop.dwell_minutes)
            status = "next" if not first_open_found else "upcoming"
            first_open_found = True
        results.append(
            StopEta(
                stop.stop_id,
                stop.name,
                status,
                arrival,
                clock,
                max(stop_m - position_m, 0.0) * scale,
            )
        )

    clock += timedelta(seconds=_travel_s(cursor_m, destination_m, speed, data.traffic))
    destination = StopEta(
        None,
        data.destination_name,
        "next" if not first_open_found else "upcoming",
        clock,
        None,
        max(destination_m - position_m, 0.0) * scale,
        is_destination=True,
    )

    open_stops = [item for item in results if item.status != "completed"]
    if open_stops:
        next_stop = open_stops[0]
    else:
        next_stop = destination
        flags["next_is_destination"] = True

    travelled = min(position_m, destination_m)
    return EtaSnapshot(
        computed_at=data.now,
        route_version_id=data.route_version_id,
        next_stop=next_stop,
        destination=destination,
        stops=tuple(results),
        remaining_distance_m=destination.remaining_m,
        travelled_distance_m=travelled * scale,
        progress_pct=100.0 * travelled / destination_m if destination_m > 0 else 100.0,
        gps_age_s=gps_age,
        flags=flags,
        warnings=tuple(warnings),
    )
