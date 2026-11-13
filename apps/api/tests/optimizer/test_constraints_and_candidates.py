import pytest

from app.optimizer import geo
from app.optimizer.candidates import generate_candidates, remaining_current_route
from app.optimizer.constraints import check_hard_constraints, is_feasible
from app.optimizer.models import ActiveStop, Candidate, CorridorVariant, Tolerances
from app.providers.routing.base import RoutingQuotaExceeded, RoutingUnavailable
from app.providers.routing.fake import FakeRoutingProvider

from .fixtures import (
    AHMEDNAGAR,
    BEED,
    LATUR,
    NANDED,
    PARBHANI,
    PUNE,
    STOP_BEED,
    STOP_PARBHANI,
    candidate_through,
    make_state,
)


def codes(candidate, state, tol=None):
    return [v.code for v in check_hard_constraints(candidate, state, tol)]


# ------------------------------------------------------------------ geometry


def test_chainage_and_distance_to_line():
    line = [(73.0, 18.0), (74.0, 18.0)]
    assert geo.chainage_m(line, (73.5, 18.0)) == pytest.approx(
        geo.line_length_m(line) / 2, rel=0.01
    )
    assert geo.distance_to_line_m(line, (73.5, 18.1)) == pytest.approx(11_100, rel=0.02)
    assert geo.distance_m((73.0, 18.0), (73.0, 18.1)) == pytest.approx(11_100, rel=0.02)


def test_slice_from_a_point_keeps_only_what_is_ahead():
    route = candidate_through([PUNE, AHMEDNAGAR, BEED, NANDED]).coordinates
    ahead = geo.slice_from(list(route), AHMEDNAGAR)
    assert geo.distance_m(ahead[0], AHMEDNAGAR) < 100
    assert ahead[-1] == route[-1]
    assert geo.line_length_m(ahead) < geo.line_length_m(list(route))
    assert geo.chainage_m(ahead, BEED) > 0


# ------------------------------------------------------------------ hard constraints


def test_route_through_all_stops_in_order_is_feasible():
    state = make_state()
    good = candidate_through([AHMEDNAGAR, BEED, PARBHANI, NANDED])
    assert check_hard_constraints(good, state) == []
    assert is_feasible(good, state)


@pytest.mark.parametrize(
    ("skipped", "expected"),
    [("Beed", [AHMEDNAGAR, PARBHANI, NANDED]), ("Parbhani", [AHMEDNAGAR, BEED, NANDED])],
)
def test_skipping_an_active_stop_is_never_feasible(skipped, expected):
    bad = candidate_through(expected)
    found = check_hard_constraints(bad, make_state())
    missed = [v for v in found if v.code == "STOP_MISSED"]
    assert [v.details["stop"] for v in missed] == [skipped]
    assert missed[0].details["distance_m"] > 10_000


def test_stops_reached_in_the_wrong_order_are_rejected():
    backwards = candidate_through([AHMEDNAGAR, PARBHANI, BEED, NANDED])
    assert "STOP_ORDER" in codes(backwards, make_state())


def test_leaving_the_corridor_is_rejected():
    far_south = (76.0, 18.5)  # roughly 55 km below the northern road
    detour = candidate_through(
        [AHMEDNAGAR, BEED, far_south, PARBHANI, NANDED], extra_waypoints=(far_south,)
    )
    state = make_state(variants=(CorridorVariant("South loop", (far_south,), insert_before=2),))
    found = codes(detour, state)
    assert "OUTSIDE_CORRIDOR" in found


def test_unapproved_extra_waypoint_is_rejected():
    near_road = (76.2675, 19.145)
    candidate = candidate_through(
        [AHMEDNAGAR, BEED, near_road, PARBHANI, NANDED], extra_waypoints=(near_road,)
    )
    assert "UNAPPROVED_STOP" in codes(candidate, make_state())  # no variant approves it


def test_approved_detour_inside_the_corridor_is_feasible():
    near_road = (76.2675, 19.145)  # about 2 km off the straight road
    variant = CorridorVariant("Via Majalgaon bypass", (near_road,), insert_before=2)
    state = make_state(variants=(variant,))
    candidate = candidate_through(
        [AHMEDNAGAR, BEED, near_road, PARBHANI, NANDED], extra_waypoints=(near_road,)
    )
    assert check_hard_constraints(candidate, state) == []


def test_truncated_route_does_not_reach_the_destination():
    truncated = candidate_through([AHMEDNAGAR, BEED, PARBHANI])
    assert "DESTINATION_NOT_REACHED" in codes(truncated, make_state())


def test_destination_reached_before_the_last_stop_is_rejected():
    # The journey must end at Beed, but the route goes on to Parbhani and doubles back:
    # it reaches the destination first, then serves a stop after it.
    state = make_state(stops=(STOP_PARBHANI,), destination=BEED)
    doubling_back = candidate_through([AHMEDNAGAR, BEED, PARBHANI, BEED])
    found = check_hard_constraints(doubling_back, state)
    assert [v.code for v in found] == ["DESTINATION_NOT_LAST"]


