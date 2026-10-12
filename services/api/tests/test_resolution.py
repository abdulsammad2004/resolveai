"""Resolving a ticket closes its widget conversation: the widget shows it as resolved and
read-only, a new message starts a new conversation that the AI handles normally, "Still
need help?" reopens the same ticket, and the customer can rate the resolution."""

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine

from app.ai.decisions import FakeDecisionClient, get_decision_client
from app.ai.decisions import fake_classification as clf
from app.core.config import get_settings
from tests.conftest import (
    SHOP_ORIGIN,
    RecordingQueue,
    SignedUp,
    WidgetSession,
    open_widget,
    signup,
    widget_key,
)
from tests.test_review import chat_ticket, detail, drafts_url
from tests.test_widget import ask, rows, use_llm

WIDGET_CONVERSATION = "/api/v1/widget/conversation"
MESSAGES_URL = "/api/v1/widget/messages"


@pytest.fixture(autouse=True)
def setup(app: FastAPI, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "widget_dev_allow_localhost", False)
    decider = FakeDecisionClient(
        {"refund": clf("refund_request", priority="high"), "hello": clf("greeting")},
        default=clf("knowledge_question"),
    )
    app.dependency_overrides[get_decision_client] = lambda: decider
    use_llm(app, "unused")


async def resolved_chat(
    client: AsyncClient, owner: SignedUp, worker_ctx: dict
) -> tuple[WidgetSession, str]:
    """A widget conversation handed off, answered by a teammate, then resolved."""
    session, ticket_id = await chat_ticket(client, owner, worker_ctx)
    draft_id = (await detail(client, owner, ticket_id))["draft"]["id"]
    await client.post(f"{drafts_url(ticket_id, draft_id)}/send", json={}, headers=owner.headers)
    resp = await client.patch(
        f"/api/v1/tickets/{ticket_id}", json={"status": "resolved"}, headers=owner.headers
    )
    assert resp.status_code == 200, resp.text
    return session, ticket_id


async def widget_state(client: AsyncClient, session: WidgetSession) -> dict:
    resp = await client.get(WIDGET_CONVERSATION, headers=session.headers)
    assert resp.status_code == 200, resp.text
    return resp.json()


async def test_resolving_closes_the_conversation(
    client: AsyncClient, worker_ctx: dict, app_role_engine: AsyncEngine
) -> None:
    owner = await signup(client, "owner@example.com")
    session, ticket_id = await resolved_chat(client, owner, worker_ctx)

    state = await widget_state(client, session)
    assert (state["status"], state["resolved"]) == ("closed", True)
    assert state["closed_at"] is not None
    assert state["resolution_rating"] is None
    # The old messages are still there, including the team's reply.
    assert state["messages"][-1]["role"] == "agent"
    # A poll for new messages carries the closed state too.
    polled = await client.get(
        WIDGET_CONVERSATION, params={"after": state["messages"][-1]["id"]}, headers=session.headers
    )
    assert (polled.json()["resolved"], polled.json()["messages"]) == (True, [])

    ticket = await detail(client, owner, ticket_id)
    closed = next(e for e in ticket["activity"] if e["action"] == "conversation.closed")
    assert (closed["actor_type"], closed["actor_id"]) == ("user", str(owner.user_id))
    assert closed["after"] == {"status": "closed"}

    # Reloading the widget resumes the closed conversation, so the banner survives.
    key = await widget_key(client, owner, [SHOP_ORIGIN])
    again = await open_widget(
        client,
        key,
        conversation_id=str(session.conversation_id),
        anonymous_id=session.anonymous_id,
    )
    assert again.conversation_id == session.conversation_id
    assert (await widget_state(client, again))["resolved"] is True


async def test_new_message_after_resolve_starts_a_new_conversation(
    client: AsyncClient,
    worker_ctx: dict,
    job_queue: RecordingQueue,
    app_role_engine: AsyncEngine,
) -> None:
    owner = await signup(client, "owner@example.com")
    session, ticket_id = await resolved_chat(client, owner, worker_ctx)
    before = await widget_state(client, session)

    # The closed conversation takes no new messages or ratings...
    blocked = await client.post(MESSAGES_URL, json={"content": "hello"}, headers=session.headers)
    assert blocked.status_code == 409
    assistant = next(m for m in before["messages"] if m["role"] == "assistant")
    rated = await client.post(
        "/api/v1/widget/feedback",
        json={"message_id": assistant["id"], "rating": "up"},
        headers=session.headers,
    )
    assert rated.status_code == 409
    assert await widget_state(client, session) == before

    # ...so the widget starts a new conversation for the same visitor.
    key = await widget_key(client, owner, [SHOP_ORIGIN])
    fresh = await open_widget(client, key, anonymous_id=session.anonymous_id)
    assert fresh.conversation_id != session.conversation_id
    assert fresh.anonymous_id == session.anonymous_id
    job_queue.drafts.clear()

    final = (await ask(client, fresh, "hello"))[-1][1]

    # The AI handles it as usual: a greeting gets small talk, and no ticket is opened.
    assert final["route"] == "small_talk"
    assert job_queue.drafts == []
    tickets = (await client.get("/api/v1/tickets", headers=owner.headers)).json()["items"]
    assert [t["id"] for t in tickets] == [ticket_id]
    assert (await detail(client, owner, ticket_id))["status"] == "resolved"
    [contacts] = await rows(app_role_engine, owner.workspace_id, "SELECT count(*) AS n FROM contacts")
    assert contacts["n"] == 1

    # A request that needs a person opens a new ticket on the new conversation.
    final = (await ask(client, fresh, "I want a refund for another order"))[-1][1]
    assert final["route"] == "handoff"
    tickets = (await client.get("/api/v1/tickets", headers=owner.headers)).json()["items"]
    assert len(tickets) == 2
    new_ticket = next(t for t in tickets if t["id"] != ticket_id)
    assert new_ticket["conversation_id"] == str(fresh.conversation_id)


