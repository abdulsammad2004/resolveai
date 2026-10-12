import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, DateTime, Float, ForeignKey, Index, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base, IdMixin, TimestampMixin


class TicketStatus(enum.StrEnum):
    NEW = "new"
    TRIAGED = "triaged"
    AWAITING_REVIEW = "awaiting_review"
    REPLIED = "replied"
    RESOLVED = "resolved"


class TicketPriority(enum.StrEnum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    URGENT = "urgent"


class TicketSource(enum.StrEnum):
    WIDGET = "widget"
    MANUAL = "manual"


PRIORITY_ORDER = {p: i for i, p in enumerate(TicketPriority)}


class Ticket(IdMixin, TimestampMixin, Base):
    __tablename__ = "tickets"
    __table_args__ = (
        CheckConstraint(
            "status IN ('new', 'triaged', 'awaiting_review', 'replied', 'resolved')",
            name="status",
        ),
        CheckConstraint("priority IN ('low', 'normal', 'high', 'urgent')", name="priority"),
        CheckConstraint("source IN ('widget', 'manual')", name="source"),
        CheckConstraint("resolution_rating IN ('up', 'down')", name="resolution_rating"),
        Index("ix_tickets_workspace_id_created_at", "workspace_id", "created_at", "id"),
        Index("ix_tickets_workspace_id_status", "workspace_id", "status"),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("conversations.id", ondelete="SET NULL"), nullable=True
    )
    contact_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("contacts.id", ondelete="SET NULL"), nullable=True
    )
    subject: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    intent: Mapped[str] = mapped_column(String(32), nullable=False)
    priority: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default=TicketStatus.NEW)
    assignee_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    # {intent, intent_probs, priority, priority_probs, needs_human_prob, confidence,
    #  provider, model}; NULL when the ticket was created without a classification.
    classification: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    source: Mapped[str] = mapped_column(String(16), nullable=False)
    # The customer's answer to "Was this helpful?" after the ticket was resolved.
    resolution_rating: Mapped[str | None] = mapped_column(String(8), nullable=True)
    resolution_rated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class DraftStatus(enum.StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    EDITED = "edited"
    REJECTED = "rejected"
    SENT = "sent"
    SUPERSEDED = "superseded"  # replaced by a newer draft before anyone reviewed it
    FAILED = "failed"  # drafting gave up; `error` says why


class DraftAuthor(enum.StrEnum):
    AI = "ai"
    HUMAN = "human"  # started blank with "Write reply"


class ReplyDraft(IdMixin, TimestampMixin, Base):
    """An AI-proposed reply. Never sent on its own: a person reviews it first."""

    __tablename__ = "reply_drafts"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'approved', 'edited', 'rejected', 'sent', 'superseded', "
            "'failed')",
            name="status",
        ),
        CheckConstraint("author_type IN ('ai', 'human')", name="author_type"),
        Index("ix_reply_drafts_workspace_id_ticket_id", "workspace_id", "ticket_id", "created_at"),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    ticket_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tickets.id", ondelete="CASCADE"), nullable=False
    )
    # The text as it stands (and, once sent, as it was sent). original_content keeps what the
    # AI wrote, empty for a reply a person started, so the edit rate can be measured.
    content: Mapped[str] = mapped_column(Text, nullable=False)
    original_content: Mapped[str] = mapped_column(
        Text, nullable=False, default="", server_default=""
    )
    author_type: Mapped[str] = mapped_column(
        String(8), nullable=False, default=DraftAuthor.AI, server_default=DraftAuthor.AI
    )
    # [{source_id, chunk_id, document_id, title, heading_path, snippet}]
    citations: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False, default=DraftStatus.PENDING)
    prompt_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    llm_call_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("llm_calls.id", ondelete="SET NULL"), nullable=True
    )
    error: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # Fingerprint of what the draft was written from (ticket, messages, prompt), so an
    # unchanged ticket isn't drafted twice.
    input_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rejection_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # use_alter: messages also reference reply_drafts.
    sent_message_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("messages.id", ondelete="SET NULL", use_alter=True),
        nullable=True,
    )
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
