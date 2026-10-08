"""Widget routing: classify every customer message, then small talk, ticket or RAG answer."""

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine

from app.ai.decisions import (
    ContextMessage,
    DecisionError,
    FakeDecisionClient,
    get_decision_client,
)
from app.ai.decisions import fake_classification as clf
from app.core.config import get_settings
from app.modules.conversations.chat import FALLBACK_MESSAGE, HANDOFF_MESSAGE, SMALL_TALK_REPLIES
from tests.conftest import SHOP_ORIGIN, WidgetSession, open_widget, signup, widget_key
from tests.test_widget import ask, ready_chunk, rows, use_llm

HACKED = "Hi, my account was hacked and money was taken"


@pytest.fixture(autouse=True)
def no_dev_localhost(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "widget_dev_allow_localhost", False)


def use_decider(app: FastAPI, rules: dict, default=None) -> FakeDecisionClient:
    decider = FakeDecisionClient(rules, default)
    app.dependency_overrides[get_decision_client] = lambda: decider
    return decider


async def session_for(client: AsyncClient, email: str = "owner@example.com"):
    owner = await signup(client, email)
    return owner, await open_widget(client, await widget_key(client, owner, [SHOP_ORIGIN]))


async def conversation_row(engine: AsyncEngine, owner, session: WidgetSession) -> dict:
    [row] = await rows(
        engine, owner.workspace_id, f"SELECT * FROM conversations WHERE id = '{session.conversation_id}'"
    )
    return row


async def test_greeting_gets_small_talk_without_retrieval_llm_or_ticket(
    app: FastAPI, client: AsyncClient, app_role_engine: AsyncEngine
) -> None:
    owner, session = await session_for(client)
    llm = use_llm(app, "should not be used [S1]")
    use_decider(app, {"hello": clf("greeting", confidence=0.95)})

    events = await ask(client, session, "Hello there!")

    assert [name for name, _ in events] == ["final"]
    final = events[0][1]
    assert final["content"] in SMALL_TALK_REPLIES["greeting"]
    assert final["route"] == "small_talk"
    assert final["grounded"] is None
    assert llm.calls == 0
    calls = await rows(app_role_engine, owner.workspace_id, "SELECT purpose FROM llm_calls")
    assert calls == []  # no query embedding either: retrieval never ran
    assert await rows(app_role_engine, owner.workspace_id, "SELECT * FROM tickets") == []
    assert (await conversation_row(app_role_engine, owner, session))["status"] == "open"

    [customer] = await rows(
        app_role_engine, owner.workspace_id, "SELECT * FROM messages WHERE role = 'customer'"
    )
    assert customer["classification"]["intent"] == "greeting"
    assert customer["classification"]["provider"] == "fake"


async def test_thanks_gets_small_talk(app: FastAPI, client: AsyncClient) -> None:
    _, session = await session_for(client)
    use_decider(app, {"thank": clf("thanks")})
    final = (await ask(client, session, "Thank you so much"))[-1][1]
    assert final["content"] in SMALL_TALK_REPLIES["thanks"]


@pytest.mark.parametrize(
    "classification",
    [
        clf("greeting", priority="urgent", needs_human=0.3, confidence=0.9),
        clf("greeting", priority="high", needs_human=0.2, confidence=0.9),
        clf("greeting", priority="normal", needs_human=0.85, confidence=0.9),
    ],
    ids=["urgent-priority", "high-priority", "needs-human"],
)
async def test_greeting_with_a_serious_request_opens_a_ticket(
    app: FastAPI, client: AsyncClient, app_role_engine: AsyncEngine, classification
) -> None:
    owner, session = await session_for(client)
    llm = use_llm(app, "unused")
    use_decider(app, {"hacked": classification})

    final = (await ask(client, session, HACKED))[-1][1]

    assert final["content"] == HANDOFF_MESSAGE
    assert final["route"] == "handoff"
    assert llm.calls == 0
    [ticket] = await rows(app_role_engine, owner.workspace_id, "SELECT * FROM tickets")
    assert ticket["subject"] == HACKED
    assert ticket["priority"] == classification.priority
    assert ticket["status"] == "new"
    assert ticket["source"] == "widget"
    conversation = await conversation_row(app_role_engine, owner, session)
    assert conversation["status"] == "needs_human"
    assert conversation["ticket_id"] == ticket["id"]


@pytest.mark.parametrize(
    ("message", "classification"),
    [
        ("I want a refund for order RA-10423", clf("refund_request", priority="high")),
        ("This is the worst service ever", clf("complaint", priority="normal")),
        ("Where is my parcel?", clf("order_status", priority="normal")),
        ("Please change my email address", clf("account_change", priority="normal")),
        ("Something odd", clf("other", priority="low", needs_human=0.75, confidence=0.4)),
    ],
    ids=["refund", "complaint", "order-status", "account-change", "high-needs-human"],
)
async def test_handoff_intents_create_a_ticket_without_llm(
    app: FastAPI, client: AsyncClient, app_role_engine: AsyncEngine, message, classification
) -> None:
    owner, session = await session_for(client)
    llm = use_llm(app, "unused [S1]")
    use_decider(app, {}, default=classification)

    final = (await ask(client, session, message))[-1][1]

    assert final["route"] == "handoff"
    assert final["content"] == HANDOFF_MESSAGE
    assert llm.calls == 0
    [ticket] = await rows(app_role_engine, owner.workspace_id, "SELECT * FROM tickets")
    assert (ticket["intent"], ticket["priority"]) == (classification.intent, classification.priority)
    assert ticket["classification"]["needs_human_prob"] == classification.needs_human_prob
    assert ticket["confidence"] == classification.confidence
    assert (await conversation_row(app_role_engine, owner, session))["status"] == "needs_human"

    # The handoff chip survives a reload.
    messages = (
        await client.get("/api/v1/widget/conversation", headers=session.headers)
    ).json()["messages"]
    assert messages[-1]["route"] == "handoff"
    assert "classification" not in messages[0]  # internal: never sent to the widget


