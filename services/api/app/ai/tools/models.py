import enum
import uuid
from typing import Any

from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base, IdMixin, TimestampMixin


class ToolCallStatus(enum.StrEnum):
    OK = "ok"  # a read tool ran and returned data
    NOT_FOUND = "not_found"  # a lookup matched nothing (or the details didn't match)
    INVALID = "invalid"  # arguments failed schema or business validation
    PROPOSED = "proposed"  # a write/sensitive tool became an action request
    DENIED = "denied"  # unknown tool, or not allowed in this run
    ERROR = "error"  # the tool itself failed


class ToolCall(IdMixin, TimestampMixin, Base):
    """Every tool call the model made, whatever the outcome. Arguments are stored with
    customer emails masked; result_summary is a short plain-language line for the Inbox."""

    __tablename__ = "tool_calls"
    __table_args__ = (
        CheckConstraint(
            "status IN ('ok', 'not_found', 'invalid', 'proposed', 'denied', 'error')",
            name="status",
        ),
        Index("ix_tool_calls_workspace_id_ticket_id", "workspace_id", "ticket_id", "created_at"),
        Index(
            "ix_tool_calls_workspace_id_conversation_id",
            "workspace_id",
            "conversation_id",
            "created_at",
        ),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("conversations.id", ondelete="SET NULL"), nullable=True
    )
    ticket_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tickets.id", ondelete="SET NULL"), nullable=True
    )
    tool_name: Mapped[str] = mapped_column(String(64), nullable=False)
    arguments: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    result_summary: Mapped[str] = mapped_column(String(300), nullable=False)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False)
