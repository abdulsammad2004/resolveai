"""Runs eval cases through the real pipeline against the dedicated eval workspace.

The eval workspace has a fixed id and holds only the fictional fixtures: the help docs in
fixtures/kb (ingested here, in-process, skipped when unchanged) and the sample orders. Each
run first resets its conversations, tickets and orders (reset_workspace_demo_data), so runs
don't affect each other; llm_calls rows are kept and every call of a run carries the request
id `eval-<run>-<case>`, which is how cost and latency are read back.

Classification cases call the decision client directly. Every other case opens a fresh widget
conversation and sends its turns through stream_answer(), exactly as the widget does (with an
in-memory token budget, so evals never use the workspace's real daily budget). Cases with
`draft: true` then run the drafting job in-process; nothing is ever approved or executed.
"""

import hashlib
import json
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import delete, func, or_, select

from app.ai.decisions import ContextMessage, DecisionClient, DecisionError
from app.ai.embeddings import EmbeddingClient
from app.ai.llm import ChatMessage, LLMError, UsageReportingLLMClient
from app.ai.prompts import load_prompt
from app.ai.tools.models import ToolCall
from app.ai.usage import LLMCall, LLMPurpose, MeteredLLMClient
from app.core.config import get_settings
from app.core.deps import tenant_session
from app.core.middleware import request_id_ctx
from app.core.storage import Storage, new_storage_key
from app.modules.approvals.models import ActionRequest
from app.modules.conversations import service as conversations
from app.modules.conversations.chat import AnswerRequest, HistoryItem, stream_answer
from app.modules.knowledge.models import Document, DocumentStatus
from app.modules.knowledge.parsing import detect_mime_type
from app.modules.knowledge.retrieval import retrieve
from app.modules.orders import service as orders_service
from app.modules.orders.models import MockOrder
from app.modules.tickets.models import Ticket
from app.modules.workspaces.demo import reset_demo_data
from app.modules.workspaces.models import Workspace
from app.workers import drafting
from app.workers.ingestion import _ingest
from evals import scoring
from evals.cases import (
    CATEGORIES,
    KB_DIR,
    ClassificationCase,
    KnowledgeCase,
    PipelineCase,
    dataset_version,
)

EVAL_WORKSPACE_ID = uuid.UUID("5e0a1e7a-0000-4000-8000-000000e7a100")
EVAL_WORKSPACE_NAME = "ResolveAI Evals"
EVAL_WORKSPACE_SLUG = "resolveai-evals"
JUDGE_PROMPT = ("eval_judge", "v1")
REPLY_CHARS_IN_REPORT = 400


class CostCapReached(Exception):
    pass


# Clients ------------------------------------------------------------------------------------


class UnmeteredBudget:
    """The widget's token budget, in memory: evals never touch the real daily budget."""

    def __init__(self) -> None:
        self.tokens = 0

    async def tokens_used_today(self, workspace_id: uuid.UUID) -> int:
        return 0

    async def add_tokens(self, workspace_id: uuid.UUID, tokens: int) -> None:
        self.tokens += tokens


class LocalLock:
    """The drafting job's ticket lock, in memory (one process, sequential cases)."""

    def __init__(self) -> None:
        self.held: set[str] = set()

    async def acquire(self, key: str, ttl_s: int) -> str | None:
        if key in self.held:
            return None
        self.held.add(key)
        return key

    async def release(self, key: str, token: str) -> None:
        self.held.discard(key)


@dataclass
class Clients:
    llm: UsageReportingLLMClient
    embedder: EmbeddingClient
    decider: DecisionClient
    judge: UsageReportingLLMClient | None  # None: answers aren't judged
    # Pure classifiers for the benchmark: name -> client, or the reason it's unavailable.
    benchmark: dict[str, DecisionClient | str] = field(default_factory=dict)


@dataclass
class RunMeta:
    classifier: str
    classify_version: str
    chat_model: str
    judge_model: str
    embedding_model: str
    cost_cap_usd: Decimal
    limit: int | None = None
    categories: list[str] | None = None


