"""Widget replies: classify, route, then answer from the knowledge base, run the agent, or
hand off.

Routing (decide_route): greetings and thanks get a fixed friendly reply; order questions
(and follow-ups to an agent reply, e.g. the customer giving their email) go to the agent
with read-only tools; requests that need a person (refunds, complaints, account changes, or
a high needs-human probability) become a ticket; everything else, including low-confidence
classifications, gets a grounded RAG answer, and a RAG fallback (nothing to cite) also
becomes a ticket. An agent run that can't answer, or a second failed order lookup, hands
off too. Every new or reused ticket gets a reply draft job.

The pipeline runs as its own task and hands SSE events to the response through a queue,
so a customer closing the tab mid-answer does not lose the stored answer or its metering.
Message text is never logged; only ids, counts and outcomes.
"""

import asyncio
import enum
import hashlib
import json
import logging
import re
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import func, select

from app.ai.agent import build_widget_messages, run_agent
from app.ai.decisions import (
    CONTEXT_MESSAGES,
    Classification,
    ContextMessage,
    DecisionClient,
    DecisionError,
)
from app.ai.embeddings import EmbeddingClient
from app.ai.grounding import CITATION_GROUP, extract_citations, format_source, neutralize
from app.ai.llm import ChatMessage, UsageReportingLLMClient
from app.ai.prompts import load_prompt
from app.ai.tools.builtin import GET_ORDER_STATUS, WIDGET_TOOLS
from app.ai.tools.models import ToolCall, ToolCallStatus
from app.ai.tools.registry import Tool, ToolContext
from app.ai.usage import LLMPurpose, MeteredLLMClient
from app.core.config import get_settings
from app.core.deps import tenant_session
from app.modules.conversations import service
from app.modules.conversations.limits import BudgetUnavailableError, WidgetLimiter
from app.modules.conversations.models import Message, MessageRole, MessageRoute
from app.modules.conversations.schemas import Citation, FinalEvent
from app.modules.knowledge.retrieval import RetrievedChunk, retrieve
from app.modules.tickets import service as tickets_service
from app.workers.queue import JobQueue

logger = logging.getLogger("app.conversations.chat")

FALLBACK_MESSAGE = (
    "I couldn't find that in our help docs. Someone from the team can follow up here."
)
ERROR_MESSAGE = "Something went wrong while answering. Please try again."
HANDOFF_MESSAGE = "Thanks — I've passed this to our team and someone will follow up here."
SMALL_TALK_REPLIES: dict[str, tuple[str, ...]] = {
    "greeting": (
        "Hi there! How can I help you today?",
        "Hello! What can I help you with?",
        "Hi! Ask me anything about our products, orders or policies.",
    ),
    "thanks": (
        "You're welcome! Anything else I can help with?",
        "Happy to help! Let me know if there's anything else.",
        "Glad I could help. Have a great day!",
    ),
}
SMALL_TALK_INTENTS = frozenset(SMALL_TALK_REPLIES)
HANDOFF_INTENTS = frozenset({"refund_request", "cancel_order", "complaint", "account_change"})
AGENT_INTENTS = frozenset({"order_status"})
PRESSING_PRIORITIES = frozenset({"high", "urgent"})
PROMPT_NAME, PROMPT_VERSION = "answer", "v1"
AGENT_PROMPT_NAME, AGENT_PROMPT_VERSION = "agent", "v2"
HISTORY_MESSAGES = 6
HISTORY_CHARS = 2000
# After this many order lookups that matched nothing, the conversation goes to a person.
MAX_FAILED_LOOKUPS = 2
LOOKUP_HANDOFF_MESSAGE = (
    "I couldn't find an order matching those details, so I've passed this to our team. "
    "Someone will follow up here."
)

_tasks: set[asyncio.Task[None]] = set()


@dataclass
class HistoryItem:
    role: str
    content: str
    route: str | None = None


@dataclass
class Answer:
    content: str
    citations: list[Citation] = field(default_factory=list)

    @property
    def grounded(self) -> bool:
        return bool(self.citations)


