import re
import secrets
import uuid

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import Principal, set_tenant_context
from app.modules.auth.models import User
from app.modules.workspaces.models import Membership, Role, Workspace
from app.modules.workspaces.schemas import MemberOut, WorkspaceSettingsUpdate

SLUG_MAX_LENGTH = 60
SLUG_SUFFIX_ATTEMPTS = 20


def slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug[:SLUG_MAX_LENGTH].strip("-") or "workspace"


def _slug_candidates(base: str):
    yield base
    for n in range(2, SLUG_SUFFIX_ATTEMPTS + 2):
        yield f"{base}-{n}"
    yield f"{base}-{secrets.token_hex(4)}"


async def create_workspace_with_owner(
    session: AsyncSession,
    workspace_id: uuid.UUID,
    name: str,
    owner_id: uuid.UUID,
) -> Workspace:
    """Insert a workspace and its owner membership.

    The caller must already have set app.workspace_id to `workspace_id` in this transaction,
    since RLS only allows writes to the current workspace. Other tenants' slugs are not
    visible under RLS, so collisions are detected by the unique constraint instead.
    """
    base = slugify(name)
    workspace: Workspace | None = None
    for slug in _slug_candidates(base):
        candidate = Workspace(id=workspace_id, name=name, slug=slug)
        try:
            async with session.begin_nested():
                session.add(candidate)
                await session.flush()
        except IntegrityError as exc:
            if "uq_workspaces_slug" not in str(exc.orig):
                raise
            continue
        workspace = candidate
        break
    if workspace is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Could not allocate a workspace slug")

    session.add(Membership(user_id=owner_id, workspace_id=workspace.id, role=Role.OWNER))
    await session.flush()
    return workspace


async def create_workspace(
    session: AsyncSession, principal: Principal, name: str
) -> tuple[Workspace, Role]:
    workspace_id = uuid.uuid4()
    # Switch this transaction's context to the new workspace so RLS permits the inserts.
    await set_tenant_context(session, workspace_id, principal.user_id)
    workspace = await create_workspace_with_owner(session, workspace_id, name, principal.user_id)
    return workspace, Role.OWNER


async def list_my_workspaces(
    session: AsyncSession, user_id: uuid.UUID
) -> list[tuple[Workspace, Role]]:
    result = await session.execute(
        select(Workspace, Membership.role)
        .join(Membership, Membership.workspace_id == Workspace.id)
        .where(Membership.user_id == user_id)
        .order_by(Membership.created_at)
    )
    return [(ws, role) for ws, role in result.all()]


async def get_membership(
    session: AsyncSession, user_id: uuid.UUID, workspace_id: uuid.UUID
) -> Membership | None:
    result = await session.execute(
        select(Membership).where(
            Membership.user_id == user_id,
            Membership.workspace_id == workspace_id,
        )
    )
    return result.scalar_one_or_none()


async def get_latest_membership(session: AsyncSession, user_id: uuid.UUID) -> Membership | None:
    result = await session.execute(
        select(Membership)
        .where(Membership.user_id == user_id)
        .order_by(Membership.created_at.desc(), Membership.id.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def get_workspace(session: AsyncSession, workspace_id: uuid.UUID) -> Workspace:
    result = await session.execute(select(Workspace).where(Workspace.id == workspace_id))
    workspace = result.scalar_one_or_none()
    if workspace is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Workspace not found")
    return workspace


async def update_settings(
    session: AsyncSession, workspace_id: uuid.UUID, changes: WorkspaceSettingsUpdate
) -> Workspace:
    workspace = await get_workspace(session, workspace_id)
    if changes.name is not None:
        workspace.name = changes.name
    if changes.allowed_origins is not None:
        workspace.allowed_origins = changes.allowed_origins
    if changes.settings is not None:
        workspace.settings = changes.settings
    await session.flush()
    await session.refresh(workspace)
    return workspace


async def list_members(session: AsyncSession, workspace_id: uuid.UUID) -> list[MemberOut]:
    # The memberships policy also exposes the caller's own memberships elsewhere,
    # so the workspace filter here is required, not redundant.
    result = await session.execute(
        select(User.id, User.email, User.full_name, Membership.role)
        .join(Membership, Membership.user_id == User.id)
        .where(Membership.workspace_id == workspace_id)
        .order_by(Membership.created_at)
    )
    return [
        MemberOut(user_id=uid, email=email, full_name=full_name, role=role)
        for uid, email, full_name, role in result.all()
    ]
