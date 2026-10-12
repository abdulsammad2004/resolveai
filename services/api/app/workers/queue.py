"""Enqueueing background jobs from the API. Tests override `get_job_queue` with a fake."""

import uuid
from typing import Protocol

from arq import ArqRedis, create_pool
from arq.connections import RedisSettings

from app.core.config import get_settings

INGEST_DOCUMENT = "ingest_document"
PROCESS_TICKET = "process_ticket"
EXECUTE_ACTION = "execute_action"


def execute_action_job_id(idempotency_key: str) -> str:
    """arq keeps one job per id, so an action is queued once however often it's approved."""
    return f"{EXECUTE_ACTION}:{idempotency_key}"


class JobQueue(Protocol):
    async def enqueue_ingest(self, document_id: uuid.UUID, workspace_id: uuid.UUID) -> None: ...

    async def enqueue_process_ticket(
        self, ticket_id: uuid.UUID, workspace_id: uuid.UUID, *, force: bool = False
    ) -> None: ...

    async def enqueue_execute_action(
        self, action_id: uuid.UUID, workspace_id: uuid.UUID, idempotency_key: str
    ) -> None: ...


class ArqJobQueue:
    def __init__(self, pool: ArqRedis | None = None) -> None:
        # Workers pass their own connection (ctx["redis"]); the API creates one lazily.
        self._pool: ArqRedis | None = pool

    async def _get_pool(self) -> ArqRedis:
        if self._pool is None:
            self._pool = await create_pool(RedisSettings.from_dsn(get_settings().redis_url))
        return self._pool

    async def enqueue_ingest(self, document_id: uuid.UUID, workspace_id: uuid.UUID) -> None:
        pool = await self._get_pool()
        await pool.enqueue_job(INGEST_DOCUMENT, str(document_id), str(workspace_id))

    async def enqueue_process_ticket(
        self, ticket_id: uuid.UUID, workspace_id: uuid.UUID, *, force: bool = False
    ) -> None:
        pool = await self._get_pool()
        await pool.enqueue_job(PROCESS_TICKET, str(ticket_id), str(workspace_id), force)

    async def enqueue_execute_action(
        self, action_id: uuid.UUID, workspace_id: uuid.UUID, idempotency_key: str
    ) -> None:
        pool = await self._get_pool()
        await pool.enqueue_job(
            EXECUTE_ACTION,
            str(action_id),
            str(workspace_id),
            _job_id=execute_action_job_id(idempotency_key),
        )

    async def close(self) -> None:
        if self._pool is not None:
            await self._pool.aclose()
            self._pool = None


_queue = ArqJobQueue()


def get_job_queue() -> JobQueue:
    return _queue


async def close_job_queue() -> None:
    await _queue.close()
