import json
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.config import Settings
from app.eta import commitment as cm

PROMISE = datetime(2031, 3, 2, 7, 30, tzinfo=UTC)
CFG = cm.CommitmentConfig()


def at(minutes: float) -> datetime:
    return PROMISE + timedelta(minutes=minutes)


def test_on_time_early_and_late_are_reported_honestly():
    on_time = cm.assess(PROMISE, at(0))
    assert on_time.delay_minutes == 0 and on_time.status == "on_time" and not on_time.is_early
    early = cm.assess(PROMISE, at(-10))
    assert early.delay_minutes == -10 and early.status == "on_time" and early.is_early
    late = cm.assess(PROMISE, at(25))
    assert late.delay_minutes == 25 and late.status == "significant"


@pytest.mark.parametrize(
    ("delay", "expected"),
    [
        (-30, "on_time"),
        (5, "on_time"),
        (5.01, "minor"),
        (14.99, "minor"),
        (15, "significant"),
        (300, "significant"),
    ],
)
def test_classification_boundaries(delay, expected):
    assert cm.classify(delay, CFG) == expected


def test_buffer_aims_earlier_but_never_hides_a_delay():
    buffered = cm.CommitmentConfig(buffer_min=15)
    assert cm.planning_target(PROMISE, buffered) == at(-15)
    assert cm.planning_target(PROMISE) == PROMISE
    # Arriving 10 minutes after the promise is a 10-minute delay, buffer or not.
    result = cm.assess(PROMISE, at(10), buffered)
    assert result.delay_minutes == 10 and result.status == "minor"


def test_assessing_never_changes_the_promise():
    result = cm.assess(PROMISE, at(40))
    assert result.original_eta == PROMISE
    with pytest.raises(AttributeError):
        result.original_eta = at(40)  # type: ignore[misc]


def test_naive_times_are_rejected():
    with pytest.raises(ValueError):
        cm.assess(datetime(2031, 3, 2, 7, 30), at(0))
    with pytest.raises(ValueError):
        cm.assess(PROMISE, datetime(2031, 3, 2, 8, 0))


@pytest.mark.parametrize(
    ("delay", "is_open", "expected"),
    [
        (10, False, "none"),
        (14.9, False, "none"),
        (15, False, "open"),
        (90, False, "open"),
        (20, True, "update"),
        (10.0, True, "update"),  # inside the clear margin: stays open
        (9.99, True, "resolve"),
        (-5, True, "resolve"),
        (-5, False, "none"),
    ],
)
def test_alert_actions_with_hysteresis(delay, is_open, expected):
    assert cm.alert_action(delay, is_open, CFG) == expected


def test_a_delay_hovering_at_the_threshold_does_not_flap():
    open_alert = False
    transitions = 0
    for delay in [14, 16, 14, 16, 12, 16, 11, 10.5, 16, 12]:
        action = cm.alert_action(delay, open_alert, CFG)
        if action == "open":
            open_alert, transitions = True, transitions + 1
        elif action == "resolve":
            open_alert, transitions = False, transitions + 1
    assert transitions == 1 and open_alert is True


def test_severity_and_message_are_public_safe():
    assert cm.severity(30, CFG) == "warning" and cm.severity(60, CFG) == "critical"
    message = cm.alert_message(24.6)
    assert message == "Running about 25 min later than promised at booking."
    assert not re.search(r"\d{6,}|@|booking [A-Z]{2}-", message)


def test_payload_is_json():
    payload = cm.assess(PROMISE, at(25)).to_payload()
    assert json.loads(json.dumps(payload)) == payload
    assert payload["delay_minutes"] == 25 and payload["status"] == "significant"
    assert payload["original_eta"] == PROMISE.isoformat()


@pytest.mark.parametrize(
    "kwargs",
    [
        {"minor_after_min": -1},
        {"minor_after_min": 20},
        {"significant_after_min": 70},
        {"clear_margin_min": 15},
        {"clear_margin_min": -1},
        {"buffer_min": -5},
    ],
)
def test_inconsistent_thresholds_are_rejected(kwargs):
    with pytest.raises(ValueError):
        cm.CommitmentConfig(**kwargs)


def test_settings_build_the_config_and_reject_bad_values(monkeypatch):
    monkeypatch.setenv("DELAY_SIGNIFICANT_AFTER_MIN", "20")
    monkeypatch.setenv("ARRIVAL_BUFFER_MIN", "10")
    config = Settings(_env_file=None).commitment_config()
    assert config.significant_after_min == 20 and config.buffer_min == 10
    monkeypatch.setenv("ARRIVAL_BUFFER_MIN", "-1")
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_no_code_path_can_change_the_booking_promise():
    """The database also forbids it; this guards the application source."""
    offenders = []
    for path in Path(__file__).resolve().parents[2].joinpath("app").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        for match in re.finditer(r"booking_eta_at\s*=", text):
            line = text[: match.start()].count("\n") + 1
            context = text[max(0, match.start() - 120) : match.start()].lower()
            if "update" in context and "set" in context:
                offenders.append(f"{path.name}:{line}")
    assert offenders == []
