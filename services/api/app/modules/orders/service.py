"""Sample orders for demos and, next, the read-only order lookup tool."""

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.orders.models import MockOrder, OrderStatus


def _item(sku: str, name: str, quantity: int, unit_price: str) -> dict[str, Any]:
    return {"sku": sku, "name": name, "quantity": quantity, "unit_price": unit_price}


# (order_number, email, status, carrier, tracking, eta offset in days or None, items)
_SAMPLES: list[tuple[str, str, str, str | None, str | None, int | None, list[dict]]] = [
    ("RA-10421", "maya.robinson@example.com", OrderStatus.SHIPPED, "UPS", "1Z999AA10123456784", 2,
     [_item("TOTE-CNV", "Canvas tote", 1, "24.00"), _item("BEAN-WOL", "Wool beanie", 2, "36.00")]),
    ("RA-10422", "liam.chen@example.com", OrderStatus.PROCESSING, None, None, 5,
     [_item("NOTE-FLD", "Field notebook", 3, "12.50")]),
    ("RA-10423", "sofia.garcia@example.com", OrderStatus.DELIVERED, "USPS", "9400111899223817364520", -3,
     [_item("JKT-RAIN", "Packable rain jacket", 1, "89.00")]),
    ("RA-10424", "noah.patel@example.com", OrderStatus.SHIPPED, "FedEx", "771234567890", 1,
     [_item("BTL-STL", "Steel water bottle", 2, "28.00"), _item("CAP-CTN", "Cotton cap", 1, "22.00")]),
    ("RA-10425", "emma.wilson@example.com", OrderStatus.CANCELLED, None, None, None,
     [_item("BOOT-HIK", "Hiking boots", 1, "149.00")]),
    ("RA-10426", "oliver.nguyen@example.com", OrderStatus.DELIVERED, "DHL", "JD014600006281234567", -10,
     [_item("SCK-MRN", "Merino socks (3 pack)", 2, "27.00")]),
    ("RA-10427", "ava.johnson@example.com", OrderStatus.PROCESSING, None, None, 6,
     [_item("PACK-DAY", "Daypack 20L", 1, "79.00"), _item("BTL-STL", "Steel water bottle", 1, "28.00")]),
    ("RA-10428", "lucas.martin@example.com", OrderStatus.SHIPPED, "UPS", "1Z999AA10123456791", 3,
     [_item("GLV-WRK", "Leather work gloves", 1, "34.00")]),
    ("RA-10429", "maya.robinson@example.com", OrderStatus.DELIVERED, "USPS", "9400111899223817364599", -21,
     [_item("MUG-ENM", "Enamel mug", 4, "14.00")]),
    ("RA-10430", "isabella.rossi@example.com", OrderStatus.SHIPPED, "FedEx", "771234567955", 4,
     [_item("BLK-WOL", "Wool blanket", 1, "119.00"), _item("TOTE-CNV", "Canvas tote", 1, "24.00")]),
]


def _total(items: list[dict]) -> Decimal:
    return sum((Decimal(i["unit_price"]) * i["quantity"] for i in items), Decimal("0.00"))


async def seed(db: AsyncSession, workspace_id: uuid.UUID) -> int:
    """Insert the sample orders; existing order numbers are left alone. Returns rows added."""
    today = datetime.now(UTC).date()
    rows = [
        {
            "id": uuid.uuid4(),
            "workspace_id": workspace_id,
            "order_number": number,
            "contact_email": email,
            "status": status_value,
            "carrier": carrier,
            "tracking_number": tracking,
            "eta": today + timedelta(days=eta) if eta is not None else None,
            "total": _total(items),
            "items": items,
        }
        for number, email, status_value, carrier, tracking, eta, items in _SAMPLES
    ]
    result = await db.execute(
        insert(MockOrder)
        .values(rows)
        .on_conflict_do_nothing(index_elements=["workspace_id", "order_number"])
        .returning(MockOrder.id)
    )
    return len(result.all())


async def list_orders(db: AsyncSession, workspace_id: uuid.UUID) -> list[MockOrder]:
    return list(
        (
            await db.execute(
                select(MockOrder)
                .where(MockOrder.workspace_id == workspace_id)
                .order_by(MockOrder.order_number)
            )
        ).scalars()
    )
