from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


@dataclass(slots=True, frozen=True)
class DatabaseHealthStatus:
    ok: bool
    schema_ready: bool
    detail: str | None = None


def _is_sqlite(database_url: str) -> bool:
    return database_url.startswith("sqlite")


def _sync_database_url(database_url: str) -> str:
    if database_url.startswith("sqlite+aiosqlite://"):
        return database_url.replace("sqlite+aiosqlite://", "sqlite+pysqlite://", 1)
    if database_url.startswith("postgresql://"):
        return database_url.replace("postgresql://", "postgresql+psycopg://", 1)
    return database_url


def _async_database_url(database_url: str) -> str:
    if database_url.startswith("sqlite+pysqlite://"):
        return database_url.replace("sqlite+pysqlite://", "sqlite+aiosqlite://", 1)
    if database_url.startswith("sqlite://"):
        return database_url.replace("sqlite://", "sqlite+aiosqlite://", 1)
    if database_url.startswith("postgresql://"):
        return database_url.replace("postgresql://", "postgresql+psycopg://", 1)
    return database_url


def _ensure_metadata_loaded() -> None:
    import after_sales.infrastructure.persistence.sqlalchemy.models  # noqa: F401


class BusinessDatabase:
    def __init__(self, database_url: str) -> None:
        self.database_url = database_url
        sync_database_url = _sync_database_url(database_url)
        async_database_url = _async_database_url(database_url)
        sync_connect_args: dict[str, object] = (
            {"check_same_thread": False} if _is_sqlite(sync_database_url) else {}
        )
        self.sync_engine: Engine = create_engine(
            sync_database_url,  # 同步数据库 URL，供 Alembic、inspect 和 run_sync 场景使用。
            future=True,  # 使用 SQLAlchemy 2.x 风格 API，避免旧版隐式行为。
            connect_args=sync_connect_args,  # SQLite 关闭同线程限制，解决测试/本地同步检查时的线程约束。
        )
        self.async_engine: AsyncEngine = create_async_engine(
            async_database_url,  # 异步数据库 URL，供 FastAPI 请求和 AsyncSession 使用。
            future=True,  # 保持 async engine 与 sync engine 的 SQLAlchemy 2.x 行为一致。
        )
        self._session_factory = async_sessionmaker(
            bind=self.async_engine,  # 所有业务 session 都从同一个异步 engine 获取连接。
            class_=AsyncSession,  # 明确创建异步 session，解决 async route 里不能用同步 session 的问题。
            autoflush=False,  # 避免查询前自动 flush 半成品对象，事务边界交给 service/UoW 控制。
            expire_on_commit=False,  # commit 后对象字段仍可读取，避免返回响应时触发额外懒加载。
        )

    async def create_schema(self) -> None:
        _ensure_metadata_loaded()
        async with self.async_engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

    async def healthcheck(self) -> DatabaseHealthStatus:
        _ensure_metadata_loaded()
        try:
            async with self.async_engine.connect() as connection:
                await connection.execute(text("SELECT 1"))
                available_tables = await connection.run_sync(
                    lambda sync_connection: set(
                        inspect(sync_connection).get_table_names()
                    )
                )
                missing_columns = await connection.run_sync(_missing_columns)
        except Exception as exc:
            return DatabaseHealthStatus(
                ok=False,
                schema_ready=False,
                detail=str(exc) or exc.__class__.__name__,
            )

        expected_tables = set(Base.metadata.tables)
        missing_tables = sorted(expected_tables - available_tables)
        if missing_tables:
            return DatabaseHealthStatus(
                ok=False,
                schema_ready=False,
                detail=f"missing tables: {', '.join(missing_tables)}",
            )

        if missing_columns:
            return DatabaseHealthStatus(
                ok=False,
                schema_ready=False,
                detail=f"missing columns: {', '.join(missing_columns)}",
            )
        return DatabaseHealthStatus(ok=True, schema_ready=True, detail=None)

    @asynccontextmanager
    async def managed_session(self) -> AsyncGenerator[AsyncSession, None]:
        async with self._session_factory() as session:
            yield session

    async def dispose(self) -> None:
        await self.async_engine.dispose()
        self.sync_engine.dispose()


def _missing_columns(connection: Connection) -> list[str]:
    inspector = inspect(connection)
    missing_columns: list[str] = []
    for table_name, table in Base.metadata.tables.items():
        existing_columns = {
            column["name"]
            for column in inspector.get_columns(table_name)
        }
        expected_columns = {column.name for column in table.columns}
        for column_name in sorted(expected_columns - existing_columns):
            missing_columns.append(f"{table_name}.{column_name}")
    return missing_columns
