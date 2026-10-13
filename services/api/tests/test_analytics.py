"""Analytics: exact numbers on a small seeded dataset, the date range, knowledge-gap grouping
and masking, and tenant isolation (filters and RLS)."""

import datetime as dt
import uuid
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import insert
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from app.ai.usage import LLMCall
from app.core.deps import tenant_session
from app.modules.analytics import service
from app.modules.approvals.models import ActionRequest
from app.modules.audit.models import AuditEvent
from app.modules.conversations.models import Contact, Conversation, Feedback, Message
from app.modules.tickets.models import ReplyDraft, Ticket
from tests.conftest import SHOP_ORIGIN, InMemoryLimiter, open_widget, signup, widget_key
from tests.test_widget import ask, rows, settings, use_llm  # noqa: F401

OVERVIEW = "/api/v1/analytics/overview"
GAPS = "/api/v1/analytics/knowledge-gaps"

NOW = dt.datetime.now(dt.UTC)


def ago(**delta: float) -> dt.datetime:
    return NOW - dt.timedelta(**delta)


async def add(conn: AsyncConnection, entity: Any, /, **values: Any) -> uuid.UUID:
    values.setdefault("id", uuid.uuid4())
    await conn.execute(insert(entity.__table__).values(**values))
    return values["id"]


class Seeder:
    def __init__(self, conn: AsyncConnection, workspace_id: uuid.UUID) -> None:
        self.conn = conn
        self.wid = workspace_id

    async def conversation(
        self,
        exchanges: list[tuple[str, str, str | None]],
        *,
        at: dt.datetime,
        rating: str | None = None,
    ) -> uuid.UUID:
        """exchanges: (customer text, assistant route, fallback reason), one minute apart.
        `rating` rates the last assistant reply."""
        contact = await add(self.conn, Contact, workspace_id=self.wid, anonymous_id=uuid.uuid4().hex)
        conv = await add(
            self.conn,
            Conversation,
            workspace_id=self.wid,
            contact_id=contact,
            channel="widget",
            status="open",
            created_at=at,
            last_message_at=at if exchanges else None,
        )
        last_reply = None
        for i, (question, route, reason) in enumerate(exchanges):
            t = at + dt.timedelta(minutes=2 * i)
            await add(
                self.conn,
                Message,
                workspace_id=self.wid,
                conversation_id=conv,
                role="customer",
                content=question,
                created_at=t,
            )
            last_reply = await add(
                self.conn,
                Message,
                workspace_id=self.wid,
                conversation_id=conv,
                role="assistant",
                content="reply",
                route=route,
                fallback_reason=reason,
                created_at=t + dt.timedelta(minutes=1),
            )
        if rating and last_reply:
            await add(
                self.conn, Feedback, workspace_id=self.wid, message_id=last_reply, rating=rating
            )
        return conv

    async def ticket(
        self,
        *,
        intent: str,
        priority: str,
        at: dt.datetime,
        conversation_id: uuid.UUID | None = None,
        **extra: Any,
    ) -> uuid.UUID:
        return await add(
            self.conn,
            Ticket,
            workspace_id=self.wid,
            conversation_id=conversation_id,
            subject="Subject",
            intent=intent,
            priority=priority,
            status="triaged",
            source="widget" if conversation_id else "manual",
            created_at=at,
            **extra,
        )

    async def draft(self, ticket_id: uuid.UUID, status: str, original: str, content: str, **extra: Any) -> None:
        await add(
            self.conn,
            ReplyDraft,
            workspace_id=self.wid,
            ticket_id=ticket_id,
            status=status,
            original_content=original,
            content=content,
            **extra,
        )

    async def action(self, ticket_id: uuid.UUID, tool: str, status: str) -> None:
        await add(
            self.conn,
            ActionRequest,
            workspace_id=self.wid,
            ticket_id=ticket_id,
            tool_name=tool,
            arguments={},
            risk="sensitive",
            reason="r",
            status=status,
            idempotency_key=uuid.uuid4().hex,
        )

    async def llm(self, purpose: str, model: str, cost: str, *, at: dt.datetime | None = None, status: str = "ok") -> None:
        await add(
            self.conn,
            LLMCall,
            workspace_id=self.wid,
            purpose=purpose,
            provider="fake",
            model=model,
            input_tokens=100,
            output_tokens=10,
            cost_usd=cost,
            latency_ms=200,
            status=status,
            created_at=at or ago(hours=1),
        )


