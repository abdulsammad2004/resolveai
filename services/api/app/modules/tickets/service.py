"""Tickets: created by widget routing or by hand, triaged in the Inbox, answered by reviewing
reply drafts.

Queries filter by workspace_id explicitly on top of RLS. Every review step (edit, approve,
send, reject) and every status, priority or assignee change writes an audit event in the
same transaction. Draft changes lock the ticket row, then the draft row, in that order (as
the drafting worker does), so a double click or a racing draft job can't send twice.
"""

import base64
import binascii
import json
import re
import uuid
from datetime import UTC, datetime

from fastapi import HTTPException, status
from sqlalchemy import and_, case, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.decisions import Classification
from app.ai.tools.models import ToolCall
from app.modules.approvals import service as approvals_service
from app.modules.audit import service as audit
from app.modules.audit.models import ActorType
from app.modules.auth.models import User
from app.modules.conversations import service as conversations_service
from app.modules.conversations.models import (
    Contact,
    Conversation,
    ConversationStatus,
    Message,
    MessageRole,
)
from app.modules.conversations.schemas import ContactOut
from app.modules.tickets.models import (
    PRIORITY_ORDER,
    DraftAuthor,
    DraftStatus,
    ReplyDraft,
    Ticket,
    TicketPriority,
    TicketSource,
    TicketStatus,
)
from app.modules.tickets.schemas import (
    ClassificationOut,
    DraftCreate,
    DraftReject,
    DraftSend,
    MemberRef,
    ReplyDraftOut,
    TicketCounts,
    TicketCreate,
    TicketDetail,
    TicketPage,
    TicketSummary,
    TicketUpdate,
    ToolCallOut,
)
from app.modules.workspaces.models import Membership

SUBJECT_CHARS = 80
TOOL_CALLS_SHOWN = 50
# Drafts a teammate can still edit, send or reject.
REVIEWABLE = frozenset({DraftStatus.PENDING, DraftStatus.EDITED})
# A new customer message brings these tickets back to the review queue. A resolved ticket's
# conversation is closed instead: new messages start a new conversation, and only the
# widget's "Still need help?" link reopens it (reopen_resolved_from_widget).
REOPENABLE = frozenset({TicketStatus.REPLIED})
# Never a ticket's intent: they say nothing about what the customer needs.
SMALL_TALK_INTENTS = frozenset({"greeting", "thanks"})
_SOURCE_MARKER = re.compile(r"\[(S\d+)\]")


def subject_from(text: str) -> str:
    subject = " ".join(text.split())[:SUBJECT_CHARS]
    return subject or "(no subject)"


def _not_found() -> HTTPException:
    return HTTPException(status.HTTP_404_NOT_FOUND, "Ticket not found")


def _fields(classification: Classification | None) -> dict:
    if classification is None:
        return {
            "intent": "other",
            "priority": TicketPriority.NORMAL,
            "classification": None,
            "confidence": None,
        }
    return {
        "intent": classification.intent,
        "priority": classification.priority,
        "classification": classification.to_json(),
        "confidence": classification.confidence,
    }


def _stored_fields(stored: dict) -> dict:
    return {
        "intent": stored["intent"],
        "priority": stored.get("priority") or TicketPriority.NORMAL,
        "classification": stored,
        "confidence": stored.get("confidence"),
    }


async def _strongest_classification(db: AsyncSession, conversation: Conversation) -> dict | None:
    """The conversation's most telling customer classification: a specific intent over
    "other", then the most confident. Greetings and thanks never count."""
    stored = (
        await db.execute(
            select(Message.classification).where(
                Message.workspace_id == conversation.workspace_id,
                Message.conversation_id == conversation.id,
                Message.role == MessageRole.CUSTOMER,
                Message.classification.is_not(None),
            )
        )
    ).scalars().all()
    candidates = [c for c in stored if c.get("intent") not in SMALL_TALK_INTENTS]
    return max(
        candidates,
        key=lambda c: (c["intent"] != "other", float(c.get("confidence") or 0.0)),
        default=None,
    )


