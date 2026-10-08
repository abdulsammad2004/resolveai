import json
import os
import subprocess
import sys
import uuid
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from pathlib import Path

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient, Response
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import Settings, get_settings

# Point the app at the test database (runtime role) before any engine is created.
# Tests never call OpenAI: force the deterministic fake embedder and chat client.
os.environ["EMBEDDING_PROVIDER"] = "fake"
os.environ["LLM_PROVIDER"] = "fake"
# Tests opt in to the dev localhost allowance explicitly, whatever the local .env says.
os.environ["WIDGET_DEV_ALLOW_LOCALHOST"] = "false"
_settings = Settings()
os.environ["DATABASE_URL"] = _settings.test_database_url
get_settings.cache_clear()

from app.ai.embeddings import FakeEmbeddingClient
from app.core.database import engine as app_engine
from app.core.storage import LocalStorage, get_storage
from app.main import create_app
from app.modules.conversations.limits import get_widget_limiter
from app.workers.queue import get_job_queue

API_DIR = Path(__file__).resolve().parents[1]
TEST_OWNER_URL = _settings.test_migrations_database_url
TEST_APP_URL = _settings.test_database_url
TABLES = (
    "feedback",
    "messages",
    "conversations",
    "contacts",
    "llm_calls",
    "document_chunks",
    "documents",
    "refresh_tokens",
    "memberships",
    "workspaces",
    "users",
)
PASSWORD = "correct-horse-battery"


@pytest.fixture(scope="session", autouse=True)
def migrate_test_db() -> None:
    subprocess.run(
        [sys.executable, "-m", "alembic", "-x", f"db_url={TEST_OWNER_URL}", "upgrade", "head"],
        cwd=API_DIR,
        check=True,
    )


@pytest.fixture
async def owner_engine() -> AsyncGenerator[AsyncEngine, None]:
    """Owner-role engine for test setup only (truncation, direct inserts)."""
    eng = create_async_engine(TEST_OWNER_URL, poolclass=NullPool)
    yield eng
    await eng.dispose()


@pytest.fixture
async def app_role_engine() -> AsyncGenerator[AsyncEngine, None]:
    """Runtime-role engine, subject to RLS, for database-level isolation checks."""
    eng = create_async_engine(TEST_APP_URL, poolclass=NullPool)
    yield eng
    await eng.dispose()


@pytest.fixture(autouse=True)
async def clean_tables(owner_engine: AsyncEngine) -> AsyncGenerator[None, None]:
    async with owner_engine.begin() as conn:
        await conn.execute(text(f"TRUNCATE {', '.join(TABLES)} CASCADE"))
    yield
    # Each test runs on its own event loop; drop pooled connections bound to this one.
    await app_engine.dispose()


class RecordingQueue:
    """Stands in for Redis/arq: records enqueued jobs instead of sending them."""

    def __init__(self) -> None:
        self.jobs: list[tuple[uuid.UUID, uuid.UUID]] = []

    async def enqueue_ingest(self, document_id: uuid.UUID, workspace_id: uuid.UUID) -> None:
        self.jobs.append((document_id, workspace_id))


class InMemoryLimiter:
    """Stands in for Redis: rate-limit counters and the daily token budget in a dict."""

    def __init__(self) -> None:
        self.hits: dict[str, int] = {}
        self.tokens: dict[uuid.UUID, int] = {}

    async def allow(self, key: str, limit: int, window_s: int) -> bool:
        self.hits[key] = self.hits.get(key, 0) + 1
        return self.hits[key] <= limit

    async def tokens_used_today(self, workspace_id: uuid.UUID) -> int:
        return self.tokens.get(workspace_id, 0)

    async def add_tokens(self, workspace_id: uuid.UUID, tokens: int) -> None:
        self.tokens[workspace_id] = self.tokens.get(workspace_id, 0) + tokens


@pytest.fixture
def storage(tmp_path: Path) -> LocalStorage:
    return LocalStorage(tmp_path / "storage")


@pytest.fixture
def job_queue() -> RecordingQueue:
    return RecordingQueue()


@pytest.fixture
def worker_ctx(storage: LocalStorage) -> dict:
    """arq-style context for calling worker jobs directly."""
    return {
        "storage": storage,
        "embedder": FakeEmbeddingClient(_settings.embedding_dim),
        "job_try": 1,
    }


@pytest.fixture
def limiter() -> InMemoryLimiter:
    return InMemoryLimiter()


@pytest.fixture
def app(storage: LocalStorage, job_queue: RecordingQueue, limiter: InMemoryLimiter) -> FastAPI:
    app = create_app()
    app.dependency_overrides[get_storage] = lambda: storage
    app.dependency_overrides[get_job_queue] = lambda: job_queue
    app.dependency_overrides[get_widget_limiter] = lambda: limiter
    return app


