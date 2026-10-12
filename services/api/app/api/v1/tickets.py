"""Inbox tickets. Any member may read, create and update them, and review drafts: edit,
send (approve and post to the customer's chat), reject, regenerate, or write a reply."""

import logging
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.ai.decisions import DecisionClient, DecisionError, get_decision_client
from app.core.config import get_settings
from app.core.deps import CurrentPrincipal, TenantDB, tenant_session
from app.core.ratelimit import user_rate_limit
from app.modules.tickets import service
from app.modules.tickets.schemas import (
    AssigneeFilter,
    DraftCreate,
    DraftEdit,
    DraftReject,
    DraftSend,
    RegenerateDraftOut,
    TicketCreate,
    TicketDetail,
    TicketIntentLiteral,
    TicketPage,
    TicketPriorityLiteral,
    TicketStatusLiteral,
    TicketUpdate,
)
from app.workers.queue import JobQueue, get_job_queue

logger = logging.getLogger("app.api.tickets")

router = APIRouter(prefix="/tickets", tags=["tickets"])

Decider = Annotated[DecisionClient, Depends(get_decision_client)]
Jobs = Annotated[JobQueue, Depends(get_job_queue)]

regenerate_limit = user_rate_limit(
    "regenerate", lambda: get_settings().rate_limit_regenerate_per_minute, 60
)


async def _enqueue_draft(
    jobs: JobQueue, ticket_id: uuid.UUID, workspace_id: uuid.UUID, *, force: bool = False
) -> bool:
    """Queue the reply-draft job. The ticket must already be committed."""
    try:
        await jobs.enqueue_process_ticket(ticket_id, workspace_id, force=force)
    except Exception:
        logger.exception("Failed to enqueue drafting (ticket_id=%s)", ticket_id)
        return False
    return True


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
    body: TicketCreate, principal: CurrentPrincipal, decider: Decider, jobs: Jobs
) -> TicketDetail:
    """A manual ticket, classified like a widget message (intent and priority). A reply
    draft is written in the background."""
    try:
        classification = await decider.classify(
            f"{body.subject}\n\n{body.description}", [], workspace_id=principal.workspace_id
        )
    except DecisionError:
        logger.warning("Manual ticket left unclassified (workspace_id=%s)", principal.workspace_id)
        classification = None
    # Committed before the draft job is queued, so the worker can see the ticket.
    async with tenant_session(principal.workspace_id, principal.user_id) as db:
        ticket = await service.create_manual_ticket(
            db, principal.workspace_id, body, classification
        )
    await _enqueue_draft(jobs, ticket.id, principal.workspace_id)
    async with tenant_session(principal.workspace_id, principal.user_id) as db:
        return await service.ticket_detail(db, principal.workspace_id, ticket.id)


@router.post(
    "/{ticket_id}/regenerate-draft",
    response_model=RegenerateDraftOut,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(regenerate_limit)],
)
async def regenerate_draft(
    ticket_id: uuid.UUID, principal: CurrentPrincipal, db: TenantDB, jobs: Jobs
) -> RegenerateDraftOut:
    """Write a fresh draft in the background; poll the ticket until it appears."""
    await service.get_ticket(db, principal.workspace_id, ticket_id)
    if not await _enqueue_draft(jobs, ticket_id, principal.workspace_id, force=True):
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "Couldn't start drafting. Try again shortly."
        )
    return RegenerateDraftOut(ticket_id=ticket_id, queued=True)


@router.patch("/{ticket_id}", response_model=TicketDetail)
async def update_ticket(
    ticket_id: uuid.UUID, body: TicketUpdate, principal: CurrentPrincipal, db: TenantDB
) -> TicketDetail:
    await service.update_ticket(
        db, principal.workspace_id, ticket_id, body, user_id=principal.user_id
    )
    return await service.ticket_detail(db, principal.workspace_id, ticket_id)


@router.post(
    "/{ticket_id}/drafts", response_model=TicketDetail, status_code=status.HTTP_201_CREATED
)
async def write_reply(
    ticket_id: uuid.UUID, body: DraftCreate, principal: CurrentPrincipal, db: TenantDB
) -> TicketDetail:
    """Start a reply from scratch (no AI text). It replaces any draft still under review."""
    await service.create_human_draft(
        db, principal.workspace_id, ticket_id, body, user_id=principal.user_id
    )
    return await service.ticket_detail(db, principal.workspace_id, ticket_id)


@router.patch("/{ticket_id}/drafts/{draft_id}", response_model=TicketDetail)
async def edit_draft(
    ticket_id: uuid.UUID,
    draft_id: uuid.UUID,
    body: DraftEdit,
    principal: CurrentPrincipal,
    db: TenantDB,
) -> TicketDetail:
    await service.edit_draft(
        db, principal.workspace_id, ticket_id, draft_id, body.content, user_id=principal.user_id
    )
    return await service.ticket_detail(db, principal.workspace_id, ticket_id)


@router.post("/{ticket_id}/drafts/{draft_id}/send", response_model=TicketDetail)
async def send_draft(
    ticket_id: uuid.UUID,
    draft_id: uuid.UUID,
    body: DraftSend,
    principal: CurrentPrincipal,
    db: TenantDB,
) -> TicketDetail:
    """Post the draft in the customer's chat as a team reply; the ticket becomes replied.
    A draft is sent once: sending it again returns 409."""
    await service.send_draft(
        db, principal.workspace_id, ticket_id, draft_id, body, user_id=principal.user_id
    )
    return await service.ticket_detail(db, principal.workspace_id, ticket_id)


@router.post("/{ticket_id}/drafts/{draft_id}/reject", response_model=TicketDetail)
async def reject_draft(
    ticket_id: uuid.UUID,
    draft_id: uuid.UUID,
    body: DraftReject,
    principal: CurrentPrincipal,
    db: TenantDB,
) -> TicketDetail:
    await service.reject_draft(
        db, principal.workspace_id, ticket_id, draft_id, body, user_id=principal.user_id
    )
    return await service.ticket_detail(db, principal.workspace_id, ticket_id)
