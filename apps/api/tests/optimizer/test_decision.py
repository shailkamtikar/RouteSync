from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from app.optimizer.decision import DecisionConfig, DecisionContext, decide
from app.optimizer.models import Candidate
from app.optimizer.scoring import ScoreContext, rank, score_candidate

NOW = datetime(2031, 3, 1, 12, 0, tzinfo=UTC)
CFG = DecisionConfig()
CTX = DecisionContext(
    now=NOW, gps_fresh=True, manual_mode=False, reroutes_so_far=0, last_reroute_at=None
)


def cand(name, hours, source="variant", km=300):
    return Candidate(name, source, ((0.0, 0.0), (1.0, 1.0)), km * 1000, hours * 3600)


def ranked(*candidates, delays=None):
    context = ScoreContext(
        now=NOW,
        arrival_target=NOW + timedelta(hours=5),
        dwell_s=0,
        extra_delay_s=delays or {},
    )
    return rank([score_candidate(c, context) for c in candidates])


CURRENT = cand("Current route", 5.0, source="current_route")


def confirm(options, context=CTX, config=CFG):
    """Run the evaluation twice, carrying the hysteresis state, as two GPS updates would."""
    first = decide(options, context, config)
    second = decide(
        options,
        replace(context, pending_name=first.pending_name, pending_count=first.pending_count),
        config,
    )
    return first, second


def test_current_route_is_kept_when_it_is_best():
    decision = decide(ranked(CURRENT, cand("Slower", 5.5)), CTX)
    assert decision.action == "keep" and decision.reason_code == "current_route_best"
    assert decision.pending_name is None


def test_marginal_gain_never_changes_the_route():
    options = ranked(CURRENT, cand("Slightly faster", 4.97))  # about 2 minutes
    first, second = confirm(options)
    assert first.action == second.action == "keep"
    assert first.reason_code == "below_threshold"
    assert first.saving_minutes == pytest.approx(1.8, abs=0.1)
    assert "not enough" in first.reason


def test_saving_must_also_be_a_meaningful_share_of_the_remaining_time():
    slow_current = cand("Current route", 10.0, source="current_route")
    options = ranked(slow_current, cand("A bit faster", 9.8))  # 12 min but only 2%
    assert decide(options, CTX).reason_code == "below_threshold"
    assert (
        decide(options, CTX, DecisionConfig(min_saving_pct=1)).reason_code
        == "awaiting_confirmation"
    )


def test_meaningful_gain_is_applied_only_after_it_is_confirmed_twice():
    options = ranked(CURRENT, cand("Bypass", 4.5))
    first, second = confirm(options)
    assert first.action == "keep" and first.reason_code == "awaiting_confirmation"
    assert first.pending_name == "Bypass" and first.pending_count == 1
    assert second.action == "reroute" and second.reason_code == "meaningful_saving"
    assert second.chosen.candidate.name == "Bypass"
    assert second.saving_minutes == pytest.approx(30)
    assert "30 min" in second.reason and second.pending_name is None


def test_a_different_winner_restarts_the_confirmation_count():
    first = decide(ranked(CURRENT, cand("Bypass A", 4.5)), CTX)
    switched = decide(
        ranked(CURRENT, cand("Bypass B", 4.4)),
        replace(CTX, pending_name=first.pending_name, pending_count=first.pending_count),
    )
    assert switched.action == "keep" and switched.pending_name == "Bypass B"
    assert switched.pending_count == 1


def test_alternating_conditions_never_cause_a_change():
    good, bad = ranked(CURRENT, cand("Bypass", 4.5)), ranked(CURRENT, cand("Bypass", 5.2))
    context, actions = CTX, []
    for options in [good, bad, good, bad, good, bad, good, bad]:
        decision = decide(options, context)
        actions.append(decision.action)
        context = replace(
            CTX, pending_name=decision.pending_name, pending_count=decision.pending_count
        )
    assert set(actions) == {"keep"}