def build_messages(
    system_prompt: str, history: list[HistoryItem], chunks: list[RetrievedChunk], question: str
) -> list[ChatMessage]:
    messages: list[ChatMessage] = [{"role": "system", "content": system_prompt}]
    for item in history[-HISTORY_MESSAGES:]:
        # Old answers cite old sources; drop their markers so ids can't be confused.
        content = CITATION_GROUP.sub("", item.content)[:HISTORY_CHARS].strip()
        if not content:
            continue
        role = "user" if item.role == MessageRole.CUSTOMER else "assistant"
        messages.append({"role": role, "content": neutralize(content)})

    sources = "\n".join(format_source(i, chunk) for i, chunk in enumerate(chunks))
    messages.append(
        {
            "role": "user",
            "content": (
                f"<sources>\n{sources}\n</sources>\n\n"
                f"<customer_message>\n{neutralize(question)}\n</customer_message>"
            ),
        }
    )
    return messages


def validate_citations(text: str, chunks: list[RetrievedChunk]) -> Answer:
    """Keep only [S#] ids that were retrieved. No valid citation left means the fallback."""
    content, citations = extract_citations(text, chunks)
    if not citations or not content:
        return Answer(content=FALLBACK_MESSAGE)
    return Answer(content=content, citations=citations)


def sse(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, separators=(',', ':'))}\n\n"


class Route(enum.StrEnum):
    SMALL_TALK = "small_talk"
    HANDOFF = "handoff"
    KNOWLEDGE = "knowledge"
    AGENT = "agent"


def top_intent(c: Classification) -> str:
    """The most probable intent (falls back to the chosen one without probabilities)."""
    return max(c.intent_probs, key=c.intent_probs.__getitem__) if c.intent_probs else c.intent


def decide_route(c: Classification | None, previous_route: str | None = None) -> Route:
    """Pure routing rules over a classification (None: classification unavailable).

    `previous_route` is the route of the last assistant reply: after an agent reply (e.g.
    "what's the email on the order?") the customer's answer goes back to the agent, unless
    its top intent is one the agent can't act on (refund, cancellation, complaint, account
    change): those hand off even below the confidence threshold.
    """
    follow_up = previous_route == MessageRoute.AGENT
    if c is None:
        return Route.AGENT if follow_up else Route.KNOWLEDGE
    settings = get_settings()
    confident = c.confidence >= settings.classify_min_confidence
    needs_human = c.needs_human_prob >= settings.needs_human_threshold
    pressing = c.priority in PRESSING_PRIORITIES
    if confident and c.intent in SMALL_TALK_INTENTS:
        # "Hi, my account was hacked" is a greeting with an urgent request in it.
        return Route.HANDOFF if needs_human or pressing else Route.SMALL_TALK
    if needs_human or (confident and c.intent in HANDOFF_INTENTS):
        return Route.HANDOFF
    if follow_up and top_intent(c) in HANDOFF_INTENTS:
        return Route.HANDOFF
    if follow_up or (confident and c.intent in AGENT_INTENTS):
        return Route.AGENT
    return Route.KNOWLEDGE


# Replies that send the customer to support somewhere else. Narrow on purpose: "the team will
# follow up here" must never match.
SUPPORT_REDIRECTS: dict[str, re.Pattern[str]] = {
    "contact_support": re.compile(
        r"\b(?:contact|reach out to|get in touch with|email|call|message)\s+(?:our|the)\s+"
        r"(?:customer\s+)?(?:support|service|care|help\s?desk)\b",
        re.IGNORECASE,
    ),
    "support_address": re.compile(r"\bsupport@[a-z0-9.-]+\.[a-z]{2,}\b", re.IGNORECASE),
    "call_us": re.compile(r"\b(?:call|phone|ring)\s+us\s+(?:at|on)\b", re.IGNORECASE),
}


def support_redirect(text: str) -> str | None:
    """The name of the first redirect pattern the reply matches, or None."""
    return next((name for name, rx in SUPPORT_REDIRECTS.items() if rx.search(text)), None)


