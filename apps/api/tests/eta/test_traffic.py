from datetime import UTC, datetime, timedelta

import pytest

from app.eta.engine import compute_snapshot
from app.eta.traffic import Incident, traffic_on_route
from app.optimizer import geo

from .test_engine import AHMEDNAGAR, BEED, NOW, PARBHANI, ROUTE, make_input

LINE = list(ROUTE.coordinates)
LATUR = (76.5604, 18.4088)


def incident(a=BEED, b=PARBHANI, kind="slow", multiplier=2.0, start=-10, end=60, **kwargs):
    return Incident(
        incident_id=kwargs.pop("incident_id", "i1"),
        kind=kind,
        multiplier=multiplier,
        from_point=a,
        to_point=b,
        starts_at=NOW + timedelta(minutes=start),
        ends_at=None if end is None else NOW + timedelta(minutes=end),
        **kwargs,
    )


def test_active_incident_becomes_a_segment_on_the_route():
    result = traffic_on_route(LINE, [incident()], NOW)
    assert len(result.segments) == 1 and result.closures == ()
    segment = result.segments[0]
    assert segment.from_m == pytest.approx(geo.chainage_m(LINE, BEED))
    assert segment.to_m == pytest.approx(geo.chainage_m(LINE, PARBHANI))
    assert segment.multiplier == 2.0 and segment.simulated is True
    assert result.incident_ids == ("i1",)


def test_reversed_points_are_normalised():
    result = traffic_on_route(LINE, [incident(a=PARBHANI, b=BEED)], NOW)
    assert result.segments[0].from_m < result.segments[0].to_m


@pytest.mark.parametrize(("start", "end"), [(5, 60), (-60, -1), (-60, 0)])
def test_incidents_not_active_now_are_ignored(start, end):
    assert traffic_on_route(LINE, [incident(start=start, end=end)], NOW).segments == ()


def test_open_ended_incident_stays_active():
    assert len(traffic_on_route(LINE, [incident(end=None)], NOW).segments) == 1


def test_incident_on_a_road_this_route_does_not_use_is_ignored():
    result = traffic_on_route(LINE, [incident(a=LATUR, b=(76.7, 18.5))], NOW)
    assert result.segments == () and result.incident_ids == ()


def test_closure_is_reported_separately():
    result = traffic_on_route(LINE, [incident(kind="closure")], NOW)
    assert result.segments == () and len(result.closures) == 1


def test_naive_now_is_not_silently_accepted():
    with pytest.raises(TypeError):
        traffic_on_route(LINE, [incident()], datetime(2031, 3, 1, 12, 0))


def test_slowdown_flows_into_the_snapshot_with_a_simulated_label():
    traffic = traffic_on_route(LINE, [incident()], NOW)
    base = compute_snapshot(make_input())
    slowed = compute_snapshot(make_input(traffic=traffic.segments))
    assert slowed.destination.eta > base.destination.eta
    assert slowed.flags["traffic_ahead"] is True and base.flags["traffic_ahead"] is False
    messages = [w["message"] for w in slowed.warnings if w["code"] == "TRAFFIC_AHEAD"]
    assert messages == ["Simulated slow traffic ahead on the route."]


def test_slowdown_already_passed_is_not_ahead():
    traffic = traffic_on_route(LINE, [incident(a=AHMEDNAGAR, b=BEED)], NOW)
    snap = compute_snapshot(make_input(position=PARBHANI, traffic=traffic.segments))
    assert snap.flags["traffic_ahead"] is False
    assert not any(w["code"] == "TRAFFIC_AHEAD" for w in snap.warnings)


def test_closure_ahead_is_flagged_and_labelled():
    traffic = traffic_on_route(LINE, [incident(kind="closure")], NOW)
    snap = compute_snapshot(make_input(closures=traffic.closures))
    assert snap.flags["closure_ahead"] is True
    message = next(w["message"] for w in snap.warnings if w["code"] == "ROAD_CLOSED_AHEAD")
    assert message == "Simulated road closure ahead. Arrival times are uncertain."
    passed = compute_snapshot(make_input(position=(77.2, 19.15), closures=traffic.closures))
    assert passed.flags["closure_ahead"] is False


def test_utc_constant_is_aware():
    assert NOW.tzinfo is UTC
