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
from app.modules.conversations.chat import (
    CLARIFY_MESSAGE,
    FALLBACK_MESSAGE,
    FALLBACK_OFFER,
    HANDOFF_MESSAGE,
    SMALL_TALK_REPLIES,
    OfferReply,
    Route,
    decide_route,
    is_low_content,
    offer_reply,
)
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
    assert ticket["intent"] == "other"  # never "greeting"; nothing else in the conversation
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
        ("Please change my email address", clf("account_change", priority="normal")),
        ("Something odd", clf("other", priority="low", needs_human=0.75, confidence=0.4)),
    ],
    ids=["refund", "complaint", "account-change", "high-needs-human"],
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


async def test_unknown_question_offers_a_teammate_without_a_ticket(
    app: FastAPI, client: AsyncClient, app_role_engine: AsyncEngine, job_queue
) -> None:
    owner, session = await session_for(client)
    use_llm(app, "unused")
    use_decider(app, {}, default=clf("knowledge_question", priority="low"))

    final = (await ask(client, session, "Do you ship to the moon?"))[-1][1]

    assert final["content"] == FALLBACK_OFFER
    assert final["route"] == "fallback"
    assert final["grounded"] is False
    assert await rows(app_role_engine, owner.workspace_id, "SELECT * FROM tickets") == []
    assert job_queue.drafts == []
    conversation = await conversation_row(app_role_engine, owner, session)
    assert (conversation["status"], conversation["ticket_id"]) == ("open", None)


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

    # No sources either, so the usual fallback: an offer, no ticket.
    assert final["route"] == "fallback"
    assert final["content"] == FALLBACK_OFFER
    assert await rows(app_role_engine, owner.workspace_id, "SELECT * FROM tickets") == []


async def test_budget_exhausted_opens_ticket_without_classifying(
    app: FastAPI, client: AsyncClient, app_role_engine: AsyncEngine, limiter
) -> None:
    owner, session = await session_for(client)
    decider = use_decider(app, {})
    limiter.tokens[owner.workspace_id] = get_settings().widget_daily_token_budget

    final = (await ask(client, session, "hello"))[-1][1]

    assert final["route"] == "fallback"
    assert final["content"] == FALLBACK_MESSAGE  # no budget to follow up on an offer
    assert decider.calls == []
    [ticket] = await rows(app_role_engine, owner.workspace_id, "SELECT * FROM tickets")
    assert (ticket["intent"], ticket["classification"]) == ("other", None)


# Low-content messages and the fallback offer ------------------------------------------------

# The real classification of "Nothing" from the dashboard review: greeting, low confidence.
NOTHING = clf("greeting", priority="low", confidence=0.46, needs_human=0.1)
MOON = "Do you ship to the moon?"


@pytest.mark.parametrize(
    ("text", "classification", "expected"),
    [
        ("Nothing", NOTHING, True),
        ("ok", clf("thanks", confidence=0.5), True),
        ("test", clf("other", confidence=0.3), True),
        ("shipping", clf("knowledge_question", confidence=0.4), False),
        ("returns?", clf("other", confidence=0.3), False),
        ("RA-10423", clf("other", confidence=0.3), False),
        ("I need help with something", clf("other", confidence=0.3), False),
        ("nothing", None, False),
    ],
)
def test_low_content_is_conservative(text: str, classification, expected: bool) -> None:
    assert is_low_content(text, classification) is expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("yes please", OfferReply.YES),
        ("Yeah, that would help", OfferReply.YES),
        ("ok", OfferReply.YES),
        ("sure", OfferReply.YES),
        ("no thanks", OfferReply.NO),
        ("nope", OfferReply.NO),
        ("yes, but do you ship to Mars?", OfferReply.OTHER),
        ("what about the return policy", OfferReply.OTHER),
        ("yesterday my parcel arrived broken and nobody answered my emails", OfferReply.OTHER),
    ],
)
def test_offer_reply(text: str, expected: OfferReply) -> None:
    assert offer_reply(text) is expected


