"""The booking-time arrival promise versus the live prediction.

The promise (`journeys.booking_eta_at`) is stored once and never changes. The predicted arrival
is tracked separately, and the difference is reported honestly. A planning buffer may make the
optimizer aim earlier, but it never reduces the reported delay.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Literal

Status = Literal["on_time", "minor", "significant"]
Severity = Literal["warning", "critical"]
AlertAction = Literal["open", "update", "resolve", "none"]


@dataclass(frozen=True)
class CommitmentConfig:
    # Delay (minutes) above which the journey counts as running late, and as seriously late.
    minor_after_min: float = 5.0
    significant_after_min: float = 15.0
    critical_after_min: float = 60.0
    # An open alert only clears once the delay drops this far below the alert threshold,
    # so a delay hovering around the threshold does not open and close alerts repeatedly.
    clear_margin_min: float = 5.0
    # Planning only: the optimizer aims to arrive this much before the promise.
    buffer_min: float = 0.0

    def __post_init__(self) -> None:
        if not 0 <= self.minor_after_min < self.significant_after_min < self.critical_after_min:
            raise ValueError("delay thresholds must satisfy 0 <= minor < significant < critical")
        if self.clear_margin_min < 0 or self.clear_margin_min >= self.significant_after_min:
            raise ValueError(
                "clear_margin_min must be zero or positive and below significant_after_min"
            )
        if self.buffer_min < 0:
            raise ValueError("buffer_min must not be negative")


@dataclass(frozen=True)
class Commitment:
    original_eta: datetime
    predicted_eta: datetime
    delay_minutes: float  # negative means early
    status: Status

    @property
    def is_early(self) -> bool:
        return self.delay_minutes < 0

    def to_payload(self) -> dict[str, Any]:
        return {
            "original_eta": self.original_eta.isoformat(),
            "predicted_eta": self.predicted_eta.isoformat(),
            "delay_minutes": round(self.delay_minutes, 1),
            "status": self.status,
            "is_early": self.is_early,
        }


def classify(delay_minutes: float, config: CommitmentConfig | None = None) -> Status:
    cfg = config or CommitmentConfig()
    if delay_minutes >= cfg.significant_after_min:
        return "significant"
    if delay_minutes > cfg.minor_after_min:
        return "minor"
    return "on_time"


def assess(
    original_eta: datetime, predicted_eta: datetime, config: CommitmentConfig | None = None
) -> Commitment:
    """Compare the prediction with the original promise. The buffer is deliberately not used."""
    for value in (original_eta, predicted_eta):
        if value.tzinfo is None:
            raise ValueError("times must be timezone-aware")
    delay = (predicted_eta - original_eta).total_seconds() / 60
    return Commitment(original_eta, predicted_eta, delay, classify(delay, config))


def planning_target(original_eta: datetime, config: CommitmentConfig | None = None) -> datetime:
    """Arrival time the optimizer should aim for: the promise minus the planning buffer."""
    cfg = config or CommitmentConfig()
    return original_eta - timedelta(minutes=cfg.buffer_min)


def severity(delay_minutes: float, config: CommitmentConfig | None = None) -> Severity:
    cfg = config or CommitmentConfig()
    return "critical" if delay_minutes >= cfg.critical_after_min else "warning"


def alert_action(
    delay_minutes: float, alert_is_open: bool, config: CommitmentConfig | None = None
) -> AlertAction:
    """What to do with the journey's single delay alert after a new prediction."""
    cfg = config or CommitmentConfig()
    if not alert_is_open:
        return "open" if delay_minutes >= cfg.significant_after_min else "none"
    if delay_minutes < cfg.significant_after_min - cfg.clear_margin_min:
        return "resolve"
    return "update"


def alert_message(delay_minutes: float) -> str:
    """Public-safe wording: no passenger or booking details."""
    minutes = round(delay_minutes)
    return f"Running about {minutes} min later than promised at booking."
