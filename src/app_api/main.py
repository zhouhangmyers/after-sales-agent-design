from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from agent_service.llm.types import ChatClient
from app_api.bootstrap import build_container
from app_api.container import RuntimeStateStore
from app_api.routers.after_sales_approvals import router as after_sales_approvals_router
from app_api.routers.after_sales_resources import router as after_sales_resources_router
from app_api.routers.after_sales_runs import router as after_sales_runs_router
from app_api.routers.health import router as health_router
from app_api.settings import AppSettings


def create_app(
    settings: AppSettings | None = None,
    *,
    chat_client_override: ChatClient | None = None,
    runtime_state_store_override: RuntimeStateStore | None = None,
) -> FastAPI:
    resolved_settings = settings or AppSettings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        container = build_container(
            resolved_settings,
            chat_client_override=chat_client_override,
            runtime_state_store_override=runtime_state_store_override,
        )
        app.state.settings = resolved_settings
        app.state.container = container
        try:
            yield
        finally:
            container.close()

    app = FastAPI(
        title="After-Sales Agent API",
        version="1.0.0",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=resolved_settings.parsed_cors_allowed_origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(health_router)
    app.include_router(after_sales_runs_router)
    app.include_router(after_sales_approvals_router)
    app.include_router(after_sales_resources_router)
    return app