async def seed_workspace_a(conn: AsyncConnection, wid: uuid.UUID) -> None:
    s = Seeder(conn, wid)
    base = ago(hours=3)
    # Contained: answered without a ticket, and not rated down.
    await s.conversation([("What sizes do you have?", "answer", None)], at=base, rating="up")
    await s.conversation([("hi", "small_talk", None)], at=base)
    # Not contained: no ticket, but the last reply was rated down.
    await s.conversation([("Where is my order?", "agent", None)], at=base, rating="down")
    # Fell back, then handed off (a ticket): three questions the docs couldn't answer.
    c3 = await s.conversation(
        [
            ("Do you ship to Canada?", "fallback", "no_sources"),
            ("do you ship to canada", "fallback", "no_sources"),
            ("How do I reset my password? I'm bob@example.com, call +1 555 123 4567", "fallback", "not_grounded"),
        ],
        at=base,
    )
    c4 = await s.conversation([("I want a refund", "handoff", None)], at=base)
    # Fallback because the token budget ran out: not a knowledge gap, no ticket (seeded).
    await s.conversation([("What is the warranty?", "fallback", "budget")], at=base)
    # Outside a 7-day range, inside 30 days.
    await s.conversation([("Old question", "answer", None)], at=ago(days=10))
    # Never got a message: not counted.
    await s.conversation([], at=base)

    created = ago(hours=2)
    t1 = await s.ticket(
        intent="knowledge_question",
        priority="normal",
        at=created,
        conversation_id=c3,
        resolution_rating="up",
        resolution_rated_at=ago(minutes=5),
    )
    t2 = await s.ticket(intent="refund_request", priority="high", at=created, conversation_id=c4)
    t3 = await s.ticket(intent="refund_request", priority="urgent", at=created)

    # First responses after 10 and 20 minutes; t1 resolved after an hour.
    await s.draft(t1, "sent", "Hello there.\n", "Hello  there.", sent_at=created + dt.timedelta(minutes=10))
    await s.draft(t2, "sent", "We can help.", "We can help with that refund.", sent_at=created + dt.timedelta(minutes=20))
    await s.draft(t2, "rejected", "No.", "No.")
    await s.draft(t3, "pending", "Pending.", "Pending.")
    await s.draft(t3, "sent", "", "Written by a person.", author_type="human", sent_at=created + dt.timedelta(minutes=1))
    await add(
        conn,
        AuditEvent,
        workspace_id=wid,
        ticket_id=t1,
        actor_type="user",
        action="ticket.status_changed",
        target_type="ticket",
        target_id=t1,
        before={"status": "replied"},
        after={"status": "resolved"},
        created_at=created + dt.timedelta(hours=1),
    )

    await s.action(t2, "issue_refund", "succeeded")
    await s.action(t2, "issue_refund", "rejected")
    await s.action(t2, "issue_refund", "failed")
    await s.action(t3, "cancel_order", "proposed")

    await s.llm("classify", "clef", "0.001")
    await s.llm("classify", "clef", "0.001")
    await s.llm("chat", "gpt", "0.01")
    await s.llm("chat", "gpt", "0", status="error")
    await s.llm("draft", "gpt", "0.02")
    await s.llm("embed_query", "emb", "0.0001")
    await s.llm("draft", "gpt", "5", at=ago(days=10))


async def seed_workspace_b(conn: AsyncConnection, wid: uuid.UUID) -> None:
    s = Seeder(conn, wid)
    conv = await s.conversation([("Secret question from B?", "fallback", "no_sources")], at=ago(hours=1))
    t = await s.ticket(intent="complaint", priority="urgent", at=ago(hours=1), conversation_id=conv)
    await s.draft(t, "sent", "B", "B edited", sent_at=ago(minutes=30))
    await s.action(t, "issue_refund", "rejected")
    await s.llm("chat", "gpt", "100")


@pytest.fixture
async def seeded(client: AsyncClient, owner_engine: AsyncEngine):
    a = await signup(client, "a@example.com", "Workspace A")
    b = await signup(client, "b@example.com", "Workspace B")
    async with owner_engine.begin() as conn:
        await seed_workspace_a(conn, a.workspace_id)
        await seed_workspace_b(conn, b.workspace_id)
    return a, b


