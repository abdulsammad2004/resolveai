"""Handing widget conversations to the team: routing precedence after an agent reply, the
hand_off_to_team tool, the "contact support elsewhere" backstop, classifier context, and
the cancel_order rules for prompts and drafts."""

import dataclasses
import logging

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine

from app.ai.decisions import CONTEXT_CHARS, INTENTS, FakeDecisionClient, get_decision_client
from app.ai.decisions import fake_classification as clf
from app.ai.llm import FakeLLMClient, fake_text, fake_tool_call
from app.ai.prompts import load_prompt
from app.ai.tools.builtin import DRAFT_TOOLS, REGISTRY, WIDGET_TOOLS
from app.ai.tools.models import ToolCallStatus
from app.ai.tools.registry import Risk
from app.api.v1.widget import get_chat_llm
from app.core.config import get_settings
from app.modules.conversations.chat import (
    HANDOFF_MESSAGE,
    Route,
    decide_route,
    support_redirect,
)
from app.workers.drafting import process_ticket
from tests.conftest import SHOP_ORIGIN, RecordingQueue, open_widget, signup, widget_key
from tests.test_tools import ORDER, ORDER_EMAIL, context, seed_orders
from tests.test_widget import ask, ready_chunk, rows

ORDER_QUESTION = f"Where is my order {ORDER}? My email is {ORDER_EMAIL}"
SHIPPED = f"Your order {ORDER} has shipped with UPS."
OFFER = "It has already shipped, so I can't cancel it here. Would you like me to pass it along?"
CANCEL = "I want to cancel this order"
# The real classification of CANCEL from the bug report: right intent, low confidence.
LOW_CONFIDENCE_CANCEL = clf("cancel_order", priority="high", confidence=0.57, needs_human=0.48)


@pytest.fixture(autouse=True)
def decider(app: FastAPI, monkeypatch: pytest.MonkeyPatch) -> FakeDecisionClient:
    s = get_settings()
    monkeypatch.setattr(s, "widget_dev_allow_localhost", False)
    monkeypatch.setattr(s, "retrieval_min_score", -1.0)
    fake = FakeDecisionClient(
        {"where is my order": clf("order_status"), "cancel": LOW_CONFIDENCE_CANCEL},
        default=clf("other", confidence=0.08, needs_human=0.6),
    )
    app.dependency_overrides[get_decision_client] = lambda: fake
    return fake


def scripted(app: FastAPI, *turns) -> FakeLLMClient:
    llm = FakeLLMClient(script=list(turns))
    app.dependency_overrides[get_chat_llm] = lambda: llm
    return llm


async def shop(client: AsyncClient):
    owner = await signup(client, "owner@example.com")
    await seed_orders(client, owner)
    return owner, await open_widget(client, await widget_key(client, owner, [SHOP_ORIGIN]))


async def tickets(engine: AsyncEngine, owner) -> list[dict]:
    return await rows(engine, owner.workspace_id, "SELECT * FROM tickets")


# Routing ------------------------------------------------------------------------------------


def test_handoff_intents_include_cancel_order() -> None:
    assert "cancel_order" in INTENTS


@pytest.mark.parametrize("intent", ["cancel_order", "refund_request", "complaint", "account_change"])
def test_low_confidence_handoff_intent_after_agent_reply_hands_off(intent: str) -> None:
    c = clf(intent, confidence=0.57)
    assert decide_route(c, previous_route="agent") is Route.HANDOFF
    # Without an agent reply before it, the old rule stands: answered from knowledge.
    assert decide_route(c, previous_route=None) is Route.KNOWLEDGE


def test_only_the_top_intent_counts_after_agent_reply() -> None:
    # Chosen intent says refund, but the most probable one is a plain order question.
    c = dataclasses.replace(
        clf("refund_request", confidence=0.4),
        intent_probs={**{i: 0.0 for i in INTENTS}, "order_status": 0.6, "refund_request": 0.4},
    )
    assert decide_route(c, previous_route="agent") is Route.AGENT


