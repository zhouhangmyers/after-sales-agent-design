from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from .api.chat import router as chat_router
from .api.health import router as health_router
from .config import Settings
from .db.session import DatabaseManager
from .services.cache_service import build_event_cache
from .services.orchestrator_service import OrchestratorService
from .services.runtime_service import RuntimeService


def bootstrap_app_state(app: FastAPI, settings: Settings) -> None:
    db_manager = DatabaseManager(settings.database_url)
    if settings.auto_create_schema:
        db_manager.create_schema()

    app.state.settings = settings
    app.state.db_manager = db_manager
    app.state.runtime_service = RuntimeService()
    # 三剑客里：
    # planner 负责想下一步，runtime 负责执行工具，orchestrator 负责把整轮 loop 串起来。
    app.state.orchestrator_service = OrchestratorService.from_settings(
        settings,
        runtime_service=app.state.runtime_service,
    )
    app.state.event_cache = build_event_cache(settings.redis_url)


def close_app_state(app: FastAPI) -> None:
    app.state.db_manager.dispose()


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved_settings = settings or Settings.from_env()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        bootstrap_app_state(app, resolved_settings)
        try:
            yield
        finally:
            close_app_state(app)

    app = FastAPI(
        title="Agent Orchestrator Platform",
        version="0.2.0",
        lifespan=lifespan,
    )
    app.include_router(health_router)
    app.include_router(chat_router, prefix="/api/v1")
    return app


app = create_app()