async def test_overview_numbers_on_seeded_data(client: AsyncClient, seeded) -> None:
    a, _ = seeded
    resp = await client.get(OVERVIEW, params={"days": 7}, headers=a.headers)
    assert resp.status_code == 200, resp.text
    data = resp.json()

    assert data["days"] == 7
    assert data["conversations"] == {
        "total": 6,
        "contained": 2,
        "contained_rate": 0.3333,
        "handed_off": 2,
        "handoff_rate": 0.3333,
        "fallback_ended": 1,  # the budget one; c3 has a ticket, so it counts as handed off
        "thumbs_down_ended": 1,
    }

    tickets = data["tickets"]
    assert tickets["total"] == 3
    assert tickets["by_intent"] == [
        {"key": "refund_request", "count": 2},
        {"key": "knowledge_question", "count": 1},
    ]
    assert tickets["by_priority"] == [
        {"key": "high", "count": 1},
        {"key": "normal", "count": 1},
        {"key": "urgent", "count": 1},
    ]
    # The human-written reply on t3 counts as a response too (1 minute).
    assert tickets["first_response"] == {"count": 3, "median_s": 600.0, "p90_s": 1080.0}
    assert tickets["resolution"] == {"count": 1, "median_s": 3600.0, "p90_s": 3600.0}

    assert data["drafts"] == {
        "sent_as_is": 1,
        "sent_edited": 1,
        "rejected": 1,
        "edit_rate": 0.5,
        "acceptance_rate": 0.6667,
    }
    assert data["actions"] == [
        {"tool_name": "issue_refund", "proposed": 0, "approved": 2, "rejected": 1, "succeeded": 1, "failed": 1},
        {"tool_name": "cancel_order", "proposed": 1, "approved": 0, "rejected": 0, "succeeded": 0, "failed": 0},
    ]
    assert data["satisfaction"] == {
        "answer_up": 1,
        "answer_down": 1,
        "resolution_up": 1,
        "resolution_down": 0,
    }

    llm = data["llm"]
    assert llm["calls"] == 6 and llm["errors"] == 1
    assert llm["total_cost_usd"] == pytest.approx(0.0321)
    assert llm["cost_per_conversation"] == pytest.approx(0.0321 / 6, abs=1e-6)
    assert [(p["purpose"], p["calls"]) for p in llm["by_purpose"]] == [
        ("draft", 1),
        ("answer", 2),
        ("classify", 2),
        ("embedding", 1),
    ]
    gpt = next(m for m in llm["by_model"] if m["model"] == "gpt")
    assert (gpt["calls"], gpt["errors"], gpt["input_tokens"]) == (3, 1, 300)
    assert len(llm["daily"]) == 7
    assert sum(d["draft"] for d in llm["daily"]) == pytest.approx(0.02)

    series = data["series"]
    assert len(series) == 7
    assert series[-1]["day"] == NOW.date().isoformat()
    assert sum(p["conversations"] for p in series) == 6
    assert sum(p["tickets"] for p in series) == 3
    assert sum(p["cost_usd"] for p in series) == pytest.approx(0.0321)


async def test_range_includes_older_data(client: AsyncClient, seeded) -> None:
    a, _ = seeded
    data = (await client.get(OVERVIEW, params={"days": 30}, headers=a.headers)).json()
    assert data["conversations"]["total"] == 7
    assert data["conversations"]["contained"] == 3
    assert data["llm"]["total_cost_usd"] == pytest.approx(5.0321)
    assert len(data["series"]) == 30


async def test_only_7_30_90_days_are_accepted(client: AsyncClient) -> None:
    owner = await signup(client, "owner@example.com")
    assert (await client.get(OVERVIEW, params={"days": 14}, headers=owner.headers)).status_code == 422
    assert (await client.get(OVERVIEW)).status_code == 401


async def test_empty_workspace_has_zeros_and_no_rates(client: AsyncClient) -> None:
    owner = await signup(client, "owner@example.com")
    data = (await client.get(OVERVIEW, params={"days": 7}, headers=owner.headers)).json()
    assert data["conversations"]["total"] == 0
    assert data["conversations"]["contained_rate"] is None
    assert data["tickets"]["first_response"] == {"count": 0, "median_s": None, "p90_s": None}
    assert data["drafts"]["edit_rate"] is None
    assert data["llm"]["cost_per_conversation"] is None
    assert data["actions"] == []
    assert [p["conversations"] for p in data["series"]] == [0] * 7
    gaps = (await client.get(GAPS, params={"days": 7}, headers=owner.headers)).json()
    assert gaps == {"days": 7, "total_fallbacks": 0, "gaps": []}


