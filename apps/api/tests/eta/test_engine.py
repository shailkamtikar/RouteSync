import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from app.eta.engine import (
    EtaConfig,
    EtaInput,
    EtaStop,
    TrafficSegment,
    compute_snapshot,
)
from app.optimizer import geo
from app.providers.routing.fake import FakeRoutingProvider

AHMEDNAGAR = (74.7496, 19.0948)
BEED = (75.7601, 18.9891)
PARBHANI = (76.7748, 19.2608)
PUNE = (73.8567, 18.5204)
NANDED = (77.321, 19.1383)

NOW = datetime(2031, 3, 1, 12, 0, tzinfo=UTC)
ROUTE = FakeRoutingProvider().route([PUNE, AHMEDNAGAR, BEED, PARBHANI, NANDED])[0]
LENGTH = geo.line_length_m(list(ROUTE.coordinates))
SPEED = LENGTH / ROUTE.duration_s  # geometry metres per second


def stops(*, beed="pending", parbhani="pending", beed_dwell=5, **extra):
    return (
        EtaStop("beed", "Beed", *BEED, dwell_minutes=beed_dwell, status=beed, **extra),
        EtaStop("parbhani", "Parbhani", *PARBHANI, dwell_minutes=5, status=parbhani),
    )


def make_input(**overrides) -> EtaInput:
    base = {
        "now": NOW,
        "route": tuple(ROUTE.coordinates),
        "route_distance_m": ROUTE.distance_m,
        "route_duration_s": ROUTE.duration_s,
        "stops": stops(),
        "destination_name": "Nanded",
        "destination": NANDED,
        "planned_departure": NOW - timedelta(hours=1),
        "position": AHMEDNAGAR,
        "position_at": NOW - timedelta(seconds=10),
        "route_version_id": "rv1",
    }
    base.update(overrides)
    return EtaInput(**base)


def chain(point) -> float:
    return geo.chainage_m(list(ROUTE.coordinates), point)


def drive_s(from_point, to_point) -> float:
    return (chain(to_point) - chain(from_point)) / SPEED


# ------------------------------------------------------------------ basic prediction


def test_etas_increase_and_match_constant_speed_arithmetic():
    snap = compute_snapshot(make_input())
    beed, parbhani = snap.stops
    assert snap.next_stop.name == "Beed"
    assert beed.eta == NOW + timedelta(seconds=drive_s(AHMEDNAGAR, BEED))
    assert beed.eta < parbhani.eta < snap.destination.eta
    # Beed wait (5 min) and Parbhani wait (5 min) are both included before Nanded.
    expected = drive_s(AHMEDNAGAR, NANDED) + 10 * 60
    assert (snap.destination.eta - NOW).total_seconds() == pytest.approx(expected, abs=1)
    assert [s.status for s in snap.stops] == ["next", "upcoming"]


def test_remaining_distance_and_progress_use_road_distance():
    snap = compute_snapshot(make_input())
    scale = ROUTE.distance_m / LENGTH
    assert snap.remaining_distance_m == pytest.approx((LENGTH - chain(AHMEDNAGAR)) * scale)
    assert snap.travelled_distance_m + snap.remaining_distance_m == pytest.approx(ROUTE.distance_m)
    assert 0 < snap.progress_pct < 100
    assert snap.stops[0].remaining_m > snap.stops[0].remaining_m - 1
    assert snap.stops[0].remaining_m < snap.stops[1].remaining_m < snap.remaining_distance_m


def test_waiting_time_at_stops_shifts_later_etas_only():
    base = compute_snapshot(make_input())
    longer = compute_snapshot(make_input(stops=stops(beed_dwell=30)))
    assert longer.stops[0].eta == base.stops[0].eta  # arrival at Beed unchanged
    assert longer.stops[0].departure_eta - base.stops[0].departure_eta == timedelta(minutes=25)
    assert longer.stops[1].eta - base.stops[1].eta == timedelta(minutes=25)
    assert longer.destination.eta - base.destination.eta == timedelta(minutes=25)