# Workspace and fixtures ---------------------------------------------------------------------


async def ensure_workspace() -> uuid.UUID:
    ws = EVAL_WORKSPACE_ID
    async with tenant_session(ws) as db:
        if await db.scalar(select(Workspace.id).where(Workspace.id == ws)) is None:
            # The slug is unique across tenants (invisible under RLS): suffix it with the id.
            db.add(
                Workspace(
                    id=ws, name=EVAL_WORKSPACE_NAME, slug=f"{EVAL_WORKSPACE_SLUG}-{ws.hex[:8]}"
                )
            )
    return ws


async def reset_workspace(ws: uuid.UUID) -> None:
    async with tenant_session(ws) as db:
        await reset_demo_data(db, ws)
        await orders_service.seed(db, ws)


async def ensure_knowledge(
    ws: uuid.UUID, storage: Storage, embedder: EmbeddingClient
) -> dict[uuid.UUID, str]:
    """Ingest the fixture docs that aren't ready yet; drop docs that are no longer fixtures.
    Returns document id -> fixture stem."""
    fixtures = {p.stem: p.read_bytes() for p in sorted(KB_DIR.glob("*.md"))}
    hashes = {hashlib.sha256(data).hexdigest(): stem for stem, data in fixtures.items()}
    async with tenant_session(ws) as db:
        docs = list(
            (await db.execute(select(Document).where(Document.workspace_id == ws))).scalars()
        )
        stale = [d for d in docs if d.content_hash not in hashes]
        for doc in stale:
            await db.execute(
                delete(Document).where(Document.workspace_id == ws, Document.id == doc.id)
            )
        current = {d.content_hash: d for d in docs if d.content_hash in hashes}
        pending: list[uuid.UUID] = []
        for content_hash, stem in hashes.items():
            doc = current.get(content_hash)
            if doc is None:
                data = fixtures[stem]
                key = new_storage_key(ws)
                await storage.save(key, data)
                filename = f"{stem}.md"
                doc = Document(
                    workspace_id=ws,
                    title=stem.replace("_", " ").title(),
                    filename=filename,
                    mime_type=detect_mime_type(filename, data),
                    size_bytes=len(data),
                    storage_key=key,
                    content_hash=content_hash,
                    status=DocumentStatus.UPLOADED,
                )
                db.add(doc)
                await db.flush()
                current[content_hash] = doc
            if doc.status != DocumentStatus.READY:
                pending.append(doc.id)
        doc_map = {d.id: hashes[h] for h, d in current.items()}
    for doc_id in pending:
        result = await _ingest(doc_id, ws, storage, embedder)
        if result != "ready":
            raise RuntimeError(f"Fixture ingestion returned {result!r} for {doc_map[doc_id]}")
    return doc_map


async def order_snapshot(ws: uuid.UUID) -> dict[str, tuple[str, str, str]]:
    async with tenant_session(ws) as db:
        rows = await db.execute(
            select(
                MockOrder.order_number,
                MockOrder.status,
                MockOrder.refunded_amount,
                MockOrder.applied_action_keys,
            ).where(MockOrder.workspace_id == ws)
        )
        return {n: (s, str(r), json.dumps(k)) for n, s, r, k in rows.all()}


async def order_identifiers(ws: uuid.UUID) -> dict[str, tuple[str, str | None]]:
    async with tenant_session(ws) as db:
        rows = await db.execute(
            select(
                MockOrder.order_number, MockOrder.contact_email, MockOrder.tracking_number
            ).where(MockOrder.workspace_id == ws)
        )
        return {n: (e, t) for n, e, t in rows.all()}


async def spent(ws: uuid.UUID, prefix: str, purpose: str | None = None) -> Decimal:
    async with tenant_session(ws) as db:
        stmt = select(func.coalesce(func.sum(LLMCall.cost_usd), 0)).where(
            LLMCall.workspace_id == ws, LLMCall.request_id.startswith(prefix, autoescape=True)
        )
        if purpose is not None:
            stmt = stmt.where(LLMCall.purpose == purpose)
        return Decimal(await db.scalar(stmt))


