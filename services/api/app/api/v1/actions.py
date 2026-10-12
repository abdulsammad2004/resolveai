"""Actions the AI proposed (refund requests, escalations). Any member may list them.

Read-only for now: approving, rejecting and executing come with the approvals flow.
"""

from typing import Annotated

from fastapi import APIRouter, Query

from app.core.deps import CurrentPrincipal, TenantDB
from app.modules.approvals import service
from app.modules.approvals.schemas import ActionList, ActionStatusLiteral

router = APIRouter(prefix="/actions", tags=["approvals"])


@router.get("", response_model=ActionList)
async def list_actions(
    principal: CurrentPrincipal,
    db: TenantDB,
    status: ActionStatusLiteral | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
) -> ActionList:
    """Newest first, across all tickets, with each ticket's subject."""
    return await service.list_actions(
        db, principal.workspace_id, status_filter=status, limit=limit
    )
