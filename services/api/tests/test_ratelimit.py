"""The shared rate limiter: 429 + Retry-After, sliding windows, per-key isolation, the limits
on auth, widget, uploads, regenerate and the dashboard API, polling staying exempt, and
failing open (with a warning and a metric) when Redis is unavailable."""

import logging
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from redis.exceptions import ConnectionError as RedisConnectionError

from app.core.config import get_settings
from app.core.metrics import RATE_LIMIT_REDIS_ERRORS, RATE_LIMITED
from app.core.ratelimit import RedisRateLimiter, email_key
from tests.conftest import (
    PASSWORD,
    SHOP_ORIGIN,
    InMemoryLimiter,
    open_widget,
    signup,
    upload_file,
    widget_key,
)
from tests.test_widget import MESSAGES_URL, ask, settings, use_llm  # noqa: F401

LOGIN = "/api/v1/auth/login"
WIDGET_CONVERSATION = "/api/v1/widget/conversation"


@pytest.fixture
def limits(monkeypatch: pytest.MonkeyPatch):
    s = get_settings()
    monkeypatch.setattr(s, "rate_limit_enabled", True)
    return s


async def login(client: AsyncClient, email: str):
    # Every test request comes from the same client IP (127.0.0.1).
    resp = await client.post(LOGIN, json={"email": email, "password": "wrong-password"})
    client.cookies.clear()
    return resp


