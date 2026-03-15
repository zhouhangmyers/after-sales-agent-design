from __future__ import annotations

from collections.abc import Iterator

from fastapi import Request
from sqlalchemy.orm import Session

from agent_service.services.cache_service import EventCache
from agent_service.services.runtime_service import RuntimeService


def get_db_session(request: Request) -> Iterator[Session]:
    # 从 app.state 里取出 DatabaseManager，并基于它创建一个新的数据库 session。
    # 这里不是复用一个全局 session，而是“当前这次请求”临时拿一个数据库操作会话。
    session = request.app.state.db_manager.session()
    try:
        # 把 session 交给 FastAPI 路由函数使用。
        # 路由处理期间，可以用这个 session 做增删改查。
        yield session
    finally:
        # 当前请求处理结束后，统一关闭这个 session，避免数据库资源泄漏。
        session.close()


def get_runtime_service(request: Request) -> RuntimeService:
    # 取出应用启动时就初始化好的 RuntimeService。
    # 它承接第一周 AgentRuntime 的能力，给聊天接口复用，不需要每次请求重新创建。
    return request.app.state.runtime_service


def get_event_cache(request: Request) -> EventCache:
    # 取出应用级共享的事件缓存对象。
    # 当前主要给 SSE 流式接口使用，底层可能是内存缓存，也可能是 Redis 缓存。
    return request.app.state.event_cache
