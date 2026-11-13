"""Onboard passenger count. Pure functions.

A verified count needs recorded boarding and alighting events. Without them only the planned
figure can be given, and it is labelled as planned.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class CountEvent:
    type: str  # boarded | alighted (other types are ignored)
    count: int
    occurred_at: datetime


@dataclass(frozen=True)
class PlannedStop:
    pickup_count: int
    drop_count: int
    departed: bool


def recorded_onboard(events: Iterable[CountEvent]) -> tuple[int, int, int]:
    """(boarded, alighted, onboard) from recorded events, in time order."""
    boarded = alighted = 0
    for event in sorted(events, key=lambda e: e.occurred_at):
        if event.type == "boarded":
            boarded += event.count
        elif event.type == "alighted":
            alighted += event.count
    return boarded, alighted, max(boarded - alighted, 0)


def onboard_summary(events: Iterable[CountEvent], planned: Iterable[PlannedStop]) -> dict:
    events = list(events)
    boarded, alighted, onboard = recorded_onboard(events)
    planned_onboard = sum(stop.pickup_count - stop.drop_count for stop in planned if stop.departed)
    has_counts = any(event.type in ("boarded", "alighted") for event in events)
    return {
        "method": "recorded_events" if has_counts else "planned_only",
        "onboard": onboard if has_counts else None,
        "boarded": boarded,
        "alighted": alighted,
        # What the confirmed plan implies after the stops departed so far. Not a verified count.
        "planned_onboard": max(planned_onboard, 0),
    }
