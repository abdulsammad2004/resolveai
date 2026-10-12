import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.modules.conversations.schemas import ContactOut

ActionStatusLiteral = Literal[
    "proposed", "approved", "rejected", "executing", "succeeded", "failed"
]
ActionRiskLiteral = Literal["write", "sensitive"]


class ActionRequestOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    ticket_id: uuid.UUID
    conversation_id: uuid.UUID | None
    tool_name: str
    arguments: dict[str, Any]
    risk: ActionRiskLiteral
    reason: str
    status: ActionStatusLiteral
    # Who approved or rejected it, when, and why (rejections only).
    decided_by: uuid.UUID | None = None
    decided_by_name: str | None = None
    decided_at: datetime | None = None
    decision_reason: str | None = None
    executed_at: datetime | None = None
    # After execution: {ok, summary, ...details}. `summary` is a short plain-language line.
    result: dict[str, Any] | None = None
    created_at: datetime
    updated_at: datetime


class ActionListItem(ActionRequestOut):
    ticket_subject: str
    contact: ContactOut | None = None
    order_number: str | None = None
    # The amount asked for; for a refund without one, the order total.
    amount: Decimal | None = None
    order_total: Decimal | None = None


class ActionList(BaseModel):
    items: list[ActionListItem]


class ActionReject(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    reason: str = Field(min_length=3, max_length=500)