async def ensure_conversation_ticket(
    db: AsyncSession,
    conversation: Conversation,
    classification: Classification | None,
    trigger_text: str,
) -> Ticket:
    """The conversation's open ticket, or a new one. A reused ticket's priority only rises.

    A new ticket's intent comes from the triggering message, or, when that one is small talk
    or unclassified, from the conversation's strongest classification; never a greeting.
    """
    ticket: Ticket | None = None
    if conversation.ticket_id is not None:
        ticket = (
            await db.execute(
                select(Ticket).where(
                    Ticket.workspace_id == conversation.workspace_id,
                    Ticket.id == conversation.ticket_id,
                    Ticket.status != TicketStatus.RESOLVED,
                )
            )
        ).scalar_one_or_none()

    if ticket is not None:
        if classification is not None and (
            PRIORITY_ORDER[TicketPriority(classification.priority)]
            > PRIORITY_ORDER[TicketPriority(ticket.priority)]
        ):
            ticket.priority = classification.priority
        await db.flush()
        return ticket

    fields = _fields(classification)
    if classification is None or classification.intent in SMALL_TALK_INTENTS:
        strongest = await _strongest_classification(db, conversation)
        if classification is None and strongest is not None:
            fields = _stored_fields(strongest)
        else:
            # A greeting says nothing about the request; the trigger's priority still holds.
            fields["intent"] = strongest["intent"] if strongest else "other"

    ticket = Ticket(
        workspace_id=conversation.workspace_id,
        conversation_id=conversation.id,
        contact_id=conversation.contact_id,
        subject=subject_from(trigger_text),
        status=TicketStatus.NEW,
        source=TicketSource.WIDGET,
        **fields,
    )
    db.add(ticket)
    await db.flush()
    conversation.ticket_id = ticket.id
    await db.flush()
    return ticket


async def create_manual_ticket(
    db: AsyncSession,
    workspace_id: uuid.UUID,
    body: TicketCreate,
    classification: Classification | None,
) -> Ticket:
    contact_id = None
    if body.contact_email:
        email = body.contact_email.lower()
        contact = (
            await db.execute(
                select(Contact)
                .where(Contact.workspace_id == workspace_id, func.lower(Contact.email) == email)
                .order_by(Contact.created_at)
                .limit(1)
            )
        ).scalar_one_or_none()
        if contact is None:
            contact = Contact(
                workspace_id=workspace_id,
                anonymous_id=conversations_service.new_anonymous_id(),
                email=email,
            )
            db.add(contact)
            await db.flush()
        contact_id = contact.id

    ticket = Ticket(
        workspace_id=workspace_id,
        contact_id=contact_id,
        subject=body.subject.strip(),
        description=body.description.strip(),
        status=TicketStatus.NEW,
        source=TicketSource.MANUAL,
        **_fields(classification),
    )
    db.add(ticket)
    await db.flush()
    return ticket


# Reading ------------------------------------------------------------------------------------

_URGENT_FIRST = case((Ticket.priority == TicketPriority.URGENT, 1), else_=0)


def _encode_cursor(urgent: int, at: datetime, ticket_id: uuid.UUID) -> str:
    raw = json.dumps([urgent, at.isoformat(), str(ticket_id)]).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _decode_cursor(cursor: str) -> tuple[int, datetime, uuid.UUID]:
    try:
        raw = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4))
        urgent, at, tid = json.loads(raw)
        return int(urgent), datetime.fromisoformat(at), uuid.UUID(tid)
    except (binascii.Error, ValueError, TypeError) as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Invalid cursor") from exc


def _summary(ticket: Ticket, contact: Contact | None, assignee: User | None) -> TicketSummary:
    return TicketSummary(
        id=ticket.id,
        subject=ticket.subject,
        intent=ticket.intent,  # type: ignore[arg-type]
        priority=ticket.priority,  # type: ignore[arg-type]
        status=ticket.status,  # type: ignore[arg-type]
        source=ticket.source,  # type: ignore[arg-type]
        confidence=ticket.confidence,
        contact=ContactOut.model_validate(contact) if contact else None,
        assignee=(
            MemberRef(user_id=assignee.id, full_name=assignee.full_name, email=assignee.email)
            if assignee
            else None
        ),
        conversation_id=ticket.conversation_id,
        created_at=ticket.created_at,
        updated_at=ticket.updated_at,
    )


