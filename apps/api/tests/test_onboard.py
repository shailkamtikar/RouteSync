from datetime import UTC, datetime, timedelta

from app.domain.onboard import CountEvent, PlannedStop, onboard_summary, recorded_onboard

T = datetime(2031, 3, 1, 12, 0, tzinfo=UTC)


def ev(kind, count, minutes=0):
    return CountEvent(kind, count, T + timedelta(minutes=minutes))


def test_boarded_minus_alighted():
    assert recorded_onboard([ev("boarded", 10), ev("alighted", 3, 30)]) == (10, 3, 7)


def test_order_of_arrival_does_not_matter():
    events = [ev("alighted", 3, 30), ev("boarded", 10, 0), ev("boarded", 2, 31)]
    assert recorded_onboard(events) == (12, 3, 9)
    assert recorded_onboard(list(reversed(events))) == (12, 3, 9)


def test_arrival_and_departure_events_are_ignored_for_counting():
    events = [ev("arrived", 0), ev("boarded", 4, 1), ev("departed", 0, 2)]
    assert recorded_onboard(events) == (4, 0, 4)


def test_never_negative():
    assert recorded_onboard([ev("alighted", 5)]) == (0, 5, 0)


def test_summary_with_recorded_counts_is_verified():
    planned = [PlannedStop(5, 0, True), PlannedStop(2, 3, False)]
    summary = onboard_summary([ev("boarded", 5), ev("alighted", 1, 10)], planned)
    assert summary == {
        "method": "recorded_events",
        "onboard": 4,
        "boarded": 5,
        "alighted": 1,
        "planned_onboard": 5,
    }


def test_summary_without_count_events_is_planned_only():
    planned = [PlannedStop(5, 0, True), PlannedStop(2, 3, True), PlannedStop(0, 4, False)]
    summary = onboard_summary([ev("arrived", 0), ev("departed", 0, 5)], planned)
    assert summary["method"] == "planned_only"
    assert summary["onboard"] is None  # no verified figure is invented
    assert summary["planned_onboard"] == 4


def test_empty_journey():
    assert onboard_summary([], []) == {
        "method": "planned_only",
        "onboard": None,
        "boarded": 0,
        "alighted": 0,
        "planned_onboard": 0,
    }
