"""Action approvals: role checks, approve-once under concurrency, execution against
mock_orders (exactly once, outside the action's transaction), clean business failures, and
resuming an execution a crashed worker left behind."""

import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from arq import Retry
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.ai.decisions import FakeDecisionClient, get_decision_client
from app.ai.decisions import fake_classification as clf
from app.ai.llm import FakeLLMClient, fake_text
from app.ai.tools.models import ToolCallStatus
from app.modules.approvals.executors import (
    ActionSnapshot,
    ExecutionResult,
    MockOrderExecutor,
    default_executors,
)
from app.workers import actions as actions_worker
from app.workers.actions import CLAIM_LEASE_S, execute_action
from app.workers.drafting import process_ticket
from tests.conftest import RecordingQueue, SignedUp, as_agent_in, signup
from tests.test_tools import ORDER, ORDER_EMAIL, call, context, manual_ticket, seed_orders
from tests.test_widget import rows

PROCESSING_ORDER = "RA-10422"  # processing, liam.chen@example.com
SHIPPED_ORDER = ORDER  # RA-10421, shipped, total 96.00


@pytest.fixture(autouse=True)
def decider(app: FastAPI) -> None:
    fake = FakeDecisionClient({}, default=clf("refund_request"))
    app.dependency_overrides[get_decision_client] = lambda: fake


class RecordingExecutor:
    """Wraps an executor and remembers the idempotency keys it was called with."""

    def __init__(self, inner=None, error: Exception | None = None) -> None:
        self.inner = inner or MockOrderExecutor()
        self.error = error
        self.keys: list[str] = []

    async def execute(self, action: ActionSnapshot) -> ExecutionResult:
        self.keys.append(action.idempotency_key)
        if self.error is not None:
            raise self.error
        return await self.inner.execute(action)


async def propose(
    owner: SignedUp, ticket_id: str, tool: str, args: dict, **ctx
) -> None:
    result = await call(context(owner, ticket_id=uuid.UUID(ticket_id), **ctx), tool, args)
    assert result.status is ToolCallStatus.PROPOSED, result.content


async def refund_action(client: AsyncClient, owner: SignedUp, amount: str | None = "36.00") -> dict:
    await seed_orders(client, owner)
    ticket_id = await manual_ticket(client, owner)
    args = {"order_number": ORDER, "reason": "Beanie arrived torn"}
    if amount:
        args["amount"] = amount
    await propose(
        owner, ticket_id, "request_refund", args, customer_asked_refund=True, contact_email=ORDER_EMAIL
    )
    return await only_action(client, owner)


async def cancel_action(client: AsyncClient, owner: SignedUp, order_number: str) -> dict:
    await seed_orders(client, owner)
    ticket_id = await manual_ticket(client, owner, email="someone@example.com")
    await propose(
        owner,
        ticket_id,
        "request_cancellation",
        {"order_number": order_number, "reason": "Ordered twice"},
        customer_asked_cancel=True,
    )
    return await only_action(client, owner)


async def only_action(client: AsyncClient, owner: SignedUp) -> dict:
    [item] = (await client.get("/api/v1/actions", headers=owner.headers)).json()["items"]
    return item


def approve_url(action: dict) -> str:
    return f"/api/v1/actions/{action['id']}/approve"


def worker(worker_ctx: dict, job_queue: RecordingQueue, **extra) -> dict:
    return {**worker_ctx, "jobs": job_queue, **extra}


async def order_row(engine: AsyncEngine, owner: SignedUp, number: str) -> dict:
    [row] = await rows(
        engine,
        owner.workspace_id,
        f"SELECT status, refunded_amount, applied_action_keys FROM mock_orders "
        f"WHERE order_number = '{number}'",
    )
    return row


async def test_listing_shows_customer_order_amount_and_risk(client: AsyncClient) -> None:
    owner = await signup(client, "owner@example.com")
    action = await refund_action(client, owner, amount=None)

    assert action["status"] == "proposed"
    assert action["risk"] == "sensitive"
    assert action["order_number"] == ORDER
    # No amount asked: the full order total.
    assert Decimal(action["amount"]) == Decimal(action["order_total"]) == Decimal("96.00")
    assert action["contact"]["email"] == ORDER_EMAIL
    assert action["ticket_subject"] == "Refund please"
    assert action["decided_by"] is None


