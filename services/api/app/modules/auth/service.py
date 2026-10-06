import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from functools import lru_cache

from fastapi import HTTPException, status
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.deps import Principal, set_tenant_context
from app.core.security import (
    create_access_token,
    hash_password,
    hash_refresh_token,
    new_refresh_token,
    verify_password,
)
from app.modules.auth.models import RefreshToken, User
from app.modules.auth.schemas import PASSWORD_MIN_LENGTH
from app.modules.workspaces import service as workspaces_service
from app.modules.workspaces.models import Role, Workspace

INVALID_CREDENTIALS = "Invalid email or password"
INVALID_REFRESH = "Invalid or expired refresh token"


@dataclass
class AuthResult:
    user: User
    workspace: Workspace
    role: Role
    access_token: str
    refresh_token: str


def normalize_email(email: str) -> str:
    return email.strip().lower()


@lru_cache
def _dummy_password_hash() -> str:
    return hash_password("timing-equalizer-not-a-real-password")


def _unauthorized(message: str) -> HTTPException:
    return HTTPException(
        status.HTTP_401_UNAUTHORIZED, message, headers={"WWW-Authenticate": "Bearer"}
    )


async def _issue_tokens(
    session: AsyncSession,
    user: User,
    workspace: Workspace,
    role: Role,
    family_id: uuid.UUID | None = None,
) -> tuple[AuthResult, RefreshToken]:
    settings = get_settings()
    raw, token_hash = new_refresh_token()
    record = RefreshToken(
        id=uuid.uuid4(),
        user_id=user.id,
        workspace_id=workspace.id,
        token_hash=token_hash,
        family_id=family_id or uuid.uuid4(),
        expires_at=datetime.now(UTC) + timedelta(days=settings.refresh_token_ttl_days),
    )
    session.add(record)
    await session.flush()
    result = AuthResult(
        user=user,
        workspace=workspace,
        role=role,
        access_token=create_access_token(user.id, workspace.id, role.value),
        refresh_token=raw,
    )
    return result, record


async def signup(
    session: AsyncSession,
    email: str,
    password: str,
    full_name: str,
    workspace_name: str,
) -> AuthResult:
    email = normalize_email(email)
    if len(password) < PASSWORD_MIN_LENGTH:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"Password must be at least {PASSWORD_MIN_LENGTH} characters",
        )

    existing = await session.execute(select(User.id).where(User.email == email))
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Email is already registered")

    # IDs are generated first so the RLS context can point at the new workspace
    # before any tenant row is written.
    user_id = uuid.uuid4()
    workspace_id = uuid.uuid4()
    await set_tenant_context(session, workspace_id, user_id)

    user = User(
        id=user_id,
        email=email,
        password_hash=hash_password(password),
        full_name=full_name.strip(),
    )
    try:
        async with session.begin_nested():
            session.add(user)
            await session.flush()
    except IntegrityError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, "Email is already registered") from exc

    workspace = await workspaces_service.create_workspace_with_owner(
        session, workspace_id, workspace_name.strip(), user_id
    )
    result, _ = await _issue_tokens(session, user, workspace, Role.OWNER)
    return result


async def login(session: AsyncSession, email: str, password: str) -> AuthResult:
    email = normalize_email(email)
    user = (await session.execute(select(User).where(User.email == email))).scalar_one_or_none()
    if user is None:
        # Spend the same hashing time so response timing doesn't reveal unknown emails.
        verify_password(password, _dummy_password_hash())
        raise _unauthorized(INVALID_CREDENTIALS)
    if not verify_password(password, user.password_hash) or not user.is_active:
        raise _unauthorized(INVALID_CREDENTIALS)

    await set_tenant_context(session, None, user.id)
    membership = await workspaces_service.get_latest_membership(session, user.id)
    if membership is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "User has no workspace membership")

    await set_tenant_context(session, membership.workspace_id, user.id)
    workspace = await workspaces_service.get_workspace(session, membership.workspace_id)
    result, _ = await _issue_tokens(session, user, workspace, membership.role)
    return result


async def _revoke_family(session: AsyncSession, family_id: uuid.UUID) -> None:
    await session.execute(
        update(RefreshToken)
        .where(RefreshToken.family_id == family_id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=datetime.now(UTC))
    )


async def refresh(session: AsyncSession, raw_token: str | None) -> AuthResult:
    if not raw_token:
        raise _unauthorized(INVALID_REFRESH)

    token = (
        await session.execute(
            select(RefreshToken)
            .where(RefreshToken.token_hash == hash_refresh_token(raw_token))
            .with_for_update()
        )
    ).scalar_one_or_none()
    if token is None:
        raise _unauthorized(INVALID_REFRESH)

    if token.revoked_at is not None or token.replaced_by_id is not None:
        # Reuse of a rotated/revoked token: assume theft and kill the whole family.
        # Committed before raising, otherwise the error would roll the revocation back.
        await _revoke_family(session, token.family_id)
        await session.commit()
        raise _unauthorized(INVALID_REFRESH)

    now = datetime.now(UTC)
    if token.expires_at <= now:
        raise _unauthorized(INVALID_REFRESH)

    user = await session.get(User, token.user_id)
    await set_tenant_context(session, token.workspace_id, token.user_id)
    membership = await workspaces_service.get_membership(
        session, token.user_id, token.workspace_id
    )
    if user is None or not user.is_active or membership is None:
        await _revoke_family(session, token.family_id)
        await session.commit()
        raise _unauthorized(INVALID_REFRESH)

    workspace = await workspaces_service.get_workspace(session, token.workspace_id)
    result, new_record = await _issue_tokens(
        session, user, workspace, membership.role, family_id=token.family_id
    )
    token.replaced_by_id = new_record.id
    token.revoked_at = now
    await session.flush()
    return result


async def logout(session: AsyncSession, raw_token: str | None) -> None:
    if not raw_token:
        return
    await session.execute(
        update(RefreshToken)
        .where(
            RefreshToken.token_hash == hash_refresh_token(raw_token),
            RefreshToken.revoked_at.is_(None),
        )
        .values(revoked_at=datetime.now(UTC))
    )


async def get_me(session: AsyncSession, principal: Principal) -> tuple[User, Workspace]:
    user = await session.get(User, principal.user_id)
    if user is None or not user.is_active:
        raise _unauthorized("User not found or inactive")
    workspace = await workspaces_service.get_workspace(session, principal.workspace_id)
    return user, workspace


async def switch_workspace(
    session: AsyncSession, principal: Principal, workspace_id: uuid.UUID
) -> AuthResult:
    # The memberships policy exposes the caller's own memberships in any workspace.
    membership = await workspaces_service.get_membership(session, principal.user_id, workspace_id)
    if membership is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Workspace not found")

    user = await session.get(User, principal.user_id)
    if user is None or not user.is_active:
        raise _unauthorized("User not found or inactive")

    await set_tenant_context(session, workspace_id, principal.user_id)
    workspace = await workspaces_service.get_workspace(session, workspace_id)
    result, _ = await _issue_tokens(session, user, workspace, membership.role)
    return result