async def test_cancel_request_after_order_answer_creates_a_ticket(
    app: FastAPI, client: AsyncClient, app_role_engine: AsyncEngine, job_queue: RecordingQueue
) -> None:
    owner, session = await shop(client)
    llm = scripted(app, fake_tool_call("get_order_status", {"order_number": ORDER, "email": ORDER_EMAIL}), fake_text(SHIPPED))
    assert (await ask(client, session, ORDER_QUESTION))[-1][1]["route"] == "agent"
    calls_before = len(llm.tool_requests)

    final = (await ask(client, session, CANCEL))[-1][1]

    assert final["route"] == "handoff"
    assert final["content"] == HANDOFF_MESSAGE
    assert len(llm.tool_requests) == calls_before  # the agent never answered it
    [ticket] = await tickets(app_role_engine, owner)
    assert (ticket["intent"], ticket["priority"]) == ("cancel_order", "high")
    assert job_queue.drafts == [(ticket["id"], owner.workspace_id, False)]


async def test_classifier_gets_the_last_three_messages_trimmed(
    app: FastAPI, client: AsyncClient, decider: FakeDecisionClient
) -> None:
    _, session = await shop(client)
    long_answer = SHIPPED + " " + "More details. " * 60
    scripted(app, fake_text(long_answer), fake_text("Anything else?"))
    await ask(client, session, ORDER_QUESTION)
    await ask(client, session, "thanks, and one more thing")

    await ask(client, session, "yes please")

    text, context_sent = decider.calls[-1]
    assert text == "yes please"
    assert [m.role for m in context_sent] == ["assistant", "customer", "assistant"]
    assert all(len(m.content) <= CONTEXT_CHARS for m in context_sent)
    assert context_sent[0].content == long_answer[:CONTEXT_CHARS]


# hand_off_to_team ---------------------------------------------------------------------------


def test_handoff_tool_is_widget_only_and_internal() -> None:
    tool = REGISTRY["hand_off_to_team"]
    assert tool.risk is Risk.INTERNAL
    assert tool in WIDGET_TOOLS
    assert tool not in DRAFT_TOOLS


async def test_yes_please_after_an_offer_hands_off(
    app: FastAPI, client: AsyncClient, app_role_engine: AsyncEngine, job_queue: RecordingQueue
) -> None:
    owner, session = await shop(client)
    llm = scripted(
        app,
        fake_text(OFFER),
        fake_tool_call("hand_off_to_team", {"reason": "Customer wants to cancel a shipped order"}),
        fake_text("Done. A teammate will review your request and follow up here."),
    )
    assert (await ask(client, session, ORDER_QUESTION))[-1][1]["route"] == "agent"  # the offer

    events = await ask(client, session, "yes please")  # also "other": back to the agent

    assert ("status", {"text": "Passing this to the team…", "tool": "hand_off_to_team"}) in events
    final = events[-1][1]
    assert final["route"] == "handoff"  # the "Passed to the team" chip
    assert final["content"] == "Done. A teammate will review your request and follow up here."
    assert final["tools_used"] == ["hand_off_to_team"]
    assert "hand_off_to_team" in llm.tool_requests[-1][1]
    [ticket] = await tickets(app_role_engine, owner)
    assert job_queue.drafts == [(ticket["id"], owner.workspace_id, False)]
    [logged] = await rows(app_role_engine, owner.workspace_id, "SELECT * FROM tool_calls")
    assert (logged["tool_name"], logged["status"]) == ("hand_off_to_team", "ok")
    reloaded = (await client.get("/api/v1/widget/conversation", headers=session.headers)).json()
    assert reloaded["messages"][-1]["route"] == "handoff"

    # Idempotent per conversation: a second handoff reuses the open ticket.
    scripted(
        app,
        fake_tool_call("hand_off_to_team", {"reason": "Customer added details"}),
        fake_text("Thanks, I've added that for the team."),
    )
    assert (await ask(client, session, ORDER_QUESTION))[-1][1]["route"] == "handoff"
    assert len(await tickets(app_role_engine, owner)) == 1


async def test_handoff_tool_needs_a_conversation(client: AsyncClient) -> None:
    from app.ai.tools.registry import run_tool

    owner = await signup(client, "owner@example.com")
    ctx = context(owner)
    call = fake_tool_call("hand_off_to_team", {"reason": "Needs a person"}).tool_calls[0]

    result = await run_tool(call, REGISTRY, ctx)

    assert result.status is ToolCallStatus.DENIED
    assert ctx.handoff_reason is None