async def test_login_is_limited_per_email_with_retry_after(
    client: AsyncClient, limits, limiter: InMemoryLimiter, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(limits, "rate_limit_login_email_per_minute", 3)
    for _ in range(3):
        assert (await login(client, "victim@example.com")).status_code == 401

    limiter.now += 15
    resp = await login(client, "victim@example.com")
    assert resp.status_code == 429
    assert resp.json()["error"]["code"] == "rate_limited"
    assert resp.headers["Retry-After"] == "45"
    assert resp.headers["X-Request-ID"]

    # Another email is a separate key (the per-IP limit is higher).
    assert (await login(client, "other@example.com")).status_code == 401
    # Keys never hold the address itself.
    assert all("victim" not in key for key in limiter.hits)
    assert f"login:email:{email_key('VICTIM@example.com ')}" in limiter.hits

    # Sliding window: once the oldest attempts are a minute old, logins are allowed again.
    limiter.now += 46
    assert (await login(client, "victim@example.com")).status_code == 401


async def test_login_is_limited_per_ip(
    client: AsyncClient, limits, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(limits, "rate_limit_login_ip_per_minute", 2)
    for i in range(2):
        assert (await login(client, f"user{i}@example.com")).status_code == 401
    resp = await login(client, "user9@example.com")
    assert resp.status_code == 429
    assert int(resp.headers["Retry-After"]) == 60


async def test_refused_attempts_do_not_extend_the_lockout(
    client: AsyncClient, limits, limiter: InMemoryLimiter, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(limits, "rate_limit_login_email_per_minute", 1)
    assert (await login(client, "a@example.com")).status_code == 401
    for _ in range(5):
        limiter.now += 10
        assert (await login(client, "a@example.com")).status_code == 429
    limiter.now += 11
    assert (await login(client, "a@example.com")).status_code == 401


async def test_signup_and_refresh_are_limited(
    client: AsyncClient, limits, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(limits, "rate_limit_signup_ip_per_hour", 1)
    monkeypatch.setattr(limits, "rate_limit_refresh_ip_per_minute", 1)
    await signup(client, "first@example.com")
    resp = await client.post(
        "/api/v1/auth/signup",
        json={
            "email": "second@example.com",
            "password": PASSWORD,
            "full_name": "Second",
            "workspace_name": "Second",
        },
    )
    assert resp.status_code == 429
    assert 3500 < int(resp.headers["Retry-After"]) <= 3600

    assert (await client.post("/api/v1/auth/refresh")).status_code == 401
    assert (await client.post("/api/v1/auth/refresh")).status_code == 429


async def test_dashboard_api_is_limited_per_user(
    client: AsyncClient, limits, monkeypatch: pytest.MonkeyPatch
) -> None:
    alice = await signup(client, "alice@example.com")
    bob = await signup(client, "bob@example.com")
    monkeypatch.setattr(limits, "rate_limit_api_user_per_minute", 3)
    before = RATE_LIMITED.values.get(("api",), 0)

    for _ in range(3):
        assert (await client.get("/api/v1/tickets", headers=alice.headers)).status_code == 200
    resp = await client.get("/api/v1/analytics/overview", headers=alice.headers)
    assert resp.status_code == 429
    assert resp.headers["Retry-After"] == "60"
    assert RATE_LIMITED.values[("api",)] == before + 1
    # Bob has his own bucket.
    assert (await client.get("/api/v1/tickets", headers=bob.headers)).status_code == 200


async def test_uploads_and_regenerate_are_limited(
    client: AsyncClient, limits, monkeypatch: pytest.MonkeyPatch
) -> None:
    owner = await signup(client, "owner@example.com")
    monkeypatch.setattr(limits, "rate_limit_uploads_per_hour", 1)
    monkeypatch.setattr(limits, "rate_limit_regenerate_per_minute", 1)

    assert (await upload_file(client, owner.headers)).status_code == 202
    resp = await upload_file(client, owner.headers, "other.md", b"# Other\n\nText.\n")
    assert resp.status_code == 429
    assert int(resp.headers["Retry-After"]) > 3000

    created = await client.post(
        "/api/v1/tickets", json={"subject": "Hi", "description": "Help"}, headers=owner.headers
    )
    ticket_id = created.json()["id"]
    url = f"/api/v1/tickets/{ticket_id}/regenerate-draft"
    assert (await client.post(url, headers=owner.headers)).status_code == 202
    assert (await client.post(url, headers=owner.headers)).status_code == 429


async def test_widget_messages_are_limited_per_workspace_but_polling_is_exempt(
    app: FastAPI, client: AsyncClient, settings, limits, monkeypatch: pytest.MonkeyPatch  # noqa: F811
) -> None:
    shop = await signup(client, "shop@example.com", "Shop")
    other = await signup(client, "other@example.com", "Other")
    use_llm(app, "unused")
    monkeypatch.setattr(settings, "widget_workspace_rate_per_minute", 2)
    key = await widget_key(client, shop, [SHOP_ORIGIN])

    first = await open_widget(client, key)
    await ask(client, first, "question one")
    await ask(client, await open_widget(client, key), "question two")
    resp = await client.post(
        MESSAGES_URL, json={"content": "question three"}, headers=(await open_widget(client, key)).headers
    )
    assert resp.status_code == 429
    assert resp.headers["Retry-After"] == "60"
    assert "wait a moment" in resp.json()["error"]["message"]

    # Polling is never limited.
    for _ in range(25):
        polled = await client.get(WIDGET_CONVERSATION, headers=first.headers)
        assert polled.status_code == 200

    # Another workspace's widget is unaffected.
    other_session = await open_widget(client, await widget_key(client, other, [SHOP_ORIGIN]))
    await ask(client, other_session, "question one")


async def test_widget_sessions_are_limited_per_ip(
    client: AsyncClient, settings, monkeypatch: pytest.MonkeyPatch  # noqa: F811
) -> None:
    owner = await signup(client, "owner@example.com")
    monkeypatch.setattr(settings, "widget_session_ip_rate_per_minute", 2)
    key = await widget_key(client, owner, [SHOP_ORIGIN])
    await open_widget(client, key)
    await open_widget(client, key)
    resp = await client.post(
        "/api/v1/widget/session", json={"public_key": key}, headers={"Origin": SHOP_ORIGIN}
    )
    assert resp.status_code == 429


async def test_limits_can_be_disabled(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    s = get_settings()
    monkeypatch.setattr(s, "rate_limit_enabled", False)
    monkeypatch.setattr(s, "rate_limit_login_email_per_minute", 1)
    for _ in range(3):
        assert (await login(client, "a@example.com")).status_code == 401


async def test_redis_outage_fails_open_with_one_warning_and_a_metric(
    caplog: pytest.LogCaptureFixture,
) -> None:
    limiter = RedisRateLimiter("redis://127.0.0.1:1/0")
    limiter._script = AsyncMock(side_effect=RedisConnectionError("down"))
    before = RATE_LIMIT_REDIS_ERRORS.values.get((), 0)
    try:
        with caplog.at_level(logging.WARNING, logger="app.ratelimit"):
            for _ in range(5):
                decision = await limiter.hit("login:ip:1.2.3.4", 1, 60)
                assert decision.allowed
    finally:
        await limiter.aclose()

    assert RATE_LIMIT_REDIS_ERRORS.values[()] == before + 5
    warnings = [r for r in caplog.records if r.name == "app.ratelimit"]
    assert len(warnings) == 1
    assert "ConnectionError" in warnings[0].getMessage()


async def test_redis_limiter_reports_retry_after_from_the_script() -> None:
    limiter = RedisRateLimiter("redis://127.0.0.1:1/0")
    limiter._script = AsyncMock(side_effect=[[1, 0], [0, 12_345]])
    try:
        assert (await limiter.hit("k", 1, 60)).allowed
        refused = await limiter.hit("k", 1, 60)
    finally:
        await limiter.aclose()
    assert (refused.allowed, refused.retry_after_s) == (False, 13)
    keys = limiter._script.call_args.kwargs["keys"]
    assert keys == ["rl:k"]
