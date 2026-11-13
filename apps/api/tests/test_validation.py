from dataclasses import replace

from hypothesis import given, settings
from hypothesis import strategies as st

from app.domain.validation import Plan, PlanBooking, PlanStop, has_errors, validate_plan

PUNE = PlanStop("pune", "Pune", 1, pickup_count=5, drop_count=0)
BEED = PlanStop("beed", "Beed", 2, pickup_count=2, drop_count=3)
NANDED = PlanStop("nanded", "Nanded", 3, pickup_count=0, drop_count=4)

B1 = PlanBooking("B1", 3, "Pune", "Beed", "pune", "beed")
B2 = PlanBooking("B2", 2, "Pune", "Nanded", "pune", "nanded")
B3 = PlanBooking("B3", 2, "Beed", "Nanded", "beed", "nanded")

VALID = Plan(capacity=40, has_route=True, stops=[PUNE, BEED, NANDED], bookings=[B1, B2, B3])


def codes(plan):
    return [issue.code for issue in validate_plan(plan)]


def test_consistent_plan_has_no_issues():
    assert validate_plan(VALID) == []
    assert not has_errors(validate_plan(VALID))


def test_missing_route():
    assert "NO_ROUTE_SELECTED" in codes(replace(VALID, has_route=False))


def test_booking_pickup_stop_not_active():
    plan = replace(VALID, stops=[BEED, NANDED])
    found = codes(plan)
    assert found.count("BOOKING_PICKUP_NOT_ACTIVE") == 2
    assert has_errors(validate_plan(plan))


def test_booking_drop_stop_not_active():
    assert "BOOKING_DROP_NOT_ACTIVE" in codes(replace(VALID, stops=[PUNE, BEED]))


def test_booking_stop_name_matching_no_stop_on_route():
    latur = PlanBooking("B9", 1, "Pune", "Latur", "pune", None)
    issues = validate_plan(replace(VALID, bookings=[*VALID.bookings, latur]))
    unresolved = [i for i in issues if i.code == "BOOKING_STOP_UNRESOLVED"]
    assert len(unresolved) == 1
    assert unresolved[0].details == {"reference": "B9", "stop": "Latur"}
    assert "Latur" in unresolved[0].message


def test_drop_before_pickup():
    backwards = PlanBooking("B4", 1, "Nanded", "Beed", "nanded", "beed")
    assert "DROP_BEFORE_PICKUP" in codes(replace(VALID, bookings=[*VALID.bookings, backwards]))


def test_same_pickup_and_drop():
    same = PlanBooking("B5", 1, "Beed", "Beed", "beed", "beed")
    found = codes(replace(VALID, bookings=[*VALID.bookings, same]))
    assert "SAME_PICKUP_AND_DROP" in found and "DROP_BEFORE_PICKUP" not in found


def test_count_mismatch_reports_both_sides():
    plan = replace(VALID, stops=[replace(PUNE, pickup_count=6), BEED, NANDED])
    mismatch = [i for i in validate_plan(plan) if i.code == "COUNT_MISMATCH"]
    assert len(mismatch) == 1
    assert mismatch[0].details["confirmed_pickups"] == 6
    assert mismatch[0].details["booked_pickups"] == 5


def test_capacity_exceeded_at_the_stop_where_it_happens():
    plan = replace(VALID, capacity=5)
    over = [i for i in validate_plan(plan) if i.code == "CAPACITY_EXCEEDED"]
    assert over == []  # 5 on board after Pune, 4 after Beed
    tight = replace(VALID, capacity=4)
    over = [i for i in validate_plan(tight) if i.code == "CAPACITY_EXCEEDED"]
    assert [i.details["stop"] for i in over] == ["Pune"]
    assert over[0].details["onboard"] == 5


def test_seats_freed_at_a_stop_can_be_reused():
    stops = [
        PlanStop("a", "A", 1, 40, 0),
        PlanStop("b", "B", 2, 40, 40),
        PlanStop("c", "C", 3, 0, 40),
    ]
    bookings = [
        PlanBooking("X", 40, "A", "B", "a", "b"),
        PlanBooking("Y", 40, "B", "C", "b", "c"),
    ]
    assert validate_plan(Plan(40, True, stops, bookings)) == []


def test_more_alight_than_onboard():
    stops = [PlanStop("a", "A", 1, 0, 3), PlanStop("b", "B", 2, 3, 0)]
    assert "MORE_ALIGHT_THAN_ONBOARD" in codes(Plan(40, True, stops, []))


def test_no_bookings_is_only_a_warning():
    issues = validate_plan(Plan(40, True, [], []))
    assert [i.code for i in issues] == ["NO_BOOKINGS"]
    assert not has_errors(issues)


def test_plan_needs_review_blocks():
    issues = validate_plan(replace(VALID, plan_needs_review=True))
    assert [i.code for i in issues] == ["PLAN_NEEDS_REVIEW"]
    assert has_errors(issues)


def test_stop_without_activity_and_pass_through_and_off_route():
    extra = [
        PlanStop("idle", "Idle", 4, 0, 0),
        PlanStop("town", "Majalgaon", 5, 1, 0, kind="pass_through"),
        PlanStop("latur", "Latur", 6, 1, 0, on_route=False),
    ]
    found = codes(replace(VALID, stops=[*VALID.stops, *extra]))
    assert {"STOP_WITHOUT_ACTIVITY", "PASS_THROUGH_ACTIVE", "STOP_NOT_ON_ROUTE"} <= set(found)


def test_duplicate_sequence():
    plan = replace(VALID, stops=[PUNE, replace(BEED, sequence=1), NANDED])
    assert "DUPLICATE_SEQUENCE" in codes(plan)


def test_errors_come_before_warnings_and_order_is_stable():
    plan = Plan(40, False, [], [])
    issues = validate_plan(plan)
    assert [i.severity for i in issues] == ["error", "warning"]
    assert validate_plan(plan) == issues


stop_strategy = st.builds(
    PlanStop,
    stop_id=st.sampled_from(["a", "b", "c", "d"]),
    name=st.sampled_from(["A", "B", "C", "D"]),
    sequence=st.integers(-2, 6),
    pickup_count=st.integers(-3, 60),
    drop_count=st.integers(-3, 60),
    kind=st.sampled_from(["passenger_stop", "pass_through"]),
    on_route=st.booleans(),
)
booking_strategy = st.builds(
    PlanBooking,
    reference=st.text(min_size=1, max_size=5),
    passenger_count=st.integers(-2, 60),
    pickup_stop_name=st.sampled_from(["A", "B", "Z"]),
    drop_stop_name=st.sampled_from(["A", "B", "Z"]),
    pickup_stop_id=st.sampled_from(["a", "b", "c", "zz", None]),
    drop_stop_id=st.sampled_from(["a", "b", "c", "zz", None]),
)
plan_strategy = st.builds(
    Plan,
    capacity=st.integers(0, 60),
    has_route=st.booleans(),
    stops=st.lists(stop_strategy, max_size=6),
    bookings=st.lists(booking_strategy, max_size=8),
    plan_needs_review=st.booleans(),
)


@settings(max_examples=300, deadline=None)
@given(plan_strategy)
def test_validator_never_raises_and_is_deterministic(plan):
    first = validate_plan(plan)
    assert first == validate_plan(plan)
    assert all(issue.severity in ("error", "warning") and issue.message for issue in first)
    if not plan.has_route:
        assert has_errors(first)