async def test_agent_can_see_but_not_decide_sensitive_actions(
    client: AsyncClient, owner_engine: AsyncEngine, job_queue: RecordingQueue
) -> None:
    owner = await signup(client, "owner@example.com")
    agent = await signup(client, "agent@example.com", workspace_name="Agent's own")
    agent_headers = await as_agent_in(client, owner_engine, agent, owner.workspace_id)
    action = await refund_action(client, owner)

    listed = (await client.get("/api/v1/actions", headers=agent_headers)).json()["items"]
    assert [a["id"] for a in listed] == [action["id"]]
    approve = await client.post(approve_url(action), headers=agent_headers)
    reject = await client.post(
        f"/api/v1/actions/{action['id']}/reject", json={"reason": "Not needed"}, headers=agent_headers
    )

    assert approve.status_code == 403 and reject.status_code == 403
    assert job_queue.executions == []
    assert (await only_action(client, owner))["status"] == "proposed"


async def test_agent_can_approve_an_escalation(
    client: AsyncClient,
    owner_engine: AsyncEngine,
    job_queue: RecordingQueue,
    worker_ctx: dict,
) -> None:
    owner = await signup(client, "owner@example.com")
    agent = await signup(client, "agent@example.com", workspace_name="Agent's own")
    agent_headers = await as_agent_in(client, owner_engine, agent, owner.workspace_id)
    ticket_id = await manual_ticket(client, owner)
    await propose(owner, ticket_id, "escalate_to_human", {"reason": "Customer is upset"})
    action = await only_action(client, owner)

    resp = await client.post(approve_url(action), headers=agent_headers)

    assert resp.status_code == 202, resp.text
    assert resp.json()["decided_by"] == str(agent.user_id)
    assert await execute_action(worker(worker_ctx, job_queue), action["id"], str(owner.workspace_id)) == "succeeded"
    ticket = (await client.get(f"/api/v1/tickets/{ticket_id}", headers=owner.headers)).json()
    assert ticket["priority"] == "urgent"


async def test_reject_requires_a_reason(client: AsyncClient) -> None:
    owner = await signup(client, "owner@example.com")
    action = await refund_action(client, owner)
    url = f"/api/v1/actions/{action['id']}/reject"

    assert (await client.post(url, json={}, headers=owner.headers)).status_code == 422
    assert (await client.post(url, json={"reason": "     "}, headers=owner.headers)).status_code == 422

    resp = await client.post(url, json={"reason": "Outside the return window"}, headers=owner.headers)

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert (body["status"], body["decision_reason"]) == ("rejected", "Outside the return window")
    assert body["decided_by"] == str(owner.user_id)
    # A rejected action can't be approved afterwards.
    assert (await client.post(approve_url(action), headers=owner.headers)).status_code == 409