def _with_people(workspace_id: uuid.UUID):
    return (
        select(Ticket, Contact, User)
        .outerjoin(
            Contact,
            and_(Contact.id == Ticket.contact_id, Contact.workspace_id == workspace_id),
        )
        .outerjoin(User, User.id == Ticket.assignee_id)
        .where(Ticket.workspace_id == workspace_id)
    )


async def counts(db: AsyncSession, workspace_id: uuid.UUID) -> TicketCounts:
    rows = (
        await db.execute(
            select(Ticket.status, Ticket.priority, func.count())
            .where(Ticket.workspace_id == workspace_id)
            .group_by(Ticket.status, Ticket.priority)
        )
    ).all()
    by_status = dict.fromkeys(TicketStatus, 0)
    urgent_open = 0
    for status_value, priority, n in rows:
        by_status[TicketStatus(status_value)] += n
        if status_value != TicketStatus.RESOLVED and priority == TicketPriority.URGENT:
            urgent_open += n
    return TicketCounts(
        new=by_status[TicketStatus.NEW],
        triaged=by_status[TicketStatus.TRIAGED],
        awaiting_review=by_status[TicketStatus.AWAITING_REVIEW],
        replied=by_status[TicketStatus.REPLIED],
        resolved=by_status[TicketStatus.RESOLVED],
        open=sum(n for s, n in by_status.items() if s != TicketStatus.RESOLVED),
        urgent_open=urgent_open,
    )


async def list_tickets(
    db: AsyncSession,
    workspace_id: uuid.UUID,
    *,
    user_id: uuid.UUID,
    status_filter: str | None,
    priority: str | None,
    intent: str | None,
    assignee: str,
    cursor: str | None,
    limit: int,
) -> TicketPage:
    """Urgent tickets first, then newest first."""
    stmt = _with_people(workspace_id).order_by(
        _URGENT_FIRST.desc(), Ticket.created_at.desc(), Ticket.id.desc()
    )
    if status_filter:
        stmt = stmt.where(Ticket.status == status_filter)
    if priority:
        stmt = stmt.where(Ticket.priority == priority)
    if intent:
        stmt = stmt.where(Ticket.intent == intent)
    if assignee == "me":
        stmt = stmt.where(Ticket.assignee_id == user_id)
    elif assignee == "unassigned":
        stmt = stmt.where(Ticket.assignee_id.is_(None))
    if cursor:
        urgent, at, tid = _decode_cursor(cursor)
        stmt = stmt.where(
            or_(
                _URGENT_FIRST < urgent,
                and_(
                    _URGENT_FIRST == urgent,
                    or_(
                        Ticket.created_at < at,
                        and_(Ticket.created_at == at, Ticket.id < tid),
                    ),
                ),
            )
        )
    rows = (await db.execute(stmt.limit(limit + 1))).all()
    page = rows[:limit]
    next_cursor = None
    if len(rows) > limit:
        tail = page[-1][0]
        next_cursor = _encode_cursor(
            1 if tail.priority == TicketPriority.URGENT else 0, tail.created_at, tail.id
        )
    return TicketPage(
        items=[_summary(t, c, u) for t, c, u in page],
        next_cursor=next_cursor,
        counts=await counts(db, workspace_id),
    )


async def latest_draft(
    db: AsyncSession, workspace_id: uuid.UUID, ticket_id: uuid.UUID
) -> ReplyDraft | None:
    """The newest draft that hasn't been replaced by a later one."""
    return await db.scalar(
        select(ReplyDraft)
        .where(
            ReplyDraft.workspace_id == workspace_id,
            ReplyDraft.ticket_id == ticket_id,
            ReplyDraft.status != DraftStatus.SUPERSEDED,
        )
        .order_by(ReplyDraft.created_at.desc(), ReplyDraft.id.desc())
        .limit(1)
    )