async def test_knowledge_question_gets_rag_answer_and_no_ticket(
    app: FastAPI,
    client: AsyncClient,
    worker_ctx: dict,
    owner_engine: AsyncEngine,
    app_role_engine: AsyncEngine,
) -> None:
    owner, session = await session_for(client)
    chunk = await ready_chunk(client, worker_ctx, owner, owner_engine)
    llm = use_llm(app, "Returns are accepted within 30 days [S1].")
    use_decider(app, {}, default=clf("knowledge_question"))

    final = (await ask(client, session, chunk))[-1][1]

    assert final["route"] == "answer"
    assert final["grounded"] is True
    assert llm.calls == 1
    assert await rows(app_role_engine, owner.workspace_id, "SELECT * FROM tickets") == []


async def test_low_confidence_is_treated_as_knowledge_question(
    app: FastAPI,
    client: AsyncClient,
    worker_ctx: dict,
    owner_engine: AsyncEngine,
    app_role_engine: AsyncEngine,
) -> None:
    owner, session = await session_for(client)
    chunk = await ready_chunk(client, worker_ctx, owner, owner_engine)
    llm = use_llm(app, "Within 30 days [S1].")
    use_decider(app, {}, default=clf("refund_request", confidence=0.45, needs_human=0.3))

    final = (await ask(client, session, chunk))[-1][1]

    assert final["route"] == "answer"
    assert llm.calls == 1
    assert await rows(app_role_engine, owner.workspace_id, "SELECT * FROM tickets") == []


async def test_rag_fallback_creates_a_ticket(
    app: FastAPI, client: AsyncClient, app_role_engine: AsyncEngine
) -> None:
    owner, session = await session_for(client)
    use_llm(app, "unused")
    use_decider(app, {}, default=clf("knowledge_question", priority="low"))

    final = (await ask(client, session, "Do you ship to the moon?"))[-1][1]

    assert final["content"] == FALLBACK_MESSAGE
    assert final["route"] == "fallback"
    [ticket] = await rows(app_role_engine, owner.workspace_id, "SELECT * FROM tickets")
    assert (ticket["intent"], ticket["priority"]) == ("knowledge_question", "low")
    assert ticket["subject"] == "Do you ship to the moon?"
    conversation = await conversation_row(app_role_engine, owner, session)
    assert (conversation["status"], conversation["ticket_id"]) == ("needs_human", ticket["id"])


async def test_open_ticket_is_reused_and_priority_only_rises(
    app: FastAPI, client: AsyncClient, app_role_engine: AsyncEngine
) -> None:
    owner, session = await session_for(client)
    use_llm(app, "unused")
    use_decider(
        app,
        {
            "refund": clf("refund_request", priority="normal"),
            "lawyer": clf("complaint", priority="urgent"),
            "again": clf("complaint", priority="low"),
        },
    )
    await ask(client, session, "I want a refund")
    await ask(client, session, "My lawyer will hear about this")
    await ask(client, session, "Asking again")

    [ticket] = await rows(app_role_engine, owner.workspace_id, "SELECT * FROM tickets")
    assert ticket["priority"] == "urgent"
    assert ticket["subject"] == "I want a refund"


async def test_classifier_sees_only_the_two_previous_messages(
    app: FastAPI, client: AsyncClient
) -> None:
    _, session = await session_for(client)
    use_llm(app, "unused")
    decider = use_decider(app, {"hello": clf("greeting")})
    await ask(client, session, "hello")
    await ask(client, session, "hello again")

    text, context = decider.calls[-1]
    assert text == "hello again"
    assert len(context) == 2
    assert [m.role for m in context] == ["customer", "assistant"]
    assert all(isinstance(m, ContextMessage) for m in context)


async def test_classifier_outage_falls_back_to_knowledge_answer(
    app: FastAPI, client: AsyncClient, app_role_engine: AsyncEngine
) -> None:
    owner, session = await session_for(client)
    use_llm(app, "unused")

    class Broken(FakeDecisionClient):
        async def classify(self, text, context, *, workspace_id):  # type: ignore[no-untyped-def]
            raise DecisionError("down")

    app.dependency_overrides[get_decision_client] = lambda: Broken()
    final = (await ask(client, session, "Do you ship to the moon?"))[-1][1]

    # No sources either, so the usual fallback: ticket without a classification.
    assert final["route"] == "fallback"
    [ticket] = await rows(app_role_engine, owner.workspace_id, "SELECT * FROM tickets")
    assert ticket["intent"] == "other"
    assert ticket["classification"] is None


async def test_budget_exhausted_opens_ticket_without_classifying(
    app: FastAPI, client: AsyncClient, app_role_engine: AsyncEngine, limiter
) -> None:
    owner, session = await session_for(client)
    decider = use_decider(app, {})
    limiter.tokens[owner.workspace_id] = get_settings().widget_daily_token_budget

    final = (await ask(client, session, "hello"))[-1][1]

    assert final["route"] == "fallback"
    assert decider.calls == []
    assert len(await rows(app_role_engine, owner.workspace_id, "SELECT * FROM tickets")) == 1
