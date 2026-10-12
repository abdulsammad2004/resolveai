"""Sample orders for demos (owners and admins only)."""

from typing import Annotated

from fastapi import APIRouter, Depends

from app.core.deps import Principal, TenantDB, require_role
from app.modules.orders import service
from app.modules.orders.schemas import MockOrderOut, SeedResult
from app.modules.workspaces.models import Role

router = APIRouter(prefix="/mock-orders", tags=["mock-orders"])

Admin = Annotated[Principal, Depends(require_role(Role.OWNER, Role.ADMIN))]


@router.post("/seed", response_model=SeedResult)
async def seed_orders(principal: Admin, db: TenantDB) -> SeedResult:
    """Insert ~10 sample orders into this workspace. Safe to call repeatedly."""
    inserted = await service.seed(db, principal.workspace_id)
    orders = await service.list_orders(db, principal.workspace_id)
    return SeedResult(
        inserted=inserted, orders=[MockOrderOut.model_validate(o) for o in orders]
    )


@router.get("", response_model=list[MockOrderOut])
async def list_orders(principal: Admin, db: TenantDB) -> list[MockOrderOut]:
    return [MockOrderOut.model_validate(o) for o in await service.list_orders(db, principal.workspace_id)]
