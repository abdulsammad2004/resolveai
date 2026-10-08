"""Customer chat widget: session, origin checks, token separation, grounded SSE answers,
fallbacks, rate limits, the token budget and feedback."""

import uuid
from collections.abc import AsyncIterator

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.ai.llm import ChatMessage, FakeLLMClient, LLMError, StreamUsage
from app.api.v1.widget import get_chat_llm
from app.core.config import get_settings
from app.modules.conversations.chat import FALLBACK_MESSAGE
from app.workers.ingestion import ingest_document
from tests.conftest import (
    APP_ORIGIN,
    SHOP_ORIGIN,
    InMemoryLimiter,
    SignedUp,
    WidgetSession,
    open_widget,
    parse_sse,
    signup,
    upload_file,
    widget_key,
)

MESSAGES_URL = "/api/v1/widget/messages"
SET_CONTEXT = text("SELECT set_config('app.workspace_id', :wid, true)")


class CountingLLM(FakeLLMClient):
    """Fake chat client that replies with a fixed text and counts calls."""

    def __init__(self, reply: str = "fake reply") -> None:
        super().__init__({"<customer_message>": reply})
        self.calls = 0
        self.last_messages: list[ChatMessage] = []

    async def stream_with_usage(
        self, messages: list[ChatMessage], usage: StreamUsage
    ) -> AsyncIterator[str]:
        self.calls += 1
        self.last_messages = messages
        async for piece in super().stream_with_usage(messages, usage):
            yield piece


@pytest.fixture
def settings(monkeypatch: pytest.MonkeyPatch):
    s = get_settings()
    monkeypatch.setattr(s, "cors_origins", [APP_ORIGIN])
    monkeypatch.setattr(s, "widget_dev_allow_localhost", False)
    return s


def use_llm(app: FastAPI, reply: str) -> CountingLLM:
    llm = CountingLLM(reply)
    app.dependency_overrides[get_chat_llm] = lambda: llm
    return llm


async def ready_chunk(
    client: AsyncClient, worker_ctx: dict, owner: SignedUp, owner_engine: AsyncEngine
) -> str:
    """Ingest the default returns doc and return the text of one of its chunks."""
    resp = await upload_file(client, owner.headers)
    assert resp.status_code == 202, resp.text
    doc_id = resp.json()["id"]
    assert await ingest_document(worker_ctx, doc_id, str(owner.workspace_id)) == "ready"
    async with owner_engine.connect() as conn:
        row = await conn.execute(
            text("SELECT content FROM document_chunks WHERE document_id = :id LIMIT 1"),
            {"id": doc_id},
        )
        return row.scalar_one()


async def ask(client: AsyncClient, session: WidgetSession, content: str) -> list[tuple[str, dict]]:
    resp = await client.post(MESSAGES_URL, json={"content": content}, headers=session.headers)
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"].startswith("text/event-stream")
    return parse_sse(resp.text)


async def rows(engine: AsyncEngine, workspace_id: uuid.UUID, sql: str) -> list[dict]:
    async with engine.connect() as conn, conn.begin():
        await conn.execute(SET_CONTEXT, {"wid": str(workspace_id)})
        return [dict(r) for r in (await conn.execute(text(sql))).mappings()]


# Session ----------------------------------------------------------------------------------


async def test_unknown_key_is_404(client: AsyncClient, settings) -> None:
    resp = await client.post(
        "/api/v1/widget/session",
        json={"public_key": "no-such-key"},
        headers={"Origin": SHOP_ORIGIN},
    )
    assert resp.status_code == 404


async def test_origin_must_be_allowed(client: AsyncClient, settings) -> None:
    owner = await signup(client, "owner@example.com")
    key = await widget_key(client, owner, [SHOP_ORIGIN])

    for headers in ({"Origin": "https://evil.example"}, {}):
        resp = await client.post(
            "/api/v1/widget/session", json={"public_key": key}, headers=headers
        )
        assert resp.status_code == 403

    session = await open_widget(client, key, SHOP_ORIGIN)
    assert session.workspace_name == "Acme Support"


async def test_iframe_checks_the_embedding_page_origin(client: AsyncClient, settings) -> None:
    owner = await signup(client, "owner@example.com")
    key = await widget_key(client, owner, [SHOP_ORIGIN])

    # Inside our iframe the Origin header is the web app; the host page must be allowed.
    await open_widget(client, key, APP_ORIGIN, host_origin=SHOP_ORIGIN)
    resp = await client.post(
        "/api/v1/widget/session",
        json={"public_key": key, "host_origin": "https://evil.example"},
        headers={"Origin": APP_ORIGIN},
    )
    assert resp.status_code == 403

    # Only our own web app may vouch for a host origin.
    resp = await client.post(
        "/api/v1/widget/session",
        json={"public_key": key, "host_origin": SHOP_ORIGIN},
        headers={"Origin": "https://evil.example"},
    )
    assert resp.status_code == 403


