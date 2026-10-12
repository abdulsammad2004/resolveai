import enum
import uuid
from typing import Any

from sqlalchemy import CheckConstraint, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base, IdMixin, TimestampMixin


class ActorType(enum.StrEnum):
    USER = "user"
    AI = "ai"
    SYSTEM = "system"
    CUSTOMER = "customer"  # a widget visitor (never has an actor_id)


class AuditEvent(IdMixin, TimestampMixin, Base):
    """Append-only record of who did what. The app role can insert and read, never update or
    delete (see the migration). before/after hold short summaries, never message text."""

    __tablename__ = "audit_events"
    __table_args__ = (
        CheckConstraint(
            "actor_type IN ('user', 'ai', 'system', 'customer')", name="actor_type"
        ),
        Index("ix_audit_events_workspace_id_ticket_id", "workspace_id", "ticket_id", "created_at"),
        Index("ix_audit_events_workspace_id_created_at", "workspace_id", "created_at"),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    # The ticket the event belongs to, for its Activity list. No foreign key: the record
    # outlives what it describes.
    ticket_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    actor_type: Mapped[str] = mapped_column(String(8), nullable=False)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    # e.g. "draft.sent", "action.approved", "ticket.status_changed"
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    target_type: Mapped[str] = mapped_column(String(32), nullable=False)
    target_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    before: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    after: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