# Cases --------------------------------------------------------------------------------------


@dataclass
class CaseResult:
    id: str
    category: str
    holdout: bool
    lang: str
    passed: bool
    failures: list[str]
    latency_ms: float | None
    cost_usd: Decimal = Decimal(0)
    details: dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "category": self.category,
            "holdout": self.holdout,
            "lang": self.lang,
            "passed": self.passed,
            "failures": self.failures,
            "latency_ms": round(self.latency_ms) if self.latency_ms is not None else None,
            "cost_usd": float(self.cost_usd),
            "details": self.details,
        }


async def classify_case(
    case: ClassificationCase, decider: DecisionClient, ws: uuid.UUID, request_id: str
) -> tuple[scoring.Prediction, float, str | None]:
    """(prediction, latency in ms, provider that answered)."""
    context = [ContextMessage(role=t.role, content=t.content) for t in case.context]
    token = request_id_ctx.set(request_id)
    started = time.perf_counter()
    try:
        c = await decider.classify(case.message, context, workspace_id=ws)
    except DecisionError:
        return scoring.Prediction(None, None, None), (time.perf_counter() - started) * 1000, None
    finally:
        request_id_ctx.reset(token)
    threshold = get_settings().needs_human_threshold
    return (
        scoring.Prediction(c.intent, c.priority, c.needs_human_prob >= threshold),
        (time.perf_counter() - started) * 1000,
        c.provider,
    )


async def run_classification_case(
    case: ClassificationCase, clients: Clients, ws: uuid.UUID, run_id: str
) -> CaseResult:
    pred, latency, provider = await classify_case(
        case, clients.decider, ws, f"eval-{run_id}-{case.id}"
    )
    score = scoring.score_classification(case.expect, pred)
    failures = []
    if pred.intent is None:
        failures.append("classification failed")
    else:
        if not score.intent:
            failures.append(f"intent {pred.intent} != {case.expect.intent}")
        if not score.priority:
            failures.append(f"priority {pred.priority} not in {case.expect.priority}")
        if not score.needs_human:
            failures.append(f"needs_human {pred.needs_human} != {case.expect.needs_human}")
    return CaseResult(
        id=case.id,
        category=case.category,
        holdout=case.holdout,
        lang=case.lang,
        passed=score.all_correct,
        failures=failures,
        latency_ms=latency,
        details={
            "expected": case.expect.model_dump(),
            "predicted": {
                "intent": pred.intent,
                "priority": pred.priority,
                "needs_human": pred.needs_human,
            },
            "scores": {
                "intent": score.intent,
                "priority": score.priority,
                "needs_human": score.needs_human,
            },
            "provider": provider,
        },
    )


def parse_sse(chunk: str) -> tuple[str, dict[str, Any]] | None:
    event, data = None, None
    for line in chunk.splitlines():
        if line.startswith("event: "):
            event = line[7:]
        elif line.startswith("data: "):
            data = json.loads(line[6:])
    return (event, data) if event and data is not None else None


async def send_turn(
    ws: uuid.UUID, conversation_id: uuid.UUID, text: str, clients: Clients, request_id: str
) -> dict[str, Any]:
    """One customer message through the widget pipeline; the `final` (or `error`) event."""
    async with tenant_session(ws) as db:
        conversation = await conversations.get_conversation(db, ws, conversation_id)
        message, history = await conversations.add_customer_message(db, conversation, text)
        items = [HistoryItem(role=m.role, content=m.content, route=m.route) for m in history]
    token = request_id_ctx.set(request_id)
    try:
        req = AnswerRequest(
            workspace_id=ws,
            conversation_id=conversation_id,
            customer_message_id=message.id,
            question=text,
            history=items,
            llm=clients.llm,
            embedder=clients.embedder,
            decider=clients.decider,
            limiter=UnmeteredBudget(),
            request_id=request_id,
            jobs=None,  # drafting runs below, only for cases that ask for it
        )
        outcome: dict[str, Any] = {"event": "none"}
        async for chunk in stream_answer(req):
            parsed = parse_sse(chunk)
            if parsed and parsed[0] in ("final", "error"):
                outcome = {"event": parsed[0], **parsed[1]}
        return outcome
    finally:
        request_id_ctx.reset(token)


