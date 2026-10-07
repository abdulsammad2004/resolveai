import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Response, status

from app.api.v1.auth import auth_response
from app.core.deps import CurrentPrincipal, Principal, TenantDB, require_role
from app.modules.auth import service as auth_service
from app.modules.auth.schemas import AuthResponse
from app.modules.workspaces import service
from app.modules.workspaces.models import Role
from app.modules.workspaces.schemas import (
    MemberOut,
    WorkspaceCreate,
    WorkspaceSettingsOut,
    WorkspaceSettingsUpdate,
    WorkspaceWithRole,
)

router = APIRouter(tags=["workspaces"])

SettingsEditor = Annotated[Principal, Depends(require_role(Role.OWNER, Role.ADMIN))]


@router.get("/workspaces", response_model=list[WorkspaceWithRole])
async def list_workspaces(principal: CurrentPrincipal, db: TenantDB) -> list[WorkspaceWithRole]:
    rows = await service.list_my_workspaces(db, principal.user_id)
    return [
        WorkspaceWithRole(id=ws.id, name=ws.name, slug=ws.slug, role=role) for ws, role in rows
    ]


@router.post(
    "/workspaces", response_model=WorkspaceWithRole, status_code=status.HTTP_201_CREATED
)
async def create_workspace(
    body: WorkspaceCreate, principal: CurrentPrincipal, db: TenantDB
) -> WorkspaceWithRole:
    ws, role = await service.create_workspace(db, principal, body.name.strip())
    return WorkspaceWithRole(id=ws.id, name=ws.name, slug=ws.slug, role=role)


@router.post("/workspaces/{workspace_id}/switch", response_model=AuthResponse)
async def switch_workspace(
    workspace_id: uuid.UUID, response: Response, principal: CurrentPrincipal, db: TenantDB
) -> AuthResponse:
    result = await auth_service.switch_workspace(db, principal, workspace_id)
    return auth_response(response, result)


@router.get("/workspace/settings", response_model=WorkspaceSettingsOut)
async def get_settings(principal: CurrentPrincipal, db: TenantDB) -> WorkspaceSettingsOut:
    ws = await service.get_workspace(db, principal.workspace_id)
    return WorkspaceSettingsOut.model_validate(ws)


@router.patch("/workspace/settings", response_model=WorkspaceSettingsOut)
async def update_settings(
    body: WorkspaceSettingsUpdate, principal: SettingsEditor, db: TenantDB
) -> WorkspaceSettingsOut:
    ws = await service.update_settings(db, principal.workspace_id, body)
    return WorkspaceSettingsOut.model_validate(ws)


@router.get("/members", response_model=list[MemberOut])
async def list_members(principal: CurrentPrincipal, db: TenantDB) -> list[MemberOut]:
    return await service.list_members(db, principal.workspace_id)