async def test_approve_executes_the_refund_once(
    client: AsyncClient,
    worker_ctx: dict,
    job_queue: RecordingQueue,
    app_role_engine: AsyncEngine,
) -> None:
    owner = await signup(client, "owner@example.com")
    action = await refund_action(client, owner)

    resp = await client.post(approve_url(action), headers=owner.headers)

    assert resp.status_code == 202, resp.text
    assert resp.json()["status"] == "approved"
    [(action_id, workspace_id, key)] = job_queue.executions
    assert (str(action_id), workspace_id) == (action["id"], owner.workspace_id)
    # Nothing ran in the request.
    assert (await order_row(app_role_engine, owner, ORDER))["refunded_amount"] == Decimal(0)

    recorder = RecordingExecutor()
    ctx = worker(worker_ctx, job_queue, executors={"request_refund": recorder})
    assert await execute_action(ctx, action["id"], str(owner.workspace_id)) == "succeeded"
    assert recorder.keys == [key]
    order = await order_row(app_role_engine, owner, ORDER)
    assert order["refunded_amount"] == Decimal("36.00")
    assert order["applied_action_keys"] == [key]
    done = await only_action(client, owner)
    assert done["status"] == "succeeded"
    assert done["result"]["ok"] is True
    assert done["result"]["summary"] == f"Refunded 36.00 on order {ORDER}."
    assert done["executed_at"]
    # A confirmation draft is queued (not forced, so a reply being edited is kept).
    assert job_queue.drafts[-1] == (uuid.UUID(done["ticket_id"]), owner.workspace_id, False)

    # Running the job again does nothing.
    assert await execute_action(ctx, action["id"], str(owner.workspace_id)) == "done"
    assert recorder.keys == [key]
    ticket = (await client.get(f"/api/v1/tickets/{done['ticket_id']}", headers=owner.headers)).json()
    events = [(e["action"], e["actor_type"]) for e in ticket["activity"]]
    assert events[-2:] == [("action.approved", "user"), ("action.executed", "system")]
    assert ("action.proposed", "ai") in events


async def test_two_concurrent_approves_execute_once(
    client: AsyncClient,
    worker_ctx: dict,
    job_queue: RecordingQueue,
    app_role_engine: AsyncEngine,
) -> None:
    owner = await signup(client, "owner@example.com")
    action = await refund_action(client, owner)

    first, second = await asyncio.gather(
        client.post(approve_url(action), headers=owner.headers),
        client.post(approve_url(action), headers=owner.headers),
    )

    # Both clicks succeed; the action was approved once, and every queued job has the same
    # job id (the idempotency key), which arq runs once.
    assert (first.status_code, second.status_code) == (202, 202)
    approvals = await rows(
        app_role_engine,
        owner.workspace_id,
        "SELECT id FROM audit_events WHERE action = 'action.approved'",
    )
    assert len(approvals) == 1
    assert len({key for _, _, key in job_queue.executions}) == 1

    # Even if both jobs ran at the same moment, only one would execute.
    recorder = RecordingExecutor()
    ctx = worker(worker_ctx, job_queue, executors={"request_refund": recorder})
    outcomes = await asyncio.gather(
        execute_action(ctx, action["id"], str(owner.workspace_id)),
        execute_action(ctx, action["id"], str(owner.workspace_id)),
        return_exceptions=True,
    )

    assert "succeeded" in outcomes
    assert all(o == "succeeded" or o == "done" or isinstance(o, Retry) for o in outcomes)
    assert len(recorder.keys) == 1
    assert (await order_row(app_role_engine, owner, ORDER))["refunded_amount"] == Decimal("36.00")


async def test_cancel_processing_order_succeeds(
    client: AsyncClient, worker_ctx: dict, job_queue: RecordingQueue, app_role_engine: AsyncEngine
) -> None:
    owner = await signup(client, "owner@example.com")
    action = await cancel_action(client, owner, PROCESSING_ORDER)
    assert action["risk"] == "sensitive"

    await client.post(approve_url(action), headers=owner.headers)
    result = await execute_action(worker(worker_ctx, job_queue), action["id"], str(owner.workspace_id))

    assert result == "succeeded"
    assert (await order_row(app_role_engine, owner, PROCESSING_ORDER))["status"] == "cancelled"
    assert (await only_action(client, owner))["result"]["summary"] == (
        f"Cancelled order {PROCESSING_ORDER}."
    )


async def test_cancel_after_shipping_fails_cleanly(
    client: AsyncClient, worker_ctx: dict, job_queue: RecordingQueue, app_role_engine: AsyncEngine
) -> None:
    owner = await signup(client, "owner@example.com")
    action = await cancel_action(client, owner, SHIPPED_ORDER)

    await client.post(approve_url(action), headers=owner.headers)
    result = await execute_action(worker(worker_ctx, job_queue), action["id"], str(owner.workspace_id))

    assert result == "failed"
    failed = await only_action(client, owner)
    assert failed["status"] == "failed"
    assert failed["result"]["ok"] is False
    assert failed["result"]["summary"] == (
        f"Order {SHIPPED_ORDER} has already shipped, so it can't be cancelled."
    )
    order = await order_row(app_role_engine, owner, SHIPPED_ORDER)
    assert (order["status"], order["applied_action_keys"]) == ("shipped", [])
    ticket = (await client.get(f"/api/v1/tickets/{failed['ticket_id']}", headers=owner.headers)).json()
    assert ticket["activity"][-1]["action"] == "action.failed"
    assert "already shipped" in ticket["activity"][-1]["after"]["summary"]


