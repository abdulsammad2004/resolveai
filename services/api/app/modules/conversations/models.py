import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base, IdMixin, TimestampMixin


class ConversationStatus(enum.StrEnum):
    OPEN = "open"
    NEEDS_HUMAN = "needs_human"
    CLOSED = "closed"


class Channel(enum.StrEnum):
    WIDGET = "widget"


class MessageRole(enum.StrEnum):
    CUSTOMER = "customer"
    ASSISTANT = "assistant"
    AGENT = "agent"
    SYSTEM = "system"


class MessageRoute(enum.StrEnum):
    """How an assistant reply was produced."""

    ANSWER = "answer"  # grounded RAG answer
    FALLBACK = "fallback"  # no sources / no valid citation / budget: handed to a person
    SMALL_TALK = "small_talk"  # fixed reply to a greeting or thanks
    HANDOFF = "handoff"  # routed straight to the team as a ticket


class Rating(enum.StrEnum):
    UP = "up"
    DOWN = "down"


class FeedbackSource(enum.StrEnum):
    CUSTOMER = "customer"


def _workspace_fk() -> Mapped[uuid.UUID]:
    return mapped_column(
        UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )


class Contact(IdMixin, TimestampMixin, Base):
    """A widget visitor. Not a user: no login, identified by a random anonymous id."""

    __tablename__ = "contacts"
    __table_args__ = (UniqueConstraint("workspace_id", "anonymous_id"),)

    workspace_id: Mapped[uuid.UUID] = _workspace_fk()
    anonymous_id: Mapped[str] = mapped_column(String(64), nullable=False)
    email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    name: Mapped[str | None] = mapped_column(String(200), nullable=True)


class Conversation(IdMixin, TimestampMixin, Base):
    __tablename__ = "conversations"
    __table_args__ = (
        CheckConstraint("channel IN ('widget')", name="channel"),
        CheckConstraint("status IN ('open', 'needs_human', 'closed')", name="status"),
        # Newest-activity-first cursor pagination within a workspace.
        Index(
            "ix_conversations_workspace_id_last_message_at",
            "workspace_id",
            "last_message_at",
            "id",
        ),
    )

    workspace_id: Mapped[uuid.UUID] = _workspace_fk()
    contact_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("contacts.id", ondelete="CASCADE"), nullable=False
    )
    channel: Mapped[str] = mapped_column(String(16), nullable=False, default=Channel.WIDGET)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default=ConversationStatus.OPEN
    )
    # NULL until the first message, so empty widget sessions stay out of the inbox.
    last_message_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # The conversation's current ticket, once one was opened. use_alter: tickets also
    # reference conversations, so this foreign key is added after both tables exist.
    ticket_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tickets.id", ondelete="SET NULL", use_alter=True),
        nullable=True,
    )


class Message(IdMixin, TimestampMixin, Base):
    __tablename__ = "messages"
    __table_args__ = (
        CheckConstraint(
            "role IN ('customer', 'assistant', 'agent', 'system')", name="role"
        ),
        CheckConstraint(
            "route IN ('answer', 'fallback', 'small_talk', 'handoff')", name="route"
        ),
        Index(
            "ix_messages_workspace_id_conversation_id_created_at",
            "workspace_id",
            "conversation_id",
            "created_at",
        ),
    )

    workspace_id: Mapped[uuid.UUID] = _workspace_fk()
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    # [{source_id, chunk_id, document_id, title, heading_path, snippet}]
    citations: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    # Only set on assistant messages.
    grounded: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    llm_call_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("llm_calls.id", ondelete="SET NULL"), nullable=True
    )
    prompt_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Customer messages: the classification that routed them (see app.ai.decisions).
    classification: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    # Assistant messages: how the reply was produced (MessageRoute).
    route: Mapped[str | None] = mapped_column(String(16), nullable=True)


class Feedback(IdMixin, TimestampMixin, Base):
    """One rating per message; a new rating replaces the previous one."""

    __tablename__ = "feedback"
    __table_args__ = (
        UniqueConstraint("message_id"),
        CheckConstraint("source IN ('customer')", name="source"),
        CheckConstraint("rating IN ('up', 'down')", name="rating"),
        Index("ix_feedback_workspace_id_created_at", "workspace_id", "created_at"),
    )

    workspace_id: Mapped[uuid.UUID] = _workspace_fk()
    message_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("messages.id", ondelete="CASCADE"), nullable=False
    )
    source: Mapped[str] = mapped_column(
        String(16), nullable=False, default=FeedbackSource.CUSTOMER
    )
    rating: Mapped[str] = mapped_column(String(8), nullable=False)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