async def tool_calls_for_ticket(db: AsyncSession, ticket: Ticket) -> list[ToolCallOut]:
    """Tool calls made for the ticket, and in its conversation before the ticket existed."""
    scope = ToolCall.ticket_id == ticket.id
    if ticket.conversation_id is not None:
        scope = or_(scope, ToolCall.conversation_id == ticket.conversation_id)
    rows = (
        await db.execute(
            select(ToolCall)
            .where(ToolCall.workspace_id == ticket.workspace_id, scope)
            .order_by(ToolCall.created_at.desc(), ToolCall.id.desc())
            .limit(TOOL_CALLS_SHOWN)
        )
    ).scalars()
    return [ToolCallOut.model_validate(c) for c in reversed(list(rows))]


async def ticket_detail(
    db: AsyncSession, workspace_id: uuid.UUID, ticket_id: uuid.UUID
) -> TicketDetail:
    row = (await db.execute(_with_people(workspace_id).where(Ticket.id == ticket_id))).first()
    if row is None:
        raise _not_found()
    ticket, contact, assignee = row
    conversation = None
    if ticket.conversation_id is not None:
        conversation = await conversations_service.conversation_detail(
            db, workspace_id, ticket.conversation_id
        )
    draft = await latest_draft(db, workspace_id, ticket.id)
    return TicketDetail(
        **_summary(ticket, contact, assignee).model_dump(),
        description=ticket.description,
        classification=(
            ClassificationOut.model_validate(ticket.classification)
            if ticket.classification
            else None
        ),
        conversation=conversation,
        resolution_rating=ticket.resolution_rating,  # type: ignore[arg-type]
        draft=ReplyDraftOut.model_validate(draft) if draft else None,
        actions=await approvals_service.actions_for_ticket(db, workspace_id, ticket.id),
        tool_calls=await tool_calls_for_ticket(db, ticket),
        activity=await audit.events_for_ticket(db, workspace_id, ticket.id),
    )


async def get_ticket(db: AsyncSession, workspace_id: uuid.UUID, ticket_id: uuid.UUID) -> Ticket:
    ticket = (
        await db.execute(
            select(Ticket).where(Ticket.workspace_id == workspace_id, Ticket.id == ticket_id)
        )
    ).scalar_one_or_none()
    if ticket is None:
        raise _not_found()
    return ticket


def record_status_change(
    db: AsyncSession,
    ticket: Ticket,
    new_status: str,
    *,
    actor_type: ActorType,
    actor_id: uuid.UUID | None,
) -> None:
    """Move the ticket to `new_status` and audit it; nothing happens if it's already there."""
    if ticket.status == new_status:
        return
    audit.record(
        db,
        workspace_id=ticket.workspace_id,
        ticket_id=ticket.id,
        actor_type=actor_type,
        actor_id=actor_id,
        action="ticket.status_changed",
        target_type="ticket",
        target_id=ticket.id,
        before={"status": ticket.status},
        after={"status": new_status},
    )
    ticket.status = new_status


async def update_ticket(
    db: AsyncSession,
    workspace_id: uuid.UUID,
    ticket_id: uuid.UUID,
    changes: TicketUpdate,
    *,
    user_id: uuid.UUID,
) -> Ticket:
    ticket = await _locked_ticket(db, workspace_id, ticket_id)

    fields = changes.model_fields_set
    if "assignee_id" in fields and changes.assignee_id is not None:
        member = (
            await db.execute(
                select(Membership.id).where(
                    Membership.workspace_id == workspace_id,
                    Membership.user_id == changes.assignee_id,
                )
            )
        ).scalar_one_or_none()
        if member is None:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                "The assignee must be a member of this workspace",
            )
    if "assignee_id" in fields and ticket.assignee_id != changes.assignee_id:
        audit.record(
            db,
            workspace_id=workspace_id,
            ticket_id=ticket.id,
            actor_type=ActorType.USER,
            actor_id=user_id,
            action="ticket.assignee_changed",
            target_type="ticket",
            target_id=ticket.id,
            before={"assignee_id": str(ticket.assignee_id) if ticket.assignee_id else None},
            after={"assignee_id": str(changes.assignee_id) if changes.assignee_id else None},
        )
        ticket.assignee_id = changes.assignee_id
    if "status" in fields and changes.status:
        was_resolved = ticket.status == TicketStatus.RESOLVED
        record_status_change(
            db, ticket, changes.status, actor_type=ActorType.USER, actor_id=user_id
        )
        is_resolved = ticket.status == TicketStatus.RESOLVED
        if is_resolved != was_resolved:
            await _sync_conversation(db, ticket, closed=is_resolved, user_id=user_id)
    if "priority" in fields and changes.priority and ticket.priority != changes.priority:
        audit.record(
            db,
            workspace_id=workspace_id,
            ticket_id=ticket.id,
            actor_type=ActorType.USER,
            actor_id=user_id,
            action="ticket.priority_changed",
            target_type="ticket",
            target_id=ticket.id,
            before={"priority": ticket.priority},
            after={"priority": changes.priority},
        )
        ticket.priority = changes.priority
    await db.flush()
    return ticket


