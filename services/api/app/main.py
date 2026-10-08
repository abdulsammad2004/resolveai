from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.health import router as health_router
from app.api.v1.auth import router as auth_router
from app.api.v1.documents import router as documents_router
from app.api.v1.knowledge import router as knowledge_router
from app.api.v1.workspaces import router as workspaces_router
from app.core.config import get_settings
from app.core.errors import register_exception_handlers
from app.core.middleware import RequestIDMiddleware
from app.workers.queue import close_job_queue


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    yield
    await close_job_queue()


def create_app() -> FastAPI:
    settings = get_settings()

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
    api_v1.include_router(auth_router)
    api_v1.include_router(workspaces_router)
    api_v1.include_router(documents_router)
    api_v1.include_router(knowledge_router)

    app.include_router(health_router)
    app.include_router(api_v1)

    return app


app = create_app()