@pytest.fixture
async def client(app: FastAPI) -> AsyncGenerator[AsyncClient, None]:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


@dataclass
class SignedUp:
    user_id: uuid.UUID
    workspace_id: uuid.UUID
    email: str
    access_token: str
    refresh_token: str

    @property
    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.access_token}"}


def refresh_cookie(resp: Response) -> str:
    value = resp.cookies.get("refresh_token")
    assert value, "expected a refresh_token cookie"
    return value


async def post_with_refresh(client: AsyncClient, url: str, token: str) -> Response:
    """POST with exactly this refresh cookie, ignoring whatever the client jar holds."""
    client.cookies.clear()
    resp = await client.post(url, headers={"Cookie": f"refresh_token={token}"})
    client.cookies.clear()
    return resp


async def signup(
    client: AsyncClient,
    email: str,
    workspace_name: str = "Acme Support",
    full_name: str = "Test User",
) -> SignedUp:
    resp = await client.post(
        "/api/v1/auth/signup",
        json={
            "email": email,
            "password": PASSWORD,
            "full_name": full_name,
            "workspace_name": workspace_name,
        },
    )
    assert resp.status_code == 201, resp.text
    client.cookies.clear()
    body = resp.json()
    return SignedUp(
        user_id=uuid.UUID(body["user"]["id"]),
        workspace_id=uuid.UUID(body["workspace"]["id"]),
        email=body["user"]["email"],
        access_token=body["access_token"],
        refresh_token=refresh_cookie(resp),
    )


async def add_member(
    owner_engine: AsyncEngine, user_id: uuid.UUID, workspace_id: uuid.UUID, role: str
) -> None:
    """Insert a membership directly (there is no invite endpoint yet)."""
    async with owner_engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO memberships (id, user_id, workspace_id, role) "
                "VALUES (:id, :uid, :wid, CAST(:role AS membership_role))"
            ),
            {"id": uuid.uuid4(), "uid": user_id, "wid": workspace_id, "role": role},
        )


MD_DOC = (
    b"# Returns policy\n\nItems can be returned within 30 days of delivery.\n\n"
    b"## Refunds\n\nRefunds go back to the original payment method within 5 business days.\n\n"
    b"## Exchanges\n\nExchanges are free for items of the same price.\n"
)


async def upload_file(
    client: AsyncClient,
    headers: dict[str, str],
    filename: str = "returns.md",
    content: bytes = MD_DOC,
) -> Response:
    return await client.post(
        "/api/v1/documents",
        files={"file": (filename, content, "application/octet-stream")},
        headers=headers,
    )


async def as_agent_in(
    client: AsyncClient, owner_engine: AsyncEngine, agent: SignedUp, workspace_id: uuid.UUID
) -> dict[str, str]:
    """Make `agent` an agent in `workspace_id` and return headers for that workspace."""
    await add_member(owner_engine, agent.user_id, workspace_id, "agent")
    resp = await client.post(f"/api/v1/workspaces/{workspace_id}/switch", headers=agent.headers)
    assert resp.status_code == 200, resp.text
    client.cookies.clear()
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


SHOP_ORIGIN = "https://shop.example"
APP_ORIGIN = "http://localhost:3000"


@dataclass
class WidgetSession:
    token: str
    conversation_id: uuid.UUID
    anonymous_id: str
    workspace_name: str

    @property
    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}"}


async def widget_key(client: AsyncClient, owner: SignedUp, origins: list[str]) -> str:
    """Set the workspace's allowed origins and return its widget key."""
    resp = await client.patch(
        "/api/v1/workspace/settings", json={"allowed_origins": origins}, headers=owner.headers
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["widget_public_key"]


async def open_widget(
    client: AsyncClient, key: str, origin: str = SHOP_ORIGIN, **body: object
) -> WidgetSession:
    resp = await client.post(
        "/api/v1/widget/session",
        json={"public_key": key, **body},
        headers={"Origin": origin},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    return WidgetSession(
        token=data["token"],
        conversation_id=uuid.UUID(data["conversation_id"]),
        anonymous_id=data["anonymous_id"],
        workspace_name=data["workspace_name"],
    )


def parse_sse(body: str) -> list[tuple[str, dict]]:
    """Split an SSE body into (event, data) pairs; comment lines are skipped."""
    events = []
    for block in body.split("\n\n"):
        name, data = "message", None
        for line in block.splitlines():
            if line.startswith("event: "):
                name = line[len("event: ") :]
            elif line.startswith("data: "):
                data = json.loads(line[len("data: ") :])
        if data is not None:
            events.append((name, data))
    return events
