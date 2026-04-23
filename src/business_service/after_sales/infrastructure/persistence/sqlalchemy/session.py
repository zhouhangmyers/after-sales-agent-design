from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


class Base(DeclarativeBase):
    pass


@dataclass(slots=True, frozen=True)
class DatabaseHealthStatus:
    ok: bool
    schema_ready: bool
    detail: str | None = None


def _is_sqlite(database_url: str) -> bool:
    return database_url.startswith("sqlite")


def _ensure_metadata_loaded() -> None:
    import business_service.after_sales.infrastructure.persistence.sqlalchemy.models  # noqa: F401


class BusinessDatabase:
    def __init__(self, database_url: str) -> None:
        connect_args: dict[str, object] = {"check_same_thread": False} if _is_sqlite(database_url) else {}
        self.engine = create_engine(database_url, future=True, connect_args=connect_args)
        self._session_factory = sessionmaker(
            bind=self.engine,
            class_=Session,
            autoflush=False,
            autocommit=False,
            expire_on_commit=False,
        )

    def create_schema(self) -> None:
        _ensure_metadata_loaded()
        Base.metadata.create_all(self.engine)

    def healthcheck(self) -> DatabaseHealthStatus:
        _ensure_metadata_loaded()
        try:
            inspector = inspect(self.engine)
            with self.engine.connect() as connection:
                connection.execute(text("SELECT 1"))
            available_tables = set(inspector.get_table_names())
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

        missing_columns: list[str] = []
        for table_name, table in Base.metadata.tables.items():
            existing_columns = {
                column["name"]
                for column in inspector.get_columns(table_name)
            }
            expected_columns = {column.name for column in table.columns}
            for column_name in sorted(expected_columns - existing_columns):
                missing_columns.append(f"{table_name}.{column_name}")

        if missing_columns:
            return DatabaseHealthStatus(
                ok=False,
                schema_ready=False,
                detail=f"missing columns: {', '.join(missing_columns)}",
            )
        return DatabaseHealthStatus(ok=True, schema_ready=True, detail=None)

    @contextmanager
    def managed_session(self) -> Generator[Session, None, None]:
        session = self._session_factory()
        try:
            yield session
        finally:
            session.close()

    def dispose(self) -> None:
        self.engine.dispose()
