import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.modules.knowledge.models import DocumentStatus


class DocumentOut(BaseModel):
    """Public document shape. Never includes storage_key."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    filename: str
    mime_type: str
    size_bytes: int
    content_hash: str
    status: DocumentStatus
    error: str | None
    chunk_count: int
    uploaded_by: uuid.UUID | None
    created_at: datetime
    updated_at: datetime


class DocumentPage(BaseModel):
    items: list[DocumentOut]
    next_cursor: str | None
