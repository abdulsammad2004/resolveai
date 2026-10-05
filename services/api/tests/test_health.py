from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.database import get_db
from app.main import create_app


@pytest.mark.asyncio
async def test_health_check() -> None:
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_health_ready_success() -> None:
    app = create_app()
    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(return_value=None)

    app.dependency_overrides[get_db] = lambda: mock_db

    with patch("redis.asyncio.from_url") as mock_from_url:
        mock_redis = AsyncMock()
        mock_redis.ping = AsyncMock(return_value=True)
        mock_redis.aclose = AsyncMock()
        mock_from_url.return_value = mock_redis

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/health/ready")

        assert response.status_code == 200
        assert response.json() == {
            "status": "ok",
            "checks": {"postgres": "ok", "redis": "ok"},
        }

    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_health_ready_degraded() -> None:
    app = create_app()
    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(side_effect=ConnectionRefusedError("DB down"))

    app.dependency_overrides[get_db] = lambda: mock_db

    with patch("redis.asyncio.from_url") as mock_from_url:
        mock_redis = AsyncMock()
        mock_redis.ping = AsyncMock(side_effect=ConnectionError("Redis down"))
        mock_redis.aclose = AsyncMock()
        mock_from_url.return_value = mock_redis

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/health/ready")

        assert response.status_code == 503
        data = response.json()
        assert data["status"] == "degraded"
        assert data["checks"]["postgres"] == "ConnectionRefusedError"
        assert data["checks"]["redis"] == "ConnectionError"

    app.dependency_overrides.clear()