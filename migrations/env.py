#
# ruff: noqa: E402
#
from __future__ import annotations

import os
import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import engine_from_config, pool

# 计算项目根目录和 src 目录路径。
# Alembic 执行迁移时，当前工作目录和模块搜索路径不一定正好指向项目源码，
# 所以这里手动把 src 加进 sys.path，保证后面能 import 到 agent_service 下的模型代码。
PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_PATH = PROJECT_ROOT / "src"
if str(SRC_PATH) not in sys.path:
    sys.path.append(str(SRC_PATH))

# 导入 Base 和所有模型定义。
# 这里 import models 的目的不是直接使用变量，而是确保所有 ORM 模型类都被加载进内存，
# 这样 Base.metadata 才会完整包含 sessions / messages / tool_calls 等表定义。
from agent_service.db.base import Base
from agent_service.db import models as db_models  # noqa: F401

# Alembic 的全局配置对象，会读取 alembic.ini 里的内容。
config = context.config

if config.config_file_name is not None:
    # 根据 alembic.ini 的日志配置初始化日志系统。
    fileConfig(config.config_file_name)

# 如果运行时显式传入了 DATABASE_URL，就用环境变量覆盖 alembic.ini 里的默认数据库地址。
# 这样同一套迁移脚本既可以跑本地 SQLite，也可以切到 PostgreSQL。
database_url = os.getenv("DATABASE_URL")
if database_url:
    config.set_main_option("sqlalchemy.url", database_url)

# 告诉 Alembic：当前项目的目标表结构来自哪里。
# 这里指向 Base.metadata，也就是所有 ORM 模型汇总后的元数据对象。
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