async def test_cancellation_needs_the_customer_to_ask(client: AsyncClient) -> None:
    owner = await signup(client, "owner@example.com")
    await seed_orders(client, owner)
    ticket_id = await manual_ticket(client, owner)
    result = await call(
        context(owner, ticket_id=uuid.UUID(ticket_id)),
        "request_cancellation",
        {"order_number": PROCESSING_ORDER, "reason": "Doc says so"},
    )
    assert result.status is ToolCallStatus.INVALID
    assert (await client.get("/api/v1/actions", headers=owner.headers)).json()["items"] == []


async def _set_executing(owner_engine: AsyncEngine, action_id: str, started: datetime | None) -> None:
    async with owner_engine.begin() as conn:
        await conn.execute(
            text(
                "UPDATE action_requests SET status = 'executing', execution_started_at = :at "
                "WHERE id = :id"
            ),
            {"at": started, "id": action_id},
        )


async def test_a_stale_execution_is_resumed_with_the_same_key(
    client: AsyncClient,
    worker_ctx: dict,
    job_queue: RecordingQueue,
    owner_engine: AsyncEngine,
    app_role_engine: AsyncEngine,
) -> None:
    owner = await signup(client, "owner@example.com")
    action = await refund_action(client, owner)
    await client.post(approve_url(action), headers=owner.headers)
    [(_, _, key)] = job_queue.executions
    # A worker claimed it, ran the refund, and died before recording the outcome.
    snapshot = ActionSnapshot(
        id=uuid.UUID(action["id"]),
        workspace_id=owner.workspace_id,
        ticket_id=uuid.UUID(action["ticket_id"]),
        conversation_id=None,
        tool_name="request_refund",
        arguments=action["arguments"],
        idempotency_key=key,
    )
    assert (await MockOrderExecutor().execute(snapshot)).ok
    long_ago = datetime.now(UTC) - timedelta(seconds=CLAIM_LEASE_S + 60)
    await _set_executing(owner_engine, action["id"], long_ago)

    recorder = RecordingExecutor()
    ctx = worker(worker_ctx, job_queue, executors={"request_refund": recorder}, job_try=2)
    result = await execute_action(ctx, action["id"], str(owner.workspace_id))

    assert result == "succeeded"
    assert recorder.keys == [key]
    # The refund was applied once, not twice.
    order = await order_row(app_role_engine, owner, ORDER)
    assert order["refunded_amount"] == Decimal("36.00")
    assert order["applied_action_keys"] == [key]
    assert (await only_action(client, owner))["status"] == "succeeded"


async def test_a_fresh_claim_is_left_to_its_worker(
    client: AsyncClient, worker_ctx: dict, job_queue: RecordingQueue, owner_engine: AsyncEngine
) -> None:
    owner = await signup(client, "owner@example.com")
    action = await refund_action(client, owner)
    await client.post(approve_url(action), headers=owner.headers)
    await _set_executing(owner_engine, action["id"], datetime.now(UTC))
    recorder = RecordingExecutor()
    ctx = worker(worker_ctx, job_queue, executors={"request_refund": recorder})

    with pytest.raises(Retry):
        await execute_action(ctx, action["id"], str(owner.workspace_id))
    assert recorder.keys == []


