"""arq worker entry point.

Run from services/api:  arq app.workers.main.WorkerSettings
"""

import logging
from typing import Any, ClassVar

from arq.connections import RedisSettings

from app.ai.embeddings import get_embedding_client
from app.core.config import get_settings
from app.core.database import engine
from app.core.storage import get_storage

# Register every model on the shared metadata so foreign keys (e.g. documents -> users)
# resolve in the worker process, which doesn't import the API routers.
from app.modules.auth import models as auth_models  # noqa: F401
from app.modules.workspaces import models as workspaces_models  # noqa: F401
from app.workers.ingestion import JOB_TIMEOUT_S, MAX_TRIES, ingest_document

# arq configures its own loggers; give the app's loggers a handler too.
_handler = logging.StreamHandler()
_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
logging.getLogger("app").addHandler(_handler)
logging.getLogger("app").setLevel(logging.INFO)


async def startup(ctx: dict[str, Any]) -> None:
    # Fail fast on bad configuration (e.g. missing OPENAI_API_KEY) instead of on the first job.
    ctx["storage"] = get_storage()
    ctx["embedder"] = get_embedding_client()


async def shutdown(ctx: dict[str, Any]) -> None:
    await engine.dispose()


class WorkerSettings:
    functions: ClassVar[list[Any]] = [ingest_document]
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
    on_startup = startup
    on_shutdown = shutdown
    max_tries = MAX_TRIES
    job_timeout = JOB_TIMEOUT_S
