from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from app.config import Settings
from app.optimizer.costs import CostConfig, estimate_cost
from app.optimizer.models import Candidate
from app.optimizer.scoring import ScoreContext, Weights, rank, rank_feasible, score_candidate

from .fixtures import AHMEDNAGAR, BEED, NANDED, PARBHANI, candidate_through, make_state

NOW = datetime(2031, 3, 1, 12, 0, tzinfo=UTC)


def cand(name, km, hours, **kwargs) -> Candidate:
    return Candidate(name, "variant", ((0.0, 0.0), (0.1, 0.1)), km * 1000, hours * 3600, **kwargs)


def context(target_hours=24, dwell_s=0, **kwargs) -> ScoreContext:
    return ScoreContext(
        now=NOW, arrival_target=NOW + timedelta(hours=target_hours), dwell_s=dwell_s, **kwargs
    )


# ------------------------------------------------------------------ cost


def test_fuel_cost_follows_distance_and_config():
    estimate = estimate_cost(100_000, CostConfig(fuel_litres_per_km=0.4, fuel_price_per_litre=100))
    assert estimate.fuel == pytest.approx(4000)
    assert estimate.is_estimate is True and estimate.currency == "INR"


def test_unknown_toll_data_is_flagged_not_invented():
    unknown = estimate_cost(100_000)
    assert unknown.toll == 0 and unknown.toll_unknown is True
    known = estimate_cost(100_000, CostConfig(toll_per_km=2.5))
    assert known.toll == pytest.approx(250) and known.toll_unknown is False
    assert known.total == pytest.approx(known.fuel + 250)


def test_zero_and_negative_distance_do_not_break_costs():
    assert estimate_cost(0).total == 0
    assert estimate_cost(-5).total == 0


@pytest.mark.parametrize(
    "kwargs",
    [{"fuel_litres_per_km": -1}, {"fuel_price_per_litre": -1}, {"toll_per_km": -0.1}],
)
def test_negative_cost_config_is_rejected(kwargs):
    with pytest.raises(ValueError):
        CostConfig(**kwargs)


# ------------------------------------------------------------------ scoring


def test_breakdown_lists_every_component_and_sums_to_the_score():
    scored = score_candidate(cand("A", 100, 2), context(dwell_s=600))
    assert set(scored.breakdown) == {"lateness", "travel_time", "cost", "distance", "risk"}
    assert scored.score == pytest.approx(sum(p["points"] for p in scored.breakdown.values()))
    assert scored.breakdown["travel_time"]["minutes"] == pytest.approx(130)  # 120 driving + 10 wait
    assert scored.predicted_arrival == NOW + timedelta(minutes=130)
    assert scored.lateness_s == 0


def test_weights_decide_between_faster_and_cheaper():
    cheaper_slower = cand("cheap", 100, 2.0)
    faster_costlier = cand("fast", 120, 1.8)
    by_default = rank([score_candidate(c, context()) for c in (cheaper_slower, faster_costlier)])
    assert [s.candidate.name for s in by_default] == ["cheap", "fast"]
    time_matters = Weights(travel_per_min=5.0)
    by_time = rank(
        [score_candidate(c, context(), time_matters) for c in (cheaper_slower, faster_costlier)]
    )
    assert [s.candidate.name for s in by_time] == ["fast", "cheap"]


def test_protecting_the_booking_eta_beats_a_small_saving():
    on_time = cand("on_time", 110, 2.0)  # a little more fuel, arrives within the promise
    late = cand("late", 100, 2.0)
    ctx = context(target_hours=2.0, extra_delay_s={"late": 20 * 60})
    ranked = rank([score_candidate(c, ctx) for c in (late, on_time)])
    assert [s.candidate.name for s in ranked] == ["on_time", "late"]
    assert ranked[1].lateness_s == pytest.approx(20 * 60)
    assert ranked[1].breakdown["lateness"]["points"] > 100


def test_delay_and_risk_from_traffic_lower_a_candidates_rank():
    a, b = cand("A", 100, 2), cand("B", 100, 2)
    ranked = rank([score_candidate(c, context(extra_risk_s={"A": 30 * 60})) for c in (a, b)])
    assert [s.candidate.name for s in ranked] == ["B", "A"]
    delayed = score_candidate(a, context(extra_delay_s={"A": 600}))
    assert delayed.predicted_arrival == NOW + timedelta(hours=2, minutes=10)


def test_negative_extras_are_ignored():
    scored = score_candidate(
        cand("A", 100, 2), context(extra_delay_s={"A": -999}, extra_risk_s={"A": -1})
    )
    assert scored.predicted_arrival == NOW + timedelta(hours=2)
    assert scored.breakdown["risk"]["points"] == 0


def test_zero_length_candidate_scores_without_error():
    scored = score_candidate(cand("Z", 0, 0), context())
    assert scored.score == 0 and scored.cost.total == 0


def test_ties_are_broken_deterministically():
    twins = [score_candidate(cand(name, 100, 2), context()) for name in ("b", "a", "c")]
    assert [s.candidate.name for s in rank(twins)] == ["a", "b", "c"]
    assert [s.candidate.name for s in rank(list(reversed(twins)))] == ["a", "b", "c"]


def test_naive_datetimes_and_negative_dwell_are_rejected():
    with pytest.raises(ValueError):
        ScoreContext(now=datetime(2031, 3, 1), arrival_target=NOW, dwell_s=0)
    with pytest.raises(ValueError):
        ScoreContext(now=NOW, arrival_target=datetime(2031, 3, 2), dwell_s=0)
    with pytest.raises(ValueError):
        ScoreContext(now=NOW, arrival_target=NOW, dwell_s=-1)


def test_scoring_never_changes_the_commitment():
    ctx = context(target_hours=2)
    before = ctx.arrival_target
    score_candidate(cand("A", 100, 5), ctx)
    assert ctx.arrival_target == before


# ------------------------------------------------------------------ weights configuration


def test_negative_weight_is_rejected():
    with pytest.raises(ValueError):
        Weights(lateness_per_min=-1)


def test_negative_weight_in_environment_is_a_startup_error(monkeypatch):
    monkeypatch.setenv("SCORE_WEIGHT_LATENESS_PER_MIN", "-3")
    with pytest.raises(ValidationError) as exc:
        Settings(_env_file=None)
    assert "score_weight_lateness_per_min" in str(exc.value)


def test_weights_come_from_settings(monkeypatch):
    monkeypatch.setenv("SCORE_WEIGHT_TRAVEL_PER_MIN", "3.5")
    monkeypatch.setenv("TOLL_PER_KM", "2.0")
    settings = Settings(_env_file=None)
    assert settings.score_weights().travel_per_min == 3.5
    assert settings.cost_config().toll_per_km == 2.0


# ------------------------------------------------------------------ infeasible plans are never ranked


def test_infeasible_candidates_are_never_ranked_even_when_cheapest():
    state = make_state()
    valid = candidate_through([AHMEDNAGAR, BEED, PARBHANI, NANDED], name="valid", source="variant")
    skips_beed = candidate_through(
        [AHMEDNAGAR, PARBHANI, NANDED], name="skips_beed", source="variant"
    )
    assert skips_beed.distance_m < valid.distance_m  # it is the cheaper, shorter plan
    ranked = rank_feasible([skips_beed, valid], state, context())
    assert [s.candidate.name for s in ranked] == ["valid"]
    assert rank_feasible([skips_beed], state, context()) == []


def test_toll_is_unknown_when_not_configured(monkeypatch):
    monkeypatch.delenv("TOLL_PER_KM", raising=False)
    assert Settings(_env_file=None).cost_config().toll_per_km is None