async def test_knowledge_gaps_are_grouped_and_masked(client: AsyncClient, seeded) -> None:
    a, _ = seeded
    resp = await client.get(GAPS, params={"days": 7}, headers=a.headers)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    # The budget fallback is not a knowledge gap.
    assert data["total_fallbacks"] == 3
    gaps = [(g["question"], g["count"]) for g in data["gaps"]]
    assert gaps[0][1] == 2 and gaps[0][0].lower().startswith("do you ship to canada")
    assert gaps[1][1] == 1
    password = gaps[1][0]
    assert "bob@example.com" not in password and "555" not in password
    assert "[email]" in password and "[phone]" in password
    assert "warranty" not in resp.text.lower()


def test_question_grouping_and_masking_units() -> None:
    seen = NOW
    gaps = service.group_questions(
        [
            ("How long does shipping take?", seen),
            ("how long does shipping take", seen),
            ("How long does shipping usually take?", seen),
            ("Can I pay with PayPal?", seen),
        ]
    )
    assert [(g.question, g.count) for g in gaps] == [
        ("How long does shipping take?", 3),
        ("Can I pay with PayPal?", 1),
    ]
    masked = service.mask_question("Order ORD-123456 for jane.doe@mail.co, see https://x.io/a")
    assert "jane" not in masked and "123456" not in masked and "x.io" not in masked


async def test_analytics_are_isolated_per_workspace(client: AsyncClient, seeded) -> None:
    a, b = seeded
    data_b = (await client.get(OVERVIEW, params={"days": 7}, headers=b.headers)).json()
    assert data_b["conversations"]["total"] == 1
    assert data_b["tickets"]["by_intent"] == [{"key": "complaint", "count": 1}]
    assert data_b["llm"]["total_cost_usd"] == pytest.approx(100)
    gaps_b = (await client.get(GAPS, params={"days": 7}, headers=b.headers)).json()
    assert [g["question"] for g in gaps_b["gaps"]] == ["Secret question from B?"]

    data_a = await client.get(OVERVIEW, params={"days": 7}, headers=a.headers)
    gaps_a = await client.get(GAPS, params={"days": 7}, headers=a.headers)
    assert "complaint" not in data_a.text
    assert "Secret question" not in gaps_a.text
    assert data_a.json()["llm"]["total_cost_usd"] < 1


async def test_rls_blocks_other_workspace_even_if_the_filter_names_it(seeded) -> None:
    """With A's tenant context, asking for B's workspace id returns nothing: RLS, not just the
    WHERE clause, keeps B's rows out."""
    a, b = seeded
    async with tenant_session(a.workspace_id, a.user_id) as db:
        data = await service.overview(db, b.workspace_id, 7)
        gaps = await service.knowledge_gaps(db, b.workspace_id, 7)
    assert data.conversations.total == 0
    assert data.tickets.total == 0
    assert data.llm.calls == 0
    assert data.actions == []
    assert gaps.total_fallbacks == 0


async def test_widget_fallbacks_record_why_they_fell_back(
    app: FastAPI,
    client: AsyncClient,
    app_role_engine: AsyncEngine,
    limiter: InMemoryLimiter,
    settings,  # noqa: F811
) -> None:
    owner = await signup(client, "owner@example.com")
    use_llm(app, "unused")
    session = await open_widget(client, await widget_key(client, owner, [SHOP_ORIGIN]))
    await ask(client, session, "Do you sell gift cards?")
    limiter.tokens[owner.workspace_id] = settings.widget_daily_token_budget
    await ask(client, session, "And what about vouchers?")

    replies = await rows(
        app_role_engine,
        owner.workspace_id,
        "SELECT fallback_reason FROM messages WHERE role = 'assistant' ORDER BY created_at",
    )
    assert [r["fallback_reason"] for r in replies] == ["no_sources", "budget"]
    gaps = (await client.get(GAPS, params={"days": 7}, headers=owner.headers)).json()
    assert [(g["question"], g["count"]) for g in gaps["gaps"]] == [("Do you sell gift cards?", 1)]
