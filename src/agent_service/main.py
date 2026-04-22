from __future__ import annotations

import logging
from collections.abc import Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from langgraph.checkpoint.base import BaseCheckpointSaver

from .api.health import router as health_router
from .api.routers.chat import router as chat_router
from .config import Settings
from .conversation.service import ConversationService
from .db.session import DatabaseManager
from .llm.service import LLMService, build_llm_service
from .tools.catalog import build_default_tool_policies, build_default_tools
from .tools.inline import InlineToolExecutor

logger = logging.getLogger(__name__)


def build_langgraph_checkpointer(settings: Settings) -> tuple[BaseCheckpointSaver, Callable[[], None]]:
    from contextlib import ExitStack

    from langgraph.checkpoint.memory import MemorySaver

    if settings.langgraph_postgres_url:
        from langgraph.checkpoint.postgres import PostgresSaver

        exit_stack = ExitStack()
        saver = exit_stack.enter_context(
            PostgresSaver.from_conn_string(settings.langgraph_postgres_url)
        )
        saver.setup()
        return saver, exit_stack.close

    if not settings.is_test:
        raise RuntimeError("LANGGRAPH_POSTGRES_URL is required when APP_ENV is not test")
    return MemorySaver(), lambda: None


def create_app(
    settings: Settings | None = None,
    *,
    llm_service: LLMService | None = None,
    tool_executor: InlineToolExecutor | None = None,
    checkpointer_override: BaseCheckpointSaver | None = None,
) -> FastAPI:
    resolved_settings = settings or Settings()

    logging.basicConfig(
        level=resolved_settings.log_level.upper(),
        format="%(asctime)s %(name)s %(levelname)s req_id=%(request_id)s %(message)s",
    )
    from .observability.context import RequestIdLogFilter, get_request_id

    root_logger = logging.getLogger()
    if not any(isinstance(f, RequestIdLogFilter) for f in root_logger.filters):
        request_id_filter = RequestIdLogFilter()
        root_logger.addFilter(request_id_filter)
        for handler in root_logger.handlers:
            handler.addFilter(request_id_filter)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        logger.info("starting up [env=%s]", resolved_settings.app_env)
        db_manager = DatabaseManager(resolved_settings.database_url)
        if resolved_settings.auto_create_schema:
            db_manager.create_schema()

        active_tool_executor = tool_executor or InlineToolExecutor(
            tools=build_default_tools(),
            tool_policies=build_default_tool_policies(),
        )
        active_llm_service = llm_service or build_llm_service(resolved_settings)
        resolved_checkpointer = checkpointer_override
        close_checkpointer = lambda: None
        if resolved_checkpointer is None:
            resolved_checkpointer, close_checkpointer = build_langgraph_checkpointer(resolved_settings)

        app.state.settings = resolved_settings
        app.state.db_manager = db_manager
        app.state.langgraph_checkpointer = resolved_checkpointer
        app.state.langgraph_checkpointer_close = close_checkpointer
        app.state.tool_executor = active_tool_executor
        app.state.llm_service = active_llm_service
        app.state.conversation_service = ConversationService(
            llm_service=active_llm_service,
            tool_executor=active_tool_executor,
            max_steps=resolved_settings.max_steps,
            approval_timeout_seconds=resolved_settings.approval_timeout_seconds,
            checkpointer=resolved_checkpointer,
        )
        try:
            yield
        finally:
            logger.info("shutting down")
            app.state.conversation_service.close()
            app.state.langgraph_checkpointer_close()
            app.state.db_manager.dispose()

    app = FastAPI(
        title="Conversation API",
        version="0.3.0",
        lifespan=lifespan,
    )

    @app.exception_handler(Exception)
    async def _unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("unhandled exception: %s %s", request.method, request.url.path)
        return JSONResponse(
            status_code=500,
            content={"detail": "Internal server error", "request_id": get_request_id()},
        )

    from .api.middleware import RequestIDMiddleware

    app.add_middleware(
        CORSMiddleware,
        allow_origins=resolved_settings.parsed_cors_allowed_origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(RequestIDMiddleware)

    app.include_router(health_router)
    app.include_router(chat_router, prefix="/api/v2")
    return app


app = create_app()
