from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import APIRouter, Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.health import router as health_router
from app.api.v1.actions import router as actions_router
from app.api.v1.analytics import router as analytics_router
from app.api.v1.auth import router as auth_router
from app.api.v1.conversations import router as conversations_router
from app.api.v1.documents import router as documents_router
from app.api.v1.knowledge import router as knowledge_router
from app.api.v1.mock_orders import router as mock_orders_router
from app.api.v1.tickets import router as tickets_router
from app.api.v1.widget import router as widget_router
from app.api.v1.workspaces import router as workspaces_router
from app.core.config import get_settings
from app.core.errors import init_error_tracking, register_exception_handlers
from app.core.logs import configure_logging
from app.core.middleware import RequestIDMiddleware
from app.core.ratelimit import api_user_limit, close_rate_limiter
from app.modules.conversations.limits import close_widget_limiter
from app.workers.queue import close_job_queue


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    yield
    await close_job_queue()
    await close_widget_limiter()
    await close_rate_limiter()


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging()
    init_error_tracking()

    app = FastAPI(
        title=settings.app_name,
        debug=settings.debug,
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Request-ID"],
    )
    # Added last so it is outermost: every response, including CORS and errors, gets an id.
    app.add_middleware(RequestIDMiddleware)

    register_exception_handlers(app)

    api_v1 = APIRouter(prefix="/api/v1")
    # Auth and widget routes have their own limits (per IP, email, visitor and workspace).
    api_v1.include_router(auth_router)
    api_v1.include_router(widget_router)
    # Every dashboard request also counts toward a general per-user limit.
    per_user = [Depends(api_user_limit)]
    for router in (
        workspaces_router,
        documents_router,
        knowledge_router,
        conversations_router,
        tickets_router,
        actions_router,
        analytics_router,
        mock_orders_router,
    ):
        api_v1.include_router(router, dependencies=per_user)

    app.include_router(health_router)
    app.include_router(api_v1)

    return app


app = create_app()
