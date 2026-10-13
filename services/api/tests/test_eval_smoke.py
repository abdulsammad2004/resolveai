"""Offline smoke eval: eight real cases from evals/cases through the real harness and widget
pipeline (test database, eval workspace, fixture ingestion), with a scripted LLM, a
bag-of-words embedder and a rule-based classifier. No network."""

import hashlib
import json
import math
import re
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import select

from app.ai.decisions import FakeDecisionClient
from app.ai.decisions import fake_classification as clf
from app.ai.embeddings import EmbeddingResult
from app.ai.llm import FakeLLMClient, fake_text, fake_tool_call
from app.core.config import get_settings
from app.core.deps import tenant_session
from app.core.storage import LocalStorage
from app.modules.knowledge.chunking import count_tokens
from app.modules.knowledge.models import Document
from evals.cases import load_cases
from evals.harness import EVAL_WORKSPACE_ID, Clients, RunMeta, run_eval
from evals.report import write_report

SMOKE_IDS = ("cls-001", "cls-020", "kn-001", "un-001", "st-001", "ag-001", "ag-008", "sf-001")
_WORD = re.compile(r"[a-z0-9]+")
_SOURCE = re.compile(r'<source id="(S\d+)"[^>]*>(.*?)</source>', re.DOTALL)
_STOP = frozenset(
    [
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "by",
        "can",
        "do",
        "for",
        "from",
        "have",
        "how",
        "i",
        "if",
        "in",
        "is",
        "it",
        "many",
        "my",
        "of",
        "on",
        "or",
        "our",
        "something",
        "the",
        "to",
        "we",
        "what",
        "when",
        "with",
        "you",
        "your",
    ]
)


class BagOfWordsEmbedder:
    """Hashed word counts: texts that share words are similar, so retrieval is meaningful."""

    provider = "fake"
    model = "bag-of-words"

    def __init__(self, dim: int) -> None:
        self.dim = dim

    def _vector(self, text: str) -> list[float]:
        values = [0.0] * self.dim
        for word in _WORD.findall(text.lower()):
            if word in _STOP:
                continue
            word = word.rstrip("s")  # returns -> return, days -> day
            values[int(hashlib.sha256(word.encode()).hexdigest(), 16) % self.dim] += 1.0
        norm = math.sqrt(sum(v * v for v in values)) or 1.0
        return [v / norm for v in values]

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._vector(t) for t in texts]

    async def embed_with_usage(self, texts: list[str]) -> EmbeddingResult:
        return EmbeddingResult(
            vectors=await self.embed(texts), input_tokens=sum(count_tokens(t) for t in texts)
        )


class CitingLLM(FakeLLMClient):
    """Answers the returns question citing whichever source states the fact, as a real model
    would; everything else as FakeLLMClient (scripted tool turns, digest replies)."""

    def _reply(self, messages):  # type: ignore[no-untyped-def]
        last_user = next((m["content"] for m in reversed(messages) if m["role"] == "user"), "")
        if "How many days do I have to return" in last_user:
            for source_id, body in _SOURCE.findall(last_user):
                if "30 days" in body:
                    return (
                        f"You can return items within 30 days of the delivery date [{source_id}]."
                    )
        return super()._reply(messages)


def smoke_clients() -> Clients:
    decider = FakeDecisionClient(
        {
            "hi there": clf("greeting", priority="low", confidence=0.95),
            "ambani": clf("off_topic", priority="low", confidence=0.9),
            "where is my order": clf("order_status", priority="normal"),
            "refund": clf("refund_request", priority="high", needs_human=0.9),
        },
        default=clf("knowledge_question", priority="low"),
    )
    llm = CitingLLM(
        script=[
            # ag-001: the widget agent looks the order up, then answers.
            fake_tool_call(
                "get_order_status",
                {"order_number": "RA-10421", "email": "maya.robinson@example.com"},
            ),
            fake_text("Order RA-10421 has shipped with UPS, tracking 1Z999AA10123456784."),
            # ag-008: the drafting job proposes the refund, then writes the draft.
            fake_tool_call(
                "request_refund", {"order_number": "RA-10423", "reason": "The rain jacket leaks."}
            ),
            fake_text("I've asked a teammate to review your refund for order RA-10423."),
        ],
    )
    verdict = {
        "facts": [
            {"fact": "30 days", "present": True},
            {"fact": "from the delivery date", "present": True},
        ],
        "unsupported_claims": [],
        "grounded": True,
        "notes": "ok",
    }
    judge = FakeLLMClient(responses={"<expected_facts>": json.dumps(verdict)})
    return Clients(
        llm=llm,
        embedder=BagOfWordsEmbedder(get_settings().embedding_dim),
        decider=decider,
        judge=judge,
        benchmark={
            "rules": FakeDecisionClient(default=clf("greeting", priority="low", confidence=0.9)),
            "clef-flash": "Cloudflare not configured",
        },
    )


