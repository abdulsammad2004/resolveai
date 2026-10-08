"""Tickets API: manual creation (classified), filters, urgent-first sort, pagination, PATCH
rules, detail with transcript, and cross-tenant isolation. Plus the mock order seed."""

import uuid

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.ai.decisions import FakeDecisionClient, get_decision_client
from app.ai.decisions import fake_classification as clf
from app.core.config import get_settings
from tests.conftest import SHOP_ORIGIN, SignedUp, as_agent_in, open_widget, signup, widget_key
from tests.test_widget import ask, use_llm

URL = "/api/v1/tickets"


@pytest.fixture(autouse=True)
def decider(app: FastAPI, monkeypatch: pytest.MonkeyPatch) -> FakeDecisionClient:
    monkeypatch.setattr(get_settings(), "widget_dev_allow_localhost", False)
    fake = FakeDecisionClient(
        {
            "urgent": clf("account_change", priority="urgent"),
            "refund": clf("refund_request", priority="high"),
            "question": clf("knowledge_question", priority="low"),
        },
        default=clf("other", priority="normal"),
    )
    app.dependency_overrides[get_decision_client] = lambda: fake
    return fake


async def create(client: AsyncClient, user: SignedUp, subject: str, **extra) -> dict:
    resp = await client.post(
        URL,
        json={"subject": subject, "description": f"Details about {subject}", **extra},
        headers=user.headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def test_manual_ticket_is_classified(client: AsyncClient) -> None:
    owner = await signup(client, "owner@example.com")

    ticket = await create(client, owner, "Need a refund", contact_email="Buyer@Example.com")

    assert (ticket["intent"], ticket["priority"]) == ("refund_request", "high")
    assert ticket["status"] == "new"
    assert ticket["source"] == "manual"
    assert ticket["description"] == "Details about Need a refund"
    assert ticket["contact"]["email"] == "buyer@example.com"
    assert ticket["classification"]["provider"] == "fake"
    assert ticket["conversation"] is None

    # The same email reuses the contact.
    again = await create(client, owner, "Another refund", contact_email="buyer@example.com")
    assert again["contact"]["id"] == ticket["contact"]["id"]

    for bad in ({"subject": "", "description": "x"}, {"subject": "x", "description": ""}):
        assert (await client.post(URL, json=bad, headers=owner.headers)).status_code == 422


async def test_urgent_first_then_newest_with_filters_and_pagination(client: AsyncClient) -> None:
    owner = await signup(client, "owner@example.com")
    first = await create(client, owner, "Old question")
    urgent = await create(client, owner, "urgent: locked out")
    refund = await create(client, owner, "refund please")
    newest = await create(client, owner, "Newest thing")

    body = (await client.get(URL, headers=owner.headers)).json()
    assert [t["id"] for t in body["items"]] == [urgent["id"], newest["id"], refund["id"], first["id"]]
    assert body["counts"]["new"] == 4
    assert (body["counts"]["open"], body["counts"]["urgent_open"]) == (4, 1)

    seen, cursor = [], None
    while True:
        url = f"{URL}?limit=1" + (f"&cursor={cursor}" if cursor else "")
        page = (await client.get(url, headers=owner.headers)).json()
        seen += [t["id"] for t in page["items"]]
        if not (cursor := page["next_cursor"]):
            break
    assert seen == [urgent["id"], newest["id"], refund["id"], first["id"]]

    async def ids(query: str) -> list[str]:
        resp = await client.get(f"{URL}?{query}", headers=owner.headers)
        assert resp.status_code == 200, resp.text
        return [t["id"] for t in resp.json()["items"]]

    assert await ids("priority=high") == [refund["id"]]
    assert await ids("intent=account_change") == [urgent["id"]]
    assert await ids("assignee=me") == []
    assert len(await ids("assignee=unassigned")) == 4

    await client.patch(
        f"{URL}/{refund['id']}",
        json={"status": "resolved", "assignee_id": str(owner.user_id)},
        headers=owner.headers,
    )
    assert await ids("status=resolved") == [refund["id"]]
    assert await ids("assignee=me") == [refund["id"]]
    counts = (await client.get(URL, headers=owner.headers)).json()["counts"]
    assert (counts["open"], counts["resolved"]) == (3, 1)

    assert (await client.get(f"{URL}?priority=extreme", headers=owner.headers)).status_code == 422
    assert (await client.get(f"{URL}?cursor=nope", headers=owner.headers)).status_code == 422


async def test_patch_validates_assignee_membership(
    client: AsyncClient, owner_engine: AsyncEngine
) -> None:
    owner = await signup(client, "owner@example.com")
    teammate = await signup(client, "teammate@example.com", workspace_name="Teammate home")
    stranger = await signup(client, "stranger@example.com", workspace_name="Elsewhere")
    await as_agent_in(client, owner_engine, teammate, owner.workspace_id)
    ticket = await create(client, owner, "Something")
    url = f"{URL}/{ticket['id']}"

    resp = await client.patch(url, json={"assignee_id": str(stranger.user_id)}, headers=owner.headers)
    assert resp.status_code == 422
    assert "member" in resp.json()["error"]["message"]

    resp = await client.patch(
        url,
        json={"assignee_id": str(teammate.user_id), "priority": "urgent", "status": "triaged"},
        headers=owner.headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["assignee"]["full_name"] == "Test User"
    assert body["assignee"]["user_id"] == str(teammate.user_id)
    assert (body["priority"], body["status"]) == ("urgent", "triaged")

    resp = await client.patch(url, json={"assignee_id": None}, headers=owner.headers)
    assert resp.json()["assignee"] is None
    assert resp.json()["priority"] == "urgent"  # untouched fields stay

    for bad in ({}, {"status": "archived"}, {"status": None}, {"subject": "x"}):
        assert (await client.patch(url, json=bad, headers=owner.headers)).status_code == 422
    assert (
        await client.patch(f"{URL}/{uuid.uuid4()}", json={"status": "new"}, headers=owner.headers)
    ).status_code == 404


async def test_widget_ticket_detail_has_transcript_and_classification(
    app: FastAPI, client: AsyncClient
) -> None:
    owner = await signup(client, "owner@example.com")
    use_llm(app, "unused")
    session = await open_widget(client, await widget_key(client, owner, [SHOP_ORIGIN]))
    await ask(client, session, "I want a refund for my boots")

    [item] = (await client.get(URL, headers=owner.headers)).json()["items"]
    assert item["source"] == "widget"
    assert item["conversation_id"] == str(session.conversation_id)
    assert item["contact"]["anonymous_id"] == session.anonymous_id

    detail = (await client.get(f"{URL}/{item['id']}", headers=owner.headers)).json()
    assert detail["classification"]["intent"] == "refund_request"
    assert set(detail["classification"]["intent_probs"]) >= {"refund_request", "greeting"}
    transcript = detail["conversation"]["messages"]
    assert [m["role"] for m in transcript] == ["customer", "assistant"]
    assert transcript[0]["classification"]["intent"] == "refund_request"
    assert transcript[1]["route"] == "handoff"
    assert detail["conversation"]["ticket_id"] == item["id"]


async def test_workspace_b_cannot_see_a_tickets_or_orders(
    app: FastAPI, client: AsyncClient, app_role_engine: AsyncEngine
) -> None:
    a = await signup(client, "a@example.com", workspace_name="Workspace A")
    b = await signup(client, "b@example.com", workspace_name="Workspace B")
    use_llm(app, "unused")
    session = await open_widget(client, await widget_key(client, a, [SHOP_ORIGIN]))
    await ask(client, session, "refund now")
    manual = await create(client, a, "Manual A ticket")
    assert (await client.post("/api/v1/mock-orders/seed", headers=a.headers)).status_code == 200

    body = (await client.get(URL, headers=b.headers)).json()
    assert body["items"] == [] and body["counts"]["open"] == 0
    assert (await client.get(f"{URL}/{manual['id']}", headers=b.headers)).status_code == 404
    resp = await client.patch(f"{URL}/{manual['id']}", json={"status": "resolved"}, headers=b.headers)
    assert resp.status_code == 404
    assert (await client.get("/api/v1/mock-orders", headers=b.headers)).json() == []

    async with app_role_engine.connect() as conn, conn.begin():
        await conn.execute(
            text("SELECT set_config('app.workspace_id', :wid, true)"), {"wid": str(b.workspace_id)}
        )
        for table in ("tickets", "mock_orders"):
            assert (await conn.execute(text(f"SELECT count(*) FROM {table}"))).scalar_one() == 0
    async with app_role_engine.connect() as conn:
        assert (await conn.execute(text("SELECT count(*) FROM tickets"))).scalar_one() == 0


async def test_mock_order_seed_is_idempotent_and_admin_only(
    client: AsyncClient, owner_engine: AsyncEngine
) -> None:
    owner = await signup(client, "owner@example.com")

    first = (await client.post("/api/v1/mock-orders/seed", headers=owner.headers)).json()
    second = (await client.post("/api/v1/mock-orders/seed", headers=owner.headers)).json()

    assert first["inserted"] == 10
    assert second["inserted"] == 0
    assert len(second["orders"]) == 10
    orders = (await client.get("/api/v1/mock-orders", headers=owner.headers)).json()
    assert [o["order_number"] for o in orders] == sorted(o["order_number"] for o in orders)
    shipped = next(o for o in orders if o["order_number"] == "RA-10421")
    assert shipped["status"] == "shipped" and shipped["carrier"] == "UPS"
    assert shipped["total"] == "96.00"
    assert {o["status"] for o in orders} == {"processing", "shipped", "delivered", "cancelled"}

    agent = await signup(client, "agent@example.com", workspace_name="Agent home")
    headers = await as_agent_in(client, owner_engine, agent, owner.workspace_id)
    assert (await client.post("/api/v1/mock-orders/seed", headers=headers)).status_code == 403
    assert (await client.get("/api/v1/mock-orders", headers=headers)).status_code == 403