async def _ticket_conversation(db: AsyncSession, ticket: Ticket) -> Conversation | None:
    if ticket.conversation_id is None:
        return None
    return await db.scalar(
        select(Conversation)
        .where(
            Conversation.workspace_id == ticket.workspace_id,
            Conversation.id == ticket.conversation_id,
        )
        .with_for_update()
    )


def _set_conversation_closed(
    db: AsyncSession,
    ticket: Ticket,
    conversation: Conversation,
    *,
    closed: bool,
    actor_type: ActorType,
    actor_id: uuid.UUID | None,
) -> None:
    """Close the conversation (its ticket was resolved) or reopen it, handed to the team."""
    new_status = ConversationStatus.CLOSED if closed else ConversationStatus.NEEDS_HUMAN
    if conversation.status == new_status:
        return
    audit.record(
        db,
        workspace_id=ticket.workspace_id,
        ticket_id=ticket.id,
        actor_type=actor_type,
        actor_id=actor_id,
        action="conversation.closed" if closed else "conversation.reopened",
        target_type="conversation",
        target_id=conversation.id,
        before={"status": conversation.status},
        after={"status": new_status},
    )
    conversation.status = new_status
    conversation.closed_at = datetime.now(UTC) if closed else None


async def _sync_conversation(
    db: AsyncSession, ticket: Ticket, *, closed: bool, user_id: uuid.UUID
) -> None:
    conversation = await _ticket_conversation(db, ticket)
    if conversation is not None:
        _set_conversation_closed(
            db, ticket, conversation, closed=closed, actor_type=ActorType.USER, actor_id=user_id
        )


def _conflict_widget(message: str) -> HTTPException:
    return HTTPException(status.HTTP_409_CONFLICT, message)


async def _resolved_ticket_for(db: AsyncSession, conversation: Conversation) -> Ticket:
    """The resolved ticket behind a closed widget conversation, row-locked."""
    ticket = None
    if conversation.status == ConversationStatus.CLOSED and conversation.ticket_id is not None:
        ticket = await db.scalar(
            select(Ticket)
            .where(
                Ticket.workspace_id == conversation.workspace_id,
                Ticket.id == conversation.ticket_id,
            )
            .with_for_update()
        )
    if ticket is None or ticket.status != TicketStatus.RESOLVED:
        raise _conflict_widget("This conversation isn't resolved.")
    return ticket


async def reopen_resolved_from_widget(db: AsyncSession, conversation: Conversation) -> Ticket:
    """"Still need help?": the same ticket back to the review queue, the same conversation
    open again and still with the team."""
    ticket = await _resolved_ticket_for(db, conversation)
    record_status_change(
        db, ticket, TicketStatus.AWAITING_REVIEW, actor_type=ActorType.CUSTOMER, actor_id=None
    )
    _set_conversation_closed(
        db, ticket, conversation, closed=False, actor_type=ActorType.CUSTOMER, actor_id=None
    )
    await db.flush()
    return ticket


async def rate_resolution(db: AsyncSession, conversation: Conversation, rating: str) -> Ticket:
    """"Was this helpful?" after a resolve. The latest answer wins; each one is audited."""
    ticket = await _resolved_ticket_for(db, conversation)
    audit.record(
        db,
        workspace_id=ticket.workspace_id,
        ticket_id=ticket.id,
        actor_type=ActorType.CUSTOMER,
        actor_id=None,
        action="ticket.resolution_rated",
        target_type="ticket",
        target_id=ticket.id,
        before={"rating": ticket.resolution_rating},
        after={"rating": rating},
    )
    ticket.resolution_rating = rating
    ticket.resolution_rated_at = datetime.now(UTC)
    await db.flush()
    return ticket