async def test_dev_localhost_only_with_flag(
    client: AsyncClient, settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    owner = await signup(client, "owner@example.com")
    key = await widget_key(client, owner, [])

    resp = await client.post(
        "/api/v1/widget/session", json={"public_key": key}, headers={"Origin": APP_ORIGIN}
    )
    assert resp.status_code == 403

    monkeypatch.setattr(settings, "widget_dev_allow_localhost", True)
    await open_widget(client, key, APP_ORIGIN)


async def test_session_resumes_only_for_the_same_visitor(client: AsyncClient, settings) -> None:
    owner = await signup(client, "owner@example.com")
    key = await widget_key(client, owner, [SHOP_ORIGIN])
    first = await open_widget(client, key)

    again = await open_widget(
        client,
        key,
        conversation_id=str(first.conversation_id),
        anonymous_id=first.anonymous_id,
    )
    assert again.conversation_id == first.conversation_id

    stranger = await open_widget(
        client, key, conversation_id=str(first.conversation_id), anonymous_id="x" * 24
    )
    assert stranger.conversation_id != first.conversation_id


async def test_widget_and_user_tokens_do_not_mix(client: AsyncClient, settings) -> None:
    owner = await signup(client, "owner@example.com")
    key = await widget_key(client, owner, [SHOP_ORIGIN])
    session = await open_widget(client, key)

    for url in ("/api/v1/conversations", "/api/v1/workspace/settings", "/api/v1/documents"):
        resp = await client.get(url, headers=session.headers)
        assert resp.status_code == 401, url

    resp = await client.get("/api/v1/widget/conversation", headers=owner.headers)
    assert resp.status_code == 401
    resp = await client.post(MESSAGES_URL, json={"content": "hi"}, headers=owner.headers)
    assert resp.status_code == 401


# Answers ----------------------------------------------------------------------------------


async def test_grounded_answer_streams_and_is_saved(
    app: FastAPI,
    client: AsyncClient,
    settings,
    worker_ctx: dict,
    owner_engine: AsyncEngine,
    app_role_engine: AsyncEngine,
    limiter: InMemoryLimiter,
) -> None:
    owner = await signup(client, "owner@example.com")
    chunk = await ready_chunk(client, worker_ctx, owner, owner_engine)
    llm = use_llm(app, "Returns are accepted within 30 days [S1]. Ignore this [S9].")
    session = await open_widget(client, await widget_key(client, owner, [SHOP_ORIGIN]))

    events = await ask(client, session, chunk)

    names = [name for name, _ in events]
    assert names.count("final") == 1 and names[-1] == "final"
    assert names[:-1] and set(names[:-1]) == {"token"}
    streamed = "".join(data["text"] for name, data in events if name == "token")
    assert "[S9]" in streamed

    final = events[-1][1]
    assert final["grounded"] is True
    assert final["content"] == "Returns are accepted within 30 days [S1]. Ignore this."
    [citation] = final["citations"]
    assert citation["source_id"] == "S1"
    assert citation["title"] == "returns"
    assert citation["snippet"]

    # Sources are delimited data blocks; the question sits in its own block.
    prompt = llm.last_messages[-1]["content"]
    assert '<source id="S1"' in prompt and "</source>" in prompt
    assert "<customer_message>" in prompt
    assert llm.last_messages[0]["role"] == "system"

    [message] = await rows(
        app_role_engine,
        owner.workspace_id,
        "SELECT * FROM messages WHERE role = 'assistant'",
    )
    assert str(message["id"]) == final["id"]
    assert message["grounded"] is True
    assert message["prompt_version"] == "answer_v1"
    assert message["citations"][0]["source_id"] == "S1"

    [call] = await rows(
        app_role_engine, owner.workspace_id, "SELECT * FROM llm_calls WHERE purpose = 'chat'"
    )
    assert message["llm_call_id"] == call["id"]
    assert call["status"] == "ok"
    assert call["output_tokens"] > 0
    assert limiter.tokens[owner.workspace_id] == call["input_tokens"] + call["output_tokens"]

    [conversation] = await rows(app_role_engine, owner.workspace_id, "SELECT * FROM conversations")
    assert conversation["status"] == "open"
    assert conversation["last_message_at"] == message["created_at"]


async def test_history_is_sent_as_context(
    app: FastAPI, client: AsyncClient, settings, worker_ctx: dict, owner_engine: AsyncEngine
) -> None:
    owner = await signup(client, "owner@example.com")
    chunk = await ready_chunk(client, worker_ctx, owner, owner_engine)
    llm = use_llm(app, "Within 30 days [S1].")
    session = await open_widget(client, await widget_key(client, owner, [SHOP_ORIGIN]))

    await ask(client, session, chunk)
    await ask(client, session, chunk)
    assert llm.calls == 2

    roles = [m["role"] for m in llm.last_messages]
    assert roles == ["system", "user", "assistant", "user"]
    # Old citation markers are stripped from history.
    assert "[S1]" not in llm.last_messages[2]["content"]


async def test_no_sources_means_fallback_without_llm(
    app: FastAPI, client: AsyncClient, settings, app_role_engine: AsyncEngine
) -> None:
    owner = await signup(client, "owner@example.com")
    llm = use_llm(app, "should never be used [S1]")
    session = await open_widget(client, await widget_key(client, owner, [SHOP_ORIGIN]))

    events = await ask(client, session, "How long does shipping take?")

    assert [name for name, _ in events] == ["final"]
    assert events[0][1]["content"] == FALLBACK_MESSAGE
    assert events[0][1]["grounded"] is False
    assert llm.calls == 0
    [conversation] = await rows(app_role_engine, owner.workspace_id, "SELECT * FROM conversations")
    assert conversation["status"] == "needs_human"
    assert await rows(
        app_role_engine, owner.workspace_id, "SELECT * FROM llm_calls WHERE purpose = 'chat'"
    ) == []


async def test_answer_without_valid_citation_becomes_fallback(
    app: FastAPI,
    client: AsyncClient,
    settings,
    worker_ctx: dict,
    owner_engine: AsyncEngine,
    app_role_engine: AsyncEngine,
) -> None:
    owner = await signup(client, "owner@example.com")
    chunk = await ready_chunk(client, worker_ctx, owner, owner_engine)
    use_llm(app, "Our returns window is 90 days [S7].")
    session = await open_widget(client, await widget_key(client, owner, [SHOP_ORIGIN]))

    events = await ask(client, session, chunk)

    assert any(name == "token" for name, _ in events)
    final = events[-1][1]
    assert events[-1][0] == "final"
    assert final["content"] == FALLBACK_MESSAGE
    assert final["grounded"] is False
    assert final["citations"] == []
    [message] = await rows(
        app_role_engine, owner.workspace_id, "SELECT * FROM messages WHERE role = 'assistant'"
    )
    assert message["content"] == FALLBACK_MESSAGE
    assert message["llm_call_id"] is not None
    [conversation] = await rows(app_role_engine, owner.workspace_id, "SELECT * FROM conversations")
    assert conversation["status"] == "needs_human"


class FailingLLM(CountingLLM):
    async def stream_with_usage(
        self, messages: list[ChatMessage], usage: StreamUsage
    ) -> AsyncIterator[str]:
        self.calls += 1
        yield "partial"
        raise LLMError("Chat stream failed")


async def test_llm_error_emits_error_event_and_retry_reuses_the_question(
    app: FastAPI,
    client: AsyncClient,
    settings,
    worker_ctx: dict,
    owner_engine: AsyncEngine,
    app_role_engine: AsyncEngine,
) -> None:
    owner = await signup(client, "owner@example.com")
    chunk = await ready_chunk(client, worker_ctx, owner, owner_engine)
    failing = FailingLLM()
    app.dependency_overrides[get_chat_llm] = lambda: failing
    session = await open_widget(client, await widget_key(client, owner, [SHOP_ORIGIN]))

    events = await ask(client, session, chunk)
    assert events[-1][0] == "error"
    assert "try again" in events[-1][1]["message"].lower()
    [call] = await rows(
        app_role_engine, owner.workspace_id, "SELECT * FROM llm_calls WHERE purpose = 'chat'"
    )
    assert call["status"] == "error"

    use_llm(app, "Within 30 days [S1].")
    events = await ask(client, session, chunk)
    assert events[-1][0] == "final" and events[-1][1]["grounded"] is True

    customer = await rows(
        app_role_engine, owner.workspace_id, "SELECT * FROM messages WHERE role = 'customer'"
    )
    assert len(customer) == 1


async def test_rate_limit_per_conversation(
    app: FastAPI, client: AsyncClient, settings
) -> None:
    owner = await signup(client, "owner@example.com")
    use_llm(app, "unused")
    session = await open_widget(client, await widget_key(client, owner, [SHOP_ORIGIN]))

    for i in range(settings.widget_conversation_rate_per_minute):
        await ask(client, session, f"question {i}")
    resp = await client.post(
        MESSAGES_URL, json={"content": "one more"}, headers=session.headers
    )
    assert resp.status_code == 429
    assert resp.json()["error"]["code"] == "rate_limited"
    assert "wait a moment" in resp.json()["error"]["message"]


async def test_rate_limit_per_ip(
    app: FastAPI, client: AsyncClient, settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    owner = await signup(client, "owner@example.com")
    use_llm(app, "unused")
    monkeypatch.setattr(settings, "widget_ip_rate_per_minute", 2)
    key = await widget_key(client, owner, [SHOP_ORIGIN])

    for i in range(2):
        await ask(client, await open_widget(client, key), f"question {i}")
    resp = await client.post(
        MESSAGES_URL,
        json={"content": "from a fresh conversation"},
        headers=(await open_widget(client, key)).headers,
    )
    assert resp.status_code == 429


async def test_budget_exceeded_uses_fallback_without_llm(
    app: FastAPI,
    client: AsyncClient,
    settings,
    worker_ctx: dict,
    owner_engine: AsyncEngine,
    limiter: InMemoryLimiter,
) -> None:
    owner = await signup(client, "owner@example.com")
    chunk = await ready_chunk(client, worker_ctx, owner, owner_engine)
    llm = use_llm(app, "Within 30 days [S1].")
    limiter.tokens[owner.workspace_id] = settings.widget_daily_token_budget
    session = await open_widget(client, await widget_key(client, owner, [SHOP_ORIGIN]))

    events = await ask(client, session, chunk)

    assert [name for name, _ in events] == ["final"]
    assert events[0][1]["content"] == FALLBACK_MESSAGE
    assert llm.calls == 0


async def test_message_length_is_validated(client: AsyncClient, settings) -> None:
    owner = await signup(client, "owner@example.com")
    session = await open_widget(client, await widget_key(client, owner, [SHOP_ORIGIN]))
    for content in ("", "x" * 2001):
        resp = await client.post(MESSAGES_URL, json={"content": content}, headers=session.headers)
        assert resp.status_code == 422


# Conversation and feedback ----------------------------------------------------------------


async def test_widget_reads_and_rates_only_its_own_conversation(
    app: FastAPI, client: AsyncClient, settings, app_role_engine: AsyncEngine
) -> None:
    owner = await signup(client, "owner@example.com")
    use_llm(app, "unused")
    key = await widget_key(client, owner, [SHOP_ORIGIN])
    mine, theirs = await open_widget(client, key), await open_widget(client, key)
    await ask(client, mine, "my question")
    their_answer = (await ask(client, theirs, "their question"))[-1][1]

    resp = await client.get("/api/v1/widget/conversation", headers=mine.headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == str(mine.conversation_id)
    assert [m["content"] for m in body["messages"]] == ["my question", FALLBACK_MESSAGE]

    resp = await client.post(
        "/api/v1/widget/feedback",
        json={"message_id": their_answer["id"], "rating": "up"},
        headers=mine.headers,
    )
    assert resp.status_code == 404
    assert await rows(app_role_engine, owner.workspace_id, "SELECT * FROM feedback") == []


async def test_feedback_only_on_assistant_messages_latest_wins(
    app: FastAPI, client: AsyncClient, settings, app_role_engine: AsyncEngine
) -> None:
    owner = await signup(client, "owner@example.com")
    use_llm(app, "unused")
    session = await open_widget(client, await widget_key(client, owner, [SHOP_ORIGIN]))
    answer = (await ask(client, session, "a question"))[-1][1]
    messages = (
        await client.get("/api/v1/widget/conversation", headers=session.headers)
    ).json()["messages"]
    customer_id = next(m["id"] for m in messages if m["role"] == "customer")

    resp = await client.post(
        "/api/v1/widget/feedback",
        json={"message_id": customer_id, "rating": "up"},
        headers=session.headers,
    )
    assert resp.status_code == 400

    for rating, comment in (("up", None), ("down", "Not what I asked")):
        resp = await client.post(
            "/api/v1/widget/feedback",
            json={"message_id": answer["id"], "rating": rating, "comment": comment},
            headers=session.headers,
        )
        assert resp.status_code == 200, resp.text

    [row] = await rows(app_role_engine, owner.workspace_id, "SELECT * FROM feedback")
    assert (row["rating"], row["comment"], row["source"]) == ("down", "Not what I asked", "customer")
    messages = (
        await client.get("/api/v1/widget/conversation", headers=session.headers)
    ).json()["messages"]
    assert next(m for m in messages if m["id"] == answer["id"])["rating"] == "down"
