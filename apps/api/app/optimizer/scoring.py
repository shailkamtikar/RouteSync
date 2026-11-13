"""Multi-objective scoring of feasible candidates. Lower score is better.

The score combines protection of the booking-time arrival promise, total travel time,
estimated cost, distance and disruption risk. It is not a shortest-path or cheapest-toll
rule. Weights are configuration; by default lateness against the promise dominates.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from app.optimizer.constraints import is_feasible
from app.optimizer.costs import CostConfig, CostEstimate, estimate_cost
from app.optimizer.models import Candidate, JourneyState, Tolerances


@dataclass(frozen=True)
class Weights:
    """Points added per unit. All must be zero or positive."""

    lateness_per_min: float = 10.0  # minutes later than the booking-time arrival
    travel_per_min: float = 1.0  # minutes of driving plus waiting at stops
    cost_per_unit: float = 0.05  # per unit of currency (estimate)
    distance_per_km: float = 0.05
    risk_per_min: float = 2.0  # expected disruption minutes

    def __post_init__(self) -> None:
        for name, value in self.__dict__.items():
            if value < 0:
                raise ValueError(f"weight {name} must not be negative")


@dataclass(frozen=True)
class ScoreContext:
    now: datetime
    # Arrival expectation communicated at booking. Never changed by scoring.
    arrival_target: datetime
    # Waiting time still to be spent at the remaining stops.
    dwell_s: float
    # Extra delay and expected disruption per candidate name (from traffic data), in seconds.
    extra_delay_s: Mapping[str, float] = field(default_factory=dict)
    extra_risk_s: Mapping[str, float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name in ("now", "arrival_target"):
            if getattr(self, name).tzinfo is None:
                raise ValueError(f"{name} must be timezone-aware")
        if self.dwell_s < 0:
            raise ValueError("dwell_s must not be negative")


@dataclass(frozen=True)
class Scored:
    candidate: Candidate
    score: float
    predicted_arrival: datetime
    lateness_s: float
    cost: CostEstimate
    # Every component of the score, so a decision can be explained.
    breakdown: dict[str, dict[str, float]]


def score_candidate(
    candidate: Candidate,
    context: ScoreContext,
    weights: Weights | None = None,
    costs: CostConfig | None = None,
) -> Scored:
    w = weights or Weights()
    cost = estimate_cost(candidate.distance_m, costs)
    delay_s = max(context.extra_delay_s.get(candidate.name, 0.0), 0.0)
    risk_s = max(context.extra_risk_s.get(candidate.name, 0.0), 0.0)
    travel_s = max(candidate.duration_s, 0.0) + context.dwell_s + delay_s
    predicted = context.now + timedelta(seconds=travel_s)
    lateness_s = max((predicted - context.arrival_target).total_seconds(), 0.0)

    components = {
        "lateness": {"minutes": lateness_s / 60, "points": lateness_s / 60 * w.lateness_per_min},
        "travel_time": {"minutes": travel_s / 60, "points": travel_s / 60 * w.travel_per_min},
        "cost": {"amount": cost.total, "points": cost.total * w.cost_per_unit},
        "distance": {
            "km": candidate.distance_m / 1000,
            "points": candidate.distance_m / 1000 * w.distance_per_km,
        },
        "risk": {"minutes": risk_s / 60, "points": risk_s / 60 * w.risk_per_min},
    }
    return Scored(
        candidate=candidate,
        score=sum(part["points"] for part in components.values()),
        predicted_arrival=predicted,
        lateness_s=lateness_s,
        cost=cost,
        breakdown=components,
    )


def rank(scored: Sequence[Scored]) -> list[Scored]:
    """Best first. Ties are broken by earlier arrival, then name, so ranking is deterministic."""
    return sorted(scored, key=lambda s: (s.score, s.predicted_arrival, s.candidate.name))


def rank_feasible(
    candidates: Sequence[Candidate],
    state: JourneyState,
    context: ScoreContext,
    *,
    weights: Weights | None = None,
    costs: CostConfig | None = None,
    tolerances: Tolerances | None = None,
) -> list[Scored]:
    """Score and rank only candidates that satisfy every hard constraint."""
    return rank(
        [
            score_candidate(candidate, context, weights, costs)
            for candidate in candidates
            if is_feasible(candidate, state, tolerances)
        ]
    )
