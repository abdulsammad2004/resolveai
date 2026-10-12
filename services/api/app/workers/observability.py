"""Job tracing, metrics and the worker heartbeat.

`traced` wraps every job: it restores the request id the job was enqueued with (or starts a new
one), binds the job name, id and workspace to the log context, and records the job's duration
and outcome. `heartbeat` runs on a cron: it refreshes the liveness key that /health/ready reads
and publishes this process's metrics so the API's /metrics can include them.
"""

import functools
import logging
import os
import socket
import time
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from arq import Retry

from app.core.logs import reset_log_context, start_log_context
from app.core.metrics import JOB_DURATION, JOBS, registry
from app.core.middleware import request_id_ctx

logger = logging.getLogger("app.workers.jobs")

HEARTBEAT_KEY = "worker:heartbeat"
HEARTBEAT_TTL_S = 24 * 3600
METRICS_KEY_PREFIX = "metrics:worker:"
METRICS_TTL_S = 120

Job = Callable[..., Awaitable[Any]]


def traced(job_name: str, fn: Job) -> Job:
    @functools.wraps(fn)
    async def wrapper(ctx: dict[str, Any], *args: Any, request_id: str | None = None, **kwargs: Any) -> Any:
        rid = request_id or str(uuid.uuid4())
        token = request_id_ctx.set(rid)
        context = {
            "request_id": rid,
            "job": job_name,
            "job_id": str(ctx.get("job_id", "")),
            "job_try": str(ctx.get("job_try", "")),
        }
        if len(args) >= 2:
            # Every job takes (entity_id, workspace_id, ...).
            context["workspace_id"] = str(args[1])
        log_token = start_log_context(**context)
        started = time.perf_counter()
        outcome = "error"
        try:
            result = await fn(ctx, *args, **kwargs)
            outcome = "ok"
            return result
        except Retry:
            outcome = "retry"
            raise
        finally:
            elapsed = time.perf_counter() - started
            JOBS.inc(job=job_name, status=outcome)
            JOB_DURATION.observe(elapsed, job=job_name)
            logger.info(
                "Job %s finished (%s)",
                job_name,
                outcome,
                extra={"outcome": outcome, "duration_ms": round(elapsed * 1000, 1)},
            )
            reset_log_context(log_token)
            request_id_ctx.reset(token)

    return wrapper


def worker_instance() -> str:
    return f"{socket.gethostname()}:{os.getpid()}"


async def heartbeat(ctx: dict[str, Any]) -> None:
    redis = ctx["redis"]
    try:
        await redis.set(HEARTBEAT_KEY, str(time.time()), ex=HEARTBEAT_TTL_S)
        await redis.set(METRICS_KEY_PREFIX + worker_instance(), registry.dumps(), ex=METRICS_TTL_S)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Heartbeat failed (error=%s)", type(exc).__name__)
