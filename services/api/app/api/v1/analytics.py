"""Workspace analytics for the dashboard. Any member may read them; everything is scoped to
the caller's workspace by RLS and by an explicit workspace filter."""

from typing import Annotated

from fastapi import APIRouter, Query

from app.core.deps import CurrentPrincipal, TenantDB
from app.modules.analytics import service
from app.modules.analytics.schemas import AnalyticsOverview, KnowledgeGapsOut, RangeDays

router = APIRouter(prefix="/analytics", tags=["analytics"])

Days = Annotated[RangeDays, Query(description="Range: today and the days before it (UTC).")]


@router.get("/overview", response_model=AnalyticsOverview)
async def analytics_overview(
    principal: CurrentPrincipal, db: TenantDB, days: Days = 30
) -> AnalyticsOverview:
    return await service.overview(db, principal.workspace_id, days)


@router.get("/knowledge-gaps", response_model=KnowledgeGapsOut)
async def knowledge_gaps(
    principal: CurrentPrincipal, db: TenantDB, days: Days = 30
) -> KnowledgeGapsOut:
    """Top questions the assistant couldn't answer from the help docs, grouped by similarity.
    Budget fallbacks are excluded. Example questions are masked; no contact details."""
    return await service.knowledge_gaps(db, principal.workspace_id, days)
