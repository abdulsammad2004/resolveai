"""Observability: request ids (echoed, logged, carried into jobs), structured logs without
sensitive data, the protected /metrics endpoint and worker liveness in /health/ready."""

import json
import logging
import time
import uuid
from collections.abc import Iterator
from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest
from arq import Retry
from fastapi import FastAPI
from httpx import AsyncClient
from pydantic import SecretStr

from app.ai.usage import LLMCallStatus, record_llm_call
from app.api import health
from app.core.config import get_settings
from app.core.logs import JSONFormatter, bind_log_context, redact
from app.core.metrics import JOBS, Registry
from app.core.middleware import get_request_id
from app.workers.observability import heartbeat, traced
from app.workers.queue import ArqJobQueue
from tests.conftest import (
    PASSWORD,
    SHOP_ORIGIN,
    RecordingQueue,
    open_widget,
    signup,
    widget_key,
)
from tests.test_widget import ask, settings, use_llm  # noqa: F401


class JSONCapture(logging.Handler):
    """Formats every record exactly as production does and keeps the lines."""

    def __init__(self) -> None:
        super().__init__(logging.DEBUG)
        self.setFormatter(JSONFormatter())
        self.lines: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.lines.append(self.format(record))

    def entries(self) -> list[dict]:
        return [json.loads(line) for line in self.lines]


@pytest.fixture
def logs() -> Iterator[JSONCapture]:
    capture = JSONCapture()
    root, app_logger = logging.getLogger(), logging.getLogger("app")
    previous = app_logger.level
    root.addHandler(capture)
    app_logger.setLevel(logging.DEBUG)
    yield capture
    root.removeHandler(capture)
    app_logger.setLevel(previous)


# Request ids --------------------------------------------------------------------------------


async def test_request_id_is_echoed_or_generated(client: AsyncClient) -> None:
    given = await client.get("/health", headers={"X-Request-ID": "abc-123"})
    assert given.headers["X-Request-ID"] == "abc-123"
    unsafe = await client.get("/health", headers={"X-Request-ID": "bad id\nwith newline"})
    assert uuid.UUID(unsafe.headers["X-Request-ID"])


async def test_access_log_has_request_id_route_template_and_principal(
    client: AsyncClient, logs: JSONCapture
) -> None:
    owner = await signup(client, "owner@example.com")
    ticket_id = uuid.uuid4()
    await client.get(
        f"/api/v1/tickets/{ticket_id}", headers={**owner.headers, "X-Request-ID": "trace-1"}
    )
    [entry] = [e for e in logs.entries() if e["logger"] == "app.access" and e["request_id"] == "trace-1"]
    assert entry["route"] == "/api/v1/tickets/{ticket_id}"
    assert entry["status"] == 404
    assert entry["workspace_id"] == str(owner.workspace_id)
    assert entry["user_id"] == str(owner.user_id)
    assert isinstance(entry["duration_ms"], float)
    assert str(ticket_id) not in json.dumps(entry)


async def test_request_id_reaches_jobs_enqueued_by_requests(
    app: FastAPI, client: AsyncClient, job_queue: RecordingQueue, settings  # noqa: F811
) -> None:
    owner = await signup(client, "owner@example.com")
    resp = await client.post(
        "/api/v1/tickets",
        json={"subject": "Hi", "description": "Help"},
        headers={**owner.headers, "X-Request-ID": "create-ticket-1"},
    )
    assert resp.status_code == 201
    assert job_queue.request_ids[-1] == ("process_ticket", "create-ticket-1")

    # A widget message that falls back opens a ticket and queues its draft in the same trace.
    use_llm(app, "unused")
    session = await open_widget(client, await widget_key(client, owner, [SHOP_ORIGIN]))
    resp = await client.post(
        "/api/v1/widget/messages",
        json={"content": "Something the docs don't cover"},
        headers={**session.headers, "X-Request-ID": "widget-msg-1"},
    )
    assert resp.status_code == 200
    assert job_queue.request_ids[-1] == ("process_ticket", "widget-msg-1")


class FakePool:
    def __init__(self) -> None:
        self.calls: list[tuple[tuple, dict]] = []

    async def enqueue_job(self, *args, **kwargs) -> None:
        self.calls.append((args, kwargs))


async def test_arq_queue_sends_the_current_request_id_with_every_job() -> None:
    from app.core.middleware import request_id_ctx

    pool = FakePool()
    queue = ArqJobQueue(pool)  # type: ignore[arg-type]
    token = request_id_ctx.set("req-42")
    try:
        await queue.enqueue_ingest(uuid.uuid4(), uuid.uuid4())
        await queue.enqueue_process_ticket(uuid.uuid4(), uuid.uuid4())
        await queue.enqueue_execute_action(uuid.uuid4(), uuid.uuid4(), "key")
    finally:
        request_id_ctx.reset(token)
    assert [kwargs["request_id"] for _, kwargs in pool.calls] == ["req-42"] * 3
    assert pool.calls[2][1]["_job_id"] == "execute_action:key"

    await queue.enqueue_ingest(uuid.uuid4(), uuid.uuid4())
    assert "request_id" not in pool.calls[-1][1]


