"""Widget rate limits and the per-workspace daily chat token budget, kept in Redis.

Rate limits fail open (a Redis outage must not take the widget down). The token budget
fails closed: without a reliable count the widget replies with the fallback message, which
hands the conversation to a human instead of spending money blindly.
"""

import logging
import time
import uuid
from datetime import UTC, datetime
from typing import Protocol

import redis.asyncio as aioredis
from redis.exceptions import RedisError

from app.core.config import get_settings

logger = logging.getLogger("app.conversations.limits")

BUDGET_KEY_TTL_S = 2 * 24 * 3600


class BudgetUnavailableError(Exception):
    """The token budget could not be read."""


class WidgetLimiter(Protocol):
    async def allow(self, key: str, limit: int, window_s: int) -> bool:
        """Count one hit on `key`; False if it exceeds `limit` in the current window."""
        ...

    async def tokens_used_today(self, workspace_id: uuid.UUID) -> int: ...

    async def add_tokens(self, workspace_id: uuid.UUID, tokens: int) -> None: ...


def _budget_key(workspace_id: uuid.UUID) -> str:
    return f"widget:tokens:{workspace_id}:{datetime.now(UTC):%Y%m%d}"


class RedisWidgetLimiter:
    """Fixed-window counters: INCR + EXPIRE per window."""

    def __init__(self, redis_url: str) -> None:
        self._redis = aioredis.from_url(redis_url, socket_connect_timeout=2, socket_timeout=2)

    async def allow(self, key: str, limit: int, window_s: int) -> bool:
        window = int(time.time() // window_s)
        redis_key = f"widget:rl:{key}:{window}"
        try:
            async with self._redis.pipeline(transaction=True) as pipe:
                pipe.incr(redis_key)
                pipe.expire(redis_key, window_s * 2)
                count, _ = await pipe.execute()
        except (RedisError, OSError) as exc:
            logger.warning("Rate limit check skipped (error=%s)", type(exc).__name__)
            return True
        return int(count) <= limit

    async def tokens_used_today(self, workspace_id: uuid.UUID) -> int:
        try:
            value = await self._redis.get(_budget_key(workspace_id))
        except (RedisError, OSError) as exc:
            raise BudgetUnavailableError from exc
        return int(value or 0)

    async def add_tokens(self, workspace_id: uuid.UUID, tokens: int) -> None:
        if tokens <= 0:
            return
        key = _budget_key(workspace_id)
        try:
            async with self._redis.pipeline(transaction=True) as pipe:
                pipe.incrby(key, tokens)
                pipe.expire(key, BUDGET_KEY_TTL_S)
                await pipe.execute()
        except (RedisError, OSError) as exc:
            logger.warning(
                "Token budget not updated (workspace_id=%s, error=%s)",
                workspace_id,
                type(exc).__name__,
            )

    async def aclose(self) -> None:
        await self._redis.aclose()


_limiter: RedisWidgetLimiter | None = None


def get_widget_limiter() -> WidgetLimiter:
    global _limiter
    if _limiter is None:
        _limiter = RedisWidgetLimiter(get_settings().redis_url)
    return _limiter


async def close_widget_limiter() -> None:
    global _limiter
    if _limiter is not None:
        await _limiter.aclose()
        _limiter = None