def test_route_must_start_at_the_bus():
    from_pune = candidate_through([PUNE, AHMEDNAGAR, BEED, PARBHANI, NANDED])
    assert "NOT_FROM_POSITION" in codes(from_pune, make_state())


def test_empty_route_is_rejected():
    empty = Candidate("x", "variant", (), 0, 0)
    assert [v.code for v in check_hard_constraints(empty, make_state())] == ["EMPTY_ROUTE"]


def test_tolerances_are_configuration():
    state = make_state()
    near_beed = (BEED[0], BEED[1] + 0.0072)  # the road passes about 800 m from Beed
    candidate = candidate_through([AHMEDNAGAR, near_beed, PARBHANI, NANDED])
    assert check_hard_constraints(candidate, state) == []  # default tolerance is 1 km
    assert "STOP_MISSED" in codes(candidate, state, Tolerances(stop_m=500))
    assert "OUTSIDE_CORRIDOR" in codes(candidate, state, Tolerances(corridor_m=100))


def test_shortcut_between_stops_is_outside_the_corridor():
    # Beed straight to Nanded skips the Parbhani stretch of the approved road by ~19 km.
    state = make_state(stops=(STOP_BEED,))
    shortcut = candidate_through([AHMEDNAGAR, BEED, NANDED])
    found = codes(shortcut, state)
    assert found == ["OUTSIDE_CORRIDOR"]


# ------------------------------------------------------------------ candidate generation


def test_current_route_remaining_is_a_feasible_candidate_without_provider_calls():
    state = make_state()
    candidate = remaining_current_route(state)
    assert candidate.source == "current_route"
    assert is_feasible(candidate, state)
    assert 0 < candidate.distance_m < state.current_route_distance_m
    assert 0 < candidate.duration_s < state.current_route_duration_s


def test_generation_covers_the_whole_remaining_journey():
    provider = FakeRoutingProvider()
    result = generate_candidates(provider, make_state())
    assert not result.degraded
    names = [c.name for c in result.candidates]
    assert names[0] == "Current route" and "Re-routed from here" in names
    # The provider was asked for position -> every remaining stop in order -> destination.
    assert provider.calls[0]["waypoints"] == [AHMEDNAGAR, BEED, PARBHANI, NANDED]
    assert all(is_feasible(c, make_state()) for c in result.candidates)


def test_long_remaining_journey_never_asks_for_provider_alternatives():
    provider = FakeRoutingProvider()
    generate_candidates(provider, make_state())
    assert all(call["alternatives"] == 0 for call in provider.calls)


def test_short_remaining_leg_asks_for_alternatives():
    near_end = (77.20, 19.12)
    state = make_state(position=near_end, stops=())
    provider = FakeRoutingProvider()
    result = generate_candidates(provider, state)
    assert provider.calls[0]["alternatives"] == 2
    sources = [c.source for c in result.candidates]
    assert "provider_alternative" in sources


def test_variants_are_routed_through_their_detour_points():
    near_road = (76.2675, 19.145)
    variant = CorridorVariant("Bypass", (near_road,), insert_before=2)
    provider = FakeRoutingProvider()
    result = generate_candidates(provider, make_state(variants=(variant,)))
    assert provider.calls[1]["waypoints"] == [AHMEDNAGAR, BEED, near_road, PARBHANI, NANDED]
    bypass = next(c for c in result.candidates if c.name == "Bypass")
    assert bypass.source == "variant" and bypass.extra_waypoints == (near_road,)


def test_infeasible_variant_is_filtered_out_and_reported():
    south = (76.0, 18.4)
    state = make_state(variants=(CorridorVariant("Via Latur road", (south,), insert_before=2),))
    result = generate_candidates(FakeRoutingProvider(), state)
    assert "Via Latur road" not in [c.name for c in result.candidates]
    assert any(note.startswith("rejected_infeasible") for note in result.notes)
    assert result.candidates  # the safe candidates are still offered


@pytest.mark.parametrize("error", [RoutingUnavailable("down"), RoutingQuotaExceeded("quota")])
def test_provider_failure_degrades_to_the_current_route(error):
    provider = FakeRoutingProvider()
    provider.fail_with = error
    result = generate_candidates(provider, make_state())
    assert result.degraded is True
    assert [c.source for c in result.candidates] == ["current_route"]
    assert any("routing_unavailable" in note for note in result.notes)


def test_infeasible_current_route_is_noted():
    stray = ActiveStop("latur", "Latur", *LATUR)
    state = make_state(stops=(STOP_BEED, stray, STOP_PARBHANI))
    result = generate_candidates(FakeRoutingProvider(), state)
    assert "current_route_infeasible" in result.notes
    assert "Current route" not in [c.name for c in result.candidates]


def test_two_journeys_on_the_same_corridor_are_independent():
    first = generate_candidates(FakeRoutingProvider(), make_state(position=AHMEDNAGAR))
    second = generate_candidates(
        FakeRoutingProvider(), make_state(position=BEED, stops=(STOP_PARBHANI,))
    )
    assert first.candidates[0].distance_m > second.candidates[0].distance_m
    assert first.candidates[0].coordinates != second.candidates[0].coordinates
