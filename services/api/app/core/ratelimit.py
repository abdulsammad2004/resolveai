"""One rate limiter for the whole API: sliding windows in Redis.

Each key is a sorted set of request timestamps. A Lua script drops entries older than the
window, counts the rest and only records the hit if it is allowed, so refused requests don't
extend a lockout. A refused hit returns how long until the oldest entry leaves the window,
which becomes the Retry-After header.

Limits fail open: if Redis is unavailable the request is allowed, a warning is logged (at most
once a minute) and a metric is incremented. Keys hold ids, hashed emails and IPs, never text.
"""

import hashlib
import logging
import math
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Annotated, Protocol

import redis.asyncio as aioredis
from fastapi import Depends, HTTPException, Request, status
from redis.exceptions import RedisError

from app.core.config import get_settings
from app.core.deps import CurrentPrincipal, Principal
from app.core.logs import EveryNSeconds
from app.core.metrics import RATE_LIMIT_REDIS_ERRORS, RATE_LIMITED

logger = logging.getLogger("app.ratelimit")

KEY_PREFIX = "rl:"
DEFAULT_MESSAGE = "Too many requests. Please wait a moment and try again."

_SLIDING_WINDOW_LUA = """
local key = KEYS[1]
local now = tonumber(ARGV[1])
local window = tonumber(ARGV[2])
local limit = tonumber(ARGV[3])
redis.call('ZREMRANGEBYSCORE', key, '-inf', now - window)
local count = redis.call('ZCARD', key)
if count < limit then
  redis.call('ZADD', key, now, ARGV[4])
  redis.call('PEXPIRE', key, window)
  return {1, 0}
end
local oldest = redis.call('ZRANGE', key, 0, 0, 'WITHSCORES')
local retry = window
if oldest[2] then retry = window - (now - tonumber(oldest[2])) end
return {0, retry}
"""


@dataclass(frozen=True)
class RateDecision:
    allowed: bool
    retry_after_s: int = 0


class RateLimiter(Protocol):
    async def hit(self, key: str, limit: int, window_s: int) -> RateDecision:
        """Count one request on `key` unless that exceeds `limit` within the last `window_s`."""
        ...


class RedisRateLimiter:
    def __init__(self, redis_url: str) -> None:
        self._redis = aioredis.from_url(redis_url, socket_connect_timeout=2, socket_timeout=2)
        self._script = self._redis.register_script(_SLIDING_WINDOW_LUA)
        self._warn = EveryNSeconds(60)

    async def hit(self, key: str, limit: int, window_s: int) -> RateDecision:
        now_ms = int(time.time() * 1000)
        try:
            allowed, retry_ms = await self._script(
                keys=[KEY_PREFIX + key],
                args=[now_ms, window_s * 1000, limit, f"{now_ms}:{uuid.uuid4().hex[:8]}"],
            )
        except (RedisError, OSError) as exc:
            RATE_LIMIT_REDIS_ERRORS.inc()
            if self._warn.ready():
                logger.warning(
                    "Rate limiter unavailable, allowing requests (error=%s)", type(exc).__name__
                )
            return RateDecision(True)
        if int(allowed):
            return RateDecision(True)
        return RateDecision(False, max(1, math.ceil(int(retry_ms) / 1000)))

    async def aclose(self) -> None:
        await self._redis.aclose()


_limiter: RedisRateLimiter | None = None


def get_rate_limiter() -> RateLimiter:
    global _limiter
    if _limiter is None:
        _limiter = RedisRateLimiter(get_settings().redis_url)
    return _limiter


async def close_rate_limiter() -> None:
    global _limiter
    if _limiter is not None:
        await _limiter.aclose()
        _limiter = None


Limiter = Annotated[RateLimiter, Depends(get_rate_limiter)]


def rate_limited(retry_after_s: int, message: str = DEFAULT_MESSAGE) -> HTTPException:
    return HTTPException(
        status.HTTP_429_TOO_MANY_REQUESTS,
        message,
        headers={"Retry-After": str(retry_after_s)},
    )


async def enforce(
    limiter: RateLimiter,
    checks: list[tuple[str, str, int, int]],
    message: str = DEFAULT_MESSAGE,
) -> None:
    """Apply (name, key, limit, window_s) checks in order; raise 429 on the first refusal."""
    if not get_settings().rate_limit_enabled:
        return
    for name, key, limit, window_s in checks:
        decision = await limiter.hit(key, limit, window_s)
        if not decision.allowed:
            RATE_LIMITED.inc(limit=name)
            logger.info("Rate limited (limit=%s)", name)
            raise rate_limited(decision.retry_after_s, message)


def client_ip(request: Request) -> str:
    # Behind the web app's proxy, uvicorn's --proxy-headers resolves the client address.
    return request.client.host if request.client else "unknown"


def email_key(email: str) -> str:
    """Emails never appear in Redis keys: a short hash of the normalised address."""
    return hashlib.sha256(email.strip().lower().encode()).hexdigest()[:32]


def user_rate_limit(
    name: str, limit: Callable[[], int], window_s: int
) -> Callable[[Principal, RateLimiter], Awaitable[None]]:
    """A dependency limiting the authenticated user: `limit` is read from settings per call."""

    async def check(principal: CurrentPrincipal, limiter: Limiter) -> None:
        await enforce(limiter, [(name, f"{name}:user:{principal.user_id}", limit(), window_s)])

    return check


# Every dashboard request, per user. Attached to the authenticated routers in main.py.
api_user_limit = user_rate_limit(
    "api", lambda: get_settings().rate_limit_api_user_per_minute, 60
)
