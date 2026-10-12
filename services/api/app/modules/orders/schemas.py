import uuid
from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict


class OrderItem(BaseModel):
    sku: str
    name: str
    quantity: int
    unit_price: Decimal


class MockOrderOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    order_number: str
    contact_email: str
    status: Literal["processing", "shipped", "delivered", "cancelled"]
    carrier: str | None
    tracking_number: str | None
    eta: date | None
    total: Decimal
    items: list[OrderItem]


class SeedResult(BaseModel):
    inserted: int
    orders: list[MockOrderOut]
