"""Agent inbox for widget conversations. Any member of the workspace may use it."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Query

from app.core.deps import CurrentPrincipal, TenantDB
from app.modules.conversations import service
from app.modules.conversations.schemas import (
    ConversationDetail,
    ConversationPage,
    ConversationStatusLiteral,
    ConversationUpdate,
)

router = APIRouter(prefix="/conversations", tags=["conversations"])


@router.get("", response_model=ConversationPage)
async def list_conversations(
    principal: CurrentPrincipal,
    db: TenantDB,
    status: ConversationStatusLiteral | None = None,
    cursor: Annotated[str | None, Query(max_length=512)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
) -> ConversationPage:
    """Conversations with messages, newest activity first, plus counts per status."""
    return await service.list_conversations(
        db, principal.workspace_id, status_filter=status, cursor=cursor, limit=limit
    )


@router.get("/{conversation_id}", response_model=ConversationDetail)
async def get_conversation(
    conversation_id: uuid.UUID, principal: CurrentPrincipal, db: TenantDB
) -> ConversationDetail:
    return await service.conversation_detail(db, principal.workspace_id, conversation_id)


@router.patch("/{conversation_id}", response_model=ConversationDetail)
async def update_conversation(
    conversation_id: uuid.UUID, body: ConversationUpdate, principal: CurrentPrincipal, db: TenantDB
) -> ConversationDetail:
    await service.update_status(db, principal.workspace_id, conversation_id, body.status)
    return await service.conversation_detail(db, principal.workspace_id, conversation_id)
