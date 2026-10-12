"""Draft review: edit, approve & send into the customer's chat, reject, "Write reply", the
ticket reopening on a new customer message, and the widget polling for team replies."""

import asyncio
import uuid

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine

from app.ai.decisions import FakeDecisionClient, get_decision_client
from app.ai.decisions import fake_classification as clf
from app.ai.llm import FakeLLMClient, fake_text
from app.core.config import get_settings
from app.workers.drafting import process_ticket
from tests.conftest import (
    SHOP_ORIGIN,
    InMemoryLimiter,
    RecordingQueue,
    SignedUp,
    WidgetSession,
    open_widget,
    signup,
    widget_key,
)
from tests.test_widget import ask, rows, use_llm

DRAFT = "Sorry about that! A teammate is reviewing your refund request and will follow up here."
EDITED = "Sorry about that! I've passed your refund request to our billing team."
WIDGET_CONVERSATION = "/api/v1/widget/conversation"


@pytest.fixture(autouse=True)
def setup(app: FastAPI, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "widget_dev_allow_localhost", False)
    decider = FakeDecisionClient(
        {"refund": clf("refund_request", priority="high")}, default=clf("knowledge_question")
    )
    app.dependency_overrides[get_decision_client] = lambda: decider
    use_llm(app, "unused")


async def chat_ticket(
    client: AsyncClient, owner: SignedUp, worker_ctx: dict
) -> tuple[WidgetSession, str]:
    """A widget conversation handed off as a ticket, with a pending AI draft."""
    session = await open_widget(client, await widget_key(client, owner, [SHOP_ORIGIN]))
    final = (await ask(client, session, "I want a refund for my order"))[-1][1]
    assert final["route"] == "handoff"
    tickets = (await client.get("/api/v1/tickets", headers=owner.headers)).json()["items"]
    ticket_id = tickets[0]["id"]
    llm = FakeLLMClient(script=[fake_text(DRAFT)])
    assert await process_ticket({**worker_ctx, "llm": llm}, ticket_id, str(owner.workspace_id)) == "drafted"
    return session, ticket_id


async def detail(client: AsyncClient, user: SignedUp, ticket_id: str) -> dict:
    resp = await client.get(f"/api/v1/tickets/{ticket_id}", headers=user.headers)
    assert resp.status_code == 200, resp.text
    return resp.json()


def drafts_url(ticket_id: str, draft_id: str | None = None) -> str:
    base = f"/api/v1/tickets/{ticket_id}/drafts"
    return f"{base}/{draft_id}" if draft_id else base


async def test_approve_and_send_posts_the_draft_into_the_chat(
    client: AsyncClient, worker_ctx: dict, app_role_engine: AsyncEngine
) -> None:
    owner = await signup(client, "owner@example.com", full_name="Dana Owner")
    session, ticket_id = await chat_ticket(client, owner, worker_ctx)
    draft = (await detail(client, owner, ticket_id))["draft"]
    assert (draft["status"], draft["author_type"]) == ("pending", "ai")
    assert draft["original_content"] == DRAFT

    resp = await client.post(
        f"{drafts_url(ticket_id, draft['id'])}/send", json={}, headers=owner.headers
    )

    assert resp.status_code == 200, resp.text
    ticket = resp.json()
    assert ticket["status"] == "replied"
    sent = ticket["draft"]
    assert sent["status"] == "sent"
    assert sent["content"] == sent["original_content"] == DRAFT
    assert sent["reviewed_by"] == str(owner.user_id) and sent["sent_at"]
    # The customer sees it in the widget, as a team reply.
    widget = (await client.get(WIDGET_CONVERSATION, headers=session.headers)).json()
    assert (widget["messages"][-1]["role"], widget["messages"][-1]["content"]) == ("agent", DRAFT)
    # The Inbox transcript says it came unchanged from an AI draft, and who sent it.
    last = ticket["conversation"]["messages"][-1]
    assert (last["role"], last["authored_by"], last["author_name"]) == (
        "agent",
        "ai_draft",
        "Dana Owner",
    )
    [message] = await rows(
        app_role_engine, owner.workspace_id, "SELECT * FROM messages WHERE role = 'agent'"
    )
    assert str(message["draft_id"]) == draft["id"]
    assert message["author_id"] == owner.user_id
    actions = [e["action"] for e in ticket["activity"]]
    assert actions[-3:] == ["draft.approved", "draft.sent", "ticket.status_changed"]

    # Sending again (a double click, a retry) doesn't post a second message.
    again = await client.post(
        f"{drafts_url(ticket_id, draft['id'])}/send", json={}, headers=owner.headers
    )
    assert again.status_code == 409
    agent_messages = await rows(
        app_role_engine, owner.workspace_id, "SELECT id FROM messages WHERE role = 'agent'"
    )
    assert len(agent_messages) == 1


