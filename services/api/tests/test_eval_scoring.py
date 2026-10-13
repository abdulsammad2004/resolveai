"""Eval scorers, case loading and report comparison: pure code, no database or model calls."""

from pathlib import Path

import pytest

from evals import scoring
from evals.cases import (
    ClassificationExpect,
    PipelineExpect,
    dataset_version,
    load_cases,
    select_cases,
)
from evals.harness import JudgeFact, JudgeVerdict, parse_sse, to_judge_result
from evals.report import compare, lower_is_better, to_markdown

ORDERS = {
    "RA-1": ("maya@example.com", "TRACK-1"),
    "RA-2": ("noah@example.com", "TRACK-2"),
}


def test_percentile_interpolates() -> None:
    assert scoring.percentile([], 50) is None
    assert scoring.percentile([7], 90) == 7
    assert scoring.percentile([1, 2, 3, 4], 50) == 2.5
    assert scoring.percentile([10, 20, 30, 40, 50], 90) == 46
    assert scoring.percentile([3, 1, 2], 0) == 1


def test_recall_at_k() -> None:
    assert scoring.recall_at_k(["shipping", "returns"], "returns", 2)
    assert not scoring.recall_at_k(["shipping", "returns"], "returns", 1)
    assert not scoring.recall_at_k([], "returns", 5)


def test_fallback_precision_and_recall() -> None:
    # (should fall back, did fall back)
    prf = scoring.fallback_scores([(True, True), (True, False), (False, True), (False, False)])
    assert (prf.tp, prf.fn, prf.fp, prf.tn) == (1, 1, 1, 1)
    assert (prf.precision, prf.recall, prf.f1) == (0.5, 0.5, 0.5)
    empty = scoring.fallback_scores([(False, False)])
    assert (empty.precision, empty.recall, empty.f1) == (None, None, None)


def test_classification_scoring_and_confusion() -> None:
    expect = ClassificationExpect(
        intent="order_status", priority=["normal", "low"], needs_human=False
    )
    right = scoring.score_classification(expect, scoring.Prediction("order_status", "low", False))
    wrong = scoring.score_classification(expect, scoring.Prediction("complaint", "high", False))
    failed = scoring.score_classification(expect, scoring.Prediction(None, None, None))
    assert right.all_correct
    assert (wrong.intent, wrong.priority, wrong.needs_human) == (False, False, True)
    assert not failed.needs_human  # a failed classification is never right
    summary = scoring.classification_summary([right, wrong, failed])
    assert summary == {
        "intent_accuracy": 0.3333,
        "priority_accuracy": 0.3333,
        "needs_human_accuracy": 0.6667,
        "exact_match": 0.3333,
    }
    matrix = scoring.confusion_matrix(
        [("order_status", "order_status"), ("order_status", "complaint"), ("off_topic", None)]
    )
    assert matrix == {
        "order_status": {"order_status": 1, "complaint": 1},
        "off_topic": {"(error)": 1},
    }


def test_citations_valid() -> None:
    assert scoring.citations_valid(["returns"], ["returns", "shipping"])
    assert not scoring.citations_valid([], ["returns"])
    assert not scoring.citations_valid(["warranty"], ["returns"])


def test_judge_result_is_positional_and_strict() -> None:
    verdict = JudgeVerdict(
        facts=[JudgeFact(fact="30 days", present=True)],
        unsupported_claims=[],
        grounded=True,
    )
    result = to_judge_result(verdict, 2)
    assert result.facts_present == [True, False]  # the judge skipped a fact: missing
    assert result.fact_coverage == 0.5
    # Claimed grounded but listed an unsupported claim: not grounded.
    contradictory = JudgeVerdict(
        facts=[], unsupported_claims=["free returns forever"], grounded=True
    )
    assert not to_judge_result(contradictory, 0).grounded


def test_leaked_identifiers() -> None:
    reply = "Order RA-1 shipped, tracking TRACK-1. Also noah@example.com and TRACK-2."
    assert scoring.leaked_identifiers(reply, ORDERS, in_scope=["RA-1"], customer_text="") == [
        "TRACK-2",
        "noah@example.com",
    ]
    # Repeating what the customer typed isn't a leak.
    assert (
        scoring.leaked_identifiers(
            "Thanks noah@example.com", ORDERS, in_scope=[], customer_text="I'm NOAH@example.com"
        )
        == []
    )


def obs(**overrides) -> scoring.Observation:
    base = {
        "route": "agent",
        "reply": "Your order shipped with UPS.",
        "ticket": False,
        "tool_calls": [("get_order_status", "ok")],
        "actions": [],
        "changed_orders": [],
    }
    return scoring.Observation(**{**base, **overrides})


def test_check_pipeline_passes() -> None:
    expect = PipelineExpect(
        route=["agent"],
        ticket=False,
        tools={"get_order_status": "ok"},
        reply_contains_any=["ups", "fedex"],
        reply_excludes=["DHL"],
        max_reply_chars=100,
    )
    assert scoring.check_pipeline(expect, obs()) == []


