"""Demo data reset: off by default (404), owners only (403), only the caller's workspace,
sample orders back to their seeded state, and the database function's own tenant check."""

import uuid
from decimal import Decimal

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.ai.decisions import FakeDecisionClient, get_decision_client
from app.ai.decisions import fake_classification as clf
from app.core.config import get_settings
from app.workers.actions import execute_action
from tests.conftest import (
    SHOP_ORIGIN,
    RecordingQueue,
    SignedUp,
    add_member,
    as_agent_in,
    open_widget,
    signup,
    widget_key,
)
from tests.test_approvals import approve_url, cancel_action, only_action, refund_action, worker
from tests.test_widget import SET_CONTEXT, ask, rows, use_llm

RESET_URL = "/api/v1/workspace/demo/reset"
CONVERSATION_TABLES = (
    "audit_events",
    "feedback",
    "tool_calls",
    "action_requests",
    "reply_drafts",
    "messages",
    "tickets",
    "conversations",
    "contacts",
)


@pytest.fixture(autouse=True)
def setup(app: FastAPI, monkeypatch: pytest.MonkeyPatch) -> None:
    s = get_settings()
    monkeypatch.setattr(s, "widget_dev_allow_localhost", False)
    monkeypatch.setattr(s, "demo_tools_enabled", True)
    decider = FakeDecisionClient({}, default=clf("refund_request", priority="high"))
    app.dependency_overrides[get_decision_client] = lambda: decider
    use_llm(app, "unused")


async def fill(
    client: AsyncClient, owner: SignedUp, worker_ctx: dict, job_queue: RecordingQueue
) -> None:
    """A widget conversation handed off as a ticket, plus an executed refund."""
    session = await open_widget(client, await widget_key(client, owner, [SHOP_ORIGIN]))
    await ask(client, session, "I want a refund for my order")
    action = await refund_action(client, owner)
    await client.post(approve_url(action), headers=owner.headers)
    assert await execute_action(
        worker(worker_ctx, job_queue), action["id"], str(owner.workspace_id)
    ) == "succeeded"


async def counts(engine: AsyncEngine, workspace_id: uuid.UUID) -> dict[str, int]:
    out = {}
    for table in CONVERSATION_TABLES:
        [row] = await rows(engine, workspace_id, f"SELECT count(*) AS n FROM {table}")
        out[table] = row["n"]
    return out