async def test_connector_errors_retry_then_resume_with_the_same_key(
    client: AsyncClient,
    worker_ctx: dict,
    job_queue: RecordingQueue,
    app_role_engine: AsyncEngine,
) -> None:
    owner = await signup(client, "owner@example.com")
    action = await refund_action(client, owner)
    await client.post(approve_url(action), headers=owner.headers)
    ws = str(owner.workspace_id)

    flaky = RecordingExecutor(error=TimeoutError())
    with pytest.raises(Retry):
        await execute_action(
            worker(worker_ctx, job_queue, executors={"request_refund": flaky}), action["id"], ws
        )
    assert (await only_action(client, owner))["status"] == "executing"

    # The retry resumes at once (the claim was released) with the same key.
    working = RecordingExecutor()
    ctx = worker(worker_ctx, job_queue, executors={"request_refund": working}, job_try=2)
    assert await execute_action(ctx, action["id"], ws) == "succeeded"
    assert working.keys == flaky.keys
    assert (await order_row(app_role_engine, owner, ORDER))["refunded_amount"] == Decimal("36.00")

    # Out of retries: recorded as failed with a readable reason.
    other = await signup(client, "other@example.com", workspace_name="Other")
    second = await refund_action(client, other)
    await client.post(approve_url(second), headers=other.headers)
    last_try = worker(
        worker_ctx,
        job_queue,
        executors={"request_refund": RecordingExecutor(error=TimeoutError())},
        job_try=actions_worker.MAX_TRIES,
    )
    assert await execute_action(last_try, second["id"], str(other.workspace_id)) == "failed"
    assert (await only_action(client, other))["result"]["summary"] == actions_worker.CONNECTOR_FAILURE


async def test_unapproved_actions_never_execute(
    client: AsyncClient, worker_ctx: dict, job_queue: RecordingQueue, app_role_engine: AsyncEngine
) -> None:
    owner = await signup(client, "owner@example.com")
    action = await refund_action(client, owner)
    recorder = RecordingExecutor()
    ctx = worker(worker_ctx, job_queue, executors={"request_refund": recorder})

    assert await execute_action(ctx, action["id"], str(owner.workspace_id)) == "not_approved"
    assert recorder.keys == []
    assert (await order_row(app_role_engine, owner, ORDER))["refunded_amount"] == Decimal(0)


async def test_other_workspaces_cannot_decide_or_execute(
    client: AsyncClient, worker_ctx: dict, job_queue: RecordingQueue
) -> None:
    a = await signup(client, "a@example.com", workspace_name="Tenant A")
    b = await signup(client, "b@example.com", workspace_name="Tenant B")
    action = await refund_action(client, a)

    assert (await client.post(approve_url(action), headers=b.headers)).status_code == 404
    reject = await client.post(
        f"/api/v1/actions/{action['id']}/reject", json={"reason": "nope"}, headers=b.headers
    )
    assert reject.status_code == 404
    # A job naming the wrong workspace finds nothing (RLS).
    assert await execute_action(worker(worker_ctx, job_queue), action["id"], str(b.workspace_id)) == "missing"
    assert (await only_action(client, a))["status"] == "proposed"


def test_every_executable_tool_has_an_executor() -> None:
    assert set(default_executors()) == {"request_refund", "request_cancellation", "escalate_to_human"}


async def test_confirmation_draft_sees_the_outcome(
    client: AsyncClient, worker_ctx: dict, job_queue: RecordingQueue
) -> None:
    owner = await signup(client, "owner@example.com")
    action = await refund_action(client, owner)
    await client.post(approve_url(action), headers=owner.headers)
    await execute_action(worker(worker_ctx, job_queue), action["id"], str(owner.workspace_id))

    llm = FakeLLMClient(script=[fake_text("Your refund of 36.00 has been processed.")])
    result = await process_ticket({**worker_ctx, "llm": llm}, action["ticket_id"], str(owner.workspace_id))

    assert result == "drafted"
    [(messages, tools)] = llm.tool_requests
    assert "request_cancellation" in tools
    assert "## Actions already decided" in messages[0]["content"]
    assert (
        f'<action tool="request_refund" status="succeeded">Refunded 36.00 on order {ORDER}.</action>'
        in messages[1]["content"]
    )