async def _ticket_id(ws: uuid.UUID, conversation_id: uuid.UUID) -> uuid.UUID | None:
    async with tenant_session(ws) as db:
        return await db.scalar(
            select(Ticket.id)
            .where(Ticket.workspace_id == ws, Ticket.conversation_id == conversation_id)
            .order_by(Ticket.created_at.desc())
            .limit(1)
        )


async def _tool_calls_and_actions(
    ws: uuid.UUID, conversation_id: uuid.UUID, ticket_id: uuid.UUID | None
) -> tuple[list[tuple[str, str]], list[tuple[str, str]]]:
    async with tenant_session(ws) as db:
        scope = [ToolCall.conversation_id == conversation_id]
        if ticket_id is not None:
            scope.append(ToolCall.ticket_id == ticket_id)
        calls = (
            await db.execute(
                select(ToolCall.tool_name, ToolCall.status)
                .where(ToolCall.workspace_id == ws, or_(*scope))
                .order_by(ToolCall.created_at)
            )
        ).all()
        actions = []
        if ticket_id is not None:
            actions = (
                await db.execute(
                    select(ActionRequest.tool_name, ActionRequest.status).where(
                        ActionRequest.workspace_id == ws, ActionRequest.ticket_id == ticket_id
                    )
                )
            ).all()
    return [(n, s) for n, s in calls], [(n, s) for n, s in actions]


class JudgeFact(BaseModel):
    fact: str
    present: bool


class JudgeVerdict(BaseModel):
    facts: list[JudgeFact]
    unsupported_claims: list[str] = Field(default_factory=list)
    grounded: bool
    notes: str = ""


def build_judge_messages(
    prompt: str, question: str, facts: list[str], sources: list[str], answer: str
) -> list[ChatMessage]:
    fact_lines = "\n".join(f"{i + 1}. {f}" for i, f in enumerate(facts))
    source_lines = "\n\n".join(f"[S{i + 1}]\n{s}" for i, s in enumerate(sources))
    return [
        {"role": "system", "content": prompt},
        {
            "role": "user",
            "content": (
                f"<question>\n{question}\n</question>\n\n"
                f"<expected_facts>\n{fact_lines}\n</expected_facts>\n\n"
                f"<sources>\n{source_lines}\n</sources>\n\n"
                f"<answer>\n{answer}\n</answer>"
            ),
        },
    ]


def to_judge_result(verdict: JudgeVerdict, n_facts: int) -> scoring.JudgeResult:
    """Positional: a judge that returns fewer facts than expected leaves the rest absent."""
    present = [f.present for f in verdict.facts[:n_facts]]
    present += [False] * (n_facts - len(present))
    return scoring.JudgeResult(
        facts_present=present,
        grounded=verdict.grounded and not verdict.unsupported_claims,
        unsupported_claims=verdict.unsupported_claims[:8],
        notes=verdict.notes[:200],
    )


async def judge_answer(
    clients: Clients,
    ws: uuid.UUID,
    request_id: str,
    case: KnowledgeCase,
    sources: list[str],
    answer: str,
) -> scoring.JudgeResult | str:
    """The judge's result, or an error message."""
    if clients.judge is None:
        return "no judge configured"
    prompt = load_prompt(*JUDGE_PROMPT)
    metered = MeteredLLMClient(
        clients.judge,
        workspace_id=ws,
        purpose=LLMPurpose.EVAL_JUDGE,
        prompt_version=prompt.id,
        request_id=request_id,
    )
    messages = build_judge_messages(prompt.text, case.question, case.expect.facts, sources, answer)
    try:
        verdict = await metered.complete_structured(messages, JudgeVerdict)
    except LLMError as exc:
        return f"judge failed: {type(exc.__cause__ or exc).__name__}"
    return to_judge_result(verdict, len(case.expect.facts))


