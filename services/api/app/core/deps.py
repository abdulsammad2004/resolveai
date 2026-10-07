import uuid
from collections.abc import AsyncGenerator, AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import async_session_factory
from app.core.security import decode_access_token

_bearer = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class Principal:
    user_id: uuid.UUID
    workspace_id: uuid.UUID
    role: str


async def get_principal(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> Principal:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    payload = decode_access_token(credentials.credentials)
    return Principal(
        user_id=uuid.UUID(payload["sub"]),
        workspace_id=uuid.UUID(payload["wid"]),
        role=payload["role"],
    )


CurrentPrincipal = Annotated[Principal, Depends(get_principal)]


async def set_tenant_context(
    session: AsyncSession,
    workspace_id: uuid.UUID | None,
    user_id: uuid.UUID | None,
) -> None:
    """Set transaction-local RLS context. Values are bound parameters, never formatted."""
    await session.execute(
        text("SELECT set_config('app.workspace_id', :wid, true), set_config('app.user_id', :uid, true)"),
        {
            "wid": str(workspace_id) if workspace_id else "",
            "uid": str(user_id) if user_id else "",
        },
    )


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """Transactional session with no tenant context, for the auth flows (signup/login/refresh)."""
    async with async_session_factory() as session, session.begin():
        yield session


@asynccontextmanager
async def tenant_session(
    workspace_id: uuid.UUID, user_id: uuid.UUID | None = None
) -> AsyncIterator[AsyncSession]:
    """One transaction as the app role with RLS context set. Commits on success.

    Shared by request handlers (via get_tenant_db) and background workers.
    """
    async with async_session_factory() as session, session.begin():
        await set_tenant_context(session, workspace_id, user_id)
        yield session


async def get_tenant_db(principal: CurrentPrincipal) -> AsyncGenerator[AsyncSession, None]:
    async with tenant_session(principal.workspace_id, principal.user_id) as session:
        yield session


DBSession = Annotated[AsyncSession, Depends(get_session)]
TenantDB = Annotated[AsyncSession, Depends(get_tenant_db)]


def require_role(*roles: str) -> Callable[[Principal], Awaitable[Principal]]:
    allowed = frozenset(roles)

    async def checker(principal: CurrentPrincipal) -> Principal:
        if principal.role not in allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient role for this action",
            )
        return principal

    return checker