async def test_traced_job_restores_the_request_id_and_passes_it_on(logs: JSONCapture) -> None:
    """A job enqueued from a request runs with that request's id, and jobs it enqueues
    (execute_action -> process_ticket) carry the same id."""
    queue = RecordingQueue()
    ticket_id, workspace_id = uuid.uuid4(), uuid.uuid4()
    seen: dict[str, str] = {}

    async def execute_action(ctx: dict, action_id: str, ws_id: str) -> str:
        seen["request_id"] = get_request_id()
        logging.getLogger("app.workers.actions").info("Action finished (action_id=%s)", action_id)
        await queue.enqueue_process_ticket(ticket_id, uuid.UUID(ws_id))
        return "succeeded"

    job = traced("execute_action", execute_action)
    before = JOBS.values.get(("execute_action", "ok"), 0)
    result = await job({"job_id": "j1", "job_try": 1}, "a1", str(workspace_id), request_id="widget-msg-1")

    assert result == "succeeded"
    assert seen["request_id"] == "widget-msg-1"
    assert queue.request_ids == [("process_ticket", "widget-msg-1")]
    assert JOBS.values[("execute_action", "ok")] == before + 1
    action_log = next(e for e in logs.entries() if e["logger"] == "app.workers.actions")
    assert action_log["request_id"] == "widget-msg-1"
    assert action_log["job"] == "execute_action"
    assert action_log["job_id"] == "j1"
    assert action_log["workspace_id"] == str(workspace_id)
    finished = next(e for e in logs.entries() if e["logger"] == "app.workers.jobs")
    assert finished["outcome"] == "ok"
    # Outside the job, the context is gone.
    assert get_request_id() == ""


async def test_traced_job_counts_retries_and_failures() -> None:
    async def retrying(ctx: dict, *args: str) -> None:
        raise Retry(defer=1)

    async def failing(ctx: dict, *args: str) -> None:
        raise RuntimeError("boom")

    retries = JOBS.values.get(("retrying", "retry"), 0)
    errors = JOBS.values.get(("failing", "error"), 0)
    with pytest.raises(Retry):
        await traced("retrying", retrying)({}, "x", str(uuid.uuid4()))
    with pytest.raises(RuntimeError):
        await traced("failing", failing)({}, "x", str(uuid.uuid4()))
    assert JOBS.values[("retrying", "retry")] == retries + 1
    assert JOBS.values[("failing", "error")] == errors + 1


# Sensitive data -----------------------------------------------------------------------------


def test_redaction_scrubs_emails_tokens_and_keys() -> None:
    jwt = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.c2lnbmF0dXJlLXZhbHVl"
    text = (
        f"user jane.doe@example.com sent Authorization: Bearer {jwt} "
        "key=sk-proj-abcdefghijklmnop password=hunter2"
    )
    cleaned = redact(text)
    for secret in ("jane.doe@example.com", jwt, "sk-proj-abcdefghijklmnop", "hunter2"):
        assert secret not in cleaned


def test_json_formatter_redacts_messages_and_exceptions() -> None:
    logger = logging.getLogger("app.test.redaction")
    capture = JSONCapture()
    logger.addHandler(capture)
    try:
        bind_log_context(workspace_id="w1")
        logger.warning("Login failed for %s", "someone@example.com")
        try:
            raise ValueError("token=abc123 for bob@example.com")
        except ValueError:
            logger.exception("Unexpected")
    finally:
        logger.removeHandler(capture)
    output = "\n".join(capture.lines)
    assert "someone@example.com" not in output and "bob@example.com" not in output
    assert "abc123" not in output
    assert all(json.loads(line)["workspace_id"] == "w1" for line in capture.lines)


async def test_no_message_bodies_emails_or_tokens_in_logs(
    app: FastAPI, client: AsyncClient, logs: JSONCapture, settings  # noqa: F811
) -> None:
    owner = await signup(client, "private.person@example.com")
    login = await client.post(
        "/api/v1/auth/login", json={"email": "private.person@example.com", "password": PASSWORD}
    )
    access_token = login.json()["access_token"]
    client.cookies.clear()
    await client.post(
        "/api/v1/auth/login", json={"email": "nobody@example.com", "password": "Wrong-Pass-123"}
    )

    use_llm(app, "unused")
    session = await open_widget(client, await widget_key(client, owner, [SHOP_ORIGIN]))
    body = "My card 4111 is lost, email me at customer.secret@example.org UNIQUE-BODY-MARKER"
    await ask(client, session, body)
    await client.get("/api/v1/conversations", headers={"Authorization": f"Bearer {access_token}"})

    output = "\n".join(logs.lines)
    assert logs.lines, "expected log output"
    for secret in (
        "private.person@example.com",
        "nobody@example.com",
        "customer.secret@example.org",
        "UNIQUE-BODY-MARKER",
        PASSWORD,
        "Wrong-Pass-123",
        access_token,
        session.token,
    ):
        assert secret not in output, secret


# Metrics -----------------------------------------------------------------------------------