async def reopen_for_customer_message(
    db: AsyncSession, conversation: Conversation
) -> uuid.UUID | None:
    """The customer wrote again after a reply: put the ticket back in the review queue.
    Returns its id when reopened, so a draft gets queued. (A resolved ticket's conversation
    is closed and takes no messages; see REOPENABLE.)"""
    if conversation.ticket_id is None:
        return None
    ticket = await db.scalar(
        select(Ticket)
        .where(
            Ticket.workspace_id == conversation.workspace_id,
            Ticket.id == conversation.ticket_id,
        )
        .with_for_update()
    )
    if ticket is None or ticket.status not in REOPENABLE:
        return None
    record_status_change(
        db, ticket, TicketStatus.AWAITING_REVIEW, actor_type=ActorType.SYSTEM, actor_id=None
    )
    await db.flush()
    return ticket.id


# Reviewing drafts ---------------------------------------------------------------------------


def _conflict(message: str) -> HTTPException:
    return HTTPException(status.HTTP_409_CONFLICT, message)


async def _locked_ticket(
    db: AsyncSession, workspace_id: uuid.UUID, ticket_id: uuid.UUID
) -> Ticket:
    ticket = await db.scalar(
        select(Ticket)
        .where(Ticket.workspace_id == workspace_id, Ticket.id == ticket_id)
        .with_for_update()
    )
    if ticket is None:
        raise _not_found()
    return ticket


async def _locked_draft(
    db: AsyncSession, workspace_id: uuid.UUID, ticket_id: uuid.UUID, draft_id: uuid.UUID
) -> tuple[Ticket, ReplyDraft]:
    """The ticket and draft, both row-locked, with the draft still open for review."""
    ticket = await _locked_ticket(db, workspace_id, ticket_id)
    draft = await db.scalar(
        select(ReplyDraft)
        .where(
            ReplyDraft.workspace_id == workspace_id,
            ReplyDraft.ticket_id == ticket_id,
            ReplyDraft.id == draft_id,
        )
        .with_for_update()
    )
    if draft is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Draft not found")
    if draft.status not in REVIEWABLE:
        raise _conflict(f"This draft can't be changed: it is {draft.status}.")
    return ticket, draft


def _audit_draft(
    db: AsyncSession,
    draft: ReplyDraft,
    action: str,
    user_id: uuid.UUID,
    *,
    before: dict | None = None,
    after: dict | None = None,
) -> None:
    audit.record(
        db,
        workspace_id=draft.workspace_id,
        ticket_id=draft.ticket_id,
        actor_type=ActorType.USER,
        actor_id=user_id,
        action=action,
        target_type="reply_draft",
        target_id=draft.id,
        before=before,
        after=after,
    )


def _edit(db: AsyncSession, draft: ReplyDraft, content: str, user_id: uuid.UUID) -> None:
    if content == draft.content:
        return
    _audit_draft(
        db,
        draft,
        "draft.edited",
        user_id,
        before={"status": draft.status, "chars": len(draft.content)},
        after={"status": DraftStatus.EDITED, "chars": len(content)},
    )
    draft.content = content
    draft.status = DraftStatus.EDITED


async def edit_draft(
    db: AsyncSession,
    workspace_id: uuid.UUID,
    ticket_id: uuid.UUID,
    draft_id: uuid.UUID,
    content: str,
    *,
    user_id: uuid.UUID,
) -> ReplyDraft:
    _, draft = await _locked_draft(db, workspace_id, ticket_id, draft_id)
    content = content.strip()
    if not content:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "The reply is empty")
    _edit(db, draft, content, user_id)
    await db.flush()
    return draft


