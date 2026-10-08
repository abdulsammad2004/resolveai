"""Conversations: widget sessions, messages, feedback and the agent inbox.

Every function runs on a tenant session (RLS context set). Queries still filter by
workspace_id explicitly; RLS is the last line of defence, not the only one.
"""

import base64
import binascii
import json
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlsplit

from fastapi import HTTPException, status
from sqlalchemy import and_, func, or_, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.conversations.models import (
    Channel,
    Contact,
    Conversation,
    ConversationStatus,
    Feedback,
    FeedbackSource,
    Message,
    MessageRole,
)
from app.modules.conversations.schemas import (
    ContactOut,
    ConversationCounts,
    ConversationDetail,
    ConversationPage,
    ConversationSummary,
    FeedbackOut,
    MessageOut,
    WidgetConversationOut,
    WidgetMessageOut,
)
from app.modules.workspaces.models import Workspace

DEV_LOCALHOST_ORIGIN = "http://localhost:3000"
PREVIEW_CHARS = 140
# A resend of the same text within this window is treated as a retry, not a new message.
RETRY_WINDOW = timedelta(minutes=10)
VISIBLE_ROLES = (MessageRole.CUSTOMER, MessageRole.ASSISTANT, MessageRole.AGENT)


def _not_found(what: str = "Conversation") -> HTTPException:
    return HTTPException(status.HTTP_404_NOT_FOUND, f"{what} not found")


def now() -> datetime:
    # Explicit timestamps: now() in Postgres is the transaction start, which would give a
    # question and its answer the same created_at if they ever shared a transaction.
    return datetime.now(UTC)


# Widget key and origin --------------------------------------------------------------------


@dataclass(frozen=True)
class WidgetKey:
    workspace_id: uuid.UUID
    allowed_origins: list[str]


async def resolve_widget_key(db: AsyncSession, public_key: str) -> WidgetKey | None:
    """Look up a workspace by widget key before any tenant context exists."""
    row = (
        await db.execute(
            text("SELECT workspace_id, allowed_origins FROM resolve_widget_key(:key)"),
            {"key": public_key},
        )
    ).first()
    if row is None:
        return None
    return WidgetKey(workspace_id=row.workspace_id, allowed_origins=list(row.allowed_origins))


def normalize_origin(value: str | None) -> str | None:
    if not value:
        return None
    parts = urlsplit(value.strip().lower())
    if parts.scheme not in ("http", "https") or not parts.hostname:
        return None
    return f"{parts.scheme}://{parts.netloc}"


def origin_allowed(
    *,
    request_origin: str | None,
    host_origin: str | None,
    allowed_origins: list[str],
    app_origins: list[str],
    dev_allow_localhost: bool,
) -> bool:
    """The widget runs in an iframe served by our web app, so two origins matter.

    `request_origin` (the Origin header) must be our web app, or the host page itself when
    the API is called directly. `host_origin` (the page embedding the widget) must be one of
    the workspace's allowed origins.
    """
    origin = normalize_origin(request_origin)
    if origin is None:
        return False
    host = normalize_origin(host_origin) or origin
    allowed = {o for o in (normalize_origin(a) for a in allowed_origins) if o}
    if dev_allow_localhost:
        allowed.add(DEV_LOCALHOST_ORIGIN)
    trusted_frames = {o for o in (normalize_origin(a) for a in app_origins) if o}
    if origin != host and origin not in trusted_frames:
        return False
    return host in allowed


# Widget session ---------------------------------------------------------------------------


def new_anonymous_id() -> str:
    return secrets.token_urlsafe(24)


async def start_session(
    db: AsyncSession,
    workspace_id: uuid.UUID,
    conversation_id: uuid.UUID | None,
    anonymous_id: str | None,
) -> tuple[Conversation, Contact]:
    """Reuse the visitor's open conversation when they prove it is theirs, else start one."""
    contact: Contact | None = None
    if anonymous_id:
        contact = (
            await db.execute(
                select(Contact).where(
                    Contact.workspace_id == workspace_id, Contact.anonymous_id == anonymous_id
                )
            )
        ).scalar_one_or_none()

    if contact is not None and conversation_id is not None:
        conversation = (
            await db.execute(
                select(Conversation).where(
                    Conversation.workspace_id == workspace_id,
                    Conversation.id == conversation_id,
                    Conversation.contact_id == contact.id,
                    Conversation.status != ConversationStatus.CLOSED,
                )
            )
        ).scalar_one_or_none()
        if conversation is not None:
            return conversation, contact

    if contact is None:
        contact = Contact(workspace_id=workspace_id, anonymous_id=new_anonymous_id())
        db.add(contact)
        await db.flush()

    conversation = Conversation(
        workspace_id=workspace_id,
        contact_id=contact.id,
        channel=Channel.WIDGET,
        status=ConversationStatus.OPEN,
    )
    db.add(conversation)
    await db.flush()
    return conversation, contact


async def workspace_name(db: AsyncSession, workspace_id: uuid.UUID) -> str:
    name = (
        await db.execute(select(Workspace.name).where(Workspace.id == workspace_id))
    ).scalar_one_or_none()
    if name is None:
        raise _not_found("Workspace")
    return name