def test_registry_renders_prometheus_text_and_merges_worker_snapshots() -> None:
    reg = Registry()
    requests = reg.counter("t_requests_total", "Requests.", ("route",))
    latency = reg.histogram("t_latency_seconds", "Latency.", ("route",), (0.1, 1.0))
    requests.inc(route="/a")
    latency.observe(0.05, route="/a")
    latency.observe(0.5, route="/a")

    worker = Registry()
    worker.counter("t_requests_total", "Requests.", ("route",)).inc(2, route="/a")
    text = reg.render([json.loads(worker.dumps())])

    assert "# TYPE t_requests_total counter" in text
    assert 't_requests_total{route="/a"} 3' in text
    assert 't_latency_seconds_bucket{route="/a",le="0.1"} 1' in text
    assert 't_latency_seconds_bucket{route="/a",le="1"} 2' in text
    assert 't_latency_seconds_bucket{route="/a",le="+Inf"} 2' in text
    assert 't_latency_seconds_count{route="/a"} 2' in text
    assert 't_latency_seconds_sum{route="/a"} 0.55' in text


@pytest.fixture
def metrics_token(monkeypatch: pytest.MonkeyPatch) -> str:
    monkeypatch.setattr(get_settings(), "metrics_token", SecretStr("scrape-secret"))
    worker = Registry()
    worker.counter("resolveai_jobs_total", "Jobs.", ("job", "status")).inc(
        4, job="process_ticket", status="ok"
    )
    monkeypatch.setattr(
        health, "_worker_snapshots", AsyncMock(return_value=[json.loads(worker.dumps())])
    )
    return "scrape-secret"


async def test_metrics_is_off_without_a_token(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(get_settings(), "metrics_token", None)
    assert (await client.get("/metrics")).status_code == 404


async def test_metrics_requires_the_token(client: AsyncClient, metrics_token: str) -> None:
    assert (await client.get("/metrics")).status_code == 401
    wrong = await client.get("/metrics", headers={"Authorization": "Bearer nope"})
    assert wrong.status_code == 401


async def test_metrics_reports_requests_llm_calls_and_worker_jobs(
    client: AsyncClient, metrics_token: str
) -> None:
    owner = await signup(client, "owner@example.com")
    await client.get("/api/v1/tickets", headers=owner.headers)
    await record_llm_call(
        workspace_id=owner.workspace_id,
        purpose="classify",
        provider="fake",
        model="clef-test",
        input_tokens=120,
        output_tokens=0,
        cost_usd=Decimal("0.0001"),
        latency_ms=250,
        status=LLMCallStatus.OK,
    )

    resp = await client.get("/metrics", headers={"Authorization": f"Bearer {metrics_token}"})
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/plain")
    text = resp.text
    assert 'resolveai_http_requests_total{method="GET",route="/api/v1/tickets",status="200"}' in text
    assert 'resolveai_http_request_duration_seconds_bucket{method="GET",route="/api/v1/tickets"' in text
    assert 'resolveai_llm_calls_total{model="clef-test",purpose="classify",status="ok"}' in text
    assert (
        'resolveai_llm_tokens_total{model="clef-test",purpose="classify",direction="input"} 120'
        in text
    )
    assert 'resolveai_llm_cost_usd_total{model="clef-test",purpose="classify"}' in text
    assert 'resolveai_jobs_total{job="process_ticket",status="ok"}' in text
    assert "/metrics" not in text.split("resolveai_http_requests_total", 1)[1].split("# HELP")[0]
    assert str(owner.workspace_id) not in text


# Health ------------------------------------------------------------------------------------


def test_worker_status() -> None:
    assert health.worker_status(None, 60) == "missing"
    assert health.worker_status(str(time.time() - 5), 60) == "ok"
    assert health.worker_status(str(time.time() - 300).encode(), 60) == "stale"
    assert health.worker_status("garbage", 60) == "missing"


@pytest.mark.parametrize(("heartbeat_age", "worker"), [(300, "stale"), (None, "missing")])
async def test_unhealthy_worker_degrades_ready_but_keeps_200(
    heartbeat_age: int | None, worker: str
) -> None:
    from app.core.database import get_db
    from app.main import create_app

    app = create_app()
    app.dependency_overrides[get_db] = lambda: AsyncMock()
    with patch("redis.asyncio.from_url") as from_url:
        redis = AsyncMock()
        redis.get = AsyncMock(
            return_value=None if heartbeat_age is None else str(time.time() - heartbeat_age)
        )
        from_url.return_value = redis
        from httpx import ASGITransport

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.get("/health/ready")
    assert resp.status_code == 200
    assert resp.json() == {
        "status": "degraded",
        "checks": {"postgres": "ok", "redis": "ok", "worker": worker},
    }


async def test_heartbeat_writes_liveness_and_publishes_metrics() -> None:
    redis = AsyncMock()
    await heartbeat({"redis": redis})
    keys = [call.args[0] for call in redis.set.await_args_list]
    assert keys[0] == "worker:heartbeat"
    assert keys[1].startswith("metrics:worker:")
    assert abs(float(redis.set.await_args_list[0].args[1]) - time.time()) < 5
    json.loads(redis.set.await_args_list[1].args[1])