async def test_still_need_help_reopens_the_same_ticket(
    client: AsyncClient, worker_ctx: dict, job_queue: RecordingQueue
) -> None:
    owner = await signup(client, "owner@example.com")
    session, ticket_id = await resolved_chat(client, owner, worker_ctx)

    resp = await client.post(f"{WIDGET_CONVERSATION}/reopen", headers=session.headers)

    assert resp.status_code == 200, resp.text
    state = resp.json()
    assert (state["status"], state["resolved"], state["closed_at"]) == ("needs_human", False, None)
    ticket = await detail(client, owner, ticket_id)
    assert ticket["status"] == "awaiting_review"
    events = [(e["action"], e["actor_type"]) for e in ticket["activity"]]
    assert events[-2:] == [("ticket.status_changed", "customer"), ("conversation.reopened", "customer")]
    # Reopening twice (or reopening something that isn't resolved) is refused.
    again = await client.post(f"{WIDGET_CONVERSATION}/reopen", headers=session.headers)
    assert again.status_code == 409

    # The customer carries on in the same chat, still with the team, on the same ticket.
    final = (await ask(client, session, "The refund still hasn't arrived, refund please"))[-1][1]
    assert final["route"] == "handoff"
    tickets = (await client.get("/api/v1/tickets", headers=owner.headers)).json()["items"]
    assert [t["id"] for t in tickets] == [ticket_id]
    assert (await widget_state(client, session))["messages"][-2]["content"].startswith(
        "The refund still"
    )


async def test_resolution_rating_is_stored_and_audited(
    client: AsyncClient, worker_ctx: dict
) -> None:
    owner = await signup(client, "owner@example.com")
    session, ticket_id = await resolved_chat(client, owner, worker_ctx)
    url = f"{WIDGET_CONVERSATION}/resolution-feedback"

    first = await client.post(url, json={"rating": "down"}, headers=session.headers)
    second = await client.post(url, json={"rating": "up"}, headers=session.headers)

    assert first.status_code == second.status_code == 200
    assert second.json()["resolution_rating"] == "up"
    ticket = await detail(client, owner, ticket_id)
    assert ticket["resolution_rating"] == "up"
    ratings = [e for e in ticket["activity"] if e["action"] == "ticket.resolution_rated"]
    assert [(e["before"], e["after"], e["actor_type"]) for e in ratings] == [
        ({"rating": None}, {"rating": "down"}, "customer"),
        ({"rating": "down"}, {"rating": "up"}, "customer"),
    ]
    assert (await client.post(url, json={"rating": "meh"}, headers=session.headers)).status_code == 422

    # Once reopened, the resolution can't be rated any more.
    await client.post(f"{WIDGET_CONVERSATION}/reopen", headers=session.headers)
    assert (await client.post(url, json={"rating": "up"}, headers=session.headers)).status_code == 409


async def test_open_conversations_cannot_be_reopened_or_rated(
    client: AsyncClient, worker_ctx: dict
) -> None:
    owner = await signup(client, "owner@example.com")
    session, _ = await chat_ticket(client, owner, worker_ctx)

    reopen = await client.post(f"{WIDGET_CONVERSATION}/reopen", headers=session.headers)
    rate = await client.post(
        f"{WIDGET_CONVERSATION}/resolution-feedback", json={"rating": "up"}, headers=session.headers
    )

    assert (reopen.status_code, rate.status_code) == (409, 409)


async def test_unresolving_in_the_inbox_reopens_the_conversation(
    client: AsyncClient, worker_ctx: dict
) -> None:
    owner = await signup(client, "owner@example.com")
    session, ticket_id = await resolved_chat(client, owner, worker_ctx)

    await client.patch(
        f"/api/v1/tickets/{ticket_id}", json={"status": "awaiting_review"}, headers=owner.headers
    )

    state = await widget_state(client, session)
    assert (state["status"], state["resolved"]) == ("needs_human", False)
    assert (await client.post(MESSAGES_URL, json={"content": "hello"}, headers=session.headers)).status_code == 200


async def test_resolution_is_tenant_isolated(
    client: AsyncClient, worker_ctx: dict, app_role_engine: AsyncEngine
) -> None:
    a = await signup(client, "a@example.com", workspace_name="Tenant A")
    b = await signup(client, "b@example.com", workspace_name="Tenant B")
    _, ticket_id = await resolved_chat(client, a, worker_ctx)
    b_session = await open_widget(client, await widget_key(client, b, [SHOP_ORIGIN]))

    # B's widget token only ever reaches B's own (open) conversation.
    assert (await client.post(f"{WIDGET_CONVERSATION}/reopen", headers=b_session.headers)).status_code == 409
    resp = await client.patch(
        f"/api/v1/tickets/{ticket_id}", json={"status": "awaiting_review"}, headers=b.headers
    )
    assert resp.status_code == 404
    assert (await detail(client, a, ticket_id))["status"] == "resolved"
    assert await rows(app_role_engine, b.workspace_id, "SELECT * FROM audit_events") == []
