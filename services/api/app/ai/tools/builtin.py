"""The allowlisted tools. The widget gets WIDGET_TOOLS (read-only plus the handoff), ticket
drafts get DRAFT_TOOLS (read tools plus proposals that need approval)."""

import json
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.grounding import format_source, neutralize
from app.ai.tools.models import ToolCallStatus
from app.ai.tools.registry import Risk, Tool, ToolContext, ToolResult
from app.modules.knowledge.retrieval import retrieve
from app.modules.orders.models import MockOrder, OrderStatus

# The same answer for an unknown order and a wrong email, so the tool never reveals
# whether an order number exists.
ORDER_NOT_FOUND = (
    "No order matched that order number and email. The details may not match our records. "
    "Ask the customer to double-check both."
)
ORDER_NUMBER = Field(
    min_length=3,
    max_length=32,
    pattern=r"^[A-Za-z0-9-]+$",
    description="The order number exactly as the customer wrote it, e.g. RA-10421.",
)
REASON = Field(min_length=3, max_length=500)


class _Args(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


def _normalize_number(value: str) -> str:
    return value.strip().upper()


async def _find_order(
    db: AsyncSession, ctx: ToolContext, order_number: str
) -> MockOrder | None:
    return await db.scalar(
        select(MockOrder).where(
            MockOrder.workspace_id == ctx.workspace_id,
            func.upper(MockOrder.order_number) == _normalize_number(order_number),
        )
    )


def _same_email(a: str, b: str) -> bool:
    return a.strip().casefold() == b.strip().casefold()


# search_knowledge ---------------------------------------------------------------------------


class SearchKnowledgeArgs(_Args):
    query: str = Field(
        min_length=2,
        max_length=300,
        description="A short, standalone search query about policies, products or how-tos.",
    )


async def _search_knowledge(
    db: AsyncSession, ctx: ToolContext, args: SearchKnowledgeArgs
) -> ToolResult:
    result = await retrieve(db, args.query, workspace_id=ctx.workspace_id, embedder=ctx.embedder)
    if not result.chunks:
        return ToolResult(
            ToolCallStatus.NOT_FOUND,
            "No relevant help articles were found. Do not answer from general knowledge.",
            "Searched the help articles — nothing relevant",
        )
    blocks = []
    known = {c.chunk_id: i for i, c in enumerate(ctx.sources)}
    for chunk in result.chunks:
        if chunk.chunk_id not in known:
            known[chunk.chunk_id] = len(ctx.sources)
            ctx.sources.append(chunk)
        blocks.append(format_source(known[chunk.chunk_id], chunk))
    titles = list(dict.fromkeys(c.document_title for c in result.chunks))
    return ToolResult(
        ToolCallStatus.OK,
        "<sources>\n" + "\n".join(blocks) + "\n</sources>",
        f"Searched the help articles — found {', '.join(titles[:3])}",
    )


# get_order_status ---------------------------------------------------------------------------


class GetOrderStatusArgs(_Args):
    order_number: str = ORDER_NUMBER
    email: str = Field(
        min_length=3,
        max_length=320,
        description="The email address the customer gave for the order. Never guess it.",
    )


async def _get_order_status(
    db: AsyncSession, ctx: ToolContext, args: GetOrderStatusArgs
) -> ToolResult:
    number = _normalize_number(args.order_number)
    order = await _find_order(db, ctx, number)
    if order is None or not _same_email(order.contact_email, args.email):
        return ToolResult(
            ToolCallStatus.NOT_FOUND,
            ORDER_NOT_FOUND,
            f"Looked up order {number} — not found or details didn't match",
        )
    details = {
        "order_number": order.order_number,
        "status": order.status,
        "carrier": order.carrier,
        "tracking_number": order.tracking_number,
        "eta": order.eta.isoformat() if order.eta else None,
        "items": [
            {"name": item.get("name"), "quantity": item.get("quantity")} for item in order.items
        ],
    }
    return ToolResult(
        ToolCallStatus.OK,
        neutralize(json.dumps(details)),
        f"Looked up order {order.order_number} — {order.status}",
    )


# request_refund (sensitive) -----------------------------------------------------------------


class RequestRefundArgs(_Args):
    order_number: str = ORDER_NUMBER
    reason: str = REASON
    amount: Decimal | None = Field(
        default=None,
        gt=0,
        max_digits=10,
        decimal_places=2,
        description="Refund amount, only if the customer asked for a specific amount.",
    )


async def _check_refund(db: AsyncSession, ctx: ToolContext, args: RequestRefundArgs) -> str | None:
    if not ctx.customer_asked_refund:
        return "A refund can only be proposed when the customer asked for one."
    order = await _find_order(db, ctx, args.order_number)
    if order is None:
        return "No order with that number was found."
    if ctx.contact_email and not _same_email(order.contact_email, ctx.contact_email):
        return "That order doesn't belong to this customer."
    if order.status == OrderStatus.CANCELLED:
        return "That order was cancelled, so there is nothing to refund."
    if args.amount is not None and args.amount > order.total:
        return f"The amount is more than the order total ({order.total})."
    return None


def _describe_refund(args: RequestRefundArgs) -> str:
    amount = f" ({args.amount})" if args.amount is not None else ""
    return f"Refund request for order {_normalize_number(args.order_number)}{amount}"


# request_cancellation (sensitive) -----------------------------------------------------------


class RequestCancellationArgs(_Args):
    order_number: str = ORDER_NUMBER
    reason: str = REASON


async def _check_cancellation(
    db: AsyncSession, ctx: ToolContext, args: RequestCancellationArgs
) -> str | None:
    # Whether the order can still be cancelled (not shipped) is decided when a teammate
    # approves it, against the order's state at that moment.
    if not ctx.customer_asked_cancel:
        return "A cancellation can only be proposed when the customer asked for one."
    order = await _find_order(db, ctx, args.order_number)
    if order is None:
        return "No order with that number was found."
    if ctx.contact_email and not _same_email(order.contact_email, ctx.contact_email):
        return "That order doesn't belong to this customer."
    if order.status == OrderStatus.CANCELLED:
        return "That order is already cancelled."
    return None


# escalate_to_human (write) ------------------------------------------------------------------


class EscalateArgs(_Args):
    reason: str = REASON


# hand_off_to_team (internal) ----------------------------------------------------------------


class HandOffArgs(_Args):
    reason: str = Field(
        min_length=3,
        max_length=300,
        description="Short note for the team: what the customer needs and why a person is needed.",
    )


HANDED_OFF = (
    "Passed to the team: a teammate will follow up in this chat. Tell the customer that in "
    "one or two sentences. Don't promise an outcome and don't point them anywhere else."
)


async def _hand_off(db: AsyncSession, ctx: ToolContext, args: HandOffArgs) -> ToolResult:
    if ctx.conversation_id is None:
        return ToolResult(
            ToolCallStatus.DENIED, "There's no chat to hand off here.", "Handoff not available"
        )
    # Idempotent: the widget opens or reuses the conversation's one open ticket after the run.
    ctx.handoff_reason = args.reason
    return ToolResult(ToolCallStatus.OK, HANDED_OFF, "Passed the conversation to the team")


# Registry -----------------------------------------------------------------------------------

SEARCH_KNOWLEDGE = Tool(
    name="search_knowledge",
    description=(
        "Search the business's help articles and policies. Returns sources with ids like S1 "
        "to cite. Use it for any question about policies, shipping, returns or products."
    ),
    input_model=SearchKnowledgeArgs,
    risk=Risk.READ,
    status_text="Searching our help articles…",
    describe=lambda args: "Searched the help articles",
    handler=_search_knowledge,
)
GET_ORDER_STATUS = Tool(
    name="get_order_status",
    description=(
        "Look up an order's status, carrier, tracking number, ETA and items. Needs both the "
        "order number and the email address on the order, as given by the customer. If the "
        "customer hasn't given the email, ask for it instead of calling this tool."
    ),
    input_model=GetOrderStatusArgs,
    risk=Risk.READ,
    status_text="Checking your order…",
    describe=lambda args: f"Looked up order {_normalize_number(args.order_number)}",
    handler=_get_order_status,
)
REQUEST_REFUND = Tool(
    name="request_refund",
    description=(
        "Propose a refund for an order. This does NOT refund anything: it creates a request "
        "a teammate must approve. Only use it when the customer asked for a refund."
    ),
    input_model=RequestRefundArgs,
    risk=Risk.SENSITIVE,
    status_text="Preparing a refund request…",
    describe=_describe_refund,
    check=_check_refund,
)
REQUEST_CANCELLATION = Tool(
    name="request_cancellation",
    description=(
        "Propose cancelling an order. This does NOT cancel anything: it creates a request a "
        "teammate must approve. Only use it when the customer asked to cancel the order."
    ),
    input_model=RequestCancellationArgs,
    risk=Risk.SENSITIVE,
    status_text="Preparing a cancellation request…",
    describe=lambda args: (
        f"Cancellation request for order {_normalize_number(args.order_number)}"
    ),
    check=_check_cancellation,
)
ESCALATE_TO_HUMAN = Tool(
    name="escalate_to_human",
    description=(
        "Flag the ticket for a teammate's attention, e.g. when the request needs judgement, "
        "the customer is upset, or the tools can't answer it."
    ),
    input_model=EscalateArgs,
    risk=Risk.WRITE,
    status_text="Flagging this for a teammate…",
    describe=lambda args: "Escalation to a teammate",
)

HAND_OFF_TO_TEAM = Tool(
    name="hand_off_to_team",
    description=(
        "Pass this chat to a human teammate, who will follow up here. Use it right away when "
        "the customer wants something your other tools can't do: cancelling or changing an "
        "order, a refund, an account change, a complaint, or anything that needs a person."
    ),
    input_model=HandOffArgs,
    risk=Risk.INTERNAL,
    status_text="Passing this to the team…",
    describe=lambda args: "Passed the conversation to the team",
    handler=_hand_off,
)

REGISTRY: dict[str, Tool] = {
    t.name: t
    for t in (
        SEARCH_KNOWLEDGE,
        GET_ORDER_STATUS,
        REQUEST_REFUND,
        REQUEST_CANCELLATION,
        ESCALATE_TO_HUMAN,
        HAND_OFF_TO_TEAM,
    )
}
WIDGET_TOOLS: tuple[Tool, ...] = (GET_ORDER_STATUS, SEARCH_KNOWLEDGE, HAND_OFF_TO_TEAM)
# A ticket is already with the team, so drafts escalate (with approval) instead of handing off.
DRAFT_TOOLS: tuple[Tool, ...] = (
    SEARCH_KNOWLEDGE,
    GET_ORDER_STATUS,
    REQUEST_REFUND,
    REQUEST_CANCELLATION,
    ESCALATE_TO_HUMAN,
)
