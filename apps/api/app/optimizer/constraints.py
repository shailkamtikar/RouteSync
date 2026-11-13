"""Hard constraints: a candidate that violates any of these is never eligible.

Pure functions. The optimizer never reorders, drops, or adds passenger stops; it only decides
which road to take between required stops.
"""

from app.optimizer import geo
from app.optimizer.models import Candidate, JourneyState, Tolerances, Violation

ORDER_SLACK_M = 50.0


def _violation(code: str, message: str, **details) -> Violation:
    return Violation(code, message, details)


def check_hard_constraints(
    candidate: Candidate, state: JourneyState, tolerances: Tolerances | None = None
) -> list[Violation]:
    """Return every hard-constraint violation. An empty list means the candidate is feasible."""
    tol = tolerances or Tolerances()
    line = list(candidate.coordinates)
    violations: list[Violation] = []

    if len(line) < 2:
        return [_violation("EMPTY_ROUTE", "The route has no geometry.")]

    # 1. Starts where the bus is.
    if geo.distance_m(line[0], state.position) > tol.position_m:
        violations.append(
            _violation("NOT_FROM_POSITION", "The route does not start at the bus's position.")
        )

    # 2. Every active stop is served: the road passes through it.
    chainages: list[tuple[str, float]] = []
    for stop in state.remaining_stops:
        gap = geo.distance_to_line_m(line, stop.point)
        if gap > tol.stop_m:
            violations.append(
                _violation(
                    "STOP_MISSED",
                    f"The route does not pass {stop.name} ({gap / 1000:.1f} km away).",
                    stop=stop.name,
                    distance_m=round(gap),
                )
            )
        chainages.append((stop.name, geo.chainage_m(line, stop.point)))

    # 3. Stops are reached in the planned order (pickup before drop-off follows from this,
    #    because the plan's stop order already puts every pickup before its drop-off).
    for (previous_name, previous), (name, current) in zip(chainages, chainages[1:], strict=False):
        if current + ORDER_SLACK_M < previous:
            violations.append(
                _violation(
                    "STOP_ORDER",
                    f"The route reaches {name} before {previous_name}.",
                    stop=name,
                    before=previous_name,
                )
            )

    # 4. Reaches the destination, after the last stop.
    if geo.distance_m(line[-1], state.destination) > tol.destination_m:
        violations.append(
            _violation(
                "DESTINATION_NOT_REACHED",
                f"The route does not end at {state.destination_name}.",
            )
        )
    elif chainages and geo.chainage_m(line, state.destination) + ORDER_SLACK_M < chainages[-1][1]:
        violations.append(
            _violation(
                "DESTINATION_NOT_LAST",
                f"The route reaches {state.destination_name} before the last stop.",
            )
        )

    # 5. Stays inside the approved corridor.
    if state.corridor_centreline:
        worst = geo.max_distance_from_line_m(line, list(state.corridor_centreline))
        if worst > tol.corridor_m:
            violations.append(
                _violation(
                    "OUTSIDE_CORRIDOR",
                    f"The route leaves the approved corridor by {(worst - tol.corridor_m) / 1000:.1f} km.",
                    max_distance_m=round(worst),
                )
            )

    # 6. No unapproved side trips: every extra waypoint must belong to an approved variant,
    #    and an extra waypoint must itself lie inside the corridor.
    approved = {point for variant in state.variants for point in variant.detour_points}
    for point in candidate.extra_waypoints:
        if point not in approved:
            violations.append(
                _violation("UNAPPROVED_STOP", "The route is forced through an unapproved place.")
            )
        elif state.corridor_centreline and (
            geo.distance_to_line_m(list(state.corridor_centreline), point) > tol.corridor_m
        ):
            violations.append(
                _violation(
                    "OUTSIDE_CORRIDOR", "An approved detour point lies outside the corridor."
                )
            )

    return violations


def is_feasible(
    candidate: Candidate, state: JourneyState, tolerances: Tolerances | None = None
) -> bool:
    return not check_hard_constraints(candidate, state, tolerances)
