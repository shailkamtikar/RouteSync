"""Candidate generation: ways to finish the whole remaining journey.

Every candidate covers the complete remaining sequence (position -> all remaining stops in
order -> destination), never only the next leg. Routing is requested for the remaining
journey only, which keeps provider usage small.
"""

import logging

from app.optimizer import geo
from app.optimizer.constraints import is_feasible
from app.optimizer.models import (
    Candidate,
    CandidateSet,
    CorridorVariant,
    JourneyState,
    LngLat,
    Tolerances,
)
from app.providers.routing.base import (
    RoutingError,
    RoutingProvider,
    alternatives_allowed,
)

logger = logging.getLogger(__name__)


def remaining_current_route(state: JourneyState) -> Candidate:
    """The route already assigned, from the bus's position onward. Needs no provider call."""
    coordinates = geo.slice_from(list(state.current_route), state.position)
    total = geo.line_length_m(list(state.current_route)) or 1.0
    length = geo.line_length_m(coordinates)
    share = min(1.0, length / total)
    return Candidate(
        name="Current route",
        source="current_route",
        coordinates=tuple(coordinates),
        # Distance and time scale with the share of the route left: an estimate, not a new
        # provider answer. Real traffic is applied later by the ETA engine.
        distance_m=state.current_route_distance_m * share,
        duration_s=state.current_route_duration_s * share,
    )


def _with_detour(waypoints: list[LngLat], variant: CorridorVariant) -> list[LngLat]:
    index = max(1, min(variant.insert_before, len(waypoints) - 1))
    return [*waypoints[:index], *variant.detour_points, *waypoints[index:]]


def _from_result(name: str, source: str, result, extra: tuple[LngLat, ...] = ()) -> Candidate:
    return Candidate(
        name=name,
        source=source,
        coordinates=tuple(result.coordinates),
        distance_m=result.distance_m,
        duration_s=result.duration_s,
        extra_waypoints=extra,
        warnings=tuple(result.warnings),
    )


def generate_candidates(
    provider: RoutingProvider,
    state: JourneyState,
    tolerances: Tolerances | None = None,
    *,
    request_alternatives: bool = True,
) -> CandidateSet:
    """Build the candidate set. Only feasible candidates are returned; the current route is
    always kept when it is feasible, and a provider failure degrades to it alone."""
    tol = tolerances or Tolerances()
    waypoints = state.waypoints()
    found: list[Candidate] = []
    notes: list[str] = []
    degraded = False

    current = remaining_current_route(state)
    if is_feasible(current, state, tol):
        found.append(current)
    else:
        notes.append("current_route_infeasible")

    try:
        wanted = 2 if request_alternatives and alternatives_allowed(waypoints) else 0
        results = provider.route(waypoints, profile=state.profile, alternatives=wanted)
        found.append(_from_result("Re-routed from here", "current_route_resolved", results[0]))
        for index, result in enumerate(results[1:], start=1):
            found.append(_from_result(f"Alternative {index}", "provider_alternative", result))
        for variant in state.variants:
            via = _with_detour(waypoints, variant)
            found.append(
                _from_result(
                    variant.name,
                    "variant",
                    provider.route(via, profile=state.profile)[0],
                    extra=tuple(variant.detour_points),
                )
            )
    except RoutingError as exc:
        degraded = True
        notes.append(f"routing_unavailable: {type(exc).__name__}")
        logger.warning("candidate generation degraded: %s", type(exc).__name__)

    feasible = [c for c in found if is_feasible(c, state, tol)]
    if len(feasible) < len(found):
        notes.append(f"rejected_infeasible: {len(found) - len(feasible)}")
    return CandidateSet(tuple(feasible), degraded=degraded, notes=tuple(notes))