async def run_pipeline_case(
    case: KnowledgeCase | PipelineCase,
    clients: Clients,
    ws: uuid.UUID,
    run_id: str,
    doc_map: dict[uuid.UUID, str],
    identifiers: dict[str, tuple[str, str | None]],
) -> CaseResult:
    request_id = f"eval-{run_id}-{case.id}"
    before = await order_snapshot(ws)
    async with tenant_session(ws) as db:
        conversation, _ = await conversations.start_session(db, ws, None, None)
        conversation_id = conversation.id

    final: dict[str, Any] = {}
    latency = 0.0
    for turn in case.turns:
        started = time.perf_counter()
        final = await send_turn(ws, conversation_id, turn, clients, request_id)
        latency += (time.perf_counter() - started) * 1000

    ticket_id = await _ticket_id(ws, conversation_id)
    draft_outcome = None
    if isinstance(case, PipelineCase) and case.draft and ticket_id is not None:
        token = request_id_ctx.set(request_id)
        try:
            draft_outcome = await drafting.process_ticket(
                {
                    "ticket_lock": LocalLock(),
                    "llm": clients.llm,
                    "embedder": clients.embedder,
                    "job_try": drafting.MAX_TRIES,  # no arq retries here: fail once, record it
                },
                str(ticket_id),
                str(ws),
            )
        finally:
            request_id_ctx.reset(token)

    tool_calls, actions = await _tool_calls_and_actions(ws, conversation_id, ticket_id)
    after = await order_snapshot(ws)
    reply = str(final.get("content") or "")
    in_scope = case.orders_in_scope if isinstance(case, PipelineCase) else []
    obs = scoring.Observation(
        route=final.get("route"),
        reply=reply,
        ticket=ticket_id is not None,
        tool_calls=tool_calls,
        actions=actions,
        changed_orders=[n for n in after if before.get(n) != after[n]],
        leaked=scoring.leaked_identifiers(
            reply, identifiers, in_scope=in_scope, customer_text=" ".join(case.turns)
        ),
        error=final.get("message") if final.get("event") != "final" else None,
    )
    details: dict[str, Any] = {
        "route": obs.route,
        "ticket": obs.ticket,
        "tool_calls": [f"{n}:{s}" for n, s in tool_calls],
        "actions": [f"{n}:{s}" for n, s in actions],
        "reply": reply[:REPLY_CHARS_IN_REPORT],
    }
    if draft_outcome is not None:
        details["draft"] = draft_outcome

    if isinstance(case, PipelineCase):
        failures = scoring.check_pipeline(case.expect, obs)
    else:
        failures = await _score_knowledge(
            case, clients, ws, request_id, doc_map, obs, final, details
        )
    return CaseResult(
        id=case.id,
        category=case.category,
        holdout=case.holdout,
        lang=case.lang,
        passed=not failures,
        failures=failures,
        latency_ms=latency,
        details=details,
    )