def small_talk_reply(intent: str, text: str) -> str:
    """A fixed reply, picked deterministically from the message so tests are stable."""
    options = SMALL_TALK_REPLIES[intent]
    index = int(hashlib.sha256(text.encode()).hexdigest(), 16) % len(options)
    return options[index]


@dataclass
class AnswerRequest:
    workspace_id: uuid.UUID
    conversation_id: uuid.UUID
    customer_message_id: uuid.UUID
    question: str
    history: list[HistoryItem]
    llm: UsageReportingLLMClient
    embedder: EmbeddingClient
    decider: DecisionClient
    limiter: WidgetLimiter
    request_id: str | None = None
    # Enqueues the reply-draft job for tickets opened here (None: no drafts, e.g. scripts).
    jobs: JobQueue | None = None


class _Pipeline:
    def __init__(self, req: AnswerRequest, queue: asyncio.Queue[str | None]) -> None:
        self.req = req
        self.queue = queue
        self.classification: Classification | None = None

    def emit(self, event: str, data: dict[str, Any]) -> None:
        self.queue.put_nowait(sse(event, data))

    async def _budget_left(self) -> bool:
        budget = get_settings().widget_daily_token_budget
        try:
            used = await self.req.limiter.tokens_used_today(self.req.workspace_id)
        except BudgetUnavailableError:
            logger.warning("Token budget unavailable (workspace_id=%s)", self.req.workspace_id)
            return False
        return used < budget

    async def _classify(self) -> Classification | None:
        req = self.req
        context = [
            ContextMessage(role=h.role, content=h.content)
            for h in req.history[-CONTEXT_MESSAGES:]
        ]
        try:
            classification = await req.decider.classify(
                req.question, context, workspace_id=req.workspace_id
            )
        except DecisionError as exc:
            logger.warning(
                "Classification unavailable, answering from knowledge "
                "(conversation_id=%s, error=%s)",
                req.conversation_id,
                type(exc.__cause__ or exc).__name__,
            )
            return None
        await req.limiter.add_tokens(req.workspace_id, classification.tokens)
        async with tenant_session(req.workspace_id) as db:
            await service.set_classification(
                db, req.workspace_id, req.customer_message_id, classification.to_json()
            )
        return classification

    async def _save(
        self,
        answer: Answer,
        *,
        route: MessageRoute,
        grounded: bool | None,
        open_ticket: bool,
        llm_call_id: uuid.UUID | None = None,
        prompt_version: str | None = None,
        tools_used: list[str] | None = None,
    ) -> None:
        req = self.req
        ticket_id: uuid.UUID | None = None
        async with tenant_session(req.workspace_id) as db:
            if open_ticket:
                conversation = await service.get_conversation(
                    db, req.workspace_id, req.conversation_id
                )
                ticket = await tickets_service.ensure_conversation_ticket(
                    db, conversation, self.classification, req.question
                )
                ticket_id = ticket.id
                logger.info(
                    "Ticket opened (conversation_id=%s, ticket_id=%s, route=%s)",
                    req.conversation_id,
                    ticket.id,
                    route.value,
                )
            message: Message = await service.add_assistant_message(
                db,
                workspace_id=req.workspace_id,
                conversation_id=req.conversation_id,
                content=answer.content,
                citations=[c.model_dump(mode="json") for c in answer.citations],
                grounded=grounded,
                route=route,
                escalate=open_ticket,
                llm_call_id=llm_call_id,
                prompt_version=prompt_version,
                tools_used=tools_used or [],
            )
        final = FinalEvent(
            id=message.id,
            content=answer.content,
            citations=answer.citations,
            grounded=grounded,
            route=route,
            tools_used=tools_used or [],
        )
        self.emit("final", final.model_dump(mode="json"))
        if ticket_id is not None:
            # After the commit, so the job sees the ticket and this message.
            await self._enqueue_draft(ticket_id)

    async def _enqueue_draft(self, ticket_id: uuid.UUID) -> None:
        if self.req.jobs is None:
            return
        try:
            await self.req.jobs.enqueue_process_ticket(ticket_id, self.req.workspace_id)
        except Exception:
            # The ticket stands; an agent can still use Regenerate draft.
            logger.exception("Failed to enqueue drafting (ticket_id=%s)", ticket_id)

    async def _fallback(
        self, *, llm_call_id: uuid.UUID | None = None, prompt_version: str | None = None
    ) -> None:
        await self._save(
            Answer(content=FALLBACK_MESSAGE),
            route=MessageRoute.FALLBACK,
            grounded=False,
            open_ticket=True,
            llm_call_id=llm_call_id,
            prompt_version=prompt_version,
        )

    async def run(self) -> None:
        req = self.req
        if not await self._budget_left():
            logger.info("Widget answer: budget exhausted (workspace_id=%s)", req.workspace_id)
            await self._fallback()
            return

        self.classification = await self._classify()
        previous_route = next(
            (h.route for h in reversed(req.history) if h.role == MessageRole.ASSISTANT), None
        )
        route = decide_route(self.classification, previous_route)
        logger.info(
            "Widget message routed (conversation_id=%s, route=%s, intent=%s, confidence=%s)",
            req.conversation_id,
            route.value,
            self.classification.intent if self.classification else None,
            self.classification.confidence if self.classification else None,
        )
        if route is Route.SMALL_TALK and self.classification is not None:
            reply = small_talk_reply(self.classification.intent, req.question)
            await self._save(
                Answer(content=reply),
                route=MessageRoute.SMALL_TALK,
                grounded=None,
                open_ticket=False,
            )
            return
        if route is Route.HANDOFF:
            await self._save(
                Answer(content=HANDOFF_MESSAGE),
                route=MessageRoute.HANDOFF,
                grounded=None,
                open_ticket=True,
            )
            return
        if route is Route.AGENT:
            await self._answer_with_agent()
            return
        await self._answer_from_knowledge()

    async def _failed_lookups(self) -> int:
        req = self.req
        async with tenant_session(req.workspace_id) as db:
            return await db.scalar(
                select(func.count())
                .select_from(ToolCall)
                .where(
                    ToolCall.workspace_id == req.workspace_id,
                    ToolCall.conversation_id == req.conversation_id,
                    ToolCall.tool_name == GET_ORDER_STATUS.name,
                    ToolCall.status == ToolCallStatus.NOT_FOUND,
                )
            ) or 0

    async def _answer_with_agent(self) -> None:
        """Order questions: the agent with read-only tools, then stream its answer."""
        req = self.req
        prompt = load_prompt(AGENT_PROMPT_NAME, AGENT_PROMPT_VERSION)
        metered = MeteredLLMClient(
            req.llm,
            workspace_id=req.workspace_id,
            purpose=LLMPurpose.AGENT,
            prompt_version=prompt.id,
            request_id=req.request_id,
        )
        ctx = ToolContext(
            workspace_id=req.workspace_id,
            embedder=req.embedder,
            conversation_id=req.conversation_id,
        )

        def on_tool(tool: Tool) -> None:
            self.emit("status", {"text": tool.status_text, "tool": tool.name})

        result = await run_agent(
            llm=metered,
            messages=build_widget_messages(
                prompt.text, [(h.role, h.content) for h in req.history], req.question
            ),
            tools=WIDGET_TOOLS,
            ctx=ctx,
            on_tool=on_tool,
        )
        await req.limiter.add_tokens(req.workspace_id, result.tokens)

        # This chat is support: an uncited reply sending the customer elsewhere is dropped and
        # the conversation goes to the team instead.
        redirect = None if result.citations else support_redirect(result.text)
        if redirect is not None:
            logger.warning(
                "Agent reply pointed the customer elsewhere; handing off "
                "(conversation_id=%s, pattern=%s)",
                req.conversation_id,
                redirect,
            )

        if ctx.handoff_reason is not None:
            logger.info("Widget agent handed off (conversation_id=%s)", req.conversation_id)
            text = result.text if result.answered and redirect is None else HANDOFF_MESSAGE
            for i, word in enumerate(text.split(" ")):
                self.emit("token", {"text": word if i == 0 else f" {word}"})
            await self._save(
                Answer(content=text, citations=result.citations if text == result.text else []),
                route=MessageRoute.HANDOFF,
                grounded=None,
                open_ticket=True,
                llm_call_id=result.llm_call_id,
                prompt_version=prompt.id,
                tools_used=result.tools_used,
            )
            return

        failed_lookups = await self._failed_lookups()
        if not result.answered or redirect is not None or failed_lookups >= MAX_FAILED_LOOKUPS:
            logger.info(
                "Widget agent handing off (conversation_id=%s, outcome=%s, failed_lookups=%d)",
                req.conversation_id,
                result.outcome.value,
                failed_lookups,
            )
            await self._save(
                Answer(
                    content=LOOKUP_HANDOFF_MESSAGE
                    if failed_lookups >= MAX_FAILED_LOOKUPS
                    else HANDOFF_MESSAGE
                ),
                route=MessageRoute.HANDOFF,
                grounded=None,
                open_ticket=True,
                llm_call_id=result.llm_call_id,
                prompt_version=prompt.id,
                tools_used=result.tools_used,
            )
            return

        for i, word in enumerate(result.text.split(" ")):
            self.emit("token", {"text": word if i == 0 else f" {word}"})
        await self._save(
            Answer(content=result.text, citations=result.citations),
            route=MessageRoute.AGENT,
            grounded=True if result.citations else None,
            open_ticket=False,
            llm_call_id=result.llm_call_id,
            prompt_version=prompt.id,
            tools_used=result.tools_used,
        )

    async def _answer_from_knowledge(self) -> None:
        req = self.req
        async with tenant_session(req.workspace_id) as db:
            result = await retrieve(
                db, req.question, workspace_id=req.workspace_id, embedder=req.embedder
            )
        chunks = result.chunks
        if not chunks:
            logger.info("Widget answer: no sources (conversation_id=%s)", req.conversation_id)
            await self._fallback()
            return

        prompt = load_prompt(PROMPT_NAME, PROMPT_VERSION)
        metered = MeteredLLMClient(
            req.llm,
            workspace_id=req.workspace_id,
            purpose=LLMPurpose.CHAT,
            prompt_version=prompt.id,
            request_id=req.request_id,
        )
        pieces: list[str] = []
        try:
            async for piece in metered.stream(
                build_messages(prompt.text, req.history, chunks, req.question)
            ):
                pieces.append(piece)
                self.emit("token", {"text": piece})
        finally:
            await req.limiter.add_tokens(
                req.workspace_id, metered.last_input_tokens + metered.last_output_tokens
            )

        answer = validate_citations("".join(pieces), chunks)
        logger.info(
            "Widget answer (conversation_id=%s, sources=%d, cited=%d, grounded=%s)",
            req.conversation_id,
            len(chunks),
            len(answer.citations),
            answer.grounded,
        )
        if not answer.grounded:
            await self._fallback(llm_call_id=metered.last_call_id, prompt_version=prompt.id)
            return
        await self._save(
            answer,
            route=MessageRoute.ANSWER,
            grounded=True,
            open_ticket=False,
            llm_call_id=metered.last_call_id,
            prompt_version=prompt.id,
        )

    async def run_safely(self) -> None:
        try:
            await self.run()
        except Exception as exc:  # noqa: BLE001 - the stream must always end with an event
            logger.warning(
                "Widget answer failed (conversation_id=%s, error=%s)",
                self.req.conversation_id,
                type(exc.__cause__ or exc).__name__,
            )
            self.emit("error", {"message": ERROR_MESSAGE})
        finally:
            self.queue.put_nowait(None)


async def stream_answer(req: AnswerRequest) -> AsyncIterator[str]:
    """SSE body: `token` events while the model writes, then `final` (or `error`)."""
    queue: asyncio.Queue[str | None] = asyncio.Queue()
    task = asyncio.create_task(_Pipeline(req, queue).run_safely())
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)

    # A comment line first, so proxies see bytes immediately and flush the headers.
    yield ": stream open\n\n"
    while (item := await queue.get()) is not None:
        yield item