# Messages ---------------------------------------------------------------------------------


async def get_conversation(
    db: AsyncSession, workspace_id: uuid.UUID, conversation_id: uuid.UUID
) -> Conversation:
    conversation = (
        await db.execute(
            select(Conversation).where(
                Conversation.workspace_id == workspace_id, Conversation.id == conversation_id
            )
        )
    ).scalar_one_or_none()
    if conversation is None:
        raise _not_found()
    return conversation


async def _messages(
    db: AsyncSession, workspace_id: uuid.UUID, conversation_id: uuid.UUID
) -> list[Message]:
    return list(
        (
            await db.execute(
                select(Message)
                .where(
                    Message.workspace_id == workspace_id,
                    Message.conversation_id == conversation_id,
                    Message.role.in_(VISIBLE_ROLES),
                )
                .order_by(Message.created_at, Message.id)
            )
        ).scalars()
    )


async def add_customer_message(
    db: AsyncSession, conversation: Conversation, content: str
) -> tuple[Message, list[Message]]:
    """Store the customer's message; return it with the messages that came before it.

    If the latest message is the same unanswered text (the client retrying after an error),
    it is reused instead of being stored twice.
    """
    history = await _messages(db, conversation.workspace_id, conversation.id)
    last = history[-1] if history else None
    if (
        last is not None
        and last.role == MessageRole.CUSTOMER
        and last.content == content
        and now() - last.created_at < RETRY_WINDOW
    ):
        return last, history[:-1]

    message = Message(
        workspace_id=conversation.workspace_id,
        conversation_id=conversation.id,
        role=MessageRole.CUSTOMER,
        content=content,
        citations=[],
        created_at=now(),
    )
    db.add(message)
    conversation.last_message_at = message.created_at
    if conversation.status == ConversationStatus.CLOSED:
        conversation.status = ConversationStatus.OPEN
    await db.flush()
    return message, history


async def add_assistant_message(
    db: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    conversation_id: uuid.UUID,
    content: str,
    citations: list[dict[str, Any]],
    grounded: bool,
    llm_call_id: uuid.UUID | None,
    prompt_version: str | None,
) -> Message:
    conversation = await get_conversation(db, workspace_id, conversation_id)
    message = Message(
        workspace_id=workspace_id,
        conversation_id=conversation_id,
        role=MessageRole.ASSISTANT,
        content=content,
        citations=citations,
        grounded=grounded,
        llm_call_id=llm_call_id,
        prompt_version=prompt_version,
        created_at=now(),
    )
    db.add(message)
    conversation.last_message_at = message.created_at
    if not grounded:
        conversation.status = ConversationStatus.NEEDS_HUMAN
    await db.flush()
    return message


async def _feedback_by_message(
    db: AsyncSession, workspace_id: uuid.UUID, message_ids: list[uuid.UUID]
) -> dict[uuid.UUID, Feedback]:
    if not message_ids:
        return {}
    rows = (
        await db.execute(
            select(Feedback).where(
                Feedback.workspace_id == workspace_id, Feedback.message_id.in_(message_ids)
            )
        )
    ).scalars()
    return {f.message_id: f for f in rows}


async def widget_conversation(
    db: AsyncSession, workspace_id: uuid.UUID, conversation_id: uuid.UUID
) -> WidgetConversationOut:
    conversation = await get_conversation(db, workspace_id, conversation_id)
    messages = await _messages(db, workspace_id, conversation_id)
    feedback = await _feedback_by_message(db, workspace_id, [m.id for m in messages])
    return WidgetConversationOut(
        id=conversation.id,
        status=conversation.status,  # type: ignore[arg-type]
        messages=[
            WidgetMessageOut(
                id=m.id,
                role=m.role,  # type: ignore[arg-type]
                content=m.content,
                citations=m.citations,  # type: ignore[arg-type]
                grounded=m.grounded,
                created_at=m.created_at,
                rating=feedback[m.id].rating if m.id in feedback else None,  # type: ignore[arg-type]
            )
            for m in messages
        ],
    )


async def set_feedback(
    db: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    conversation_id: uuid.UUID,
    message_id: uuid.UUID,
    rating: str,
    comment: str | None,
) -> Feedback:
    """Rate an assistant message in this conversation. The latest rating wins."""
    message = (
        await db.execute(
            select(Message).where(
                Message.workspace_id == workspace_id,
                Message.conversation_id == conversation_id,
                Message.id == message_id,
            )
        )
    ).scalar_one_or_none()
    if message is None:
        raise _not_found("Message")
    if message.role != MessageRole.ASSISTANT:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "Only assistant answers can be rated"
        )

    stmt = (
        insert(Feedback)
        .values(
            id=uuid.uuid4(),
            workspace_id=workspace_id,
            message_id=message_id,
            source=FeedbackSource.CUSTOMER,
            rating=rating,
            comment=comment,
        )
        .on_conflict_do_update(
            index_elements=[Feedback.message_id],
            set_={"rating": rating, "comment": comment, "updated_at": func.now()},
        )
        .returning(Feedback)
    )
    return (await db.execute(stmt)).scalar_one()


