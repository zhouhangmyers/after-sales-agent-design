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
    import business_service.after_sales.infrastructure.persistence.sqlalchemy.models  # noqa: F401


class BusinessDatabase:
    def __init__(self, database_url: str) -> None:
        self.database_url = database_url
        sync_database_url = _sync_database_url(database_url)
        async_database_url = _async_database_url(database_url)
        sync_connect_args: dict[str, object] = (
            {"check_same_thread": False} if _is_sqlite(sync_database_url) else {}
        )
        self.sync_engine: Engine = create_engine(
            sync_database_url,
            future=True,
            connect_args=sync_connect_args,
        )
        self.async_engine: AsyncEngine = create_async_engine(
            async_database_url,
            future=True,
        )
        self._session_factory = async_sessionmaker(
            bind=self.async_engine,
            class_=AsyncSession,
            autoflush=False,
            expire_on_commit=False,
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