async def test_nothing_gets_a_clarifying_reply_without_search_or_ticket(
    app: FastAPI, client: AsyncClient, app_role_engine: AsyncEngine
) -> None:
    owner, session = await session_for(client)
    llm = use_llm(app, "should not be used [S1]")
    use_decider(app, {"nothing": NOTHING})

    events = await ask(client, session, "Nothing")

    assert [name for name, _ in events] == ["final"]
    final = events[0][1]
    assert (final["content"], final["route"]) == (CLARIFY_MESSAGE, "small_talk")
    assert llm.calls == 0
    # No query embedding: the knowledge search never ran.
    assert await rows(app_role_engine, owner.workspace_id, "SELECT * FROM llm_calls") == []
    assert await rows(app_role_engine, owner.workspace_id, "SELECT * FROM tickets") == []
    assert (await conversation_row(app_role_engine, owner, session))["status"] == "open"


async def test_yes_after_the_offer_hands_off_through_the_tool(
    app: FastAPI, client: AsyncClient, app_role_engine: AsyncEngine, job_queue
) -> None:
    owner, session = await session_for(client)
    llm = use_llm(app, "unused")
    use_decider(
        app,
        {"yes please": clf("thanks", confidence=0.7)},
        default=clf("knowledge_question", priority="low"),
    )
    assert (await ask(client, session, MOON))[-1][1]["content"] == FALLBACK_OFFER

    events = await ask(client, session, "yes please")

    assert ("status", {"text": "Passing this to the team…", "tool": "hand_off_to_team"}) in events
    final = events[-1][1]
    assert (final["content"], final["route"]) == (HANDOFF_MESSAGE, "handoff")
    assert final["tools_used"] == ["hand_off_to_team"]
    assert llm.calls == 0
    [logged] = await rows(app_role_engine, owner.workspace_id, "SELECT * FROM tool_calls")
    assert (logged["tool_name"], logged["status"]) == ("hand_off_to_team", "ok")
    assert logged["conversation_id"] == session.conversation_id
    # The ticket is about the question, not the "yes" (whose intent was thanks).
    [ticket] = await rows(app_role_engine, owner.workspace_id, "SELECT * FROM tickets")
    assert ticket["subject"] == MOON
    assert (ticket["intent"], ticket["priority"]) == ("knowledge_question", "low")
    assert job_queue.drafts == [(ticket["id"], owner.workspace_id, False)]
    conversation = await conversation_row(app_role_engine, owner, session)
    assert (conversation["status"], conversation["ticket_id"]) == ("needs_human", ticket["id"])


async def test_no_after_the_offer_gets_a_clarifying_reply(
    app: FastAPI, client: AsyncClient, app_role_engine: AsyncEngine
) -> None:
    owner, session = await session_for(client)
    use_llm(app, "unused")
    use_decider(app, {"no thanks": clf("thanks", confidence=0.9)})
    await ask(client, session, MOON)

    final = (await ask(client, session, "no thanks"))[-1][1]

    assert (final["content"], final["route"]) == (CLARIFY_MESSAGE, "small_talk")
    assert await rows(app_role_engine, owner.workspace_id, "SELECT * FROM tickets") == []


async def test_refund_request_still_opens_a_ticket_immediately(
    app: FastAPI, client: AsyncClient, app_role_engine: AsyncEngine
) -> None:
    owner, session = await session_for(client)
    use_llm(app, "unused")
    use_decider(app, {"refund": clf("refund_request", priority="high")})
    await ask(client, session, MOON)  # an offer first: a request is never read as a yes/no

    final = (await ask(client, session, "Ok, then I want a refund for my order"))[-1][1]

    assert (final["content"], final["route"]) == (HANDOFF_MESSAGE, "handoff")
    assert final["tools_used"] == []
    [ticket] = await rows(app_role_engine, owner.workspace_id, "SELECT * FROM tickets")
    assert (ticket["intent"], ticket["priority"]) == ("refund_request", "high")


