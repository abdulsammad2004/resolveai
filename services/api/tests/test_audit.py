"""audit_events: ticket changes are recorded, the table is append-only for the app role, and
RLS keeps each workspace's events to itself."""

import uuid

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.ai.decisions import FakeDecisionClient, get_decision_client
from app.ai.decisions import fake_classification as clf
from tests.conftest import as_agent_in, signup
from tests.test_widget import SET_CONTEXT, rows


@pytest.fixture(autouse=True)
def decider(app: FastAPI) -> None:
    fake = FakeDecisionClient({}, default=clf("knowledge_question"))
    app.dependency_overrides[get_decision_client] = lambda: fake


async def new_ticket(client: AsyncClient, headers: dict[str, str]) -> str:
    resp = await client.post(
        "/api/v1/tickets",
        json={"subject": "Where is my parcel?", "description": "It hasn't arrived yet"},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def test_status_priority_and_assignee_changes_are_recorded(
    client: AsyncClient, owner_engine: AsyncEngine
) -> None:
    owner = await signup(client, "owner@example.com", full_name="Dana Owner")
    agent = await signup(client, "agent@example.com", workspace_name="Agent's own")
    await as_agent_in(client, owner_engine, agent, owner.workspace_id)
    ticket_id = await new_ticket(client, owner.headers)
    url = f"/api/v1/tickets/{ticket_id}"

    await client.patch(url, json={"status": "triaged"}, headers=owner.headers)
    await client.patch(url, json={"priority": "high"}, headers=owner.headers)
    await client.patch(url, json={"assignee_id": str(agent.user_id)}, headers=owner.headers)
    # No change, no event.
    resp = await client.patch(url, json={"status": "triaged"}, headers=owner.headers)

    activity = resp.json()["activity"]
    assert [(e["action"], e["before"], e["after"]) for e in activity] == [
        ("ticket.status_changed", {"status": "new"}, {"status": "triaged"}),
        ("ticket.priority_changed", {"priority": "normal"}, {"priority": "high"}),
        (
            "ticket.assignee_changed",
            {"assignee_id": None},
            {"assignee_id": str(agent.user_id)},
        ),
    ]
    assert all(e["actor_type"] == "user" for e in activity)
    assert all(e["actor_name"] == "Dana Owner" for e in activity)


async def test_audit_events_are_append_only(
    client: AsyncClient, app_role_engine: AsyncEngine
) -> None:
    owner = await signup(client, "owner@example.com")
    ticket_id = await new_ticket(client, owner.headers)
    await client.patch(
        f"/api/v1/tickets/{ticket_id}", json={"status": "resolved"}, headers=owner.headers
    )

    for sql in (
        "UPDATE audit_events SET action = 'tampered'",
        "DELETE FROM audit_events",
        "TRUNCATE audit_events",
    ):
        async with app_role_engine.connect() as conn, conn.begin():
            await conn.execute(SET_CONTEXT, {"wid": str(owner.workspace_id)})
            with pytest.raises(Exception, match="permission denied"):
                await conn.execute(text(sql))

    [event] = await rows(app_role_engine, owner.workspace_id, "SELECT action FROM audit_events")
    assert event["action"] == "ticket.status_changed"


async def test_audit_events_are_tenant_isolated(
    client: AsyncClient, app_role_engine: AsyncEngine, owner_engine: AsyncEngine
) -> None:
    a = await signup(client, "a@example.com", workspace_name="Tenant A")
    b = await signup(client, "b@example.com", workspace_name="Tenant B")
    ticket_id = await new_ticket(client, a.headers)
    await client.patch(
        f"/api/v1/tickets/{ticket_id}", json={"status": "resolved"}, headers=a.headers
    )

    # B sees nothing, with its own context or with none...
    assert await rows(app_role_engine, b.workspace_id, "SELECT * FROM audit_events") == []
    async with app_role_engine.connect() as conn:
        assert (await conn.execute(text("SELECT count(*) FROM audit_events"))).scalar_one() == 0
    async with owner_engine.connect() as conn:
        assert (await conn.execute(text("SELECT count(*) FROM audit_events"))).scalar_one() == 1
    assert (await client.get(f"/api/v1/tickets/{ticket_id}", headers=b.headers)).status_code == 404

    # ...and can't write events into A's workspace.
    async with app_role_engine.connect() as conn, conn.begin():
        await conn.execute(SET_CONTEXT, {"wid": str(b.workspace_id)})
        with pytest.raises(Exception, match="row-level security"):
            await conn.execute(
                text(
                    "INSERT INTO audit_events (id, workspace_id, actor_type, action, target_type) "
                    "VALUES (:id, :wid, 'system', 'forged', 'ticket')"
                ),
                {"id": uuid.uuid4(), "wid": a.workspace_id},
            )
