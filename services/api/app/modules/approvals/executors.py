"""Executors carry out approved actions. They sit behind one small interface so the mock order
system can be swapped for a real connector (Shopify, Stripe) without touching the approval
flow.

The contract every executor follows:

- It gets a frozen snapshot of the approved action, never an ORM object or the caller's
  transaction. The worker commits `executing` first and calls the executor outside any
  database transaction, so a slow or hanging provider never holds a row lock.
- It is idempotent on `idempotency_key`: the worker may call it again with the same key
  after a crash, and the second call must not repeat the effect. A real connector passes the
  key to the provider (Stripe's Idempotency-Key header); the mock remembers applied keys on
  the order row.
- It returns an ExecutionResult. Business failures ("already shipped") are results with
  ok=False and a reason a teammate can read; exceptions mean "unknown, try again".
- Summaries carry order numbers, amounts and statuses only, never customer emails.
"""

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Protocol

from sqlalchemy import func, select

from app.core.deps import tenant_session
from app.modules.conversations.models import Conversation, ConversationStatus
from app.modules.orders.models import MockOrder, OrderStatus
from app.modules.tickets.models import Ticket, TicketPriority

REFUND = "request_refund"
CANCEL = "request_cancellation"
ESCALATE = "escalate_to_human"


@dataclass(frozen=True)
class ActionSnapshot:
    id: uuid.UUID
    workspace_id: uuid.UUID
    ticket_id: uuid.UUID
    conversation_id: uuid.UUID | None
    tool_name: str
    arguments: dict[str, Any]
    idempotency_key: str


@dataclass(frozen=True)
class ExecutionResult:
    ok: bool
    summary: str
    details: dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> dict[str, Any]:
        return {"ok": self.ok, "summary": self.summary, **self.details}


class ActionExecutor(Protocol):
    async def execute(self, action: ActionSnapshot) -> ExecutionResult: ...


def _order_number(action: ActionSnapshot) -> str:
    return str(action.arguments.get("order_number", "")).strip().upper()


class MockOrderExecutor:
    """Refunds and cancellations against mock_orders, in its own short transaction (it stands
    in for an external order API)."""

    async def execute(self, action: ActionSnapshot) -> ExecutionResult:
        async with tenant_session(action.workspace_id) as db:
            number = _order_number(action)
            order = await db.scalar(
                select(MockOrder)
                .where(
                    MockOrder.workspace_id == action.workspace_id,
                    func.upper(MockOrder.order_number) == number,
                )
                .with_for_update()
            )
            if order is None:
                return ExecutionResult(False, f"Order {number} wasn't found.")
            if action.idempotency_key in (order.applied_action_keys or []):
                return self._already_applied(action, order)
            if action.tool_name == REFUND:
                result = self._refund(action, order)
            elif action.tool_name == CANCEL:
                result = self._cancel(order)
            else:
                return ExecutionResult(False, "This action isn't supported by the order system.")
            if result.ok:
                order.applied_action_keys = [
                    *(order.applied_action_keys or []),
                    action.idempotency_key,
                ]
            return result

    @staticmethod
    def _refund(action: ActionSnapshot, order: MockOrder) -> ExecutionResult:
        number = order.order_number
        if order.status == OrderStatus.CANCELLED:
            return ExecutionResult(
                False, f"Order {number} was cancelled, so there is nothing to refund."
            )
        remaining = order.total - order.refunded_amount
        raw = action.arguments.get("amount")
        amount = Decimal(str(raw)) if raw not in (None, "") else remaining
        if remaining <= 0:
            return ExecutionResult(False, f"Order {number} has already been fully refunded.")
        if amount <= 0 or amount > remaining:
            return ExecutionResult(
                False,
                f"Can't refund {amount} on order {number}: only {remaining} is left to refund.",
            )
        order.refunded_amount = order.refunded_amount + amount
        order.refunded_at = datetime.now(UTC)
        return ExecutionResult(
            True,
            f"Refunded {amount} on order {number}.",
            {
                "order_number": number,
                "amount": str(amount),
                "refunded_total": str(order.refunded_amount),
            },
        )

    @staticmethod
    def _cancel(order: MockOrder) -> ExecutionResult:
        number = order.order_number
        if order.status == OrderStatus.CANCELLED:
            return ExecutionResult(False, f"Order {number} is already cancelled.")
        if order.status != OrderStatus.PROCESSING:
            return ExecutionResult(
                False,
                f"Order {number} has already {order.status}, so it can't be cancelled.",
                {"order_number": number, "order_status": order.status},
            )
        order.status = OrderStatus.CANCELLED
        return ExecutionResult(
            True,
            f"Cancelled order {number}.",
            {"order_number": number, "order_status": order.status},
        )

    @staticmethod
    def _already_applied(action: ActionSnapshot, order: MockOrder) -> ExecutionResult:
        """A retry after a crash: the effect is already there, report it without repeating it."""
        number = order.order_number
        if action.tool_name == REFUND:
            return ExecutionResult(
                True,
                f"Refund on order {number} was already applied.",
                {"order_number": number, "refunded_total": str(order.refunded_amount)},
            )
        return ExecutionResult(
            True,
            f"Cancelled order {number}.",
            {"order_number": number, "order_status": order.status},
        )


class EscalationExecutor:
    """Inside ResolveAI: raise the ticket to urgent and flag its chat for a person. Repeating it
    changes nothing, so it is idempotent without remembering keys."""

    async def execute(self, action: ActionSnapshot) -> ExecutionResult:
        async with tenant_session(action.workspace_id) as db:
            ticket = await db.scalar(
                select(Ticket)
                .where(Ticket.workspace_id == action.workspace_id, Ticket.id == action.ticket_id)
                .with_for_update()
            )
            if ticket is None:
                return ExecutionResult(False, "The ticket no longer exists.")
            ticket.priority = TicketPriority.URGENT
            if ticket.conversation_id is not None:
                conversation = await db.scalar(
                    select(Conversation).where(
                        Conversation.workspace_id == action.workspace_id,
                        Conversation.id == ticket.conversation_id,
                    )
                )
                if conversation is not None:
                    conversation.status = ConversationStatus.NEEDS_HUMAN
        return ExecutionResult(True, "Escalated: the ticket is now urgent.", {"priority": "urgent"})


def default_executors() -> dict[str, ActionExecutor]:
    """Tool name -> executor. Replace the order entries with a real connector later."""
    orders = MockOrderExecutor()
    return {REFUND: orders, CANCEL: orders, ESCALATE: EscalationExecutor()}