def test_cooldown_blocks_a_second_change():
    recent = replace(CTX, last_reroute_at=NOW - timedelta(minutes=5), reroutes_so_far=1)
    _, second = confirm(ranked(CURRENT, cand("Bypass", 4.5)), recent)
    assert second.action == "keep" and second.reason_code == "cooldown"
    later = replace(CTX, last_reroute_at=NOW - timedelta(minutes=25), reroutes_so_far=1)
    assert confirm(ranked(CURRENT, cand("Bypass", 4.5)), later)[1].action == "reroute"


def test_reroute_limit_per_journey():
    maxed = replace(CTX, reroutes_so_far=3)
    _, second = confirm(ranked(CURRENT, cand("Bypass", 4.5)), maxed)
    assert second.action == "keep" and second.reason_code == "max_reroutes"


def test_stale_gps_blocks_a_change():
    stale = replace(CTX, gps_fresh=False)
    first, second = confirm(ranked(CURRENT, cand("Bypass", 4.5)), stale)
    assert first.reason_code == second.reason_code == "gps_stale"
    assert second.action == "keep"


def test_degraded_routing_blocks_a_change():
    degraded = replace(CTX, degraded=True)
    assert decide(ranked(CURRENT, cand("Bypass", 4.5)), degraded).reason_code == "routing_degraded"


def test_manual_mode_only_recommends():
    manual = replace(CTX, manual_mode=True)
    _, second = confirm(ranked(CURRENT, cand("Bypass", 4.5)), manual)
    assert second.action == "recommend" and second.chosen.candidate.name == "Bypass"
    off = DecisionConfig(autoapply=False)
    assert confirm(ranked(CURRENT, cand("Bypass", 4.5)), CTX, off)[1].action == "recommend"


def test_blocked_current_route_reroutes_at_once_without_thresholds():
    blocked = replace(
        CTX,
        current_route_blocked=True,
        reroutes_so_far=3,
        last_reroute_at=NOW - timedelta(minutes=1),
    )
    decision = decide(ranked(CURRENT, cand("Detour", 5.4)), blocked)  # slower, but passable
    assert decision.action == "reroute" and decision.reason_code == "current_route_blocked"
    assert decision.chosen.candidate.name == "Detour"


def test_blocked_route_with_no_alternative_reports_no_feasible_route():
    blocked = replace(CTX, current_route_blocked=True)
    decision = decide(ranked(CURRENT), blocked)
    assert decision.action == "no_feasible_route" and decision.chosen is None


def test_blocked_route_respects_manual_mode_and_stale_gps():
    options = ranked(CURRENT, cand("Detour", 5.4))
    manual = replace(CTX, current_route_blocked=True, manual_mode=True)
    assert decide(options, manual).action == "recommend"
    stale = replace(CTX, current_route_blocked=True, gps_fresh=False)
    assert decide(options, stale).action == "keep"
    assert decide(options, stale).reason_code == "gps_stale"


def test_missing_current_route_counts_as_blocked():
    decision = decide(ranked(cand("Only option", 5.0)), CTX)
    assert decision.action == "reroute" and decision.reason_code == "current_route_blocked"
    assert decide([], CTX).action == "no_feasible_route"


def test_traffic_delay_on_the_current_route_can_justify_a_change():
    options = ranked(CURRENT, cand("Bypass", 5.1), delays={"Current route": 45 * 60})
    _, second = confirm(options)
    assert second.action == "reroute"
    assert second.saving_minutes == pytest.approx(39)


def test_decision_never_picks_something_absent_from_the_feasible_list():
    options = ranked(CURRENT, cand("Bypass", 4.5))
    _, second = confirm(options)
    assert second.chosen in options


@pytest.mark.parametrize(
    "kwargs",
    [
        {"min_saving_minutes": -1},
        {"cooldown_minutes": -1},
        {"confirmations_required": 0},
        {"max_reroutes_per_journey": -1},
    ],
)
def test_invalid_config_is_rejected(kwargs):
    with pytest.raises(ValueError):
        DecisionConfig(**kwargs)
