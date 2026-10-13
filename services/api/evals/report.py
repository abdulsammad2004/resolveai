"""Reports: a JSON document per run, a Markdown summary, and comparison between runs.

Metrics are a flat {name: value} map ("knowledge.recall_at_k", "classification.holdout.
intent_accuracy", ...), so two runs compare name by name. Latency and cost are better when
lower; every other metric is better when higher.
"""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

LOWER_IS_BETTER = ("latency", "cost", "_ms", "_usd")
# Changes smaller than this are noise, not a regression (1 case in 100 is 0.01).
DEFAULT_TOLERANCE = 0.0


def lower_is_better(metric: str) -> bool:
    return any(token in metric for token in LOWER_IS_BETTER)


@dataclass(frozen=True)
class MetricChange:
    metric: str
    old: float | None
    new: float | None

    @property
    def delta(self) -> float | None:
        if self.old is None or self.new is None:
            return None
        return round(self.new - self.old, 4)

    def regressed(self, tolerance: float = DEFAULT_TOLERANCE) -> bool:
        if self.delta is None:
            return False
        worse = self.delta > 0 if lower_is_better(self.metric) else self.delta < 0
        return worse and abs(self.delta) > tolerance

    def improved(self, tolerance: float = DEFAULT_TOLERANCE) -> bool:
        if self.delta is None:
            return False
        better = self.delta < 0 if lower_is_better(self.metric) else self.delta > 0
        return better and abs(self.delta) > tolerance


@dataclass(frozen=True)
class Comparison:
    old_meta: dict[str, Any]
    changes: list[MetricChange]
    newly_failing: list[str]  # case ids that passed before and fail now
    newly_passing: list[str]

    def regressions(self, tolerance: float = DEFAULT_TOLERANCE) -> list[MetricChange]:
        return [c for c in self.changes if c.regressed(tolerance)]

    def quality_regressions(self, tolerance: float = DEFAULT_TOLERANCE) -> list[MetricChange]:
        """Regressions that aren't latency or cost."""
        return [c for c in self.regressions(tolerance) if not lower_is_better(c.metric)]


def compare(old: dict[str, Any], new: dict[str, Any]) -> Comparison:
    old_metrics, new_metrics = old.get("metrics", {}), new.get("metrics", {})
    names = sorted(set(old_metrics) | set(new_metrics))
    changes = [MetricChange(n, old_metrics.get(n), new_metrics.get(n)) for n in names]
    old_cases = {c["id"]: c["passed"] for c in old.get("cases", [])}
    new_cases = {c["id"]: c["passed"] for c in new.get("cases", [])}
    shared = sorted(set(old_cases) & set(new_cases))
    return Comparison(
        old_meta=old.get("meta", {}),
        changes=changes,
        newly_failing=[i for i in shared if old_cases[i] and not new_cases[i]],
        newly_passing=[i for i in shared if not old_cases[i] and new_cases[i]],
    )


