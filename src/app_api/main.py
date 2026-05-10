from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from langchain_core.language_models.chat_models import BaseChatModel

from app_api.composition.bootstrap import build_container
from app_api.composition.container import RuntimeStateStore
from app_api.routers.after_sales_approvals import router as after_sales_approvals_router
from app_api.routers.after_sales_resources import router as after_sales_resources_router
from app_api.routers.after_sales_runs import router as after_sales_runs_router
from app_api.routers.agents import router as agents_router
from app_api.routers.health import router as health_router
from app_api.settings import AppSettings


def create_app(
    settings: AppSettings | None = None,
    *,
    chat_model_override: BaseChatModel | None = None,
    runtime_state_store_override: RuntimeStateStore | None = None,
) -> FastAPI:
    resolved_settings = settings or AppSettings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        container = await build_container(
            resolved_settings,
            chat_model_override=chat_model_override,
            runtime_state_store_override=runtime_state_store_override,
        )
        app.state.settings = resolved_settings
        app.state.container = container
        try:
            yield
        finally:
            await container.close()

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
    app.include_router(agents_router)
    app.include_router(after_sales_runs_router)
    app.include_router(after_sales_approvals_router)
    app.include_router(after_sales_resources_router)
    return app