# "Contact support elsewhere" backstop -------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "pattern"),
    [
        ("Please contact our support team for help with that.", "contact_support"),
        ("You can reach out to the customer service desk.", "contact_support"),
        ("Email support@shop.example and they'll sort it out.", "support_address"),
        ("Just call us at 555-0100.", "call_us"),
        ("A teammate will follow up here.", None),
        ("Our support team will reach out to you in this chat.", None),
        ("I've passed this to the team, they'll contact you here.", None),
    ],
)
def test_support_redirect_patterns_are_narrow(text: str, pattern: str | None) -> None:
    assert support_redirect(text) == pattern


async def test_agent_reply_sending_customer_elsewhere_becomes_a_handoff(
    app: FastAPI,
    client: AsyncClient,
    app_role_engine: AsyncEngine,
    caplog: pytest.LogCaptureFixture,
) -> None:
    owner, session = await shop(client)
    bad = "I can't forward the request from this chat. Please contact our support team."
    scripted(app, fake_text(bad))

    with caplog.at_level(logging.WARNING, logger="app.conversations.chat"):
        events = await ask(client, session, ORDER_QUESTION)

    final = events[-1][1]
    assert final["route"] == "handoff"
    assert final["content"] == HANDOFF_MESSAGE
    assert "contact our support" not in "".join(d.get("text", "") for _, d in events)
    assert len(await tickets(app_role_engine, owner)) == 1
    [record] = [r for r in caplog.records if "pointed the customer elsewhere" in r.getMessage()]
    message = record.getMessage()
    assert f"conversation_id={session.conversation_id}" in message
    assert "pattern=contact_support" in message
    assert "support team" not in message  # no reply text in the log


async def test_backstop_skips_cited_answers(
    app: FastAPI,
    client: AsyncClient,
    worker_ctx: dict,
    owner_engine: AsyncEngine,
    app_role_engine: AsyncEngine,
) -> None:
    owner, session = await shop(client)
    await ready_chunk(client, worker_ctx, owner, owner_engine)
    cited = "Returns are accepted within 30 days [S1]. Contact our support team with questions."
    scripted(app, fake_tool_call("search_knowledge", {"query": "returns"}), fake_text(cited))

    final = (await ask(client, session, ORDER_QUESTION))[-1][1]

    assert final["route"] == "agent"
    assert final["content"] == cited
    assert await tickets(app_role_engine, owner) == []


# Prompts and drafts -------------------------------------------------------------------------


def test_agent_v2_keeps_customers_in_this_chat() -> None:
    text = load_prompt("agent", "v2").text
    assert "Never tell the customer to contact support" in text
    assert "This chat is support" in text
    assert "hand_off_to_team" in text
    assert "Don't ask whether they want you to pass it on" in text
    # The prompt itself must not contain the pattern it forbids as advice.
    assert support_redirect(text.replace("Never tell the customer to contact support", "")) is None


def test_draft_v2_never_confirms_a_cancellation() -> None:
    text = load_prompt("draft", "v2").text
    assert "`cancel_order`, never say the order is or will be cancelled" in text
    assert "say only that the team will review the cancellation request" in text


async def test_cancel_order_draft_gets_the_intent_and_the_rule(
    client: AsyncClient, worker_ctx: dict
) -> None:
    owner = await signup(client, "owner@example.com")
    resp = await client.post(
        "/api/v1/tickets",
        json={"subject": "Cancel please", "description": "Please cancel order RA-10421"},
        headers=owner.headers,
    )
    assert resp.status_code == 201
    ticket = resp.json()
    assert ticket["intent"] == "cancel_order"
    llm = FakeLLMClient(
        script=[fake_text("Thanks! The team will review your cancellation request shortly.")]
    )

    result = await process_ticket(
        {**worker_ctx, "llm": llm}, ticket["id"], str(owner.workspace_id)
    )

    assert result == "drafted"
    messages, _ = llm.tool_requests[0]
    assert "`cancel_order`, never say the order is or will be cancelled" in messages[0]["content"]
    assert '<ticket subject="Cancel please" intent="cancel_order"' in messages[1]["content"]
