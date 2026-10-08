import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, model_validator

from app.modules.conversations.schemas import ContactOut, ConversationDetail

TicketStatusLiteral = Literal["new", "triaged", "awaiting_review", "replied", "resolved"]
TicketPriorityLiteral = Literal["low", "normal", "high", "urgent"]
TicketIntentLiteral = Literal[
    "greeting",
    "thanks",
    "knowledge_question",
    "order_status",
    "refund_request",
    "complaint",
    "account_change",
    "other",
]
AssigneeFilter = Literal["me", "unassigned", "any"]


class ClassificationOut(BaseModel):
    intent: str
    intent_probs: dict[str, float]
    priority: str
    priority_probs: dict[str, float]
    needs_human_prob: float
    confidence: float
    provider: str
    model: str


class MemberRef(BaseModel):
    user_id: uuid.UUID
    full_name: str
    email: str


class TicketSummary(BaseModel):
    id: uuid.UUID
    subject: str
    intent: TicketIntentLiteral
    priority: TicketPriorityLiteral
    status: TicketStatusLiteral
    source: Literal["widget", "manual"]
    confidence: float | None
    contact: ContactOut | None
    assignee: MemberRef | None
    conversation_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime


class TicketCounts(BaseModel):
    new: int
    triaged: int
    awaiting_review: int
    replied: int
    resolved: int
    # Not resolved, and not resolved with urgent priority.
    open: int
    urgent_open: int


class TicketPage(BaseModel):
    items: list[TicketSummary]
    next_cursor: str | None
    counts: TicketCounts


class TicketDetail(TicketSummary):
    description: str | None
    classification: ClassificationOut | None
    conversation: ConversationDetail | None


class TicketCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    subject: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1, max_length=5000)
    contact_email: EmailStr | None = None


class TicketUpdate(BaseModel):
    """Only the fields sent are changed; `assignee_id: null` unassigns."""

    model_config = ConfigDict(extra="forbid")

    status: TicketStatusLiteral | None = None
    priority: TicketPriorityLiteral | None = None
    assignee_id: uuid.UUID | None = None

    @model_validator(mode="after")
    def at_least_one_field(self) -> "TicketUpdate":
        if not self.model_fields_set:
            raise ValueError("send at least one of status, priority or assignee_id")
        if "status" in self.model_fields_set and self.status is None:
            raise ValueError("status can't be null")
        if "priority" in self.model_fields_set and self.priority is None:
            raise ValueError("priority can't be null")
        return self
