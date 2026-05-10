from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

from after_sales.infrastructure.persistence.sqlalchemy import (
    models as _after_sales_models,
)
from after_sales.infrastructure.persistence.sqlalchemy.session import (
    Base,
)

_ = _after_sales_models


_BASELINE_REVISION = "20260422_000001"
_CURRENT_REVISION = "20260423_000002"


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def build_alembic_config(*, database_url: str) -> Config:
    config = Config(str(_project_root() / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", database_url)
    return config


def _infer_unversioned_revision(*, database_url: str) -> str | None:
    engine = create_engine(database_url, future=True)
    try:
        inspector = inspect(engine)
        available_tables = set(inspector.get_table_names())
        if "alembic_version" in available_tables:
            with engine.connect() as connection:
                version_rows = list(
                    connection.execute(text("SELECT version_num FROM alembic_version"))
                )
            if version_rows:
                return None
            available_tables.remove("alembic_version")

        business_tables = set(Base.metadata.tables)
        existing_business_tables = available_tables & business_tables
        if not existing_business_tables:
            return None

        missing_tables = sorted(business_tables - available_tables)
        if missing_tables:
            missing = ", ".join(missing_tables)
            raise RuntimeError(
                "database contains an unversioned partial schema; "
                f"missing tables: {missing}"
            )

        approval_columns = {
            column["name"]
            for column in inspector.get_columns("approval_records")
        }
        if "tool_call_id" in approval_columns:
            return _CURRENT_REVISION
        return _BASELINE_REVISION
    finally:
        engine.dispose()


def upgrade_business_database(*, database_url: str, revision: str = "head") -> None:
    config = build_alembic_config(database_url=database_url)
    inferred_revision = _infer_unversioned_revision(database_url=database_url)
    if inferred_revision is not None:
        command.stamp(config, inferred_revision)
    command.upgrade(config, revision)