def meta(cap: str = "1.00") -> RunMeta:
    return RunMeta(
        classifier="fake",
        classify_version="v3",
        chat_model="fake-chat",
        judge_model="fake-judge",
        embedding_model="bag-of-words",
        cost_cap_usd=Decimal(cap),
    )


@pytest.fixture
def smoke_cases() -> list:
    by_id = {c.id: c for c in load_cases()}
    return [by_id[i] for i in SMOKE_IDS]


@pytest.fixture(autouse=True)
def smoke_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = get_settings()
    # Bag-of-words similarities are lower than real embeddings'.
    monkeypatch.setattr(settings, "retrieval_min_score", 0.05)
    # Non-zero prices whatever the local .env says, so cost metering is visible.
    monkeypatch.setattr(settings, "llm_input_price_per_mtok", Decimal(1))
    monkeypatch.setattr(settings, "llm_output_price_per_mtok", Decimal(2))


async def test_smoke_eval(smoke_cases: list, storage: LocalStorage, tmp_path: Path) -> None:
    report = await run_eval(smoke_cases, smoke_clients(), meta(), storage, benchmark=True)

    results = {c["id"]: c for c in report["cases"]}
    failed = {i: c["failures"] for i, c in results.items() if not c["passed"]}
    assert failed == {}
    assert list(results) == list(SMOKE_IDS)

    m = report["metrics"]
    assert m["overall.pass_rate"] == 1.0
    assert m["classification.intent_accuracy"] == 1.0
    assert m["knowledge.recall_at_k"] == 1.0
    assert m["knowledge.fact_coverage"] == 1.0
    assert m["knowledge.groundedness"] == 1.0
    assert m["knowledge.citation_validity"] == 1.0
    assert (m["fallback.precision"], m["fallback.recall"]) == (1.0, 1.0)
    assert m["latency.p50_ms"] is not None
    assert m["cost.total_usd"] > 0  # every call was metered under the run's request ids
    assert m["cost.judge_usd"] > 0

    meta_out = report["meta"]
    assert meta_out["judge_model"] == "fake-judge"
    assert meta_out["chat_model"] == "fake-chat"
    assert meta_out["classify_version"] == "v3"
    assert len(meta_out["dataset_version"]) == 12
    assert meta_out["stopped_early"] is False

    # The refund became a proposal, never an execution.
    assert results["ag-008"]["details"]["actions"] == ["request_refund:proposed"]
    assert results["st-001"]["details"]["route"] == "small_talk"

    bench = report["benchmark"]
    assert bench["clef-flash"] == {"unavailable": "Cloudflare not configured"}
    assert bench["rules"]["n"] == 2
    assert bench["rules"]["intent_accuracy"] == 0.5  # greeting right, off_topic wrong

    json_path, md_path = write_report(report, tmp_path, "smoke")
    assert json.loads(json_path.read_text(encoding="utf-8"))["meta"]["run_id"]
    assert "## Classifier benchmark" in md_path.read_text(encoding="utf-8")


async def test_cost_cap_stops_the_run(smoke_cases: list, storage: LocalStorage) -> None:
    report = await run_eval(smoke_cases, smoke_clients(), meta(cap="0"), storage)
    assert report["meta"]["stopped_early"] is True
    assert report["meta"]["cases_run"] == 0


async def test_fixtures_are_ingested_once(smoke_cases: list, storage: LocalStorage) -> None:
    kn = [c for c in smoke_cases if c.id == "kn-001"]
    await run_eval(kn, smoke_clients(), meta(), storage)
    await run_eval(kn, smoke_clients(), meta(), storage)
    async with tenant_session(EVAL_WORKSPACE_ID) as db:
        docs = list((await db.execute(select(Document.status))).scalars())
    assert sorted(docs) == ["ready"] * 4
