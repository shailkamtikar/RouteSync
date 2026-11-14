import json
from datetime import UTC, datetime, timedelta

import pytest

from app.companion import tools
from app.companion.context import build_context
from app.companion.tools import Binding, UnknownTool, run_tool

from .live_fixtures import PARBHANI, build_live_journey

pytestmark = pytest.mark.db

PRIVATE = ["Asha", "Kulkarni", "REF-SECRET", "12A", "9800000000"]


@pytest.fixture
def live(conn, actor, tenants):
    actor.admin()
    w = build_live_journey(conn, tenants)
    booking = conn.execute(
        "insert into public.bookings (operator_id, journey_id, reference, contact_name, "
        "passenger_count, pickup_stop_name, drop_stop_name) values (%s, %s, 'REF-SECRET', "
        "'Asha Kulkarni', 2, 'Pune', 'Nanded') returning id",
        (w["op"], w["journey"]),
    ).fetchone()[0]
    conn.execute(
        "insert into public.booking_passengers (operator_id, journey_id, booking_id, name, "
        "seat_number, phone) values (%s, %s, %s, 'Asha Kulkarni', '12A', '+919800000000')",
        (w["op"], w["journey"], booking),
    )
    conn.execute(
        "insert into public.route_template_stops (operator_id, route_template_id, name, location, "
        "kind, chainage_m) values (%s, %s, 'Majalgaon', 'POINT(76.208 19.151)'::extensions.geography, "
        "'pass_through', 250000)",
        (w["op"], w["template"]),
    )
    w["binding"] = Binding(w["journey"], w["op"])
    return w


def run(conn, w, name, **args):
    return run_tool(conn, w["binding"], name, args)


def test_every_tool_runs_and_is_public_safe(conn, live):
    for name in tools.REGISTRY:
        result = run(conn, live, name, stop_name="Beed")
        assert set(result) >= {"data", "availability", "as_of"}
        text = json.dumps(result)
        for secret in PRIVATE:
            assert secret not in text, name
        assert "journey_id" not in text and "operator_id" not in text


def test_overview_and_route_summary(conn, live):
    overview = run(conn, live, "get_journey_overview")["data"]
    assert overview["origin"] == "Pune" and overview["destination"] == "Nanded"
    summary = run(conn, live, "get_route_summary")["data"]
    assert summary["passenger_stops_in_order"] == ["Beed", "Parbhani"]
    assert summary["route_changed_during_journey"] is False


def test_geography_separates_stops_from_pass_through_places(conn, live):
    geo = run(conn, live, "get_route_geography")["data"]
    assert geo["passenger_stops"] == ["Beed", "Parbhani"]
    assert geo["places_passed_without_stopping"] == ["Majalgaon"]
    assert "Latur" not in json.dumps(geo)


def test_remaining_stops_and_next_after(conn, live):
    remaining = run(conn, live, "get_remaining_stops")
    assert remaining["data"]["count"] == 2
    assert [s["name"] for s in remaining["data"]["stops"]] == ["Beed", "Parbhani"]
    assert remaining["data"]["stops"][0]["expected_arrival"]
    assert (
        run(conn, live, "get_next_stop_after", stop_name="beed")["data"]["next_stop"] == "Parbhani"
    )
    assert (
        run(conn, live, "get_next_stop_after", stop_name="Parbhani")["data"]["next_stop"]
        == "Nanded"
    )
    off = run(conn, live, "get_next_stop_after", stop_name="Latur")
    assert off["availability"] == "not_on_route" and "not a passenger stop" in off["note"]


def test_stop_status_is_recorded_not_inferred(conn, live):
    conn.execute(
        "update public.journeys set last_position = %s::extensions.geography where id = %s",
        (f"POINT({PARBHANI[0]} {PARBHANI[1]})", live["journey"]),
    )
    status = run(conn, live, "get_stop_status", stop_name="Beed")["data"]
    assert status["recorded_status"] == "pending"  # bus is past Beed, but nothing was recorded
    arrived = datetime.now(UTC) - timedelta(minutes=12)
    conn.execute(
        "update public.journey_stops set status = 'departed', arrived_at = %s, departed_at = %s "
        "where id = %s",
        (arrived, arrived + timedelta(minutes=7), live["journey_stops"]["Beed"]),
    )
    assert (
        run(conn, live, "get_stop_status", stop_name="Beed")["data"]["recorded_status"]
        == "departed"
    )
    history = run(conn, live, "get_stop_history")["data"]
    assert history["completed_stops"] == ["Beed"] and history["total_waiting_minutes_at_stops"] == 7
    assert run(conn, live, "get_remaining_stops")["data"]["count"] == 1


