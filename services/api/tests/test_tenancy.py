from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from tests.conftest import add_member, refresh_cookie, signup


async def test_workspace_a_cannot_reach_workspace_b(client: AsyncClient) -> None:
    a = await signup(client, "a@example.com", workspace_name="Tenant A")
    b = await signup(client, "b@example.com", workspace_name="Tenant B")

    # A only ever sees its own workspace.
    resp = await client.get("/api/v1/workspace/settings", headers=a.headers)
    assert resp.status_code == 200
    assert resp.json()["id"] == str(a.workspace_id)

    resp = await client.get("/api/v1/workspaces", headers=a.headers)
    assert [w["id"] for w in resp.json()] == [str(a.workspace_id)]

    # A cannot switch into B.
    resp = await client.post(f"/api/v1/workspaces/{b.workspace_id}/switch", headers=a.headers)
    assert resp.status_code == 404
    assert "refresh_token" not in resp.cookies

    # A's PATCH only touches A; B is unchanged.
    resp = await client.patch(
        "/api/v1/workspace/settings", json={"name": "Hijacked"}, headers=a.headers
    )
    assert resp.status_code == 200
    assert resp.json()["id"] == str(a.workspace_id)

    resp = await client.get("/api/v1/workspace/settings", headers=b.headers)
    assert resp.json()["name"] == "Tenant B"


async def test_patch_settings_validates(client: AsyncClient) -> None:
    a = await signup(client, "owner@example.com")
    resp = await client.patch(
        "/api/v1/workspace/settings",
        json={"allowed_origins": ["https://Shop.example.com/", "http://localhost:3000"]},
        headers=a.headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["allowed_origins"] == ["https://shop.example.com", "http://localhost:3000"]

    resp = await client.patch(
        "/api/v1/workspace/settings",
        json={"allowed_origins": ["javascript:alert(1)"]},
        headers=a.headers,
    )
    assert resp.status_code == 422

    resp = await client.patch(
        "/api/v1/workspace/settings",
        json={"widget_public_key": "mine-now"},
        headers=a.headers,
    )
    assert resp.status_code == 422


async def test_members_only_shows_own_workspace(
    client: AsyncClient, owner_engine: AsyncEngine
) -> None:
    a = await signup(client, "a@example.com", workspace_name="Tenant A")
    b = await signup(client, "b@example.com", workspace_name="Tenant B")
    await signup(client, "c@example.com", workspace_name="Tenant C")
    # B is also an agent in A. B's own membership in A is visible to B under RLS,
    # but must not show up in B's own workspace member list.
    await add_member(owner_engine, b.user_id, a.workspace_id, "agent")

    resp = await client.get("/api/v1/members", headers=a.headers)
    assert resp.status_code == 200
    assert sorted(m["email"] for m in resp.json()) == ["a@example.com", "b@example.com"]
    assert "password_hash" not in resp.text

    resp = await client.get("/api/v1/members", headers=b.headers)
    assert [(m["email"], m["role"]) for m in resp.json()] == [("b@example.com", "owner")]


async def test_agent_cannot_patch_settings(
    client: AsyncClient, owner_engine: AsyncEngine
) -> None:
    a = await signup(client, "a@example.com", workspace_name="Tenant A")
    b = await signup(client, "b@example.com", workspace_name="Tenant B")
    await add_member(owner_engine, b.user_id, a.workspace_id, "agent")

    resp = await client.post(f"/api/v1/workspaces/{a.workspace_id}/switch", headers=b.headers)
    assert resp.status_code == 200
    assert resp.json()["role"] == "agent"
    refresh_cookie(resp)
    client.cookies.clear()
    agent_headers = {"Authorization": f"Bearer {resp.json()['access_token']}"}

    resp = await client.get("/api/v1/workspace/settings", headers=agent_headers)
    assert resp.status_code == 200
    assert resp.json()["id"] == str(a.workspace_id)

    resp = await client.patch(
        "/api/v1/workspace/settings", json={"name": "Agent was here"}, headers=agent_headers
    )
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "forbidden"

    resp = await client.get("/api/v1/workspace/settings", headers=a.headers)
    assert resp.json()["name"] == "Tenant A"


async def test_rls_blocks_other_workspace_at_db_level(
    client: AsyncClient, app_role_engine: AsyncEngine
) -> None:
    a = await signup(client, "a@example.com", workspace_name="Tenant A")
    b = await signup(client, "b@example.com", workspace_name="Tenant B")
    set_context = text(
        "SELECT set_config('app.workspace_id', :wid, true), set_config('app.user_id', :uid, true)"
    )

    async with app_role_engine.connect() as conn, conn.begin():
        await conn.execute(set_context, {"wid": str(a.workspace_id), "uid": str(a.user_id)})

        ids = (await conn.execute(text("SELECT id FROM workspaces"))).scalars().all()
        assert ids == [a.workspace_id]

        # Even asking for B's row by id returns nothing.
        rows = await conn.execute(
            text("SELECT id FROM workspaces WHERE id = :id"), {"id": b.workspace_id}
        )
        assert rows.first() is None

        members = (
            await conn.execute(text("SELECT workspace_id FROM memberships"))
        ).scalars().all()
        assert members == [a.workspace_id]

        updated = await conn.execute(
            text("UPDATE workspaces SET name = 'pwned' WHERE id = :id"),
            {"id": b.workspace_id},
        )
        assert updated.rowcount == 0

    # No tenant context at all: nothing is visible, and unset settings don't error.
    async with app_role_engine.connect() as conn:
        assert (await conn.execute(text("SELECT count(*) FROM workspaces"))).scalar() == 0
        assert (await conn.execute(text("SELECT count(*) FROM memberships"))).scalar() == 0
