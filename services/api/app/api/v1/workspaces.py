import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status

from app.api.v1.auth import auth_response
from app.core.config import get_settings as get_app_settings
from app.core.deps import CurrentPrincipal, Principal, TenantDB, require_role
from app.modules.auth import service as auth_service
from app.modules.auth.schemas import AuthResponse
from app.modules.workspaces import demo, service
from app.modules.workspaces.models import Role
from app.modules.workspaces.schemas import (
    DemoResetOut,
    DemoToolsOut,
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


@router.get("/workspace/demo", response_model=DemoToolsOut)
async def demo_tools(principal: CurrentPrincipal) -> DemoToolsOut:
    """Whether dev/demo tools (the reset button) are available on this server."""
    return DemoToolsOut(enabled=get_app_settings().demo_tools_enabled)


@router.post("/workspace/demo/reset", response_model=DemoResetOut)
async def reset_demo_data(principal: CurrentPrincipal, db: TenantDB) -> DemoResetOut:
    """Dev/demo only (DEMO_TOOLS_ENABLED), owners only: delete the caller's workspace's
    conversations, inbox, drafts, actions and audit events, and reset its sample orders.
    The workspace always comes from the access token."""
    if not get_app_settings().demo_tools_enabled:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    if principal.role != Role.OWNER:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only the workspace owner can reset demo data")
    counts = await demo.reset_demo_data(db, principal.workspace_id)
    orders = counts.pop(demo.ORDERS_KEY, 0)
    return DemoResetOut(deleted=counts, mock_orders_reset=orders)