async def _score_knowledge(
    case: KnowledgeCase,
    clients: Clients,
    ws: uuid.UUID,
    request_id: str,
    doc_map: dict[uuid.UUID, str],
    obs: scoring.Observation,
    final: dict[str, Any],
    details: dict[str, Any],
) -> list[str]:
    settings = get_settings()
    token = request_id_ctx.set(request_id)
    try:
        async with tenant_session(ws) as db:
            # Every candidate, unfiltered, for the ranking; then the same cut as the pipeline.
            result = await retrieve(
                db,
                case.question,
                top_k=settings.retrieval_top_k,
                workspace_id=ws,
                embedder=clients.embedder,
                min_score=-1.0,
                keep=settings.retrieval_top_k,
            )
    finally:
        request_id_ctx.reset(token)
    ranked = list(dict.fromkeys(doc_map.get(c.document_id, "?") for c in result.chunks))
    kept_chunks = [c for c in result.chunks if c.score >= settings.retrieval_min_score][
        : settings.retrieval_keep
    ]
    kept = list(dict.fromkeys(doc_map.get(c.document_id, "?") for c in kept_chunks))
    cited = list(
        dict.fromkeys(
            doc_map.get(uuid.UUID(c["document_id"]), "?") for c in final.get("citations") or []
        )
    )
    answered = obs.route == "answer"
    details.update(
        {
            "expected_source": case.expect.source,
            "ranked_sources": ranked,
            "kept_sources": kept,
            "top_score": result.chunks[0].score if result.chunks else None,
            "recall_at_k": scoring.recall_at_k(kept, case.expect.source, settings.retrieval_keep),
            "recall_at_top_k": scoring.recall_at_k(
                ranked, case.expect.source, settings.retrieval_top_k
            ),
            "answered": answered,
            "cited_sources": cited,
            "citations_valid": scoring.citations_valid(cited, kept) if answered else None,
            "cites_expected_source": case.expect.source in cited if answered else None,
        }
    )
    failures = []
    if obs.error:
        failures.append(f"pipeline error: {obs.error}")
    if not details["recall_at_k"]:
        failures.append(f"{case.expect.source} not retrieved in top {settings.retrieval_keep}")
    if not answered:
        failures.append(f"not answered (route {obs.route})")
        details["fact_coverage"] = 0.0
        return failures
    if not details["citations_valid"]:
        failures.append("invalid citations")
    if not details["cites_expected_source"]:
        failures.append(f"doesn't cite {case.expect.source}")
    judged = await judge_answer(
        clients, ws, request_id, case, [c.content for c in kept_chunks], obs.reply
    )
    if isinstance(judged, str):
        failures.append(judged)
        details["fact_coverage"] = None
        return failures
    details.update(
        {
            "fact_coverage": round(judged.fact_coverage, 4),
            "facts_present": judged.facts_present,
            "grounded": judged.grounded,
            "unsupported_claims": judged.unsupported_claims,
            "judge_notes": judged.notes,
        }
    )
    if judged.fact_coverage < 1.0:
        missing = [
            f for f, ok in zip(case.expect.facts, judged.facts_present, strict=True) if not ok
        ]
        failures.append(f"missing facts: {missing}")
    if not judged.grounded:
        failures.append(f"ungrounded: {judged.unsupported_claims}")
    return failures


# Metrics ------------------------------------------------------------------------------------


def _split(results: list[CaseResult]) -> dict[str, list[CaseResult]]:
    return {
        "": results,
        "visible.": [r for r in results if not r.holdout],
        "holdout.": [r for r in results if r.holdout],
    }


def classification_metrics(results: list[CaseResult]) -> tuple[dict[str, Any], dict[str, Any]]:
    metrics: dict[str, Any] = {}
    for prefix, group in _split(results).items():
        if not group:
            continue
        scores = [scoring.ClassificationScore(**r.details["scores"]) for r in group]
        for name, value in scoring.classification_summary(scores).items():
            metrics[f"classification.{prefix}{name}"] = value
    for lang in sorted({r.lang for r in results}):
        group = [r for r in results if r.lang == lang]
        metrics[f"classification.lang.{lang}.intent_accuracy"] = scoring.rate(
            sum(r.details["scores"]["intent"] for r in group), len(group)
        )
    latencies = [r.latency_ms for r in results if r.latency_ms is not None]
    metrics["classification.latency_p50_ms"] = scoring.percentile(latencies, 50)
    metrics["classification.latency_p90_ms"] = scoring.percentile(latencies, 90)
    providers: dict[str, int] = {}
    for r in results:
        key = r.details.get("provider") or "(error)"
        providers[key] = providers.get(key, 0) + 1
    extra = {
        "confusion": scoring.confusion_matrix(
            (r.details["expected"]["intent"], r.details["predicted"]["intent"]) for r in results
        ),
        "providers": providers,
    }
    return metrics, extra


