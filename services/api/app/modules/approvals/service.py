"""Action requests proposed by the AI, and the human decision on each one.

Approving is a one-way state transition under a row lock: proposed -> approved, recorded
with the approver in the audit log. Execution happens in the execute_action worker job
(app.workers.actions), never in the request. Refunds and cancellations (risk "sensitive")
can only be approved or rejected by owners and admins.

Queries filter by workspace_id explicitly on top of RLS.
"""

import uuid
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation

from fastapi import HTTPException, status
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.approvals.models import ActionRequest, ActionRisk, ActionStatus
from app.modules.approvals.schemas import ActionList, ActionListItem, ActionRequestOut
from app.modules.audit import service as audit
from app.modules.audit.models import ActorType
from app.modules.auth.models import User
from app.modules.conversations.models import Contact
from app.modules.conversations.schemas import ContactOut
from app.modules.orders.models import MockOrder
from app.modules.tickets.models import Ticket
from app.modules.workspaces.models import Role

SENSITIVE_DECIDERS = frozenset({Role.OWNER, Role.ADMIN})


def can_decide(role: str, risk: str) -> bool:
    return risk != ActionRisk.SENSITIVE or role in SENSITIVE_DECIDERS


def _out(action: ActionRequest, decided_by_name: str | None) -> ActionRequestOut:
    return ActionRequestOut.model_validate(action).model_copy(
        update={"decided_by_name": decided_by_name}
    )


def _decider_join(stmt):
    return stmt.outerjoin(User, User.id == ActionRequest.decided_by)


def _amount(raw: object) -> Decimal | None:
    if raw in (None, ""):
        return None
    try:
        return Decimal(str(raw))
    except InvalidOperation:
        return None


async def list_actions(
    db: AsyncSession, workspace_id: uuid.UUID, *, status_filter: str | None, limit: int
) -> ActionList:
    """Newest first, with each action's ticket subject, customer and order."""
    stmt = _decider_join(
        select(ActionRequest, Ticket.subject, Contact, User.full_name)
        .join(
            Ticket,
            (Ticket.id == ActionRequest.ticket_id) & (Ticket.workspace_id == workspace_id),
        )
        .outerjoin(
            Contact, and_(Contact.id == Ticket.contact_id, Contact.workspace_id == workspace_id)
        )
    )
    stmt = (
        stmt.where(ActionRequest.workspace_id == workspace_id)
        .order_by(ActionRequest.created_at.desc(), ActionRequest.id.desc())
        .limit(limit)
    )
    if status_filter:
        stmt = stmt.where(ActionRequest.status == status_filter)
    rows = (await db.execute(stmt)).all()

    numbers = {
        str(a.arguments.get("order_number", "")).strip().upper()
        for a, *_ in rows
        if a.arguments.get("order_number")
    }
    totals: dict[str, Decimal] = {}
    if numbers:
        totals = dict(
            (
                await db.execute(
                    select(func.upper(MockOrder.order_number), MockOrder.total).where(
                        MockOrder.workspace_id == workspace_id,
                        func.upper(MockOrder.order_number).in_(numbers),
                    )
                )
            ).all()
        )

    items = []
    for action, subject, contact, decider in rows:
        number = str(action.arguments.get("order_number", "")).strip().upper() or None
        total = totals.get(number) if number else None
        amount = _amount(action.arguments.get("amount"))
        if amount is None and action.tool_name == "request_refund":
            amount = total
        items.append(
            ActionListItem(
                **_out(action, decider).model_dump(),
                ticket_subject=subject,
                contact=ContactOut.model_validate(contact) if contact else None,
                order_number=number,
                amount=amount,
                order_total=total,
            )
        )
    return ActionList(items=items)


async def actions_for_ticket(
    db: AsyncSession, workspace_id: uuid.UUID, ticket_id: uuid.UUID
) -> list[ActionRequestOut]:
    rows = (
        await db.execute(
            _decider_join(select(ActionRequest, User.full_name))
            .where(ActionRequest.workspace_id == workspace_id, ActionRequest.ticket_id == ticket_id)
            .order_by(ActionRequest.created_at.desc(), ActionRequest.id.desc())
        )
    ).all()
    return [_out(a, name) for a, name in rows]


async def get_action_out(
    db: AsyncSession, workspace_id: uuid.UUID, action_id: uuid.UUID
) -> ActionRequestOut:
    row = (
        await db.execute(
            _decider_join(select(ActionRequest, User.full_name)).where(
                ActionRequest.workspace_id == workspace_id, ActionRequest.id == action_id
            )
        )
    ).first()
    if row is None:
        raise _not_found()
    return _out(*row)


def _not_found() -> HTTPException:
    return HTTPException(status.HTTP_404_NOT_FOUND, "Action not found")


async def _locked(
    db: AsyncSession, workspace_id: uuid.UUID, action_id: uuid.UUID, role: str
) -> ActionRequest:
    action = await db.scalar(
        select(ActionRequest)
        .where(ActionRequest.workspace_id == workspace_id, ActionRequest.id == action_id)
        .with_for_update()
    )
    if action is None:
        raise _not_found()
    if not can_decide(role, action.risk):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Only owners and admins can approve or reject refunds and cancellations",
        )
    return action


async def approve(
    db: AsyncSession,
    workspace_id: uuid.UUID,
    action_id: uuid.UUID,
    *,
    user_id: uuid.UUID,
    role: str,
) -> ActionRequest:
    """proposed -> approved, once. Approving an already approved action (a retry, or a
    second click) changes nothing; the caller queues execution again, which is safe because
    the job runs at most once per idempotency key. Anything further along is a 409."""
    action = await _locked(db, workspace_id, action_id, role)
    if action.status == ActionStatus.APPROVED:
        return action
    if action.status != ActionStatus.PROPOSED:
        raise HTTPException(status.HTTP_409_CONFLICT, f"This action is already {action.status}.")
    action.status = ActionStatus.APPROVED
    action.decided_by = user_id
    action.decided_at = datetime.now(UTC)
    audit.record(
        db,
        workspace_id=workspace_id,
        ticket_id=action.ticket_id,
        actor_type=ActorType.USER,
        actor_id=user_id,
        action="action.approved",
        target_type="action_request",
        target_id=action.id,
        before={"status": ActionStatus.PROPOSED},
        after={"status": ActionStatus.APPROVED, "tool_name": action.tool_name},
    )
    await db.flush()
    return action


async def reject(
    db: AsyncSession,
    workspace_id: uuid.UUID,
    action_id: uuid.UUID,
    reason: str,
    *,
    user_id: uuid.UUID,
    role: str,
) -> ActionRequest:
    action = await _locked(db, workspace_id, action_id, role)
    if action.status != ActionStatus.PROPOSED:
        raise HTTPException(status.HTTP_409_CONFLICT, f"This action is already {action.status}.")
    reason = reason.strip()
    action.status = ActionStatus.REJECTED
    action.decided_by = user_id
    action.decided_at = datetime.now(UTC)
    action.decision_reason = reason
    audit.record(
        db,
        workspace_id=workspace_id,
        ticket_id=action.ticket_id,
        actor_type=ActorType.USER,
        actor_id=user_id,
        action="action.rejected",
        target_type="action_request",
        target_id=action.id,
        before={"status": ActionStatus.PROPOSED},
        after={"status": ActionStatus.REJECTED, "tool_name": action.tool_name, "reason": reason},
    )
    await db.flush()
    return action
