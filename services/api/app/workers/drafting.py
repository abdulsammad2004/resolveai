"""Ticket drafting job: run the agent with all tools and save a reply draft for review.

Read tools execute; write and sensitive tools only become proposed action_requests. The
draft is never sent here. One run per ticket at a time (Redis lock). If a pending draft was
already written from the same ticket and messages, the job does nothing unless forced
(Regenerate). Logs carry ids and outcomes only, never ticket or message text.
"""

import asyncio
import hashlib
import json
import logging
import uuid
from typing import Any, Protocol

from arq import Retry
from sqlalchemy import select, update

from app.ai.agent import DraftInput, build_draft_messages, run_agent
from app.ai.embeddings import EmbeddingClient, get_embedding_client
from app.ai.llm import UsageReportingLLMClient, get_llm_client
from app.ai.prompts import load_prompt
from app.ai.tools.builtin import DRAFT_TOOLS
from app.ai.tools.registry import ToolContext
from app.ai.usage import LLMPurpose, MeteredLLMClient
from app.core.deps import tenant_session
from app.modules.conversations.models import Contact, Message, MessageRole
from app.modules.tickets.models import DraftStatus, ReplyDraft, Ticket, TicketStatus

logger = logging.getLogger("app.workers.drafting")

PROMPT_NAME, PROMPT_VERSION = "draft", "v2"
MAX_TRIES = 3
JOB_TIMEOUT_S = 120
# Finish (or give up) before arq cancels the job, so the failure can be recorded.
WORK_TIMEOUT_S = JOB_TIMEOUT_S - 20
RETRY_DELAY_S = 10
LOCK_TTL_S = JOB_TIMEOUT_S + 30
LOCKED_RETRY_S = 15
MESSAGES_USED = 16
REFUND_INTENT = "refund_request"
FINAL_FAILURE_MESSAGE = "The assistant couldn't write a draft after several attempts."
# Statuses a fresh draft moves the ticket out of; a replied or resolved ticket keeps its own.
DRAFTABLE_STATUSES = frozenset({TicketStatus.NEW, TicketStatus.TRIAGED, TicketStatus.AWAITING_REVIEW})

_RELEASE_LUA = """
if redis.call('get', KEYS[1]) == ARGV[1] then return redis.call('del', KEYS[1]) end
return 0
"""


class DraftError(Exception):
    """The agent ended without a usable answer."""


class TicketLock(Protocol):
    async def acquire(self, key: str, ttl_s: int) -> str | None:
        """A token if the lock was taken, None if someone else holds it."""
        ...

    async def release(self, key: str, token: str) -> None: ...


class RedisTicketLock:
    """SET NX EX with a random token; release only deletes our own token."""

    def __init__(self, redis: Any) -> None:
        self._redis = redis

    async def acquire(self, key: str, ttl_s: int) -> str | None:
        token = uuid.uuid4().hex
        return token if await self._redis.set(key, token, nx=True, ex=ttl_s) else None

    async def release(self, key: str, token: str) -> None:
        await self._redis.eval(_RELEASE_LUA, 1, key, token)


def lock_key(ticket_id: uuid.UUID) -> str:
    return f"lock:process_ticket:{ticket_id}"


async def process_ticket(
    ctx: dict[str, Any], ticket_id: str, workspace_id: str, force: bool = False
) -> str:
    t_id = uuid.UUID(ticket_id)
    ws_id = uuid.UUID(workspace_id)
    lock: TicketLock = ctx.get("ticket_lock") or RedisTicketLock(ctx["redis"])
    job_try: int = ctx.get("job_try", 1)

    token = await lock.acquire(lock_key(t_id), LOCK_TTL_S)
    if token is None:
        logger.info("Drafting already running (ticket_id=%s, force=%s)", t_id, force)
        if force and job_try < MAX_TRIES:
            # A regenerate must not be lost: run again once the current run is done.
            raise Retry(defer=LOCKED_RETRY_S)
        return "locked"

    try:
        async with asyncio.timeout(WORK_TIMEOUT_S):
            return await _draft(ctx, t_id, ws_id, force=force)
    except Exception as exc:
        if job_try < MAX_TRIES:
            logger.warning(
                "Drafting attempt %d/%d failed, will retry (ticket_id=%s, error=%s)",
                job_try,
                MAX_TRIES,
                t_id,
                type(exc).__name__,
            )
            raise Retry(defer=RETRY_DELAY_S * job_try) from exc
        logger.warning(
            "Drafting failed after %d attempts (ticket_id=%s, error=%s)",
            job_try,
            t_id,
            type(exc).__name__,
        )
        await _record_failure(t_id, ws_id, FINAL_FAILURE_MESSAGE)
        return "failed"
    finally:
        await lock.release(lock_key(t_id), token)


def _input_hash(subject: str, description: str | None, message_ids: list[uuid.UUID]) -> str:
    raw = json.dumps(
        [PROMPT_NAME, PROMPT_VERSION, subject, description or "", [str(m) for m in message_ids]]
    )
    return hashlib.sha256(raw.encode()).hexdigest()


