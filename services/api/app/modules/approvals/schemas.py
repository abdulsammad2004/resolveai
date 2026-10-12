import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

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
    created_at: datetime
    updated_at: datetime


class ActionListItem(ActionRequestOut):
    ticket_subject: str


class ActionList(BaseModel):
    items: list[ActionListItem]
