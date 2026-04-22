from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from .base import Base


def _is_sqlite(database_url: str) -> bool:
    return database_url.startswith("sqlite")


def _build_connect_args(database_url: str) -> dict[str, object]:
    if _is_sqlite(database_url):
        return {"check_same_thread": False}
    return {}


def _build_engine_kwargs(database_url: str) -> dict[str, object]:
    """为不同数据库后端返回合适的连接池配置。

    SQLite 不支持连接池参数（它使用 StaticPool 或 NullPool），
    PostgreSQL 等需要显式配置，避免生产环境连接泄漏和雪崩。
    """
    if _is_sqlite(database_url):
        return {}
    return {
        # 连接前先 SELECT 1 探活，确保从池里拿到的连接是有效的。
        # 这可以避免因数据库重启或网络抖动导致的"拿到死连接"问题。
        "pool_pre_ping": True,
        # 连接池大小：维持的常驻连接数。
        "pool_size": 5,
        # 超过 pool_size 时允许的最大溢出连接数。
        "max_overflow": 10,
    }


class DatabaseManager:
    def __init__(self, database_url: str) -> None:
        self.database_url = database_url
        self.engine = create_engine(
            database_url,
            future=True,
            connect_args=_build_connect_args(database_url),
            **_build_engine_kwargs(database_url),
        )
        self._session_factory = sessionmaker(
            bind=self.engine,
            class_=Session,
            autoflush=False,
            autocommit=False,
            expire_on_commit=False,
        )

    def create_schema(self) -> None:
        Base.metadata.create_all(self.engine)

    def session(self) -> Session:
        return self._session_factory()

    @contextmanager
    def managed_session(self) -> Generator[Session, None, None]:
        session = self._session_factory()
        try:
            yield session
        finally:
            session.close()

    def dispose(self) -> None:
        self.engine.dispose()
