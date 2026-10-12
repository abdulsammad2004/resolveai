"""execute_action job: carry out one approved action, at most once.

1. Claim: lock the action row; approved -> executing (with execution_started_at), COMMIT.
2. Execute: call the executor with the stored arguments and the action's idempotency key,
   outside any database transaction (a real connector may be slow or hang).
3. Record: in a new transaction, executing -> succeeded | failed, with the result, an audit
   event (the ticket's note) and a fresh reply draft so the agent can confirm to the customer.

Only one run can claim an approved action (the row lock serialises claims). A run that finds
the action executing with a fresh claim backs off; if the claim is older than CLAIM_LEASE_S
the worker that held it is presumed dead and this run resumes it with the same idempotency
key, which the executor uses to avoid repeating the effect. Logs carry ids and outcomes only.
"""

import asyncio
import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from arq import Retry
from sqlalchemy import select

from app.core.deps import tenant_session
from app.modules.approvals.executors import (
    ActionExecutor,
    ActionSnapshot,
    ExecutionResult,
    default_executors,
)
from app.modules.approvals.models import ActionRequest, ActionStatus
from app.modules.audit import service as audit
from app.modules.audit.models import ActorType
from app.workers.queue import ArqJobQueue, JobQueue

logger = logging.getLogger("app.workers.actions")

MAX_TRIES = 5
EXECUTOR_TIMEOUT_S = 30
JOB_TIMEOUT_S = EXECUTOR_TIMEOUT_S + 30
# A claim older than this belongs to a worker that died mid-run.
CLAIM_LEASE_S = JOB_TIMEOUT_S + 30
RETRY_DELAY_S = 10
CONNECTOR_FAILURE = "The action couldn't be completed: the order system didn't respond."
FINISHED = frozenset({ActionStatus.SUCCEEDED, ActionStatus.FAILED, ActionStatus.REJECTED})


def _now() -> datetime:
    return datetime.now(UTC)


async def execute_action(ctx: dict[str, Any], action_id: str, workspace_id: str) -> str:
    a_id = uuid.UUID(action_id)
    ws_id = uuid.UUID(workspace_id)
    job_try: int = ctx.get("job_try", 1)

    claimed = await _claim(a_id, ws_id)
    if isinstance(claimed, str):
        if claimed == "busy" and job_try < MAX_TRIES:
            # Someone else is running it; come back after their claim would have expired.
            raise Retry(defer=CLAIM_LEASE_S)
        return claimed

    executors: dict[str, ActionExecutor] = ctx.get("executors") or default_executors()
    executor = executors.get(claimed.tool_name)
    if executor is None:
        result = ExecutionResult(False, "This action can't be carried out automatically.")
    else:
        try:
            async with asyncio.timeout(EXECUTOR_TIMEOUT_S):
                result = await executor.execute(claimed)
        except Exception as exc:
            logger.warning(
                "Action execution attempt %d/%d failed (action_id=%s, error=%s)",
                job_try,
                MAX_TRIES,
                a_id,
                type(exc).__name__,
            )
            if job_try < MAX_TRIES:
                # Release the claim so the retry resumes at once, with the same key.
                await _release(a_id, ws_id)
                raise Retry(defer=RETRY_DELAY_S * job_try) from exc
            result = ExecutionResult(False, CONNECTOR_FAILURE)

    outcome = await _record(a_id, ws_id, result)
    if outcome in (ActionStatus.SUCCEEDED, ActionStatus.FAILED):
        await _queue_confirmation_draft(ctx, claimed)
    return outcome


async def _claim(a_id: uuid.UUID, ws_id: uuid.UUID) -> ActionSnapshot | str:
    """Lock the action and mark it executing. Returns the snapshot to run, or why not."""
    async with tenant_session(ws_id) as db:
        action = await db.scalar(
            select(ActionRequest)
            .where(ActionRequest.workspace_id == ws_id, ActionRequest.id == a_id)
            .with_for_update()
        )
        if action is None:
            return "missing"
        if action.status in FINISHED:
            logger.info("Action already finished (action_id=%s, status=%s)", a_id, action.status)
            return "done"
        if action.status == ActionStatus.PROPOSED:
            logger.warning("Action not approved, not executing (action_id=%s)", a_id)
            return "not_approved"
        if action.status == ActionStatus.EXECUTING:
            started = action.execution_started_at
            if started is not None and _now() - started < timedelta(seconds=CLAIM_LEASE_S):
                logger.info("Action is being executed elsewhere (action_id=%s)", a_id)
                return "busy"
            logger.warning("Resuming a stale execution (action_id=%s)", a_id)
        action.status = ActionStatus.EXECUTING
        action.execution_started_at = _now()
        return ActionSnapshot(
            id=action.id,
            workspace_id=action.workspace_id,
            ticket_id=action.ticket_id,
            conversation_id=action.conversation_id,
            tool_name=action.tool_name,
            arguments=dict(action.arguments),
            idempotency_key=action.idempotency_key,
        )


async def _release(a_id: uuid.UUID, ws_id: uuid.UUID) -> None:
    async with tenant_session(ws_id) as db:
        action = await db.scalar(
            select(ActionRequest)
            .where(ActionRequest.workspace_id == ws_id, ActionRequest.id == a_id)
            .with_for_update()
        )
        if action is not None and action.status == ActionStatus.EXECUTING:
            action.execution_started_at = None


async def _record(a_id: uuid.UUID, ws_id: uuid.UUID, result: ExecutionResult) -> str:
    async with tenant_session(ws_id) as db:
        action = await db.scalar(
            select(ActionRequest)
            .where(ActionRequest.workspace_id == ws_id, ActionRequest.id == a_id)
            .with_for_update()
        )
        if action is None:
            return "missing"
        if action.status != ActionStatus.EXECUTING:
            # A resumed run finished it first.
            return "done"
        new_status = ActionStatus.SUCCEEDED if result.ok else ActionStatus.FAILED
        action.status = new_status
        action.result = result.to_json()
        action.executed_at = _now()
        audit.record(
            db,
            workspace_id=ws_id,
            ticket_id=action.ticket_id,
            actor_type=ActorType.SYSTEM,
            actor_id=None,
            action="action.executed" if result.ok else "action.failed",
            target_type="action_request",
            target_id=action.id,
            before={"status": ActionStatus.EXECUTING},
            after={"status": new_status, "tool_name": action.tool_name, "summary": result.summary},
        )
    logger.info("Action finished (action_id=%s, status=%s)", a_id, new_status)
    return new_status


async def _queue_confirmation_draft(ctx: dict[str, Any], action: ActionSnapshot) -> None:
    """A fresh draft that knows the outcome, so the agent can confirm it to the customer.
    Not forced: the outcome changes the draft's input, and a reply a teammate is editing is
    left alone."""
    jobs: JobQueue = ctx.get("jobs") or ArqJobQueue(ctx["redis"])
    try:
        await jobs.enqueue_process_ticket(action.ticket_id, action.workspace_id)
    except Exception:
        logger.exception(
            "Failed to enqueue the confirmation draft (ticket_id=%s)", action.ticket_id
        )
