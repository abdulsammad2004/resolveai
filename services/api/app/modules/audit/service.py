"""The audit log: an append-only record of reviews, decisions, executions and ticket changes.

Callers record events in the same transaction as the change they describe, so a change and
its record commit together. Summaries carry ids, statuses, counts and amounts, never
message bodies or customer emails.
"""

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.audit.models import ActorType, AuditEvent
from app.modules.audit.schemas import AuditEventOut
from app.modules.auth.models import User

ACTIVITY_SHOWN = 100


def record(
    db: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    actor_type: ActorType,
    actor_id: uuid.UUID | None,
    action: str,
    target_type: str,
    target_id: uuid.UUID | None,
    ticket_id: uuid.UUID | None = None,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
) -> AuditEvent:
    event = AuditEvent(
        # Set here, not by the database: events in one transaction keep their order.
        created_at=datetime.now(UTC),
        workspace_id=workspace_id,
        ticket_id=ticket_id,
        actor_type=actor_type,
        actor_id=actor_id,
        action=action,
        target_type=target_type,
        target_id=target_id,
        before=before,
        after=after,
    )
    db.add(event)
    return event


async def events_for_ticket(
    db: AsyncSession, workspace_id: uuid.UUID, ticket_id: uuid.UUID
) -> list[AuditEventOut]:
    """The ticket's most recent events, oldest first."""
    rows = (
        await db.execute(
            select(AuditEvent, User.full_name)
            .outerjoin(
                User,
                (AuditEvent.actor_type == ActorType.USER) & (User.id == AuditEvent.actor_id),
            )
            .where(AuditEvent.workspace_id == workspace_id, AuditEvent.ticket_id == ticket_id)
            .order_by(AuditEvent.created_at.desc(), AuditEvent.id.desc())
            .limit(ACTIVITY_SHOWN)
        )
    ).all()
    return [
        AuditEventOut(
            id=e.id,
            actor_type=e.actor_type,  # type: ignore[arg-type]
            actor_id=e.actor_id,
            actor_name=name,
            action=e.action,
            target_type=e.target_type,
            target_id=e.target_id,
            before=e.before,
            after=e.after,
            created_at=e.created_at,
        )
        for e, name in reversed(rows)
    ]
