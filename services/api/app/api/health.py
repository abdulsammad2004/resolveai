from typing import Annotated

import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, status
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.database import get_db

router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/health/ready")
async def health_ready(
    db: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> JSONResponse:
    checks: dict[str, str] = {}
    is_healthy = True

    try:
        await db.execute(text("SELECT 1"))
        checks["postgres"] = "ok"
    except Exception as exc:  # noqa: BLE001
        checks["postgres"] = type(exc).__name__
        is_healthy = False

    try:
        redis_client = aioredis.from_url(
            settings.redis_url,
            encoding="utf-8",
            decode_responses=True,
        )
        try:
            await redis_client.ping()
            checks["redis"] = "ok"
        finally:
            await redis_client.aclose()
    except Exception as exc:  # noqa: BLE001
        checks["redis"] = type(exc).__name__
        is_healthy = False

    if is_healthy:
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={"status": "ok", "checks": checks},
        )

    return JSONResponse(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        content={"status": "degraded", "checks": checks},
    )