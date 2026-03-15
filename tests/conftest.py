from __future__ import annotations

import asyncio
from collections.abc import Generator
from pathlib import Path

import pytest
from fastapi import FastAPI
from sqlalchemy.orm import Session

from agent_service.config import Settings
from agent_service.main import create_app


@pytest.fixture()
def app(tmp_path: Path) -> Generator[FastAPI, None, None]:
    database_path = tmp_path / "agent-platform-test.db"
    settings = Settings(
        app_env="test",
        database_url=f"sqlite+pysqlite:///{database_path}",
        redis_url=None,
        auto_create_schema=True,
    )
    application = create_app(settings)
    lifespan = application.router.lifespan_context(application)
    # 测试里会直接访问 app.state，所以这里手动进入应用生命周期，
    # 先触发 bootstrap_app_state(...)，测试结束后再走关闭清理。
    asyncio.run(lifespan.__aenter__())
    try:
        yield application
    finally:
        asyncio.run(lifespan.__aexit__(None, None, None))


@pytest.fixture()
def db_session(app) -> Generator[Session, None, None]:
    session = app.state.db_manager.session()
    try:
        yield session
    finally:
        session.close()
