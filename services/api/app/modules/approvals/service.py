"""Action requests proposed by the AI. Read-only for now: approving and executing come next.

Queries filter by workspace_id explicitly on top of RLS.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.approvals.models import ActionRequest
from app.modules.approvals.schemas import ActionList, ActionListItem, ActionRequestOut
from app.modules.tickets.models import Ticket


async def list_actions(
    db: AsyncSession, workspace_id: uuid.UUID, *, status_filter: str | None, limit: int
) -> ActionList:
    """Newest first, with the subject of each action's ticket."""
    stmt = (
        select(ActionRequest, Ticket.subject)
        .join(
            Ticket,
            (Ticket.id == ActionRequest.ticket_id) & (Ticket.workspace_id == workspace_id),
        )
        .where(ActionRequest.workspace_id == workspace_id)
        .order_by(ActionRequest.created_at.desc(), ActionRequest.id.desc())
        .limit(limit)
    )
    if status_filter:
        stmt = stmt.where(ActionRequest.status == status_filter)
    rows = (await db.execute(stmt)).all()
    return ActionList(
        items=[
            ActionListItem(
                **ActionRequestOut.model_validate(action).model_dump(), ticket_subject=subject
            )
            for action, subject in rows
        ]
    )


async def actions_for_ticket(
    db: AsyncSession, workspace_id: uuid.UUID, ticket_id: uuid.UUID
) -> list[ActionRequestOut]:
    rows = (
        await db.execute(
            select(ActionRequest)
            .where(ActionRequest.workspace_id == workspace_id, ActionRequest.ticket_id == ticket_id)
            .order_by(ActionRequest.created_at.desc(), ActionRequest.id.desc())
        )
    ).scalars()
    return [ActionRequestOut.model_validate(a) for a in rows]