async def test_concurrent_sends_post_one_message(
    client: AsyncClient, worker_ctx: dict, app_role_engine: AsyncEngine
) -> None:
    owner = await signup(client, "owner@example.com")
    _, ticket_id = await chat_ticket(client, owner, worker_ctx)
    draft_id = (await detail(client, owner, ticket_id))["draft"]["id"]
    url = f"{drafts_url(ticket_id, draft_id)}/send"

    first, second = await asyncio.gather(
        client.post(url, json={}, headers=owner.headers),
        client.post(url, json={}, headers=owner.headers),
    )

    assert sorted([first.status_code, second.status_code]) == [200, 409]
    agent_messages = await rows(
        app_role_engine, owner.workspace_id, "SELECT id FROM messages WHERE role = 'agent'"
    )
    assert len(agent_messages) == 1


async def test_edit_then_send_keeps_the_original_and_marks_it_edited(
    client: AsyncClient, worker_ctx: dict
) -> None:
    owner = await signup(client, "owner@example.com")
    session, ticket_id = await chat_ticket(client, owner, worker_ctx)
    draft_id = (await detail(client, owner, ticket_id))["draft"]["id"]

    edited = await client.patch(
        drafts_url(ticket_id, draft_id), json={"content": f"  {EDITED}  "}, headers=owner.headers
    )
    assert edited.status_code == 200, edited.text
    assert edited.json()["draft"]["status"] == "edited"
    assert edited.json()["draft"]["content"] == EDITED

    resp = await client.post(
        f"{drafts_url(ticket_id, draft_id)}/send", json={}, headers=owner.headers
    )

    assert resp.status_code == 200, resp.text
    sent = resp.json()["draft"]
    assert (sent["status"], sent["content"], sent["original_content"]) == ("sent", EDITED, DRAFT)
    assert resp.json()["conversation"]["messages"][-1]["authored_by"] == "ai_draft_edited"
    widget = (await client.get(WIDGET_CONVERSATION, headers=session.headers)).json()
    assert widget["messages"][-1]["content"] == EDITED
    sent_event = next(e for e in resp.json()["activity"] if e["action"] == "draft.sent")
    assert sent_event["after"]["edited"] is True
    # Audit summaries carry sizes, never the text itself.
    assert all(EDITED not in str(e) and DRAFT not in str(e) for e in resp.json()["activity"])


async def test_send_with_content_saves_the_edit_in_the_same_step(
    client: AsyncClient, worker_ctx: dict
) -> None:
    owner = await signup(client, "owner@example.com")
    _, ticket_id = await chat_ticket(client, owner, worker_ctx)
    draft_id = (await detail(client, owner, ticket_id))["draft"]["id"]

    resp = await client.post(
        f"{drafts_url(ticket_id, draft_id)}/send", json={"content": EDITED}, headers=owner.headers
    )

    assert resp.status_code == 200, resp.text
    assert resp.json()["draft"]["content"] == EDITED
    actions = [e["action"] for e in resp.json()["activity"]]
    assert "draft.edited" in actions and "draft.approved" not in actions