def test_traffic_slowdown_delays_everything_beyond_it():
    base = compute_snapshot(make_input())
    segment = TrafficSegment(chain(BEED), chain(PARBHANI), multiplier=2.0)
    slowed = compute_snapshot(make_input(traffic=(segment,)))
    stretch = timedelta(seconds=drive_s(BEED, PARBHANI))
    assert slowed.stops[0].eta == base.stops[0].eta  # before the slowdown
    assert (slowed.stops[1].eta - base.stops[1].eta).total_seconds() == pytest.approx(
        stretch.total_seconds(), abs=0.01
    )
    assert (slowed.destination.eta - base.destination.eta).total_seconds() == pytest.approx(
        stretch.total_seconds(), abs=0.01
    )
    assert slowed.flags["traffic_simulated"] is True and base.flags["traffic_simulated"] is False


def test_overlapping_slowdowns_use_the_larger_multiplier():
    a = TrafficSegment(chain(BEED), chain(PARBHANI), 2.0)
    b = TrafficSegment(chain(BEED), chain(PARBHANI), 3.0)
    base = compute_snapshot(make_input())
    both = compute_snapshot(make_input(traffic=(a, b)))
    stretch = timedelta(seconds=drive_s(BEED, PARBHANI))
    assert (both.destination.eta - base.destination.eta).total_seconds() == pytest.approx(
        stretch.total_seconds() * 2, abs=0.01
    )


def test_slowdown_behind_the_bus_has_no_effect():
    behind = TrafficSegment(0, chain(AHMEDNAGAR) - 1000, 5.0)
    assert compute_snapshot(make_input(traffic=(behind,))).destination.eta == (
        compute_snapshot(make_input()).destination.eta
    )


@pytest.mark.parametrize("multiplier", [0.5, 0.0, 25.0])
def test_invalid_traffic_multiplier_is_rejected(multiplier):
    with pytest.raises(ValueError):
        TrafficSegment(0, 100, multiplier)


# ------------------------------------------------------------------ states of the journey


def test_stale_position_is_flagged_but_still_predicts():
    snap = compute_snapshot(make_input(position_at=NOW - timedelta(minutes=10)))
    assert snap.flags["stale"] is True and snap.gps_age_s == 600
    assert any(w["code"] == "GPS_STALE" for w in snap.warnings)
    assert snap.next_stop.eta is not None


def test_fresh_position_is_not_stale():
    snap = compute_snapshot(make_input())
    assert snap.flags["stale"] is False and snap.gps_age_s == 10
    stricter = compute_snapshot(make_input(config=EtaConfig(stale_after_s=5)))
    assert stricter.flags["stale"] is True


def test_no_gps_before_departure_gives_a_plan_based_eta():
    departure = NOW + timedelta(hours=2)
    snap = compute_snapshot(
        make_input(position=None, position_at=None, planned_departure=departure)
    )
    assert snap.flags["plan_based"] is True and snap.gps_age_s is None
    assert snap.progress_pct == 0
    assert snap.stops[0].eta == departure + timedelta(seconds=chain(BEED) / SPEED)
    assert snap.remaining_distance_m == pytest.approx(ROUTE.distance_m)


def test_no_gps_after_planned_departure_starts_the_clock_now():
    snap = compute_snapshot(make_input(position=None, position_at=None))
    assert snap.flags["plan_based"] is True
    assert snap.stops[0].eta == NOW + timedelta(seconds=chain(BEED) / SPEED)


def test_off_route_position_is_snapped_and_warned():
    five_km_off = (AHMEDNAGAR[0], AHMEDNAGAR[1] + 0.05)
    snap = compute_snapshot(make_input(position=five_km_off))
    assert snap.flags["off_route"] is True
    assert any(w["code"] == "OFF_ROUTE" for w in snap.warnings)
    assert snap.next_stop.eta is not None and snap.progress_pct > 0


def test_completed_stop_is_skipped():
    snap = compute_snapshot(make_input(stops=stops(beed="departed"), position=BEED))
    assert [s.status for s in snap.stops] == ["completed", "next"]
    assert snap.stops[0].eta is None
    assert snap.next_stop.name == "Parbhani"


