"""Inbox tickets. Any member may read, create and update them."""

import logging
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from app.ai.decisions import DecisionClient, DecisionError, get_decision_client
from app.core.deps import CurrentPrincipal, TenantDB
from app.modules.tickets import service
from app.modules.tickets.schemas import (
    AssigneeFilter,
    TicketCreate,
    TicketDetail,
    TicketIntentLiteral,
    TicketPage,
    TicketPriorityLiteral,
    TicketStatusLiteral,
    TicketUpdate,
)

logger = logging.getLogger("app.api.tickets")

router = APIRouter(prefix="/tickets", tags=["tickets"])

Decider = Annotated[DecisionClient, Depends(get_decision_client)]


@router.get("", response_model=TicketPage)
async def list_tickets(
    principal: CurrentPrincipal,
    db: TenantDB,
    status: TicketStatusLiteral | None = None,
    priority: TicketPriorityLiteral | None = None,
    intent: TicketIntentLiteral | None = None,
    assignee: AssigneeFilter = "any",
    cursor: Annotated[str | None, Query(max_length=512)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
) -> TicketPage:
    """Urgent first, then newest. `counts` cover the whole workspace, ignoring filters."""
    return await service.list_tickets(
        db,
        principal.workspace_id,
        user_id=principal.user_id,
        status_filter=status,
        priority=priority,
        intent=intent,
        assignee=assignee,
        cursor=cursor,
        limit=limit,
    )


@router.get("/{ticket_id}", response_model=TicketDetail)
async def get_ticket(ticket_id: uuid.UUID, principal: CurrentPrincipal, db: TenantDB) -> TicketDetail:
    return await service.ticket_detail(db, principal.workspace_id, ticket_id)


@router.post("", response_model=TicketDetail, status_code=status.HTTP_201_CREATED)
async def create_ticket(
    body: TicketCreate, principal: CurrentPrincipal, db: TenantDB, decider: Decider
) -> TicketDetail:
    """A manual ticket, classified like a widget message (intent and priority)."""
    try:
        classification = await decider.classify(
            f"{body.subject}\n\n{body.description}", [], workspace_id=principal.workspace_id
        )
    except DecisionError:
        logger.warning("Manual ticket left unclassified (workspace_id=%s)", principal.workspace_id)
        classification = None
    ticket = await service.create_manual_ticket(db, principal.workspace_id, body, classification)
    return await service.ticket_detail(db, principal.workspace_id, ticket.id)


@router.patch("/{ticket_id}", response_model=TicketDetail)
async def update_ticket(
    ticket_id: uuid.UUID, body: TicketUpdate, principal: CurrentPrincipal, db: TenantDB
) -> TicketDetail:
    await service.update_ticket(db, principal.workspace_id, ticket_id, body)
    return await service.ticket_detail(db, principal.workspace_id, ticket_id)