async def test_reject_with_optional_reason(client: AsyncClient, worker_ctx: dict) -> None:
    owner = await signup(client, "owner@example.com")
    _, ticket_id = await chat_ticket(client, owner, worker_ctx)
    draft_id = (await detail(client, owner, ticket_id))["draft"]["id"]

    resp = await client.post(
        f"{drafts_url(ticket_id, draft_id)}/reject",
        json={"reason": "Wrong tone"},
        headers=owner.headers,
    )

    assert resp.status_code == 200, resp.text
    ticket = resp.json()
    assert ticket["draft"]["status"] == "rejected"
    assert ticket["draft"]["rejection_reason"] == "Wrong tone"
    assert ticket["status"] == "awaiting_review"
    [event] = [e for e in ticket["activity"] if e["action"] == "draft.rejected"]
    assert event["after"]["reason"] == "Wrong tone"
    assert (event["actor_type"], event["actor_id"]) == ("user", str(owner.user_id))
    # A rejected draft can't be sent, and a reason isn't required.
    send = await client.post(f"{drafts_url(ticket_id, draft_id)}/send", json={}, headers=owner.headers)
    assert send.status_code == 409


async def test_reject_without_a_reason(client: AsyncClient, worker_ctx: dict) -> None:
    owner = await signup(client, "owner@example.com")
    _, ticket_id = await chat_ticket(client, owner, worker_ctx)
    draft_id = (await detail(client, owner, ticket_id))["draft"]["id"]
    resp = await client.post(
        f"{drafts_url(ticket_id, draft_id)}/reject", json={}, headers=owner.headers
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["draft"]["rejection_reason"] is None


async def test_write_reply_starts_a_blank_human_draft_and_sends_it(
    client: AsyncClient, worker_ctx: dict, app_role_engine: AsyncEngine
) -> None:
    owner = await signup(client, "owner@example.com")
    session, ticket_id = await chat_ticket(client, owner, worker_ctx)
    ai_draft_id = (await detail(client, owner, ticket_id))["draft"]["id"]

    created = await client.post(drafts_url(ticket_id), json={}, headers=owner.headers)

    assert created.status_code == 201, created.text
    draft = created.json()["draft"]
    assert draft["id"] != ai_draft_id
    assert (draft["author_type"], draft["original_content"], draft["content"]) == ("human", "", "")
    # An empty reply can't be sent.
    empty = await client.post(f"{drafts_url(ticket_id, draft['id'])}/send", json={}, headers=owner.headers)
    assert empty.status_code == 422

    resp = await client.post(
        f"{drafts_url(ticket_id, draft['id'])}/send",
        json={"content": "Hi! I've checked your order myself."},
        headers=owner.headers,
    )

    assert resp.status_code == 200, resp.text
    assert resp.json()["conversation"]["messages"][-1]["authored_by"] == "human"
    widget = (await client.get(WIDGET_CONVERSATION, headers=session.headers)).json()
    assert widget["messages"][-1]["content"] == "Hi! I've checked your order myself."
    # The AI draft it replaced is kept, but superseded.
    [old] = await rows(
        app_role_engine, owner.workspace_id, f"SELECT status FROM reply_drafts WHERE id = '{ai_draft_id}'"
    )
    assert old["status"] == "superseded"


async def test_drafting_job_leaves_a_reply_being_written_alone(
    client: AsyncClient, worker_ctx: dict
) -> None:
    owner = await signup(client, "owner@example.com")
    _, ticket_id = await chat_ticket(client, owner, worker_ctx)
    created = await client.post(
        drafts_url(ticket_id), json={"content": "Working on it"}, headers=owner.headers
    )
    human_id = created.json()["draft"]["id"]

    llm = FakeLLMClient(script=[fake_text("A new AI draft")])
    result = await process_ticket({**worker_ctx, "llm": llm}, ticket_id, str(owner.workspace_id))

    assert result == "being_edited"
    assert (await detail(client, owner, ticket_id))["draft"]["id"] == human_id


async def test_manual_ticket_without_chat_cannot_be_sent(
    client: AsyncClient, worker_ctx: dict
) -> None:
    owner = await signup(client, "owner@example.com")
    resp = await client.post(
        "/api/v1/tickets",
        json={"subject": "Hello", "description": "Just checking in"},
        headers=owner.headers,
    )
    ticket_id = resp.json()["id"]
    llm = FakeLLMClient(script=[fake_text("Hi! Thanks for reaching out.")])
    await process_ticket({**worker_ctx, "llm": llm}, ticket_id, str(owner.workspace_id))
    draft_id = (await detail(client, owner, ticket_id))["draft"]["id"]

    send = await client.post(f"{drafts_url(ticket_id, draft_id)}/send", json={}, headers=owner.headers)

    assert send.status_code == 409
    assert "no chat" in send.json()["error"]["message"]


async def test_new_customer_message_reopens_a_replied_ticket(
    client: AsyncClient, worker_ctx: dict, job_queue: RecordingQueue
) -> None:
    owner = await signup(client, "owner@example.com")
    session, ticket_id = await chat_ticket(client, owner, worker_ctx)
    draft_id = (await detail(client, owner, ticket_id))["draft"]["id"]
    await client.post(f"{drafts_url(ticket_id, draft_id)}/send", json={}, headers=owner.headers)
    assert (await detail(client, owner, ticket_id))["status"] == "replied"
    job_queue.drafts.clear()

    await ask(client, session, "Actually, can I get the refund to a different card? refund")

    ticket = await detail(client, owner, ticket_id)
    assert ticket["status"] == "awaiting_review"
    assert (uuid.UUID(ticket_id), owner.workspace_id, False) in job_queue.drafts
    # Still one ticket for the conversation.
    tickets = (await client.get("/api/v1/tickets", headers=owner.headers)).json()["items"]
    assert [t["id"] for t in tickets] == [ticket_id]
    reopened = ticket["activity"][-1]
    assert (reopened["action"], reopened["actor_type"]) == ("ticket.status_changed", "system")
    assert reopened["before"] == {"status": "replied"}


async def test_widget_polls_only_new_messages_without_using_limits(
    client: AsyncClient, worker_ctx: dict, limiter: InMemoryLimiter
) -> None:
    owner = await signup(client, "owner@example.com")
    session, ticket_id = await chat_ticket(client, owner, worker_ctx)
    full = (await client.get(WIDGET_CONVERSATION, headers=session.headers)).json()
    newest = full["messages"][-1]["id"]
    hits, tokens = dict(limiter.hits), dict(limiter.tokens)

    nothing_new = await client.get(WIDGET_CONVERSATION, params={"after": newest}, headers=session.headers)
    assert nothing_new.status_code == 200
    assert nothing_new.json()["messages"] == []

    draft_id = (await detail(client, owner, ticket_id))["draft"]["id"]
    await client.post(f"{drafts_url(ticket_id, draft_id)}/send", json={}, headers=owner.headers)
    for _ in range(30):
        polled = await client.get(WIDGET_CONVERSATION, params={"after": newest}, headers=session.headers)
        assert polled.status_code == 200

    assert [(m["role"], m["content"]) for m in polled.json()["messages"]] == [("agent", DRAFT)]
    # Polling counts toward no rate limit and spends no tokens.
    assert (limiter.hits, limiter.tokens) == (hits, tokens)
    # An id from elsewhere falls back to the whole conversation, never another chat's messages.
    unknown = await client.get(
        WIDGET_CONVERSATION, params={"after": str(uuid.uuid4())}, headers=session.headers
    )
    assert len(unknown.json()["messages"]) == len(full["messages"]) + 1


async def test_draft_review_is_tenant_isolated(client: AsyncClient, worker_ctx: dict) -> None:
    a = await signup(client, "a@example.com", workspace_name="Tenant A")
    b = await signup(client, "b@example.com", workspace_name="Tenant B")
    _, ticket_id = await chat_ticket(client, a, worker_ctx)
    draft_id = (await detail(client, a, ticket_id))["draft"]["id"]

    for method, url, body in (
        ("POST", f"{drafts_url(ticket_id, draft_id)}/send", {}),
        ("POST", f"{drafts_url(ticket_id, draft_id)}/reject", {}),
        ("PATCH", drafts_url(ticket_id, draft_id), {"content": "hijacked"}),
        ("POST", drafts_url(ticket_id), {}),
    ):
        resp = await client.request(method, url, json=body, headers=b.headers)
        assert resp.status_code == 404, (url, resp.text)
    assert (await detail(client, a, ticket_id))["draft"]["status"] == "pending"