async def _draft(ctx: dict[str, Any], t_id: uuid.UUID, ws_id: uuid.UUID, *, force: bool) -> str:
    async with tenant_session(ws_id) as db:
        ticket = await db.scalar(
            select(Ticket).where(Ticket.workspace_id == ws_id, Ticket.id == t_id)
        )
        if ticket is None:
            logger.info("Ticket no longer exists, skipping (ticket_id=%s)", t_id)
            return "missing"
        if ticket.status == TicketStatus.RESOLVED:
            logger.info("Ticket is resolved, skipping (ticket_id=%s)", t_id)
            return "skipped"
        messages: list[Message] = []
        if ticket.conversation_id is not None:
            messages = list(
                (
                    await db.execute(
                        select(Message)
                        .where(
                            Message.workspace_id == ws_id,
                            Message.conversation_id == ticket.conversation_id,
                            Message.role.in_(
                                (MessageRole.CUSTOMER, MessageRole.ASSISTANT, MessageRole.AGENT)
                            ),
                        )
                        .order_by(Message.created_at.desc(), Message.id.desc())
                        .limit(MESSAGES_USED)
                    )
                ).scalars()
            )
            messages.reverse()
        contact_email = None
        if ticket.contact_id is not None:
            contact_email = await db.scalar(
                select(Contact.email).where(
                    Contact.workspace_id == ws_id, Contact.id == ticket.contact_id
                )
            )
        input_hash = _input_hash(ticket.subject, ticket.description, [m.id for m in messages])
        # From the classifier, never from the model: only the customer's request counts.
        asked_refund = ticket.intent == REFUND_INTENT or any(
            m.role == MessageRole.CUSTOMER
            and (m.classification or {}).get("intent") == REFUND_INTENT
            for m in messages
        )
        current = await db.scalar(
            select(ReplyDraft)
            .where(
                ReplyDraft.workspace_id == ws_id,
                ReplyDraft.ticket_id == t_id,
                ReplyDraft.status != DraftStatus.SUPERSEDED,
            )
            .order_by(ReplyDraft.created_at.desc(), ReplyDraft.id.desc())
            .limit(1)
        )
        if (
            not force
            and current is not None
            and current.status == DraftStatus.PENDING
            and current.input_hash == input_hash
        ):
            logger.info("Pending draft is up to date, skipping (ticket_id=%s)", t_id)
            return "unchanged"
        data = DraftInput(
            subject=ticket.subject,
            description=ticket.description,
            contact_email=contact_email,
            intent=ticket.intent,
            messages=[(m.role, m.content) for m in messages],
        )
        conversation_id = ticket.conversation_id

    llm: UsageReportingLLMClient = ctx.get("llm") or get_llm_client()
    embedder: EmbeddingClient = ctx.get("embedder") or get_embedding_client()
    prompt = load_prompt(PROMPT_NAME, PROMPT_VERSION)
    metered = MeteredLLMClient(
        llm, workspace_id=ws_id, purpose=LLMPurpose.DRAFT, prompt_version=prompt.id
    )
    tool_ctx = ToolContext(
        workspace_id=ws_id,
        embedder=embedder,
        conversation_id=conversation_id,
        ticket_id=t_id,
        contact_email=contact_email,
        customer_asked_refund=asked_refund,
    )
    result = await run_agent(
        llm=metered,
        messages=build_draft_messages(prompt.text, data),
        tools=DRAFT_TOOLS,
        ctx=tool_ctx,
    )
    if not result.answered:
        raise DraftError(f"Agent ended without a draft ({result.outcome.value})")

    async with tenant_session(ws_id) as db:
        # The row lock serialises the status change with Inbox edits to the same ticket.
        ticket = await db.scalar(
            select(Ticket)
            .where(Ticket.workspace_id == ws_id, Ticket.id == t_id)
            .with_for_update()
        )
        if ticket is None:
            return "missing"
        await _supersede_pending(db, ws_id, t_id)
        db.add(
            ReplyDraft(
                workspace_id=ws_id,
                ticket_id=t_id,
                content=result.text,
                citations=[c.model_dump(mode="json") for c in result.citations],
                status=DraftStatus.PENDING,
                prompt_version=prompt.id,
                llm_call_id=result.llm_call_id,
                input_hash=input_hash,
            )
        )
        if ticket.status in DRAFTABLE_STATUSES:
            ticket.status = TicketStatus.AWAITING_REVIEW

    logger.info(
        "Draft saved (ticket_id=%s, workspace_id=%s, tool_calls=%d, cited=%d)",
        t_id,
        ws_id,
        len(result.tool_uses),
        len(result.citations),
    )
    return "drafted"


async def _supersede_pending(db: Any, ws_id: uuid.UUID, t_id: uuid.UUID) -> None:
    await db.execute(
        update(ReplyDraft)
        .where(
            ReplyDraft.workspace_id == ws_id,
            ReplyDraft.ticket_id == t_id,
            ReplyDraft.status.in_((DraftStatus.PENDING, DraftStatus.FAILED)),
        )
        .values(status=DraftStatus.SUPERSEDED)
    )


async def _record_failure(t_id: uuid.UUID, ws_id: uuid.UUID, message: str) -> None:
    """Leave the ticket as it is; store a failed draft so the Inbox can show what happened."""
    async with tenant_session(ws_id) as db:
        exists = await db.scalar(
            select(Ticket.id).where(Ticket.workspace_id == ws_id, Ticket.id == t_id)
        )
        if exists is None:
            return
        await db.execute(
            update(ReplyDraft)
            .where(
                ReplyDraft.workspace_id == ws_id,
                ReplyDraft.ticket_id == t_id,
                ReplyDraft.status == DraftStatus.FAILED,
            )
            .values(status=DraftStatus.SUPERSEDED)
        )
        db.add(
            ReplyDraft(
                workspace_id=ws_id,
                ticket_id=t_id,
                content="",
                citations=[],
                status=DraftStatus.FAILED,
                prompt_version=f"{PROMPT_NAME}_{PROMPT_VERSION}",
                error=message[:500],
            )
        )