def test_counts_respect_the_operator_toggle(conn, live):
    hidden = run(conn, live, "get_stop_passenger_counts", stop_name="Beed")
    assert hidden["availability"] == "not_public" and hidden["data"] == {}
    assert run(conn, live, "get_onboard_passenger_count")["availability"] == "not_public"
    conn.execute(
        "update public.journeys set public_counts_enabled = true where id = %s", (live["journey"],)
    )
    shown = run(conn, live, "get_stop_passenger_counts", stop_name="Beed")["data"]
    assert shown["planned_boarding"] == 2 and shown["planned_alighting"] == 1
    onboard = run(conn, live, "get_onboard_passenger_count")
    assert onboard["data"]["method"] == "planned only" and "No boardings" in onboard["note"]
    conn.execute(
        "insert into public.stop_events (operator_id, journey_id, journey_stop_id, type, count, "
        "client_event_id, occurred_at) values (%s, %s, %s, 'boarded', 4, 'e1', now())",
        (live["op"], live["journey"], live["journey_stops"]["Beed"]),
    )
    recorded = run(conn, live, "get_onboard_passenger_count")["data"]
    assert recorded == {"onboard": 4, "method": "recorded boardings and alightings"}


def test_progress_delay_and_traffic(conn, live):
    progress = run(conn, live, "get_journey_progress")
    assert progress["availability"] == "available"
    assert 0 < progress["data"]["progress_percent"] < 100
    assert progress["data"]["travelled_km"] + progress["data"]["remaining_km"] == pytest.approx(
        pytest.approx(progress["data"]["travelled_km"] + progress["data"]["remaining_km"])
    )
    delay = run(conn, live, "get_journey_delay")["data"]
    assert delay["status"] in ("on_time", "minor", "significant")
    assert delay["arrival_promised_at_booking"] and delay["arrival_now_expected"]
    traffic = run(conn, live, "get_traffic_summary")["data"]
    assert traffic["slow_traffic_ahead"] is False and "simulated" in traffic["source"]


def test_stale_position_is_reported(conn, live):
    conn.execute(
        "update public.journeys set last_position_at = now() - interval '10 minutes' where id = %s",
        (live["journey"],),
    )
    conn.execute(
        "delete from public.journey_eta_snapshots where journey_id = %s", (live["journey"],)
    )
    assert run(conn, live, "get_journey_progress")["availability"] == "stale"


def test_route_comparison_is_explanation_only(conn, live):
    none = run(conn, live, "compare_remaining_routes")["data"]
    assert none["evaluated"] is False
    conn.execute(
        "insert into public.route_decisions (operator_id, journey_id, outcome, reason_code, reason, "
        "chosen_name, saving_minutes) values (%s, %s, 'keep', 'below_threshold', "
        "'Bypass would save about 3 min, which is not enough to justify changing the route.', 'Bypass', 3)",
        (live["op"], live["journey"]),
    )
    result = run(conn, live, "compare_remaining_routes")["data"]
    assert result["evaluated"] is True and result["outcome"] == "keep"
    assert result["minutes_saved_by_alternative"] == 3
    versions = conn.execute(
        "select count(*) from public.route_versions where journey_id = %s", (live["journey"],)
    ).fetchone()[0]
    assert versions == 1  # nothing changed


def test_tool_arguments_cannot_redirect_to_another_journey(conn, live, tenants):
    other = build_live_journey(conn, tenants, position=PARBHANI)
    conn.execute(
        "update public.journey_stops set status = 'departed' where journey_id = %s",
        (other["journey"],),
    )
    result = run_tool(
        conn,
        live["binding"],
        "get_remaining_stops",
        {
            "journey_id": str(other["journey"]),
            "operator_id": str(other["op"]),
            "stop_name": "x" * 500,
        },
    )
    assert result["data"]["count"] == 2  # still this journey
    with pytest.raises(UnknownTool):
        run_tool(conn, live["binding"], "run_sql", {"query": "select 1"})
    with pytest.raises(UnknownTool):
        run_tool(conn, live["binding"], "get_bookings", {})
    missing = run_tool(conn, live["binding"], "get_stop_status", {})
    assert missing["availability"] == "unknown"


def test_two_journeys_have_independent_answers(conn, live, tenants):
    other = build_live_journey(
        conn, tenants, position=PARBHANI, template=live["template"], service=live["service"]
    )
    conn.execute(
        "update public.journey_stops set status = 'departed' where journey_id = %s",
        (other["journey"],),
    )
    assert run(conn, live, "get_remaining_stops")["data"]["count"] == 2
    assert (
        run_tool(conn, Binding(other["journey"], other["op"]), "get_remaining_stops", {})["data"][
            "count"
        ]
        == 0
    )


def test_context_is_compact_and_safe(conn, live):
    context = build_context(conn, live["binding"])
    assert context["origin"] == "Pune" and context["next_stop"] == "Beed"
    assert context["remaining_stops"] == ["Beed", "Parbhani"] and context["position"] == "live"
    text = json.dumps(context)
    assert len(text) < 1500
    for secret in PRIVATE:
        assert secret not in text


def test_tools_never_write(conn, live):
    # Counted for this operator only: other processes may write to the shared dev database.
    before = {
        t: conn.execute(
            f"select count(*) from public.{t} where operator_id = %s", (live["op"],)
        ).fetchone()[0]
        for t in (
            "journeys",
            "journey_stops",
            "bookings",
            "route_versions",
            "stop_events",
            "journey_events",
        )
    }
    for name in tools.REGISTRY:
        run(conn, live, name, stop_name="Beed")
    after = {
        t: conn.execute(
            f"select count(*) from public.{t} where operator_id = %s", (live["op"],)
        ).fetchone()[0]
        for t in before
    }
    assert after == before
