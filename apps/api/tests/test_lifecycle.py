import itertools

import pytest

from app.domain.errors import Conflict, Forbidden
from app.domain.lifecycle import STATUSES, TRANSITIONS, allowed_transitions, check_transition


def test_every_status_is_covered_and_targets_exist():
    assert set(STATUSES) == {
        "draft",
        "awaiting_confirmation",
        "ready",
        "published",
        "boarding",
        "in_progress",
        "completed",
        "cancelled",
        "disrupted",
    }
    for options in TRANSITIONS.values():
        assert set(options) <= set(STATUSES)


@pytest.mark.parametrize(("current", "to"), list(itertools.product(STATUSES, STATUSES)))
def test_exhaustive_matrix_for_owner(current, to):
    if to in TRANSITIONS[current]:
        check_transition(current, to, "owner")
    else:
        with pytest.raises(Conflict) as exc:
            check_transition(current, to, "owner")
        assert exc.value.details == {"allowed": list(TRANSITIONS[current])}


@pytest.mark.parametrize("current", [s for s in STATUSES if "cancelled" in TRANSITIONS[s]])
def test_only_owner_can_cancel(current):
    check_transition(current, "cancelled", "owner")
    with pytest.raises(Forbidden):
        check_transition(current, "cancelled", "dispatcher")
    assert "cancelled" not in allowed_transitions(current, "dispatcher")
    assert "cancelled" in allowed_transitions(current, "owner")


@pytest.mark.parametrize("terminal", ["completed", "cancelled"])
def test_terminal_states_allow_nothing(terminal):
    assert allowed_transitions(terminal, "owner") == []
    for to in STATUSES:
        with pytest.raises(Conflict):
            check_transition(terminal, to, "owner")


def test_happy_path_is_reachable_for_a_dispatcher():
    path = [
        "draft",
        "awaiting_confirmation",
        "ready",
        "published",
        "boarding",
        "in_progress",
        "completed",
    ]
    for current, to in itertools.pairwise(path):
        check_transition(current, to, "dispatcher")


def test_no_skipping_ahead():
    for to in ("ready", "published", "boarding", "in_progress", "completed"):
        with pytest.raises(Conflict):
            check_transition("draft", to, "owner")


def test_unknown_role_or_status_is_rejected():
    with pytest.raises(Forbidden):
        check_transition("draft", "awaiting_confirmation", "viewer")
    with pytest.raises(Conflict):
        check_transition("nonsense", "draft", "owner")