async def test_offered_fallback_is_still_a_knowledge_gap(
    app: FastAPI, client: AsyncClient, app_role_engine: AsyncEngine
) -> None:
    owner, session = await session_for(client)
    use_llm(app, "unused")
    use_decider(app, {})
    await ask(client, session, MOON)

    [reply] = await rows(
        app_role_engine, owner.workspace_id, "SELECT * FROM messages WHERE role = 'assistant'"
    )
    assert (reply["route"], reply["fallback_reason"]) == ("fallback", "no_sources")
    gaps = (
        await client.get(
            "/api/v1/analytics/knowledge-gaps", params={"days": 7}, headers=owner.headers
        )
    ).json()
    assert [(g["question"], g["count"]) for g in gaps["gaps"]] == [(MOON, 1)]
    overview = (
        await client.get("/api/v1/analytics/overview", params={"days": 7}, headers=owner.headers)
    ).json()["conversations"]
    assert (overview["fallback_ended"], overview["handed_off"]) == (1, 0)


async def test_greeting_triggered_ticket_takes_the_conversations_real_intent(
    app: FastAPI, client: AsyncClient, app_role_engine: AsyncEngine
) -> None:
    owner, session = await session_for(client)
    use_llm(app, "unused")
    use_decider(
        app,
        {
            # Below the confidence threshold: answered from knowledge (an offer), no ticket.
            "broken": clf("complaint", confidence=0.5),
            "hacked": clf("greeting", priority="urgent", needs_human=0.3, confidence=0.9),
        },
    )
    await ask(client, session, "My parcel arrived broken")

    await ask(client, session, HACKED)

    [ticket] = await rows(app_role_engine, owner.workspace_id, "SELECT * FROM tickets")
    assert (ticket["intent"], ticket["priority"]) == ("complaint", "urgent")


async def test_off_topic_gets_a_short_redirect_and_no_ticket(
    app: FastAPI, client: AsyncClient, app_role_engine: AsyncEngine
) -> None:
    owner, session = await session_for(client)
    llm = use_llm(app, "Mukesh Ambani is a businessman [S1]")
    use_decider(app, {}, default=clf("off_topic", priority="low", confidence=0.9))

    final = (await ask(client, session, "who is Ambani?"))[-1][1]

    assert final["route"] == "small_talk"
    assert final["content"] in SMALL_TALK_REPLIES["off_topic"]
    assert llm.calls == 0
    assert await rows(app_role_engine, owner.workspace_id, "SELECT * FROM tickets") == []


async def test_account_security_hands_off_even_with_low_confidence(
    app: FastAPI, client: AsyncClient, app_role_engine: AsyncEngine
) -> None:
    owner, session = await session_for(client)
    llm = use_llm(app, "unused [S1]")
    use_decider(
        app, {}, default=clf("account_security", priority="high", needs_human=0.95, confidence=0.4)
    )

    final = (await ask(client, session, "I can't get my 2FA code"))[-1][1]

    assert final["route"] == "handoff"
    assert llm.calls == 0
    [ticket] = await rows(app_role_engine, owner.workspace_id, "SELECT * FROM tickets")
    assert (ticket["intent"], ticket["priority"]) == ("account_security", "high")


@pytest.mark.parametrize(
    ("classification", "previous", "expected"),
    [
        (clf("account_security", confidence=0.3, needs_human=0.1), None, Route.HANDOFF),
        (clf("account_security", confidence=0.9), "agent", Route.HANDOFF),
        (clf("off_topic", priority="low", confidence=0.9), None, Route.SMALL_TALK),
        (clf("off_topic", priority="low", confidence=0.4), None, Route.KNOWLEDGE),
        (clf("off_topic", priority="low", confidence=0.9, needs_human=0.9), None, Route.HANDOFF),
    ],
    ids=["security-low-confidence", "security-follow-up", "off-topic", "off-topic-unsure", "off-topic-needs-human"],
)
def test_new_intent_routes(classification, previous, expected: Route) -> None:
    assert decide_route(classification, previous) is expected