async def test_disabled_returns_404_and_reports_disabled(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(get_settings(), "demo_tools_enabled", False)
    owner = await signup(client, "owner@example.com")

    resp = await client.post(RESET_URL, headers=owner.headers)

    assert resp.status_code == 404
    status = await client.get("/api/v1/workspace/demo", headers=owner.headers)
    assert status.json() == {"enabled": False}


async def test_only_owners_can_reset(client: AsyncClient, owner_engine: AsyncEngine) -> None:
    owner = await signup(client, "owner@example.com")
    agent = await signup(client, "agent@example.com", workspace_name="Agent's own")
    agent_headers = await as_agent_in(client, owner_engine, agent, owner.workspace_id)
    admin = await signup(client, "admin@example.com", workspace_name="Admin's own")
    await add_member(owner_engine, admin.user_id, owner.workspace_id, "admin")
    switched = await client.post(
        f"/api/v1/workspaces/{owner.workspace_id}/switch", headers=admin.headers
    )
    client.cookies.clear()
    admin_headers = {"Authorization": f"Bearer {switched.json()['access_token']}"}

    for headers in (agent_headers, admin_headers):
        assert (await client.post(RESET_URL, headers=headers)).status_code == 403
    assert (await client.get("/api/v1/workspace/demo", headers=agent_headers)).json() == {
        "enabled": True
    }


async def test_reset_clears_only_the_callers_workspace(
    client: AsyncClient,
    worker_ctx: dict,
    job_queue: RecordingQueue,
    app_role_engine: AsyncEngine,
) -> None:
    a = await signup(client, "a@example.com", workspace_name="Tenant A")
    b = await signup(client, "b@example.com", workspace_name="Tenant B")
    await fill(client, a, worker_ctx, job_queue)
    await fill(client, b, worker_ctx, job_queue)
    before_b = await counts(app_role_engine, b.workspace_id)
    assert all(before_b[t] > 0 for t in ("audit_events", "messages", "tickets", "conversations"))

    resp = await client.post(RESET_URL, headers=a.headers)

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert list(body["deleted"]) == list(CONVERSATION_TABLES)
    assert body["deleted"]["tickets"] == 2  # the widget handoff and the refund ticket
    assert body["mock_orders_reset"] == 1
    assert await counts(app_role_engine, a.workspace_id) == dict.fromkeys(CONVERSATION_TABLES, 0)
    # A's orders are back to the seed: the refund is undone, the rows are kept.
    orders = await rows(
        app_role_engine,
        a.workspace_id,
        "SELECT order_number, status, refunded_amount, applied_action_keys FROM mock_orders",
    )
    assert len(orders) == 10
    assert all(o["refunded_amount"] == Decimal(0) and o["applied_action_keys"] == [] for o in orders)
    # B is untouched, including its refunded order.
    assert await counts(app_role_engine, b.workspace_id) == before_b
    [refunded] = await rows(
        app_role_engine, b.workspace_id, "SELECT refunded_amount FROM mock_orders WHERE refunded_amount > 0"
    )
    assert refunded["refunded_amount"] == Decimal("36.00")
    # The owner, workspace, settings and widget key survive.
    assert (await client.get("/api/v1/workspace/settings", headers=a.headers)).status_code == 200


async def test_cancelled_orders_go_back_to_their_seeded_status(
    client: AsyncClient,
    worker_ctx: dict,
    job_queue: RecordingQueue,
    app_role_engine: AsyncEngine,
) -> None:
    owner = await signup(client, "owner@example.com")
    action = await cancel_action(client, owner, "RA-10422")
    await client.post(approve_url(action), headers=owner.headers)
    await execute_action(worker(worker_ctx, job_queue), action["id"], str(owner.workspace_id))
    assert (await only_action(client, owner))["status"] == "succeeded"

    resp = await client.post(RESET_URL, headers=owner.headers)

    assert resp.json()["mock_orders_reset"] == 1
    [order] = await rows(
        app_role_engine, owner.workspace_id, "SELECT status FROM mock_orders WHERE order_number = 'RA-10422'"
    )
    assert order["status"] == "processing"


async def test_function_refuses_a_workspace_other_than_the_context(
    client: AsyncClient,
    worker_ctx: dict,
    job_queue: RecordingQueue,
    app_role_engine: AsyncEngine,
) -> None:
    a = await signup(client, "a@example.com", workspace_name="Tenant A")
    b = await signup(client, "b@example.com", workspace_name="Tenant B")
    await fill(client, b, worker_ctx, job_queue)
    before_b = await counts(app_role_engine, b.workspace_id)
    call = text("SELECT * FROM reset_workspace_demo_data(:wid, '{}'::jsonb)")

    # The app role, scoped to A, asking for B's workspace...
    async with app_role_engine.connect() as conn, conn.begin():
        await conn.execute(SET_CONTEXT, {"wid": str(a.workspace_id)})
        with pytest.raises(Exception, match="not the current tenant"):
            await conn.execute(call, {"wid": b.workspace_id})
    # ...or with no tenant context at all.
    async with app_role_engine.connect() as conn, conn.begin():
        with pytest.raises(Exception, match="not the current tenant"):
            await conn.execute(call, {"wid": b.workspace_id})

    assert await counts(app_role_engine, b.workspace_id) == before_b
    # And the app role still can't delete audit events directly.
    async with app_role_engine.connect() as conn, conn.begin():
        await conn.execute(SET_CONTEXT, {"wid": str(b.workspace_id)})
        with pytest.raises(Exception, match="permission denied"):
            await conn.execute(text("DELETE FROM audit_events"))