# Agent inbox ------------------------------------------------------------------------------


def _encode_cursor(at: datetime, conversation_id: uuid.UUID) -> str:
    raw = json.dumps([at.isoformat(), str(conversation_id)]).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _decode_cursor(cursor: str) -> tuple[datetime, uuid.UUID]:
    try:
        raw = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4))
        at, cid = json.loads(raw)
        return datetime.fromisoformat(at), uuid.UUID(cid)
    except (binascii.Error, ValueError, TypeError) as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Invalid cursor") from exc


async def list_conversations(
    db: AsyncSession,
    workspace_id: uuid.UUID,
    *,
    status_filter: str | None,
    cursor: str | None,
    limit: int,
) -> ConversationPage:
    """Conversations with at least one message, newest activity first."""
    last = (
        select(Message.content, Message.role)
        .where(
            Message.workspace_id == workspace_id,
            Message.conversation_id == Conversation.id,
            Message.role.in_(VISIBLE_ROLES),
        )
        .order_by(Message.created_at.desc(), Message.id.desc())
        .limit(1)
        .correlate(Conversation)
        .lateral("last_message")
    )
    stmt = (
        select(Conversation, Contact, last.c.content, last.c.role)
        .join(Contact, Contact.id == Conversation.contact_id)
        .outerjoin(last, text("true"))
        .where(
            Conversation.workspace_id == workspace_id,
            Contact.workspace_id == workspace_id,
            Conversation.last_message_at.is_not(None),
        )
        .order_by(Conversation.last_message_at.desc(), Conversation.id.desc())
        .limit(limit + 1)
    )
    if status_filter:
        stmt = stmt.where(Conversation.status == status_filter)
    if cursor:
        at, cid = _decode_cursor(cursor)
        stmt = stmt.where(
            or_(
                Conversation.last_message_at < at,
                and_(Conversation.last_message_at == at, Conversation.id < cid),
            )
        )
    rows = (await db.execute(stmt)).all()
    page = rows[:limit]
    next_cursor = None
    if len(rows) > limit:
        tail = page[-1][0]
        next_cursor = _encode_cursor(tail.last_message_at, tail.id)

    counts = dict(
        (
            await db.execute(
                select(Conversation.status, func.count())
                .where(
                    Conversation.workspace_id == workspace_id,
                    Conversation.last_message_at.is_not(None),
                )
                .group_by(Conversation.status)
            )
        ).all()
    )
    return ConversationPage(
        items=[
            ConversationSummary(
                id=conv.id,
                status=conv.status,  # type: ignore[arg-type]
                channel=conv.channel,
                contact=ContactOut.model_validate(contact),
                last_message_at=conv.last_message_at,
                last_message_preview=content[:PREVIEW_CHARS] if content else None,
                last_message_role=role,
                created_at=conv.created_at,
            )
            for conv, contact, content, role in page
        ],
        next_cursor=next_cursor,
        counts=ConversationCounts(
            open=counts.get(ConversationStatus.OPEN, 0),
            needs_human=counts.get(ConversationStatus.NEEDS_HUMAN, 0),
            closed=counts.get(ConversationStatus.CLOSED, 0),
        ),
    )


async def conversation_detail(
    db: AsyncSession, workspace_id: uuid.UUID, conversation_id: uuid.UUID
) -> ConversationDetail:
    conversation = await get_conversation(db, workspace_id, conversation_id)
    contact = (
        await db.execute(
            select(Contact).where(
                Contact.workspace_id == workspace_id, Contact.id == conversation.contact_id
            )
        )
    ).scalar_one()
    messages = await _messages(db, workspace_id, conversation_id)
    feedback = await _feedback_by_message(db, workspace_id, [m.id for m in messages])
    return ConversationDetail(
        id=conversation.id,
        status=conversation.status,  # type: ignore[arg-type]
        channel=conversation.channel,
        contact=ContactOut.model_validate(contact),
        last_message_at=conversation.last_message_at,
        created_at=conversation.created_at,
        messages=[
            MessageOut(
                id=m.id,
                role=m.role,  # type: ignore[arg-type]
                content=m.content,
                citations=m.citations,  # type: ignore[arg-type]
                grounded=m.grounded,
                prompt_version=m.prompt_version,
                created_at=m.created_at,
                feedback=(
                    FeedbackOut(
                        message_id=m.id,
                        rating=feedback[m.id].rating,  # type: ignore[arg-type]
                        comment=feedback[m.id].comment,
                        created_at=feedback[m.id].updated_at,
                    )
                    if m.id in feedback
                    else None
                ),
            )
            for m in messages
        ],
    )


async def update_status(
    db: AsyncSession, workspace_id: uuid.UUID, conversation_id: uuid.UUID, new_status: str
) -> Conversation:
    conversation = await get_conversation(db, workspace_id, conversation_id)
    conversation.status = new_status
    await db.flush()
    return conversation
