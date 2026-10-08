"""Agent inbox: list, detail, status changes, pagination and cross-tenant isolation."""

import uuid

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.ai.llm import FakeLLMClient
from app.api.v1.widget import get_chat_llm
from app.core.config import get_settings
from app.modules.conversations.chat import FALLBACK_MESSAGE
from tests.conftest import (
    SHOP_ORIGIN,
    WidgetSession,
    open_widget,
    parse_sse,
    signup,
    widget_key,
)

LIST_URL = "/api/v1/conversations"


@pytest.fixture(autouse=True)
def fake_llm(app: FastAPI, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "widget_dev_allow_localhost", False)
    app.dependency_overrides[get_chat_llm] = lambda: FakeLLMClient()


async def say(client: AsyncClient, session: WidgetSession, content: str) -> dict:
    resp = await client.post(
        "/api/v1/widget/messages", json={"content": content}, headers=session.headers
    )
    assert resp.status_code == 200, resp.text
    return parse_sse(resp.text)[-1][1]


async def test_list_detail_and_close(client: AsyncClient) -> None:
    owner = await signup(client, "owner@example.com")
    key = await widget_key(client, owner, [SHOP_ORIGIN])
    await open_widget(client, key)  # never writes: stays out of the inbox
    session = await open_widget(client, key)
    answer = await say(client, session, "Do you ship to Canada?")
    await client.post(
        "/api/v1/widget/feedback",
        json={"message_id": answer["id"], "rating": "down", "comment": "No answer"},
        headers=session.headers,
    )

    resp = await client.get(LIST_URL, headers=owner.headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    [item] = body["items"]
    assert item["id"] == str(session.conversation_id)
    assert item["status"] == "needs_human"
    assert item["last_message_preview"] == FALLBACK_MESSAGE
    assert item["last_message_role"] == "assistant"
    assert item["contact"]["anonymous_id"] == session.anonymous_id
    assert body["counts"] == {"open": 0, "needs_human": 1, "closed": 0}
    assert body["next_cursor"] is None

    resp = await client.get(f"{LIST_URL}?status=open", headers=owner.headers)
    assert resp.json()["items"] == []

    resp = await client.get(f"{LIST_URL}/{session.conversation_id}", headers=owner.headers)
    assert resp.status_code == 200
    detail = resp.json()
    assert [m["role"] for m in detail["messages"]] == ["customer", "assistant"]
    assert detail["messages"][1]["grounded"] is False
    assert detail["messages"][1]["feedback"]["rating"] == "down"
    assert detail["messages"][1]["feedback"]["comment"] == "No answer"

    resp = await client.patch(
        f"{LIST_URL}/{session.conversation_id}", json={"status": "closed"}, headers=owner.headers
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "closed"
    counts = (await client.get(LIST_URL, headers=owner.headers)).json()["counts"]
    assert counts == {"open": 0, "needs_human": 0, "closed": 1}

    resp = await client.patch(
        f"{LIST_URL}/{session.conversation_id}", json={"status": "archived"}, headers=owner.headers
    )
    assert resp.status_code == 422


async def test_closed_conversation_starts_fresh_widget_session(client: AsyncClient) -> None:
    owner = await signup(client, "owner@example.com")
    key = await widget_key(client, owner, [SHOP_ORIGIN])
    session = await open_widget(client, key)
    await say(client, session, "hello")
    await client.patch(
        f"{LIST_URL}/{session.conversation_id}", json={"status": "closed"}, headers=owner.headers
    )

    again = await open_widget(
        client,
        key,
        conversation_id=str(session.conversation_id),
        anonymous_id=session.anonymous_id,
    )
    assert again.conversation_id != session.conversation_id
    assert again.anonymous_id == session.anonymous_id


async def test_cursor_pagination_newest_activity_first(client: AsyncClient) -> None:
    owner = await signup(client, "owner@example.com")
    key = await widget_key(client, owner, [SHOP_ORIGIN])
    sessions = [await open_widget(client, key) for _ in range(3)]
    for i, session in enumerate(sessions):
        await say(client, session, f"question {i}")
    # Activity on the first conversation moves it to the top.
    await say(client, sessions[0], "follow-up")

    seen: list[str] = []
    cursor = None
    while True:
        url = f"{LIST_URL}?limit=2" + (f"&cursor={cursor}" if cursor else "")
        body = (await client.get(url, headers=owner.headers)).json()
        seen += [item["id"] for item in body["items"]]
        cursor = body["next_cursor"]
        if cursor is None:
            break

    expected = [sessions[0], sessions[2], sessions[1]]
    assert seen == [str(s.conversation_id) for s in expected]

    resp = await client.get(f"{LIST_URL}?cursor=not-a-cursor", headers=owner.headers)
    assert resp.status_code == 422


async def test_workspace_b_cannot_see_a_conversations(
    client: AsyncClient, app_role_engine: AsyncEngine
) -> None:
    a = await signup(client, "a@example.com", workspace_name="Workspace A")
    b = await signup(client, "b@example.com", workspace_name="Workspace B")
    session = await open_widget(client, await widget_key(client, a, [SHOP_ORIGIN]))
    await say(client, session, "private question from A")

    body = (await client.get(LIST_URL, headers=b.headers)).json()
    assert body["items"] == []
    assert body["counts"] == {"open": 0, "needs_human": 0, "closed": 0}

    url = f"{LIST_URL}/{session.conversation_id}"
    assert (await client.get(url, headers=b.headers)).status_code == 404
    resp = await client.patch(url, json={"status": "closed"}, headers=b.headers)
    assert resp.status_code == 404
    assert (await client.get(url, headers=a.headers)).json()["status"] == "needs_human"

    # Database level: with B's context, none of A's rows exist.
    async with app_role_engine.connect() as conn, conn.begin():
        await conn.execute(
            text("SELECT set_config('app.workspace_id', :wid, true)"), {"wid": str(b.workspace_id)}
        )
        for table in ("contacts", "conversations", "messages", "feedback"):
            count = (await conn.execute(text(f"SELECT count(*) FROM {table}"))).scalar_one()
            assert count == 0, table

    # And without any context, nothing at all.
    async with app_role_engine.connect() as conn:
        count = (await conn.execute(text("SELECT count(*) FROM messages"))).scalar_one()
        assert count == 0


async def test_widget_token_of_a_cannot_reach_b(client: AsyncClient) -> None:
    a = await signup(client, "a@example.com", workspace_name="Workspace A")
    b = await signup(client, "b@example.com", workspace_name="Workspace B")
    session_b = await open_widget(client, await widget_key(client, b, [SHOP_ORIGIN]))
    answer_b = await say(client, session_b, "B's question")
    session_a = await open_widget(client, await widget_key(client, a, [SHOP_ORIGIN]))

    resp = await client.post(
        "/api/v1/widget/feedback",
        json={"message_id": answer_b["id"], "rating": "up"},
        headers=session_a.headers,
    )
    assert resp.status_code == 404
    body = (await client.get("/api/v1/widget/conversation", headers=session_a.headers)).json()
    assert body["messages"] == []


async def test_unknown_conversation_is_404(client: AsyncClient) -> None:
    owner = await signup(client, "owner@example.com")
    resp = await client.get(f"{LIST_URL}/{uuid.uuid4()}", headers=owner.headers)
    assert resp.status_code == 404