async def create_human_draft(
    db: AsyncSession,
    workspace_id: uuid.UUID,
    ticket_id: uuid.UUID,
    body: DraftCreate,
    *,
    user_id: uuid.UUID,
) -> ReplyDraft:
    """"Write reply": a draft with no AI text, replacing any draft still open for review.

    Stored as `edited`, so the drafting job leaves it alone (only Regenerate replaces it).
    """
    await _locked_ticket(db, workspace_id, ticket_id)
    await db.execute(
        update(ReplyDraft)
        .where(
            ReplyDraft.workspace_id == workspace_id,
            ReplyDraft.ticket_id == ticket_id,
            ReplyDraft.status.in_((*REVIEWABLE, DraftStatus.FAILED)),
        )
        .values(status=DraftStatus.SUPERSEDED)
    )
    draft = ReplyDraft(
        workspace_id=workspace_id,
        ticket_id=ticket_id,
        content=body.content.strip(),
        original_content="",
        author_type=DraftAuthor.HUMAN,
        citations=[],
        status=DraftStatus.EDITED,
        created_at=datetime.now(UTC),
    )
    db.add(draft)
    await db.flush()
    _audit_draft(db, draft, "draft.created", user_id, after={"author_type": DraftAuthor.HUMAN})
    return draft


def _cited(content: str, citations: list[dict]) -> list[dict]:
    """The draft's citations that the final text still refers to."""
    used = set(_SOURCE_MARKER.findall(content))
    return [c for c in citations if c.get("source_id") in used]


async def send_draft(
    db: AsyncSession,
    workspace_id: uuid.UUID,
    ticket_id: uuid.UUID,
    draft_id: uuid.UUID,
    body: DraftSend,
    *,
    user_id: uuid.UUID,
) -> ReplyDraft:
    """Approve (or keep the edits) and post the text in the customer's chat, exactly once."""
    ticket, draft = await _locked_draft(db, workspace_id, ticket_id, draft_id)
    if ticket.conversation_id is None:
        raise _conflict(
            "This ticket has no chat to reply in. Copy the text and reply another way."
        )
    if body.content is not None:
        _edit(db, draft, body.content.strip(), user_id)
    if not draft.content.strip():
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "The reply is empty")

    conversation = await conversations_service.get_conversation(
        db, workspace_id, ticket.conversation_id
    )
    if draft.status == DraftStatus.PENDING:
        _audit_draft(
            db,
            draft,
            "draft.approved",
            user_id,
            before={"status": DraftStatus.PENDING},
            after={"status": DraftStatus.APPROVED},
        )
        draft.status = DraftStatus.APPROVED
    message = await conversations_service.add_agent_message(
        db,
        conversation,
        content=draft.content,
        citations=_cited(draft.content, draft.citations),
        author_id=user_id,
        draft_id=draft.id,
    )
    sent_at = datetime.now(UTC)
    _audit_draft(
        db,
        draft,
        "draft.sent",
        user_id,
        before={"status": draft.status},
        after={
            "status": DraftStatus.SENT,
            "message_id": str(message.id),
            "author_type": draft.author_type,
            "edited": draft.content != draft.original_content,
            "chars": len(draft.content),
        },
    )
    draft.status = DraftStatus.SENT
    draft.sent_message_id = message.id
    draft.sent_at = sent_at
    draft.reviewed_by = user_id
    draft.reviewed_at = sent_at
    record_status_change(
        db, ticket, TicketStatus.REPLIED, actor_type=ActorType.USER, actor_id=user_id
    )
    await db.flush()
    return draft


async def reject_draft(
    db: AsyncSession,
    workspace_id: uuid.UUID,
    ticket_id: uuid.UUID,
    draft_id: uuid.UUID,
    body: DraftReject,
    *,
    user_id: uuid.UUID,
) -> ReplyDraft:
    _, draft = await _locked_draft(db, workspace_id, ticket_id, draft_id)
    reason = (body.reason or "").strip() or None
    _audit_draft(
        db,
        draft,
        "draft.rejected",
        user_id,
        before={"status": draft.status},
        after={"status": DraftStatus.REJECTED, "reason": reason},
    )
    draft.status = DraftStatus.REJECTED
    draft.rejection_reason = reason
    draft.reviewed_by = user_id
    draft.reviewed_at = datetime.now(UTC)
    await db.flush()
    return draft
