"""Tickets: created by widget routing or by hand, triaged in the Inbox.

Queries filter by workspace_id explicitly on top of RLS. Status, priority and assignee
changes write nothing else yet (the audit log comes later).
"""

import base64
import binascii
import json
import uuid
from datetime import datetime

from fastapi import HTTPException, status
from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.decisions import Classification
from app.modules.auth.models import User
from app.modules.conversations import service as conversations_service
from app.modules.conversations.models import Contact, Conversation
from app.modules.conversations.schemas import ContactOut
from app.modules.tickets.models import (
    PRIORITY_ORDER,
    Ticket,
    TicketPriority,
    TicketSource,
    TicketStatus,
)
from app.modules.tickets.schemas import (
    ClassificationOut,
    MemberRef,
    TicketCounts,
    TicketCreate,
    TicketDetail,
    TicketPage,
    TicketSummary,
    TicketUpdate,
)
from app.modules.workspaces.models import Membership

SUBJECT_CHARS = 80


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


async def ensure_conversation_ticket(
    db: AsyncSession,
    conversation: Conversation,
    classification: Classification | None,
    trigger_text: str,
) -> Ticket:
    """The conversation's open ticket, or a new one. A reused ticket's priority only rises."""
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

    ticket = Ticket(
        workspace_id=conversation.workspace_id,
        conversation_id=conversation.id,
        contact_id=conversation.contact_id,
        subject=subject_from(trigger_text),
        status=TicketStatus.NEW,
        source=TicketSource.WIDGET,
        **_fields(classification),
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
    return TicketDetail(
        **_summary(ticket, contact, assignee).model_dump(),
        description=ticket.description,
        classification=(
            ClassificationOut.model_validate(ticket.classification)
            if ticket.classification
            else None
        ),
        conversation=conversation,
    )


async def update_ticket(
    db: AsyncSession, workspace_id: uuid.UUID, ticket_id: uuid.UUID, changes: TicketUpdate
) -> Ticket:
    ticket = (
        await db.execute(
            select(Ticket).where(Ticket.workspace_id == workspace_id, Ticket.id == ticket_id)
        )
    ).scalar_one_or_none()
    if ticket is None:
        raise _not_found()

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
    if "assignee_id" in fields:
        ticket.assignee_id = changes.assignee_id
    if "status" in fields and changes.status:
        ticket.status = changes.status
    if "priority" in fields and changes.priority:
        ticket.priority = changes.priority
    await db.flush()
    return ticket
