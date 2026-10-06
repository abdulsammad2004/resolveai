import os
import subprocess
import sys
import uuid
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient, Response
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import Settings, get_settings

# Point the app at the test database (runtime role) before any engine is created.
_settings = Settings()
os.environ["DATABASE_URL"] = _settings.test_database_url
get_settings.cache_clear()

from app.core.database import engine as app_engine
from app.main import create_app

API_DIR = Path(__file__).resolve().parents[1]
TEST_OWNER_URL = _settings.test_migrations_database_url
TEST_APP_URL = _settings.test_database_url
TABLES = ("refresh_tokens", "memberships", "workspaces", "users")
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


@pytest.fixture
async def client() -> AsyncGenerator[AsyncClient, None]:
    app = create_app()
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
