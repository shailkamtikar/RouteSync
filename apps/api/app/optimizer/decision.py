"""Reroute decision: keep the current route unless a change is clearly worth it.

Pure functions. Inputs are feasible, scored candidates (hard constraints were already
enforced). A route is changed automatically only when every guardrail passes; otherwise the
current route stays, or the change is only recommended to the operator.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal

from app.optimizer.scoring import Scored

Action = Literal["keep", "recommend", "reroute", "no_feasible_route"]
CURRENT_ROUTE = "current_route"


@dataclass(frozen=True)
class DecisionConfig:
    # A change must save at least this many minutes AND this share of the remaining time.
    min_saving_minutes: float = 10.0
    min_saving_pct: float = 5.0
    # No second automatic change within this time, and no more than this many per journey.
    cooldown_minutes: float = 20.0
    max_reroutes_per_journey: int = 3
    # The same alternative must win this many evaluations in a row (anti-flapping).
    confirmations_required: int = 2
    # False turns every automatic change into a recommendation.
    autoapply: bool = True

    def __post_init__(self) -> None:
        if min(self.min_saving_minutes, self.min_saving_pct, self.cooldown_minutes) < 0:
            raise ValueError("thresholds must not be negative")
        if self.max_reroutes_per_journey < 0 or self.confirmations_required < 1:
            raise ValueError("max_reroutes_per_journey >= 0 and confirmations_required >= 1")


@dataclass(frozen=True)
class DecisionContext:
    now: datetime
    gps_fresh: bool
    manual_mode: bool
    reroutes_so_far: int
    last_reroute_at: datetime | None
    # The current route cannot be driven (closure on it, or it no longer satisfies the plan).
    current_route_blocked: bool = False
    # The routing provider failed, so alternatives could not be checked properly.
    degraded: bool = False
    # Hysteresis state carried from the previous evaluation.
    pending_name: str | None = None
    pending_count: int = 0


@dataclass(frozen=True)
class Decision:
    action: Action
    reason_code: str
    reason: str
    chosen: Scored | None = None
    incumbent: Scored | None = None
    saving_minutes: float = 0.0
    saving_pct: float = 0.0
    # Hysteresis state to store for the next evaluation.
    pending_name: str | None = None
    pending_count: int = 0


def _keep(code: str, reason: str, incumbent: Scored | None, **kwargs) -> Decision:
    return Decision("keep", code, reason, incumbent=incumbent, **kwargs)


def decide(
    ranked: Sequence[Scored], context: DecisionContext, config: DecisionConfig | None = None
) -> Decision:
    """`ranked` holds only feasible candidates, best first."""
    cfg = config or DecisionConfig()
    incumbent = next((s for s in ranked if s.candidate.source == CURRENT_ROUTE), None)
    challengers = [s for s in ranked if s.candidate.source != CURRENT_ROUTE]

    # ---- the current route cannot be used: a change is needed, not merely attractive
    if context.current_route_blocked or incumbent is None:
        if not challengers:
            return Decision(
                "no_feasible_route",
                "no_feasible_route",
                "The current route is blocked and no approved alternative serves every stop.",
                incumbent=incumbent,
            )
        best = challengers[0]
        if not context.gps_fresh:
            return _keep(
                "gps_stale",
                "The current route is blocked, but the bus position is not recent enough to reroute.",
                incumbent,
            )
        action: Action = "recommend" if context.manual_mode or not cfg.autoapply else "reroute"
        return Decision(
            action,
            "current_route_blocked",
            f"The current route is blocked. {best.candidate.name} serves every remaining stop.",
            chosen=best,
            incumbent=incumbent,
        )

    # ---- the current route is usable: change only for a meaningful, confirmed gain
    best = ranked[0]
    if best is incumbent or not challengers:
        return _keep("current_route_best", "The current route is still the best option.", incumbent)

    remaining_min = max(incumbent.breakdown["travel_time"]["minutes"], 1e-9)
    saving = (incumbent.predicted_arrival - best.predicted_arrival) / timedelta(minutes=1)
    saving_pct = 100.0 * saving / remaining_min
    numbers = {"saving_minutes": saving, "saving_pct": saving_pct, "chosen": best}

    if saving < cfg.min_saving_minutes or saving_pct < cfg.min_saving_pct:
        return _keep(
            "below_threshold",
            f"{best.candidate.name} would save about {max(saving, 0):.0f} min, "
            "which is not enough to justify changing the route.",
            incumbent,
            **numbers,
        )
    if context.degraded:
        return _keep(
            "routing_degraded",
            "Alternatives could not be checked reliably, so the current route is kept.",
            incumbent,
            **numbers,
        )
    if not context.gps_fresh:
        return _keep(
            "gps_stale",
            "The bus position is not recent enough to change the route.",
            incumbent,
            **numbers,
        )

    count = context.pending_count + 1 if context.pending_name == best.candidate.name else 1
    pending = {"pending_name": best.candidate.name, "pending_count": count}
    if count < cfg.confirmations_required:
        return _keep(
            "awaiting_confirmation",
            f"{best.candidate.name} looks better by {saving:.0f} min; "
            "waiting for the next check to confirm it.",
            incumbent,
            **numbers,
            **pending,
        )
    if context.last_reroute_at is not None and context.now - context.last_reroute_at < timedelta(
        minutes=cfg.cooldown_minutes
    ):
        return _keep(
            "cooldown",
            "The route was changed recently, so it is not changed again yet.",
            incumbent,
            **numbers,
            **pending,
        )
    if context.reroutes_so_far >= cfg.max_reroutes_per_journey:
        return _keep(
            "max_reroutes",
            "This journey has reached its limit of route changes.",
            incumbent,
            **numbers,
            **pending,
        )

    reason = (
        f"{best.candidate.name} saves about {saving:.0f} min ({saving_pct:.0f}% of the remaining "
        "time) and serves every remaining stop."
    )
    if context.manual_mode or not cfg.autoapply:
        return Decision(
            "recommend", "manual_mode", reason, incumbent=incumbent, **numbers, **pending
        )
    return Decision("reroute", "meaningful_saving", reason, incumbent=incumbent, **numbers)
