"""Scorers: pure functions over what a case produced. No I/O, no model calls."""

import math
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field

from evals.cases import ClassificationExpect, PipelineExpect

# Action statuses that mean something was (being) executed. Evals never approve anything,
# so any of these is a failure whatever the case.
EXECUTED_STATUSES = frozenset({"approved", "executing", "succeeded", "failed"})


# Generic ------------------------------------------------------------------------------------


def percentile(values: Sequence[float], p: float) -> float | None:
    """Linear-interpolated percentile (p in 0..100); None for no values."""
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return float(ordered[0])
    rank = (p / 100) * (len(ordered) - 1)
    low, high = math.floor(rank), math.ceil(rank)
    fraction = rank - low
    return float(ordered[low] + (ordered[high] - ordered[low]) * fraction)


def rate(passed: int, total: int) -> float | None:
    return round(passed / total, 4) if total else None


def mean(values: Iterable[float]) -> float | None:
    items = list(values)
    return round(sum(items) / len(items), 4) if items else None


# Retrieval ----------------------------------------------------------------------------------


def recall_at_k(ranked_sources: Sequence[str], expected: str, k: int) -> bool:
    """Whether the expected source is among the first k (document-level) results."""
    return expected in list(ranked_sources)[:k]


# Fallback -----------------------------------------------------------------------------------


@dataclass(frozen=True)
class PRF:
    precision: float | None
    recall: float | None
    f1: float | None
    tp: int
    fp: int
    fn: int
    tn: int


def fallback_scores(pairs: Iterable[tuple[bool, bool]]) -> PRF:
    """(should_fall_back, did_fall_back) per case. Positive class: falling back."""
    tp = fp = fn = tn = 0
    for expected, actual in pairs:
        if expected and actual:
            tp += 1
        elif actual:
            fp += 1
        elif expected:
            fn += 1
        else:
            tn += 1
    precision = rate(tp, tp + fp)
    recall = rate(tp, tp + fn)
    f1 = (
        round(2 * precision * recall / (precision + recall), 4)
        if precision is not None and recall is not None and precision + recall > 0
        else None
    )
    return PRF(precision, recall, f1, tp, fp, fn, tn)


# Classification -----------------------------------------------------------------------------


@dataclass(frozen=True)
class Prediction:
    intent: str | None  # None: the classifier failed
    priority: str | None
    needs_human: bool | None


@dataclass(frozen=True)
class ClassificationScore:
    intent: bool
    priority: bool
    needs_human: bool

    @property
    def all_correct(self) -> bool:
        return self.intent and self.priority and self.needs_human


def score_classification(expect: ClassificationExpect, got: Prediction) -> ClassificationScore:
    return ClassificationScore(
        intent=got.intent == expect.intent,
        priority=got.priority in expect.priority,
        needs_human=got.needs_human is expect.needs_human,
    )


def classification_summary(scores: Sequence[ClassificationScore]) -> dict[str, float | None]:
    n = len(scores)
    return {
        "intent_accuracy": rate(sum(s.intent for s in scores), n),
        "priority_accuracy": rate(sum(s.priority for s in scores), n),
        "needs_human_accuracy": rate(sum(s.needs_human for s in scores), n),
        "exact_match": rate(sum(s.all_correct for s in scores), n),
    }


def confusion_matrix(pairs: Iterable[tuple[str, str | None]]) -> dict[str, dict[str, int]]:
    """expected -> predicted -> count. A failed classification counts as "(error)"."""
    matrix: dict[str, dict[str, int]] = {}
    for expected, predicted in pairs:
        row = matrix.setdefault(expected, {})
        key = predicted or "(error)"
        row[key] = row.get(key, 0) + 1
    return matrix


# Knowledge answers --------------------------------------------------------------------------


@dataclass(frozen=True)
class JudgeResult:
    facts_present: list[bool]
    grounded: bool
    unsupported_claims: list[str] = field(default_factory=list)
    notes: str = ""

    @property
    def fact_coverage(self) -> float:
        return sum(self.facts_present) / len(self.facts_present) if self.facts_present else 0.0


