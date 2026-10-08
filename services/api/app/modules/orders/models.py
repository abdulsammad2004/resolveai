import enum
import uuid
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import CheckConstraint, Date, ForeignKey, Numeric, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base, IdMixin, TimestampMixin


class OrderStatus(enum.StrEnum):
    PROCESSING = "processing"
    SHIPPED = "shipped"
    DELIVERED = "delivered"
    CANCELLED = "cancelled"


class MockOrder(IdMixin, TimestampMixin, Base):
    """Sample orders standing in for a real order API (looked up by tools later)."""

    __tablename__ = "mock_orders"
    __table_args__ = (
        UniqueConstraint("workspace_id", "order_number"),
        CheckConstraint(
            "status IN ('processing', 'shipped', 'delivered', 'cancelled')", name="status"
        ),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    order_number: Mapped[str] = mapped_column(String(32), nullable=False)
    contact_email: Mapped[str] = mapped_column(String(320), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    carrier: Mapped[str | None] = mapped_column(String(64), nullable=True)
    tracking_number: Mapped[str | None] = mapped_column(String(64), nullable=True)
    eta: Mapped[date | None] = mapped_column(Date, nullable=True)
    total: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    # [{sku, name, quantity, unit_price}]
    items: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)
