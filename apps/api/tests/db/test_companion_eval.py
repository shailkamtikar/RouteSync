"""The evaluation harness, run with the scripted model so it is deterministic."""

import pytest
import yaml

from app.companion import eval as ev

pytestmark = pytest.mark.db

CASES = yaml.safe_load(ev.GOLDEN.read_text(encoding="utf-8"))["cases"]


def test_golden_file_is_well_formed():
    ids = [c["id"] for c in CASES]
    assert len(ids) == len(set(ids)) and len(ids) >= 35
    families = {c["family"] for c in CASES}
    assert families == {"A", "B", "C", "D", "E", "F", "X"}
    assert sum(1 for c in CASES if c["family"] == "X") >= 7
    for case in CASES:
        assert case["fixture"] in {
            "running",
            "not_started",
            "beed_done",
            "past_beed_unrecorded",
            "counts_on",
            "counts_on_boarded",
            "no_gps",
            "stale",
            "slow_ahead",
        }, case["id"]


def test_harness_passes_all_gates_with_the_scripted_model(conn, actor):
    actor.admin()
    results = ev.run_cases(conn, ev.fake_provider_for, CASES)
    summary = ev.summarise(results)
    failed = [(r.case_id, r.reasons) for r in results if not r.passed]
    assert failed == []
    assert ev.gates_met(summary)
    assert summary["privacy_leaks"] == 0 and summary["adversarial_pass_rate"] == 1.0
    assert all(r.tools for r in results)  # every answer was grounded in a tool call


def test_judge_catches_leaks_and_missing_facts():
    from app.companion.orchestrator import ChatResult

    case = {
        "id": "T",
        "family": "X",
        "question": "q",
        "must_contain": ["beed"],
        "must_not_contain": ["latur"],
    }
    bad = ev.judge(case, ChatResult("Asha goes via Latur, phone 9800000000"))
    assert not bad.passed and bad.leaked and len(bad.reasons) == 3
    good = ev.judge(case, ChatResult("Next stop Beed."))
    assert good.passed


def test_report_lists_every_case(conn, actor):
    actor.admin()
    results = ev.run_cases(conn, ev.fake_provider_for, CASES[:3])
    text = ev.report_markdown(ev.summarise(results), results, "fake", "scripted")
    for case in CASES[:3]:
        assert case["id"] in text and case["question"] in text
    assert "Gates met" in text


def test_fixtures_leave_nothing_behind(conn, actor):
    actor.admin()
    before = conn.execute("select count(*) from public.journeys").fetchone()[0]
    ev.run_cases(conn, ev.fake_provider_for, CASES[:2])
    assert conn.execute("select count(*) from public.journeys").fetchone()[0] == before
