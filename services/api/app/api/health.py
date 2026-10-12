import hmac
import json
import logging
import time
from typing import Annotated

import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse, PlainTextResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.database import get_db
from app.core.metrics import registry
from app.workers.observability import HEARTBEAT_KEY, METRICS_KEY_PREFIX

logger = logging.getLogger("app.api.health")

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
            checks["worker"] = worker_status(
                await redis_client.get(HEARTBEAT_KEY), settings.worker_heartbeat_stale_s
            )
        finally:
            await redis_client.aclose()
    except Exception as exc:  # noqa: BLE001
        checks["redis"] = type(exc).__name__
        is_healthy = False

    if is_healthy:
        # A stale or missing worker degrades the report but keeps the API in rotation: the API
        # still serves requests, and queued jobs run once the worker is back.
        worker_ok = checks.get("worker") == "ok"
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={"status": "ok" if worker_ok else "degraded", "checks": checks},
        )

    return JSONResponse(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        content={"status": "degraded", "checks": checks},
    )

def worker_status(heartbeat: str | bytes | None, stale_after_s: int) -> str:
    if heartbeat is None:
        return "missing"
    try:
        age = time.time() - float(heartbeat)
    except (TypeError, ValueError):
        return "missing"
    return "ok" if age <= stale_after_s else "stale"


@router.get("/metrics", include_in_schema=False)
async def metrics(
    request: Request, settings: Annotated[Settings, Depends(get_settings)]
) -> PlainTextResponse:
    """Prometheus text format. Needs `Authorization: Bearer <METRICS_TOKEN>`; without a
    configured token the endpoint does not exist (404)."""
    expected = settings.metrics_token.get_secret_value() if settings.metrics_token else ""
    if not expected:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not Found")
    supplied = request.headers.get("authorization", "")
    scheme, _, token = supplied.partition(" ")
    if scheme.lower() != "bearer" or not hmac.compare_digest(token.encode(), expected.encode()):
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return PlainTextResponse(
        registry.render(await _worker_snapshots(settings)),
        media_type="text/plain; version=0.0.4; charset=utf-8",
    )


async def _worker_snapshots(settings: Settings) -> list[dict]:
    """Metrics the workers published with their heartbeat. Missing if Redis is down."""
    snapshots: list[dict] = []
    try:
        client = aioredis.from_url(
            settings.redis_url, socket_connect_timeout=2, socket_timeout=2, decode_responses=True
        )
        try:
            async for key in client.scan_iter(match=f"{METRICS_KEY_PREFIX}*", count=100):
                raw = await client.get(key)
                if raw:
                    snapshots.append(json.loads(raw))
        finally:
            await client.aclose()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Worker metrics unavailable (error=%s)", type(exc).__name__)
    return snapshots