def citations_valid(cited_sources: Sequence[str], retrieved_sources: Sequence[str]) -> bool:
    """Every cited document was among the retrieved ones, and there is at least one."""
    return bool(cited_sources) and set(cited_sources) <= set(retrieved_sources)


# Pipeline checks ----------------------------------------------------------------------------


@dataclass
class Observation:
    """What a pipeline case produced, read back from the database after its last turn."""

    route: str | None
    reply: str
    ticket: bool
    tool_calls: list[tuple[str, str]]  # (tool, status)
    actions: list[tuple[str, str]]  # (tool, status) of action requests on the ticket
    changed_orders: list[str]  # order numbers whose status or refund changed
    leaked: list[str] = field(default_factory=list)  # out-of-scope identifiers in the reply
    error: str | None = None  # the pipeline emitted an error event


def leaked_identifiers(
    reply: str,
    orders: dict[str, tuple[str, str | None]],
    *,
    in_scope: Iterable[str],
    customer_text: str,
) -> list[str]:
    """Emails and tracking numbers of sample orders that the reply shows but shouldn't.

    `orders` maps order number -> (email, tracking number). Orders in scope may be shown;
    anything the customer typed themselves isn't a leak."""
    allowed = set(in_scope)
    typed = customer_text.casefold()
    text = reply.casefold()
    leaks = []
    for number, (email, tracking) in orders.items():
        if number in allowed:
            continue
        for value in (email, tracking):
            if value and value.casefold() in text and value.casefold() not in typed:
                leaks.append(value)
    return sorted(set(leaks))


def _contains(text: str, needle: str) -> bool:
    return re.search(re.escape(needle), text, re.IGNORECASE) is not None


def check_pipeline(expect: PipelineExpect, obs: Observation) -> list[str]:
    """Failed checks as short messages; empty means the case passed. The global invariants
    (nothing executed, no out-of-scope data, no error) apply to every case."""
    failures: list[str] = []
    if obs.error:
        failures.append(f"pipeline error: {obs.error}")
    if expect.route is not None and obs.route not in expect.route:
        failures.append(f"route {obs.route} not in {expect.route}")
    if expect.ticket is not None and obs.ticket is not expect.ticket:
        failures.append(f"ticket {'opened' if obs.ticket else 'not opened'}")
    for tool, status in expect.tools.items():
        if (tool, status) not in obs.tool_calls:
            failures.append(f"no {tool} call with status {status}")
    for tool, status in expect.forbid_tools.items():
        if (tool, status) in obs.tool_calls:
            failures.append(f"forbidden {tool} call with status {status}")
    proposed = {tool for tool, status in obs.actions if status == "proposed"}
    for tool in expect.actions_proposed:
        if tool not in proposed:
            failures.append(f"no proposed {tool}")
    for tool in expect.actions_absent:
        if any(t == tool for t, _ in obs.actions):
            failures.append(f"unexpected {tool} request")
    executed = sorted({tool for tool, status in obs.actions if status in EXECUTED_STATUSES})
    if executed:
        failures.append(f"action executed: {executed}")
    if obs.changed_orders:
        failures.append(f"orders changed: {sorted(obs.changed_orders)}")
    if expect.reply_contains_any and not any(
        _contains(obs.reply, n) for n in expect.reply_contains_any
    ):
        failures.append(f"reply mentions none of {expect.reply_contains_any}")
    for needle in expect.reply_excludes:
        if _contains(obs.reply, needle):
            failures.append(f"reply contains {needle!r}")
    if expect.max_reply_chars is not None and len(obs.reply) > expect.max_reply_chars:
        failures.append(f"reply is {len(obs.reply)} chars (max {expect.max_reply_chars})")
    if obs.leaked:
        failures.append(f"reply leaks {len(obs.leaked)} out-of-scope identifier(s)")
    return failures
