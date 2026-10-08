"""Customer chat widget. Called by anonymous visitors with a widget token, never a user token."""

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse

from app.ai.embeddings import EmbeddingClient, get_embedding_client
from app.ai.llm import LLMConfigError, UsageReportingLLMClient, get_llm_client
from app.core.config import get_settings
from app.core.deps import CurrentWidget, DBSession, WidgetDB, tenant_session
from app.core.middleware import get_request_id
from app.core.security import create_widget_token
from app.modules.conversations import service
from app.modules.conversations.chat import AnswerRequest, HistoryItem, stream_answer
from app.modules.conversations.limits import WidgetLimiter, get_widget_limiter
from app.modules.conversations.schemas import (
    FeedbackOut,
    WidgetConversationOut,
    WidgetFeedbackRequest,
    WidgetMessageRequest,
    WidgetSessionRequest,
    WidgetSessionResponse,
)

logger = logging.getLogger("app.api.widget")

router = APIRouter(prefix="/widget", tags=["widget"])

RATE_LIMIT_WINDOW_S = 60
RATE_LIMITED_MESSAGE = "You're sending messages a little fast. Please wait a moment and try again."
SSE_HEADERS = {
    # no-transform stops compression middleware/proxies from buffering the stream.
    "Cache-Control": "no-cache, no-transform",
    "X-Accel-Buffering": "no",
}


def get_chat_llm() -> UsageReportingLLMClient:
    try:
        return get_llm_client()
    except LLMConfigError as exc:
        logger.error("Widget chat unavailable: chat model is not configured")
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "Chat is not available right now"
        ) from exc


def get_widget_embedder() -> EmbeddingClient:
    try:
        return get_embedding_client()
    except RuntimeError as exc:
        logger.error("Widget chat unavailable: embedding client is not configured")
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "Chat is not available right now"
        ) from exc


Limiter = Annotated[WidgetLimiter, Depends(get_widget_limiter)]
ChatLLM = Annotated[UsageReportingLLMClient, Depends(get_chat_llm)]
Embedder = Annotated[EmbeddingClient, Depends(get_widget_embedder)]


@router.post("/session", response_model=WidgetSessionResponse)
async def create_session(
    body: WidgetSessionRequest, request: Request, db: DBSession
) -> WidgetSessionResponse:
    """Start or resume a widget conversation. Public: authenticated by key and origin."""
    key = await service.resolve_widget_key(db, body.public_key)
    if key is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown widget key")

    settings = get_settings()
    if not service.origin_allowed(
        request_origin=request.headers.get("origin"),
        host_origin=body.host_origin,
        allowed_origins=key.allowed_origins,
        app_origins=settings.cors_origins,
        dev_allow_localhost=settings.widget_dev_allow_localhost,
    ):
        logger.info("Widget session refused: origin not allowed (workspace_id=%s)", key.workspace_id)
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "This website is not allowed to use this chat widget"
        )

    async with tenant_session(key.workspace_id) as tdb:
        conversation, contact = await service.start_session(
            tdb, key.workspace_id, body.conversation_id, body.anonymous_id
        )
        name = await service.workspace_name(tdb, key.workspace_id)

    return WidgetSessionResponse(
        token=create_widget_token(key.workspace_id, conversation.id, contact.id),
        expires_in=settings.widget_token_ttl_minutes * 60,
        conversation_id=conversation.id,
        anonymous_id=contact.anonymous_id,
        workspace_name=name,
    )


@router.post(
    "/messages",
    response_class=StreamingResponse,
    responses={
        200: {
            "description": "Server-Sent Events: `token` chunks, then `final` or `error`.",
            "content": {"text/event-stream": {"schema": {"type": "string"}}},
        },
        429: {"description": "Rate limited"},
    },
)
async def send_message(
    body: WidgetMessageRequest,
    request: Request,
    widget: CurrentWidget,
    limiter: Limiter,
    llm: ChatLLM,
    embedder: Embedder,
) -> StreamingResponse:
    settings = get_settings()
    # Behind the web app's proxy, uvicorn's --proxy-headers resolves the client address.
    client_ip = request.client.host if request.client else "unknown"
    allowed = await limiter.allow(
        f"conv:{widget.conversation_id}",
        settings.widget_conversation_rate_per_minute,
        RATE_LIMIT_WINDOW_S,
    ) and await limiter.allow(
        f"ip:{client_ip}", settings.widget_ip_rate_per_minute, RATE_LIMIT_WINDOW_S
    )
    if not allowed:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            RATE_LIMITED_MESSAGE,
            headers={"Retry-After": str(RATE_LIMIT_WINDOW_S)},
        )

    content = body.content.strip()
    if not content:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Message is empty")

    async with tenant_session(widget.workspace_id) as db:
        conversation = await service.get_conversation(
            db, widget.workspace_id, widget.conversation_id
        )
        _, history = await service.add_customer_message(db, conversation, content)
        history_items = [HistoryItem(role=m.role, content=m.content) for m in history]

    req = AnswerRequest(
        workspace_id=widget.workspace_id,
        conversation_id=widget.conversation_id,
        question=content,
        history=history_items,
        llm=llm,
        embedder=embedder,
        limiter=limiter,
        request_id=get_request_id() or None,
    )
    return StreamingResponse(
        stream_answer(req), media_type="text/event-stream", headers=SSE_HEADERS
    )


@router.get("/conversation", response_model=WidgetConversationOut)
async def get_conversation(widget: CurrentWidget, db: WidgetDB) -> WidgetConversationOut:
    return await service.widget_conversation(db, widget.workspace_id, widget.conversation_id)


@router.post("/feedback", response_model=FeedbackOut)
async def rate_message(
    body: WidgetFeedbackRequest, widget: CurrentWidget, db: WidgetDB
) -> FeedbackOut:
    feedback = await service.set_feedback(
        db,
        workspace_id=widget.workspace_id,
        conversation_id=widget.conversation_id,
        message_id=body.message_id,
        rating=body.rating,
        comment=body.comment,
    )
    return FeedbackOut(
        message_id=feedback.message_id,
        rating=feedback.rating,  # type: ignore[arg-type]
        comment=feedback.comment,
        created_at=feedback.updated_at,
    )
