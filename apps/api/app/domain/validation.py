"""Journey plan validation.

Pure functions: no database, no HTTP. The plan is validated exactly as the operator
confirmed it; nothing here changes the plan.
"""

from collections import Counter
from dataclasses import dataclass, field
from typing import Literal

Severity = Literal["error", "warning"]


@dataclass(frozen=True)
class PlanStop:
    """An operator-confirmed active stop."""

    stop_id: str
    name: str
    sequence: int
    pickup_count: int
    drop_count: int
    kind: str = "passenger_stop"
    on_route: bool = True


@dataclass(frozen=True)
class PlanBooking:
    """A confirmed booking. Stop ids are None when the stop name matched no stop on the route."""

    reference: str
    passenger_count: int
    pickup_stop_name: str
    drop_stop_name: str
    pickup_stop_id: str | None
    drop_stop_id: str | None


@dataclass(frozen=True)
class Plan:
    capacity: int
    has_route: bool
    stops: list[PlanStop]
    bookings: list[PlanBooking]
    plan_needs_review: bool = False


@dataclass(frozen=True)
class Issue:
    code: str
    severity: Severity
    message: str
    details: dict = field(default_factory=dict)


def _error(code: str, message: str, **details) -> Issue:
    return Issue(code, "error", message, details)


def _warning(code: str, message: str, **details) -> Issue:
    return Issue(code, "warning", message, details)


def validate_plan(plan: Plan) -> list[Issue]:
    """Return every problem with the plan. Errors block assignment; warnings do not."""
    issues: list[Issue] = []

    if not plan.has_route:
        issues.append(_error("NO_ROUTE_SELECTED", "Choose a route option for this journey."))
    if plan.plan_needs_review:
        issues.append(
            _error(
                "PLAN_NEEDS_REVIEW",
                "Bookings changed after the stops were confirmed. Review and confirm the stops again.",
            )
        )
    if not plan.bookings:
        issues.append(_warning("NO_BOOKINGS", "This journey has no confirmed bookings."))

    by_id = {stop.stop_id: stop for stop in plan.stops}

    # ---- the stops themselves
    for sequence, count in sorted(Counter(stop.sequence for stop in plan.stops).items()):
        if count > 1:
            issues.append(
                _error(
                    "DUPLICATE_SEQUENCE",
                    f"{count} stops share position {sequence}.",
                    sequence=sequence,
                )
            )
    for stop in plan.stops:
        if not stop.on_route:
            issues.append(
                _error(
                    "STOP_NOT_ON_ROUTE",
                    f"{stop.name} is not a stop on the selected route option.",
                    stop=stop.name,
                )
            )
        if stop.kind != "passenger_stop":
            issues.append(
                _error(
                    "PASS_THROUGH_ACTIVE",
                    f"{stop.name} is marked as no passenger stop, so it cannot be an active stop.",
                    stop=stop.name,
                )
            )
        if stop.pickup_count < 0 or stop.drop_count < 0:
            issues.append(
                _error(
                    "NEGATIVE_COUNT", f"{stop.name} has a negative passenger count.", stop=stop.name
                )
            )
        elif stop.pickup_count + stop.drop_count == 0:
            issues.append(
                _error(
                    "STOP_WITHOUT_ACTIVITY",
                    f"No passenger boards or alights at {stop.name}, so it should not be active.",
                    stop=stop.name,
                )
            )

    # ---- each booking against the stops
    pickups: Counter[str] = Counter()
    drops: Counter[str] = Counter()
    for booking in plan.bookings:
        pickup = by_id.get(booking.pickup_stop_id) if booking.pickup_stop_id else None
        drop = by_id.get(booking.drop_stop_id) if booking.drop_stop_id else None

        if booking.pickup_stop_id is None:
            issues.append(
                _error(
                    "BOOKING_STOP_UNRESOLVED",
                    f"Booking {booking.reference}: pickup stop “{booking.pickup_stop_name}” "
                    "is not a stop on the selected route option.",
                    reference=booking.reference,
                    stop=booking.pickup_stop_name,
                )
            )
        elif pickup is None:
            issues.append(
                _error(
                    "BOOKING_PICKUP_NOT_ACTIVE",
                    f"Booking {booking.reference}: pickup stop {booking.pickup_stop_name} is not active.",
                    reference=booking.reference,
                    stop=booking.pickup_stop_name,
                )
            )
        else:
            pickups[pickup.stop_id] += booking.passenger_count

        if booking.drop_stop_id is None:
            issues.append(
                _error(
                    "BOOKING_STOP_UNRESOLVED",
                    f"Booking {booking.reference}: drop stop “{booking.drop_stop_name}” "
                    "is not a stop on the selected route option.",
                    reference=booking.reference,
                    stop=booking.drop_stop_name,
                )
            )
        elif drop is None:
            issues.append(
                _error(
                    "BOOKING_DROP_NOT_ACTIVE",
                    f"Booking {booking.reference}: drop stop {booking.drop_stop_name} is not active.",
                    reference=booking.reference,
                    stop=booking.drop_stop_name,
                )
            )
        else:
            drops[drop.stop_id] += booking.passenger_count

        if booking.pickup_stop_id is not None and booking.pickup_stop_id == booking.drop_stop_id:
            issues.append(
                _error(
                    "SAME_PICKUP_AND_DROP",
                    f"Booking {booking.reference} has the same pickup and drop stop.",
                    reference=booking.reference,
                )
            )
        elif pickup and drop and drop.sequence <= pickup.sequence:
            issues.append(
                _error(
                    "DROP_BEFORE_PICKUP",
                    f"Booking {booking.reference}: {drop.name} comes before {pickup.name} on this route.",
                    reference=booking.reference,
                )
            )

    # ---- confirmed counts against the bookings
    for stop in plan.stops:
        expected_pickups, expected_drops = pickups[stop.stop_id], drops[stop.stop_id]
        if (stop.pickup_count, stop.drop_count) != (expected_pickups, expected_drops):
            issues.append(
                _error(
                    "COUNT_MISMATCH",
                    f"{stop.name}: confirmed {stop.pickup_count} boarding and {stop.drop_count} "
                    f"alighting, but bookings show {expected_pickups} and {expected_drops}.",
                    stop=stop.name,
                    confirmed_pickups=stop.pickup_count,
                    confirmed_drops=stop.drop_count,
                    booked_pickups=expected_pickups,
                    booked_drops=expected_drops,
                )
            )

    # ---- seats, walking the stops in order (alighting happens before boarding at a stop)
    onboard = 0
    for stop in sorted(plan.stops, key=lambda s: (s.sequence, s.stop_id)):
        onboard -= max(stop.drop_count, 0)
        if onboard < 0:
            issues.append(
                _error(
                    "MORE_ALIGHT_THAN_ONBOARD",
                    f"More passengers alight at {stop.name} than are on board.",
                    stop=stop.name,
                )
            )
            onboard = 0
        onboard += max(stop.pickup_count, 0)
        if onboard > plan.capacity:
            issues.append(
                _error(
                    "CAPACITY_EXCEEDED",
                    f"After {stop.name} there would be {onboard} passengers on a bus "
                    f"with {plan.capacity} seats.",
                    stop=stop.name,
                    onboard=onboard,
                    capacity=plan.capacity,
                )
            )

    return sorted(issues, key=lambda issue: (issue.severity != "error", issue.code, issue.message))


def has_errors(issues: list[Issue]) -> bool:
    return any(issue.severity == "error" for issue in issues)
