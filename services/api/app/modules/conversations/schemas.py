import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

ConversationStatusLiteral = Literal["open", "needs_human", "closed"]
RatingLiteral = Literal["up", "down"]
RoleLiteral = Literal["customer", "assistant", "agent", "system"]


class Citation(BaseModel):
    source_id: str
    chunk_id: uuid.UUID
    document_id: uuid.UUID
    title: str
    heading_path: list[str]
    snippet: str = ""


# Widget ---------------------------------------------------------------------------------


class WidgetSessionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    public_key: str = Field(min_length=1, max_length=64)
    conversation_id: uuid.UUID | None = None
    anonymous_id: str | None = Field(
        default=None, min_length=16, max_length=64, pattern=r"^[A-Za-z0-9_-]+$"
    )
    # The embedding page's origin, as reported to the iframe by the browser (postMessage
    # event.origin). Omitted when the widget page is opened directly.
    host_origin: str | None = Field(default=None, max_length=255)


class WidgetSessionResponse(BaseModel):
    token: str
    expires_in: int
    conversation_id: uuid.UUID
    anonymous_id: str
    workspace_name: str


class WidgetMessageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: str = Field(min_length=1, max_length=2000)


class WidgetMessageOut(BaseModel):
    id: uuid.UUID
    role: RoleLiteral
    content: str
    citations: list[Citation]
    grounded: bool | None
    created_at: datetime
    rating: RatingLiteral | None = None


class WidgetConversationOut(BaseModel):
    id: uuid.UUID
    status: ConversationStatusLiteral
    messages: list[WidgetMessageOut]


class WidgetFeedbackRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message_id: uuid.UUID
    rating: RatingLiteral
    comment: str | None = Field(default=None, max_length=1000)


class FeedbackOut(BaseModel):
    message_id: uuid.UUID
    rating: RatingLiteral
    comment: str | None
    created_at: datetime


class FinalEvent(BaseModel):
    """Payload of the SSE `final` event: the authoritative assistant message."""

    id: uuid.UUID
    content: str
    citations: list[Citation]
    grounded: bool


# Dashboard ------------------------------------------------------------------------------


class ContactOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str | None
    email: str | None
    anonymous_id: str


class ConversationSummary(BaseModel):
    id: uuid.UUID
    status: ConversationStatusLiteral
    channel: str
    contact: ContactOut
    last_message_at: datetime | None
    last_message_preview: str | None
    last_message_role: RoleLiteral | None
    created_at: datetime


class ConversationCounts(BaseModel):
    open: int
    needs_human: int
    closed: int


class ConversationPage(BaseModel):
    items: list[ConversationSummary]
    next_cursor: str | None
    counts: ConversationCounts


class MessageOut(BaseModel):
    id: uuid.UUID
    role: RoleLiteral
    content: str
    citations: list[Citation]
    grounded: bool | None
    prompt_version: str | None
    created_at: datetime
    feedback: FeedbackOut | None = None


class ConversationDetail(BaseModel):
    id: uuid.UUID
    status: ConversationStatusLiteral
    channel: str
    contact: ContactOut
    last_message_at: datetime | None
    created_at: datetime
    messages: list[MessageOut]


class ConversationUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: ConversationStatusLiteral
