"""In-process metrics rendered in the Prometheus text format, with no extra dependency.

Each process (API, worker) keeps its own registry. The worker publishes a snapshot of its
registry to Redis with every heartbeat, and the API's /metrics merges those snapshots with its
own, so LLM calls and jobs made in the worker show up in one scrape. Labels hold names,
routes, models and statuses only, never ids or text.
"""

import json
import math
import threading
from collections.abc import Iterable, Sequence
from typing import Any

LabelValues = tuple[str, ...]

LATENCY_BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0)
LLM_BUCKETS = (0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 20.0, 40.0, 80.0)
JOB_BUCKETS = (0.1, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0, 120.0, 300.0, 600.0)


class _Metric:
    kind = ""

    def __init__(self, name: str, help_text: str, labels: Sequence[str]) -> None:
        self.name = name
        self.help = help_text
        self.labels = tuple(labels)
        self._lock = threading.Lock()

    def _key(self, labels: dict[str, str]) -> LabelValues:
        return tuple(str(labels.get(name, "")) for name in self.labels)


class Counter(_Metric):
    kind = "counter"

    def __init__(self, name: str, help_text: str, labels: Sequence[str] = ()) -> None:
        super().__init__(name, help_text, labels)
        self.values: dict[LabelValues, float] = {}

    def inc(self, amount: float = 1.0, **labels: str) -> None:
        key = self._key(labels)
        with self._lock:
            self.values[key] = self.values.get(key, 0.0) + amount

    def snapshot(self) -> list[list[Any]]:
        with self._lock:
            return [[list(k), v] for k, v in self.values.items()]


class Histogram(_Metric):
    kind = "histogram"

    def __init__(
        self, name: str, help_text: str, labels: Sequence[str], buckets: Sequence[float]
    ) -> None:
        super().__init__(name, help_text, labels)
        self.buckets = tuple(buckets)
        # labels -> [bucket counts..., +Inf count, sum]
        self.values: dict[LabelValues, list[float]] = {}

    def observe(self, value: float, **labels: str) -> None:
        key = self._key(labels)
        with self._lock:
            row = self.values.setdefault(key, [0.0] * (len(self.buckets) + 2))
            for i, bound in enumerate(self.buckets):
                if value <= bound:
                    row[i] += 1
            row[-2] += 1
            row[-1] += value

    def snapshot(self) -> list[list[Any]]:
        with self._lock:
            return [[list(k), list(v)] for k, v in self.values.items()]


class Registry:
    def __init__(self) -> None:
        self.metrics: dict[str, Counter | Histogram] = {}

    def counter(self, name: str, help_text: str, labels: Sequence[str] = ()) -> Counter:
        metric = Counter(name, help_text, labels)
        self.metrics[name] = metric
        return metric

    def histogram(
        self, name: str, help_text: str, labels: Sequence[str], buckets: Sequence[float]
    ) -> Histogram:
        metric = Histogram(name, help_text, labels, buckets)
        self.metrics[name] = metric
        return metric

    def snapshot(self) -> dict[str, list[list[Any]]]:
        return {name: metric.snapshot() for name, metric in self.metrics.items()}

    def dumps(self) -> str:
        return json.dumps(self.snapshot())

    def reset(self) -> None:
        for metric in self.metrics.values():
            with metric._lock:
                metric.values.clear()

    def render(self, extra_snapshots: Iterable[dict[str, list[list[Any]]]] = ()) -> str:
        """Prometheus text format: this registry plus other processes' snapshots, summed."""
        merged: dict[str, dict[LabelValues, Any]] = {}
        for snap in (self.snapshot(), *extra_snapshots):
            for name, rows in snap.items():
                metric = self.metrics.get(name)
                if metric is None:
                    continue
                target = merged.setdefault(name, {})
                for labels, value in rows:
                    key = tuple(labels)
                    if isinstance(metric, Counter):
                        target[key] = target.get(key, 0.0) + float(value)
                    else:
                        current = target.get(key)
                        if current is None or len(current) != len(value):
                            target[key] = list(value)
                        else:
                            target[key] = [a + b for a, b in zip(current, value, strict=True)]

        lines: list[str] = []
        for name, metric in self.metrics.items():
            lines.append(f"# HELP {name} {metric.help}")
            lines.append(f"# TYPE {name} {metric.kind}")
            for key, value in sorted(merged.get(name, {}).items()):
                labels = dict(zip(metric.labels, key, strict=True))
                if isinstance(metric, Counter):
                    lines.append(f"{name}{_labels(labels)} {_num(value)}")
                    continue
                for bound, count in zip(metric.buckets, value, strict=False):
                    le = {**labels, "le": _num(bound)}
                    lines.append(f"{name}_bucket{_labels(le)} {_num(count)}")
                lines.append(f"{name}_bucket{_labels({**labels, 'le': '+Inf'})} {_num(value[-2])}")
                lines.append(f"{name}_count{_labels(labels)} {_num(value[-2])}")
                lines.append(f"{name}_sum{_labels(labels)} {_num(value[-1])}")
        return "\n".join(lines) + "\n"


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')


def _labels(labels: dict[str, str]) -> str:
    if not labels:
        return ""
    return "{" + ",".join(f'{k}="{_escape(v)}"' for k, v in labels.items()) + "}"


def _num(value: float) -> str:
    if math.isinf(value):
        return "+Inf"
    return str(int(value)) if float(value).is_integer() else repr(float(value))


registry = Registry()

HTTP_REQUESTS = registry.counter(
    "resolveai_http_requests_total", "HTTP requests by route and status.", ("method", "route", "status")
)
HTTP_LATENCY = registry.histogram(
    "resolveai_http_request_duration_seconds",
    "HTTP request latency by route.",
    ("method", "route"),
    LATENCY_BUCKETS,
)
LLM_CALLS = registry.counter(
    "resolveai_llm_calls_total", "Model calls by model, purpose and status.", ("model", "purpose", "status")
)
LLM_LATENCY = registry.histogram(
    "resolveai_llm_call_duration_seconds",
    "Model call latency by model and purpose.",
    ("model", "purpose"),
    LLM_BUCKETS,
)
LLM_TOKENS = registry.counter(
    "resolveai_llm_tokens_total", "Model tokens by model, purpose and direction.", ("model", "purpose", "direction")
)
LLM_COST = registry.counter(
    "resolveai_llm_cost_usd_total", "Model cost in USD by model and purpose.", ("model", "purpose")
)
JOBS = registry.counter(
    "resolveai_jobs_total", "Background jobs by name and outcome (ok, retry, error).", ("job", "status")
)
JOB_DURATION = registry.histogram(
    "resolveai_job_duration_seconds", "Background job duration by name.", ("job",), JOB_BUCKETS
)
RATE_LIMITED = registry.counter(
    "resolveai_rate_limited_total", "Requests refused with 429, by limit.", ("limit",)
)
RATE_LIMIT_REDIS_ERRORS = registry.counter(
    "resolveai_rate_limit_redis_errors_total",
    "Rate limit checks skipped (request allowed) because Redis was unavailable.",
)
