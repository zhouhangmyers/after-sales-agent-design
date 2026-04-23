from __future__ import annotations

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from business_service.after_sales.infrastructure.persistence.sqlalchemy import (
    models as _after_sales_models,
)
from business_service.after_sales.infrastructure.persistence.sqlalchemy.session import Base

_ = _after_sales_models

# Alembic 的全局配置对象，会读取 alembic.ini 里的内容。
config = context.config

if config.config_file_name is not None:
    # 根据 alembic.ini 的日志配置初始化日志系统。
    fileConfig(config.config_file_name, disable_existing_loggers=False)

# 如果运行时显式传入了 DATABASE_URL，就用环境变量覆盖 alembic.ini 里的默认数据库地址。
# 这样同一套迁移脚本既可以跑本地 SQLite，也可以切到 PostgreSQL。
database_url = os.getenv("DATABASE_URL")
if database_url:
    config.set_main_option("sqlalchemy.url", database_url)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    # 离线模式：不真正连接数据库，而是基于配置生成 SQL 迁移语句。
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    # 在线模式：真正创建数据库连接并执行迁移。
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        # 把数据库连接和项目模型元数据都交给 Alembic，
        # 这样它才能根据当前数据库状态和目标模型结构执行迁移。
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )

        with context.begin_transaction():
            context.run_migrations()


# Alembic 会根据当前运行模式选择离线迁移还是在线迁移。
if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