def load_report(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_report(report: dict[str, Any], reports_dir: Path, stem: str) -> tuple[Path, Path]:
    reports_dir.mkdir(parents=True, exist_ok=True)
    json_path = reports_dir / f"{stem}.json"
    md_path = reports_dir / f"{stem}.md"
    json_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    md_path.write_text(to_markdown(report), encoding="utf-8")
    return json_path, md_path


# Formatting ---------------------------------------------------------------------------------


def fmt(value: Any) -> str:
    if value is None:
        return "–"
    if isinstance(value, float):
        return f"{value:.4f}".rstrip("0").rstrip(".") if abs(value) < 1000 else f"{value:.0f}"
    return str(value)


def _table(headers: list[str], rows: list[list[Any]]) -> list[str]:
    lines = ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
    lines += ["| " + " | ".join(fmt(v) for v in row) + " |" for row in rows]
    return lines


def comparison_lines(comparison: Comparison) -> list[str]:
    meta = comparison.old_meta
    lines = [
        (
            f"Compared with run `{meta.get('run_id', '?')}` (dataset "
            f"{meta.get('dataset_version')}, classify {meta.get('classify_version')}, "
            f"classifier {meta.get('classifier')})."
        ),
        "",
    ]
    rows = [
        [
            c.metric,
            c.old,
            c.new,
            c.delta,
            "REGRESSION" if c.regressed() else ("better" if c.improved() else ""),
        ]
        for c in comparison.changes
        if c.delta is not None and c.delta != 0
    ]
    lines += (
        _table(["metric", "before", "after", "delta", ""], rows) if rows else ["No metric changed."]
    )
    if comparison.newly_failing:
        lines += ["", f"Newly failing: {', '.join(comparison.newly_failing)}"]
    if comparison.newly_passing:
        lines += ["", f"Newly passing: {', '.join(comparison.newly_passing)}"]
    return lines


def to_markdown(report: dict[str, Any], comparison: Comparison | None = None) -> str:
    meta = report["meta"]
    lines = [
        f"# Eval run {meta['run_id']}",
        "",
        *_table(
            ["field", "value"],
            [
                ["started", meta["started_at"]],
                ["dataset version", meta["dataset_version"]],
                ["chat model", meta["chat_model"]],
                ["judge model", meta["judge_model"]],
                ["classifier", meta["classifier"]],
                ["classify version", meta["classify_version"]],
                ["embedding model", meta["embedding_model"]],
                ["cases run", meta["cases_run"]],
                ["cost (USD)", meta["cost_usd"]],
                ["cost cap (USD)", meta["cost_cap_usd"]],
                ["stopped early", meta["stopped_early"]],
            ],
        ),
        "",
        "## Metrics",
        "",
        *_table(["metric", "value"], [[k, v] for k, v in sorted(report["metrics"].items())]),
    ]
    matrix = report.get("classification", {}).get("confusion")
    if matrix:
        labels = sorted(set(matrix) | {p for row in matrix.values() for p in row})
        lines += [
            "",
            "## Intent confusion matrix (rows: expected, columns: predicted)",
            "",
            *_table(
                ["expected \\ predicted", *labels],
                [[e, *[matrix[e].get(p, 0) or "" for p in labels]] for e in sorted(matrix)],
            ),
        ]
    benchmark = report.get("benchmark")
    if benchmark:
        lines += ["", "## Classifier benchmark", "", *benchmark_lines(benchmark)]
    failed = [c for c in report["cases"] if not c["passed"]]
    lines += ["", f"## Failed cases ({len(failed)})", ""]
    lines += [
        f"- `{c['id']}`{' (holdout)' if c.get('holdout') else ''}: {'; '.join(c['failures'])}"
        for c in failed
    ] or ["None."]
    if comparison is not None:
        lines += ["", "## Comparison", "", *comparison_lines(comparison)]
    return "\n".join(lines) + "\n"


def benchmark_lines(benchmark: dict[str, Any]) -> list[str]:
    rows = []
    for name, b in benchmark.items():
        if b.get("unavailable"):
            rows.append([name, b["unavailable"], None, None, None, None, None, None, None])
            continue
        rows.append(
            [
                name,
                b["n"],
                b["intent_accuracy"],
                b["priority_accuracy"],
                b["needs_human_accuracy"],
                b["holdout_intent_accuracy"],
                b["latency_p50_ms"],
                b["latency_p90_ms"],
                b["cost_per_1k_usd"],
            ]
        )
    lines = _table(
        [
            "classifier",
            "n",
            "intent acc",
            "priority acc",
            "needs_human acc",
            "holdout intent acc",
            "p50 ms",
            "p90 ms",
            "USD / 1k msgs",
        ],
        rows,
    )
    errors = {n: b.get("errors") for n, b in benchmark.items() if b.get("errors")}
    if errors:
        lines += [
            "",
            "Errors (counted as wrong): " + ", ".join(f"{n}: {e}" for n, e in errors.items()),
        ]
    return lines


def summary_rows(report: dict[str, Any]) -> list[tuple[str, str]]:
    """The headline numbers for the terminal."""
    m = report["metrics"]
    keys = [
        "overall.pass_rate",
        "classification.intent_accuracy",
        "classification.priority_accuracy",
        "classification.needs_human_accuracy",
        "classification.holdout.intent_accuracy",
        "knowledge.recall_at_k",
        "knowledge.fact_coverage",
        "knowledge.groundedness",
        "knowledge.citation_validity",
        "knowledge.holdout.fact_coverage",
        "fallback.precision",
        "fallback.recall",
        "agent.pass_rate",
        "safety.pass_rate",
        "small_talk.pass_rate",
        "latency.p50_ms",
        "latency.p90_ms",
        "cost.total_usd",
    ]
    return [(k, fmt(m[k])) for k in keys if k in m]
