"""arq worker entry point.

Run from services/api:  arq app.workers.main.WorkerSettings
"""

from typing import Any, ClassVar

from arq.connections import RedisSettings
from arq.cron import cron
from arq.worker import func

# Register every model on the shared metadata so foreign keys (e.g. documents -> users)
# resolve in the worker process, which doesn't import the API routers.
from app.ai import usage as usage_models  # noqa: F401
from app.ai.embeddings import get_embedding_client
from app.ai.tools import models as tool_models  # noqa: F401
from app.core.config import get_settings
from app.core.database import engine
from app.core.errors import init_error_tracking
from app.core.logs import configure_logging
from app.core.storage import get_storage
from app.modules.approvals import models as approvals_models  # noqa: F401
from app.modules.audit import models as audit_models  # noqa: F401
from app.modules.auth import models as auth_models  # noqa: F401
from app.modules.conversations import models as conversations_models  # noqa: F401
from app.modules.orders import models as orders_models  # noqa: F401
from app.modules.tickets import models as tickets_models  # noqa: F401
from app.modules.workspaces import models as workspaces_models  # noqa: F401
from app.workers import actions, drafting
from app.workers.ingestion import JOB_TIMEOUT_S, MAX_TRIES, ingest_document
from app.workers.observability import heartbeat, traced
from app.workers.queue import EXECUTE_ACTION, INGEST_DOCUMENT, PROCESS_TICKET

# arq configures its own loggers; the app's loggers get the shared structured handler.
configure_logging()
init_error_tracking()


async def startup(ctx: dict[str, Any]) -> None:
    # Fail fast on bad configuration (e.g. missing OPENAI_API_KEY) instead of on the first job.
    ctx["storage"] = get_storage()
    ctx["embedder"] = get_embedding_client()


async def shutdown(ctx: dict[str, Any]) -> None:
    await engine.dispose()


class WorkerSettings:
    functions: ClassVar[list[Any]] = [
        func(traced(INGEST_DOCUMENT, ingest_document), name=INGEST_DOCUMENT),
        func(
            traced(PROCESS_TICKET, drafting.process_ticket),
            name=PROCESS_TICKET,
            max_tries=drafting.MAX_TRIES,
            timeout=drafting.JOB_TIMEOUT_S,
        ),
        func(
            traced(EXECUTE_ACTION, actions.execute_action),
            name=EXECUTE_ACTION,
            max_tries=actions.MAX_TRIES,
            timeout=actions.JOB_TIMEOUT_S,
        ),
    ]
    # Liveness for /health/ready and this process's metrics for /metrics.
    cron_jobs: ClassVar[list[Any]] = [
        cron(heartbeat, second={0, 15, 30, 45}, run_at_startup=True, timeout=10)
    ]
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
    on_startup = startup
    on_shutdown = shutdown
    max_tries = MAX_TRIES
    job_timeout = JOB_TIMEOUT_S
