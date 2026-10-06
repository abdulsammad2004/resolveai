from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from tests.conftest import PASSWORD, add_member, post_with_refresh, refresh_cookie, signup


async def test_signup_login_me(client: AsyncClient) -> None:
    resp = await client.post(
        "/api/v1/auth/signup",
        json={
            "email": "Alice@Example.com",
            "password": PASSWORD,
            "full_name": "Alice",
            "workspace_name": "Alice Co",
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["token_type"] == "bearer"
    assert body["role"] == "owner"
    assert body["user"]["email"] == "alice@example.com"
    assert body["workspace"]["slug"] == "alice-co"
    assert "password_hash" not in resp.text
    set_cookie = resp.headers["set-cookie"].lower()
    assert "httponly" in set_cookie
    assert "samesite=lax" in set_cookie
    assert "path=/api/v1/auth" in set_cookie
    client.cookies.clear()

    resp = await client.post(
        "/api/v1/auth/login", json={"email": "alice@EXAMPLE.com", "password": PASSWORD}
    )
    assert resp.status_code == 200, resp.text
    login = resp.json()
    assert login["workspace"]["id"] == body["workspace"]["id"]
    assert refresh_cookie(resp)

    resp = await client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {login['access_token']}"}
    )
    assert resp.status_code == 200, resp.text
    me = resp.json()
    assert me["user"]["id"] == body["user"]["id"]
    assert me["workspace"]["id"] == body["workspace"]["id"]
    assert me["role"] == "owner"


async def test_wrong_password_and_unknown_email_same_401(client: AsyncClient) -> None:
    await signup(client, "bob@example.com")

    wrong_pw = await client.post(
        "/api/v1/auth/login", json={"email": "bob@example.com", "password": "nope-nope-nope"}
    )
    unknown = await client.post(
        "/api/v1/auth/login", json={"email": "nobody@example.com", "password": PASSWORD}
    )
    assert wrong_pw.status_code == 401
    assert unknown.status_code == 401
    assert wrong_pw.json()["error"]["message"] == unknown.json()["error"]["message"]


async def test_duplicate_email_409(client: AsyncClient) -> None:
    await signup(client, "carol@example.com")
    resp = await client.post(
        "/api/v1/auth/signup",
        json={
            "email": "CAROL@example.com",
            "password": PASSWORD,
            "full_name": "Carol 2",
            "workspace_name": "Other",
        },
    )
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "conflict"


async def test_short_password_rejected(client: AsyncClient) -> None:
    resp = await client.post(
        "/api/v1/auth/signup",
        json={
            "email": "dan@example.com",
            "password": "short",
            "full_name": "Dan",
            "workspace_name": "Dan Co",
        },
    )
    assert resp.status_code == 422
    assert "short" not in resp.json()["error"]["message"]


async def test_duplicate_workspace_names_get_suffixed_slugs(client: AsyncClient) -> None:
    await signup(client, "a1@example.com", workspace_name="Same Name")
    await signup(client, "a2@example.com", workspace_name="Same Name")
    third = await signup(client, "a3@example.com", workspace_name="Same Name")
    resp = await client.get("/api/v1/workspace/settings", headers=third.headers)
    assert resp.json()["slug"] == "same-name-3"


async def test_refresh_rotates(client: AsyncClient) -> None:
    user = await signup(client, "erin@example.com")

    resp = await post_with_refresh(client, "/api/v1/auth/refresh", user.refresh_token)
    assert resp.status_code == 200, resp.text
    new_refresh = refresh_cookie(resp)
    assert new_refresh != user.refresh_token

    new_access = resp.json()["access_token"]
    me = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {new_access}"})
    assert me.status_code == 200

    resp = await post_with_refresh(client, "/api/v1/auth/refresh", new_refresh)
    assert resp.status_code == 200


async def test_refresh_reuse_revokes_family(client: AsyncClient) -> None:
    user = await signup(client, "frank@example.com")
    first = user.refresh_token

    resp = await post_with_refresh(client, "/api/v1/auth/refresh", first)
    assert resp.status_code == 200
    second = refresh_cookie(resp)

    # Replaying the already-rotated token is treated as theft...
    resp = await post_with_refresh(client, "/api/v1/auth/refresh", first)
    assert resp.status_code == 401

    # ...so the newer token in the same family is dead too.
    resp = await post_with_refresh(client, "/api/v1/auth/refresh", second)
    assert resp.status_code == 401


async def test_refresh_without_cookie_401(client: AsyncClient) -> None:
    resp = await client.post("/api/v1/auth/refresh")
    assert resp.status_code == 401


async def test_logout_revokes_refresh_token(client: AsyncClient) -> None:
    user = await signup(client, "grace@example.com")

    resp = await post_with_refresh(client, "/api/v1/auth/logout", user.refresh_token)
    assert resp.status_code == 204
    assert 'refresh_token=""' in resp.headers["set-cookie"] or "max-age=0" in (
        resp.headers["set-cookie"].lower()
    )

    resp = await post_with_refresh(client, "/api/v1/auth/refresh", user.refresh_token)
    assert resp.status_code == 401


async def test_switch_workspace_and_refresh_keeps_it(client: AsyncClient) -> None:
    user = await signup(client, "heidi@example.com", workspace_name="First")
    resp = await client.post("/api/v1/workspaces", json={"name": "Second"}, headers=user.headers)
    assert resp.status_code == 201, resp.text
    second_id = resp.json()["id"]
    assert resp.json()["role"] == "owner"

    resp = await client.post(f"/api/v1/workspaces/{second_id}/switch", headers=user.headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["workspace"]["id"] == second_id
    switched_refresh = refresh_cookie(resp)
    client.cookies.clear()

    resp = await post_with_refresh(client, "/api/v1/auth/refresh", switched_refresh)
    assert resp.status_code == 200
    assert resp.json()["workspace"]["id"] == second_id


async def test_refresh_rechecks_membership(
    client: AsyncClient, owner_engine: AsyncEngine
) -> None:
    owner = await signup(client, "ivan@example.com", workspace_name="Ivan Co")
    agent = await signup(client, "judy@example.com", workspace_name="Judy Co")
    await add_member(owner_engine, agent.user_id, owner.workspace_id, "agent")

    resp = await client.post(
        f"/api/v1/workspaces/{owner.workspace_id}/switch", headers=agent.headers
    )
    assert resp.status_code == 200
    assert resp.json()["role"] == "agent"
    agent_refresh = refresh_cookie(resp)
    client.cookies.clear()

    async with owner_engine.begin() as conn:
        await conn.execute(
            text("DELETE FROM memberships WHERE user_id = :u AND workspace_id = :w"),
            {"u": agent.user_id, "w": owner.workspace_id},
        )

    resp = await post_with_refresh(client, "/api/v1/auth/refresh", agent_refresh)
    assert resp.status_code == 401


async def test_me_requires_valid_token(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/auth/me")
    assert resp.status_code == 401
    resp = await client.get("/api/v1/auth/me", headers={"Authorization": "Bearer not-a-jwt"})
    assert resp.status_code == 401


async def test_error_shape_and_request_id(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/auth/me", headers={"X-Request-ID": "req-abc-123"})
    assert resp.status_code == 401
    assert resp.headers["x-request-id"] == "req-abc-123"
    assert resp.json() == {
        "error": {
            "code": "unauthorized",
            "message": "Not authenticated",
            "request_id": "req-abc-123",
        }
    }

    resp = await client.post("/api/v1/auth/login", json={"email": "not-an-email"})
    assert resp.status_code == 422
    error = resp.json()["error"]
    assert error["code"] == "validation_error"
    assert error["request_id"] == resp.headers["x-request-id"]
    assert len(error["request_id"]) == 36
