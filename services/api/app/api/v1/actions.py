"""Actions the AI proposed (refunds, cancellations, escalations). Any member may list them
and decide escalations; refunds and cancellations need an owner or admin.

Approving only records the decision; the execute_action worker job carries the action out.
"""

import logging
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.core.deps import CurrentPrincipal, TenantDB, tenant_session
from app.modules.approvals import service
from app.modules.approvals.schemas import (
    ActionList,
    ActionReject,
    ActionRequestOut,
    ActionStatusLiteral,
)
from app.workers.queue import JobQueue, get_job_queue

logger = logging.getLogger("app.api.actions")

router = APIRouter(prefix="/actions", tags=["approvals"])

Jobs = Annotated[JobQueue, Depends(get_job_queue)]


@router.get("", response_model=ActionList)
async def list_actions(
    principal: CurrentPrincipal,
    db: TenantDB,
    status: ActionStatusLiteral | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
) -> ActionList:
    """Newest first, across all tickets, with each ticket's subject, customer and order."""
    return await service.list_actions(
        db, principal.workspace_id, status_filter=status, limit=limit
    )


@router.post(
    "/{action_id}/approve",
    response_model=ActionRequestOut,
    status_code=status.HTTP_202_ACCEPTED,
)
async def approve_action(
    action_id: uuid.UUID, principal: CurrentPrincipal, jobs: Jobs
) -> ActionRequestOut:
    """Approve and queue execution; poll the action (or its ticket) for the result.

    Approving twice is safe: the action moves to approved once and runs at most once."""
    # Committed before the job is queued, so the worker sees the approval.
    async with tenant_session(principal.workspace_id, principal.user_id) as db:
        action = await service.approve(
            db,
            principal.workspace_id,
            action_id,
            user_id=principal.user_id,
            role=principal.role,
        )
        key = action.idempotency_key
    try:
        await jobs.enqueue_execute_action(action_id, principal.workspace_id, key)
    except Exception as exc:
        logger.exception("Failed to enqueue execution (action_id=%s)", action_id)
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Approved, but couldn't start it. Approve again shortly to retry.",
        ) from exc
    async with tenant_session(principal.workspace_id, principal.user_id) as db:
        return await service.get_action_out(db, principal.workspace_id, action_id)


@router.post("/{action_id}/reject", response_model=ActionRequestOut)
async def reject_action(
    action_id: uuid.UUID, body: ActionReject, principal: CurrentPrincipal, db: TenantDB
) -> ActionRequestOut:
    """Reject with a reason. Nothing is carried out."""
    await service.reject(
        db,
        principal.workspace_id,
        action_id,
        body.reason,
        user_id=principal.user_id,
        role=principal.role,
    )
    return await service.get_action_out(db, principal.workspace_id, action_id)