def test_check_pipeline_failures() -> None:
    expect = PipelineExpect(
        route=["small_talk"],
        ticket=False,
        tools={"get_order_status": "not_found"},
        forbid_tools={"get_order_status": "ok"},
        actions_proposed=["request_refund"],
        actions_absent=["request_cancellation"],
        reply_contains_any=["FedEx"],
        reply_excludes=["ups"],
        max_reply_chars=10,
    )
    failures = scoring.check_pipeline(
        expect,
        obs(
            ticket=True,
            actions=[("request_cancellation", "proposed")],
            leaked=["TRACK-2"],
            error="boom",
        ),
    )
    assert len(failures) == 11
    assert failures[0] == "pipeline error: boom"
    assert "route agent not in ['small_talk']" in failures


def test_global_invariants_apply_to_every_case() -> None:
    failures = scoring.check_pipeline(
        PipelineExpect(),
        obs(actions=[("request_refund", "succeeded")], changed_orders=["RA-1"]),
    )
    assert failures == ["action executed: ['request_refund']", "orders changed: ['RA-1']"]


def test_parse_sse() -> None:
    assert parse_sse('event: final\ndata: {"route":"agent"}\n\n') == ("final", {"route": "agent"})
    assert parse_sse(": stream open\n\n") is None


# Cases --------------------------------------------------------------------------------------


def test_repo_cases_load_and_holdout_is_about_a_fifth() -> None:
    cases = load_cases()
    assert len(cases) >= 80
    for category in ("classification", "knowledge"):
        group = [c for c in cases if c.category == category]
        share = sum(c.holdout for c in group) / len(group)
        assert 0.15 <= share <= 0.25, category
    assert {c.category for c in cases} == {
        "classification",
        "knowledge",
        "unanswerable",
        "agent",
        "safety",
        "small_talk",
    }
    assert any(c.lang != "en" for c in cases if c.category == "classification")


def test_select_cases_limits_per_category() -> None:
    cases = load_cases()
    picked = select_cases(cases, limit=2)
    assert len(picked) == 12  # 2 per category
    only = select_cases(cases, categories=["safety"], limit=1)
    assert [c.category for c in only] == ["safety"]


def test_invalid_cases_are_rejected(tmp_path: Path) -> None:
    (tmp_path / "bad.yaml").write_text(
        "- id: ag-x\n  category: agent\n  turns: [hi]\n  expect: {actions_proposed: [request_refund]}\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="draft: true"):
        load_cases(tmp_path)


def test_dataset_version_changes_with_the_data(tmp_path: Path) -> None:
    (tmp_path / "cases").mkdir()
    (tmp_path / "fixtures").mkdir()
    (tmp_path / "cases" / "a.yaml").write_bytes(b"- x\r\n")
    first = dataset_version(tmp_path)
    (tmp_path / "cases" / "a.yaml").write_bytes(b"- x\n")
    assert dataset_version(tmp_path) == first  # line endings don't matter
    (tmp_path / "fixtures" / "kb.md").write_text("new doc", encoding="utf-8")
    assert dataset_version(tmp_path) != first


# Reports ------------------------------------------------------------------------------------


def report(metrics: dict, cases: dict[str, bool], **meta) -> dict:
    return {
        "meta": {
            "run_id": "r1",
            "started_at": "2026-10-13T00:00:00+00:00",
            "dataset_version": "abc",
            "chat_model": "m",
            "judge_model": "j",
            "classifier": "llm",
            "classify_version": "v2",
            "embedding_model": "e",
            "cases_run": len(cases),
            "cost_usd": 0.01,
            "cost_cap_usd": 1.0,
            "stopped_early": False,
            **meta,
        },
        "metrics": metrics,
        "cases": [
            {"id": i, "category": "agent", "passed": p, "failures": [] if p else ["x"]}
            for i, p in cases.items()
        ],
    }


def test_lower_is_better() -> None:
    assert lower_is_better("latency.p50_ms")
    assert lower_is_better("cost.total_usd")
    assert not lower_is_better("knowledge.recall_at_k")


def test_compare_finds_regressions_and_flipped_cases() -> None:
    old = report(
        {"agent.pass_rate": 0.9, "safety.pass_rate": 1.0, "latency.p50_ms": 100.0, "gone": 1.0},
        {"a": True, "b": False, "c": True},
    )
    new = report(
        {"agent.pass_rate": 0.95, "safety.pass_rate": 0.9, "latency.p50_ms": 150.0, "added": 1.0},
        {"a": False, "b": True, "c": True, "d": False},
    )
    comparison = compare(old, new)
    assert [c.metric for c in comparison.regressions()] == ["latency.p50_ms", "safety.pass_rate"]
    assert [c.metric for c in comparison.quality_regressions()] == ["safety.pass_rate"]
    assert comparison.newly_failing == ["a"]
    assert comparison.newly_passing == ["b"]
    improved = [c.metric for c in comparison.changes if c.improved()]
    assert improved == ["agent.pass_rate"]
    # Metrics present in only one run are listed but never a regression.
    assert {c.metric: c.delta for c in comparison.changes}["added"] is None
    # Within the tolerance nothing counts: -0.1 on safety, +50 ms on latency.
    assert comparison.regressions(tolerance=60) == []


def test_markdown_lists_meta_failures_and_comparison() -> None:
    old = report({"agent.pass_rate": 1.0}, {"a": True})
    new = report({"agent.pass_rate": 0.5}, {"a": False}, classify_version="v3")
    md = to_markdown(new, compare(old, new))
    for text in (
        "judge model",
        "dataset version",
        "classify version",
        "| v3 |",
        "`a`",
        "REGRESSION",
    ):
        assert text in md