def knowledge_metrics(results: list[CaseResult]) -> dict[str, Any]:
    metrics: dict[str, Any] = {}
    for prefix, group in _split(results).items():
        if not group:
            continue
        answered = [r for r in group if r.details.get("answered")]
        judged = [r for r in answered if r.details.get("grounded") is not None]
        coverage = [
            r.details["fact_coverage"] for r in group if r.details.get("fact_coverage") is not None
        ]
        k = f"knowledge.{prefix}"
        metrics[f"{k}recall_at_k"] = scoring.rate(
            sum(r.details["recall_at_k"] for r in group), len(group)
        )
        metrics[f"{k}recall_at_top_k"] = scoring.rate(
            sum(r.details["recall_at_top_k"] for r in group), len(group)
        )
        metrics[f"{k}answer_rate"] = scoring.rate(len(answered), len(group))
        metrics[f"{k}fact_coverage"] = scoring.mean(coverage)
        metrics[f"{k}groundedness"] = scoring.rate(
            sum(r.details["grounded"] for r in judged), len(judged)
        )
        metrics[f"{k}citation_validity"] = scoring.rate(
            sum(bool(r.details["citations_valid"]) for r in answered), len(answered)
        )
        metrics[f"{k}cites_expected_source"] = scoring.rate(
            sum(bool(r.details["cites_expected_source"]) for r in answered), len(answered)
        )
        metrics[f"{k}pass_rate"] = scoring.rate(sum(r.passed for r in group), len(group))
    return metrics


def build_metrics(results: list[CaseResult]) -> tuple[dict[str, Any], dict[str, Any]]:
    by_category = {c: [r for r in results if r.category == c] for c in CATEGORIES}
    metrics: dict[str, Any] = {
        "overall.pass_rate": scoring.rate(sum(r.passed for r in results), len(results))
    }
    extra: dict[str, Any] = {}
    if by_category["classification"]:
        cls_metrics, extra = classification_metrics(by_category["classification"])
        metrics.update(cls_metrics)
    if by_category["knowledge"]:
        metrics.update(knowledge_metrics(by_category["knowledge"]))
    for category in ("unanswerable", "agent", "safety", "small_talk", "classification"):
        group = by_category[category]
        if group:
            metrics[f"{category}.pass_rate"] = scoring.rate(
                sum(r.passed for r in group), len(group)
            )
    fallback_pairs = [
        (r.category == "unanswerable", r.details.get("route") == "fallback")
        for r in by_category["knowledge"] + by_category["unanswerable"]
    ]
    if fallback_pairs:
        prf = scoring.fallback_scores(fallback_pairs)
        metrics["fallback.precision"] = prf.precision
        metrics["fallback.recall"] = prf.recall
        metrics["fallback.f1"] = prf.f1
    latencies = [
        r.latency_ms for r in results if r.category != "classification" and r.latency_ms is not None
    ]
    metrics["latency.p50_ms"] = scoring.percentile(latencies, 50)
    metrics["latency.p90_ms"] = scoring.percentile(latencies, 90)
    return metrics, extra


# Benchmark ----------------------------------------------------------------------------------


async def run_benchmark(
    cases: list[ClassificationCase],
    clients: Clients,
    ws: uuid.UUID,
    run_id: str,
    check_budget: Callable[[], Any],
) -> dict[str, Any]:
    out: dict[str, Any] = {}
    threshold = get_settings().needs_human_threshold
    for name, client in clients.benchmark.items():
        if isinstance(client, str):
            out[name] = {"unavailable": client}
            continue
        prefix = f"eval-{run_id}-bench-{name}-"
        scores, holdout_intent, latencies, errors = [], [], [], 0
        for case in cases:
            await check_budget()
            pred, latency, _ = await classify_case(case, client, ws, prefix + case.id)
            errors += pred.intent is None
            latencies.append(latency)
            score = scoring.score_classification(case.expect, pred)
            scores.append(score)
            if case.holdout:
                holdout_intent.append(score.intent)
        cost = await spent(ws, prefix)
        summary = scoring.classification_summary(scores)
        out[name] = {
            "n": len(cases),
            **summary,
            "holdout_intent_accuracy": scoring.rate(sum(holdout_intent), len(holdout_intent)),
            "latency_p50_ms": scoring.percentile(latencies, 50),
            "latency_p90_ms": scoring.percentile(latencies, 90),
            "cost_usd": float(cost),
            "cost_per_1k_usd": round(float(cost) / len(cases) * 1000, 6) if cases else None,
            "errors": errors,
            "needs_human_threshold": threshold,
        }
    return out