def test_bus_waiting_at_a_stop_counts_remaining_wait_only():
    arrived = NOW - timedelta(minutes=2)
    snap = compute_snapshot(
        make_input(stops=stops(beed="arrived", arrived_at=arrived), position=BEED)
    )
    beed, parbhani = snap.stops
    assert beed.status == "current" and beed.eta == arrived
    assert beed.departure_eta == NOW + timedelta(minutes=3)
    assert parbhani.status == "next"
    assert parbhani.eta == beed.departure_eta + timedelta(seconds=drive_s(BEED, PARBHANI))


def test_no_intermediate_stops_makes_destination_the_next_endpoint():
    snap = compute_snapshot(make_input(stops=()))
    assert snap.stops == ()
    assert snap.next_stop is snap.destination or snap.next_stop.name == "Nanded"
    assert snap.flags["next_is_destination"] is True


def test_all_stops_completed_makes_destination_next():
    snap = compute_snapshot(
        make_input(stops=stops(beed="departed", parbhani="departed"), position=PARBHANI)
    )
    assert snap.flags["next_is_destination"] is True
    assert snap.next_stop.name == "Nanded"
    assert snap.destination.status == "next"


def test_stop_passed_without_a_recorded_event_is_reported_not_hidden():
    snap = compute_snapshot(make_input(position=PARBHANI))  # beyond Beed, which is still pending
    assert any(
        w["code"] == "STOP_PASSED_WITHOUT_EVENT" and "Beed" in w["message"] for w in snap.warnings
    )
    assert snap.stops[0].remaining_m == 0
    assert snap.stops[0].status == "next"  # still owed to the passengers; never silently dropped


def test_bus_at_the_destination_has_zero_remaining():
    snap = compute_snapshot(
        make_input(stops=stops(beed="departed", parbhani="departed"), position=NANDED)
    )
    assert snap.remaining_distance_m == pytest.approx(0, abs=ROUTE.distance_m * 0.001)
    assert snap.destination.eta == NOW
    assert snap.progress_pct == pytest.approx(100, abs=0.5)


# ------------------------------------------------------------------ consistency and validation


def test_payload_is_complete_json_and_consistent():
    snap = compute_snapshot(make_input())
    payload = snap.to_payload()
    assert json.loads(json.dumps(payload)) == payload
    assert payload["schema_version"] == 1 and payload["route_version_id"] == "rv1"
    assert payload["next_stop"]["name"] == "Beed"
    assert payload["destination"]["eta"] == snap.destination.eta.isoformat()
    assert [s["name"] for s in payload["stops"]] == ["Beed", "Parbhani"]
    assert compute_snapshot(make_input()).to_payload() == payload  # deterministic


def test_naive_datetimes_and_bad_routes_are_rejected():
    with pytest.raises(ValueError):
        make_input(now=datetime(2031, 3, 1, 12, 0))
    with pytest.raises(ValueError):
        make_input(route_duration_s=0)
    with pytest.raises(ValueError):
        make_input(route=((73.0, 18.0),))


def test_two_journeys_do_not_influence_each_other():
    first = compute_snapshot(make_input())
    second = compute_snapshot(make_input(stops=stops(beed="departed"), position=BEED))
    assert first.stops[0].status == "next" and second.stops[0].status == "completed"
    assert compute_snapshot(make_input()).to_payload() == first.to_payload()


# ------------------------------------------------------------------ property


@settings(max_examples=150, deadline=None)
@given(
    fraction=st.floats(0, 1),
    multiplier=st.floats(1, 5),
    dwell=st.integers(0, 60),
    beed_status=st.sampled_from(["pending", "departed"]),
)
def test_etas_never_go_backwards_and_never_precede_now(fraction, multiplier, dwell, beed_status):
    coords = list(ROUTE.coordinates)
    index = min(int(fraction * (len(coords) - 1)), len(coords) - 1)
    segment = TrafficSegment(0, LENGTH, multiplier)
    snap = compute_snapshot(
        make_input(
            position=coords[index],
            stops=stops(beed=beed_status, beed_dwell=dwell),
            traffic=(segment,),
        )
    )
    arrivals = [s.eta for s in snap.stops if s.eta is not None] + [snap.destination.eta]
    assert arrivals == sorted(arrivals)
    assert all(a >= NOW for a in arrivals)
    assert 0 <= snap.progress_pct <= 100.0001
    assert snap.remaining_distance_m >= 0
    assert replace(make_input(), traffic=(segment,)).traffic == (segment,)
