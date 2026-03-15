from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from .api.chat import router as chat_router
from .api.health import router as health_router
from .config import Settings
from .db.session import DatabaseManager
from .services.cache_service import build_event_cache
from .services.runtime_service import RuntimeService


# 这个文件是整个 Agent 服务的启动装配入口。
# 主线可以理解成：
# 1. 读取配置
# 2. 初始化数据库
# 3. 初始化智能体运行时服务
# 4. 初始化缓存
# 5. 注册路由，组成可启动的 FastAPI 应用
def bootstrap_app_state(app: FastAPI, settings: Settings) -> None:
    # 根据配置创建数据库管理器；底层会按 DATABASE_URL 决定连接 SQLite 还是 PostgreSQL。
    db_manager = DatabaseManager(settings.database_url)
    # 本地开发时可以直接自动建表，方便快速启动；生产环境通常更建议走 Alembic。
    if settings.auto_create_schema:
        db_manager.create_schema()

    # app.state 用来挂载应用级共享对象。
    # 后面的依赖注入和路由处理都可以从这里取配置、数据库和运行时服务，
    # 而不是在每个请求里重复创建。
    app.state.settings = settings
    app.state.db_manager = db_manager
    # RuntimeService 承接第一周 runtime 的能力，给聊天服务层调用。
    app.state.runtime_service = RuntimeService()
    # 根据 redis_url 决定使用 Redis 缓存还是内存缓存，为 SSE 事件流提供存取能力。
    app.state.event_cache = build_event_cache(settings.redis_url)


def close_app_state(app: FastAPI) -> None:
    # 应用关闭时释放数据库连接等资源。
    app.state.db_manager.dispose()


def create_app(settings: Settings | None = None) -> FastAPI:
    # 如果外部没有显式传入配置，就从环境变量/.env 构造一份默认配置。
    resolved_settings = settings or Settings.from_env()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # 应用启动时初始化运行所需的共享资源。
        bootstrap_app_state(app, resolved_settings)
        try:
            yield
        finally:
            # 应用关闭时统一释放资源，保证生命周期前后对称。
            close_app_state(app)

    # 创建 FastAPI 应用实例，title 和 version 会出现在文档页里。
    app = FastAPI(
        title="Agent Orchestrator Platform",
        version="0.2.0",
        lifespan=lifespan,
    )
    # 注册健康检查路由，通常用于启动后探活和联通性验证。
    app.include_router(health_router)
    # 注册业务路由，并统一挂在 /api/v1 前缀下。
    app.include_router(chat_router, prefix="/api/v1")
    return app


# 暴露给 uvicorn 的模块级 app。
# 当执行 uvicorn agent_service.main:app 时，uvicorn 会直接加载这个对象作为应用入口。
# 也就是说，模块被导入时就会调用 create_app()，把完整的 FastAPI 应用实例创建出来。
app = create_app()