# Run ----------------------------------------------------------------------------------------


def new_run_id(now: datetime | None = None) -> str:
    now = now or datetime.now(UTC)
    return now.strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:4]


async def run_eval(
    cases: list[ClassificationCase | KnowledgeCase | PipelineCase],
    clients: Clients,
    meta: RunMeta,
    storage: Storage,
    *,
    benchmark: bool = False,
    run_id: str | None = None,
    on_case: Callable[[CaseResult], None] | None = None,
) -> dict[str, Any]:
    run_id = run_id or new_run_id()
    started_at = datetime.now(UTC)
    ws = await ensure_workspace()
    await reset_workspace(ws)
    needs_pipeline = any(not isinstance(c, ClassificationCase) for c in cases)
    doc_map = await ensure_knowledge(ws, storage, clients.embedder) if needs_pipeline else {}
    identifiers = await order_identifiers(ws)
    prefix = f"eval-{run_id}-"
    stopped_early = False

    async def check_budget() -> None:
        if await spent(ws, prefix) >= meta.cost_cap_usd:
            raise CostCapReached

    results: list[CaseResult] = []
    bench: dict[str, Any] = {}
    try:
        for case in cases:
            await check_budget()
            if isinstance(case, ClassificationCase):
                result = await run_classification_case(case, clients, ws, run_id)
            else:
                result = await run_pipeline_case(case, clients, ws, run_id, doc_map, identifiers)
            result.cost_usd = await spent(ws, f"{prefix}{case.id}")
            results.append(result)
            if on_case is not None:
                on_case(result)
        if benchmark:
            cls_cases = [c for c in cases if isinstance(c, ClassificationCase)]
            bench = await run_benchmark(cls_cases, clients, ws, run_id, check_budget)
    except CostCapReached:
        stopped_early = True

    metrics, extra = build_metrics(results)
    total = await spent(ws, prefix)
    judge = await spent(ws, prefix, LLMPurpose.EVAL_JUDGE.value)
    bench_cost = await spent(ws, f"{prefix}bench-")
    metrics["cost.total_usd"] = float(total)
    metrics["cost.judge_usd"] = float(judge)
    metrics["cost.benchmark_usd"] = float(bench_cost)
    metrics["cost.pipeline_usd"] = float(total - judge - bench_cost)
    report: dict[str, Any] = {
        "meta": {
            "run_id": run_id,
            "started_at": started_at.isoformat(timespec="seconds"),
            "finished_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "dataset_version": dataset_version(),
            "chat_model": meta.chat_model,
            "judge_model": meta.judge_model,
            "judge_prompt": "_".join(JUDGE_PROMPT),
            "classifier": meta.classifier,
            "classify_version": meta.classify_version,
            "embedding_model": meta.embedding_model,
            "retrieval": {
                "top_k": get_settings().retrieval_top_k,
                "min_score": get_settings().retrieval_min_score,
                "keep": get_settings().retrieval_keep,
            },
            "categories": meta.categories,
            "limit": meta.limit,
            "cases_selected": len(cases),
            "cases_run": len(results),
            "holdout_cases_run": sum(r.holdout for r in results),
            "cost_usd": float(total),
            "cost_cap_usd": float(meta.cost_cap_usd),
            "stopped_early": stopped_early,
        },
        "metrics": metrics,
        "classification": extra,
        "cases": [r.to_json() for r in results],
    }
    if bench:
        report["benchmark"] = bench
    return report
