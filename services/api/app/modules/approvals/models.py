import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base, IdMixin, TimestampMixin


class ActionRisk(enum.StrEnum):
    WRITE = "write"
    SENSITIVE = "sensitive"


class ActionStatus(enum.StrEnum):
    PROPOSED = "proposed"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXECUTING = "executing"
    SUCCEEDED = "succeeded"  # executed
    FAILED = "failed"


class ActionRequest(IdMixin, TimestampMixin, Base):
    """A write or sensitive tool call the model proposed. It never runs on its own: a person
    approves it first, and the stored arguments are what will run."""

    __tablename__ = "action_requests"
    __table_args__ = (
        UniqueConstraint("idempotency_key"),
        CheckConstraint("risk IN ('write', 'sensitive')", name="risk"),
        CheckConstraint(
            "status IN ('proposed', 'approved', 'rejected', 'executing', 'succeeded', 'failed')",
            name="status",
        ),
        Index("ix_action_requests_workspace_id_status", "workspace_id", "status", "created_at"),
        Index("ix_action_requests_workspace_id_ticket_id", "workspace_id", "ticket_id"),
        Index("ix_action_requests_workspace_id_created_at", "workspace_id", "created_at"),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    ticket_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tickets.id", ondelete="CASCADE"), nullable=False
    )
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("conversations.id", ondelete="SET NULL"), nullable=True
    )
    tool_name: Mapped[str] = mapped_column(String(64), nullable=False)
    arguments: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    risk: Mapped[str] = mapped_column(String(16), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default=ActionStatus.PROPOSED
    )
    # sha256 of (ticket, tool, canonical arguments): the same proposal is stored once.
    idempotency_key: Mapped[str] = mapped_column(String(64), nullable=False)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    # Who approved or rejected it, when, and (for a rejection) why.
    decided_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    decision_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # Set when a worker claims the action; a stale value means the worker died mid-run.
    execution_started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    executed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
