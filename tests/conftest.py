from __future__ import annotations

from collections.abc import Generator
from pathlib import Path

import pytest
from fastapi import FastAPI

from agent_service.config import Settings
from agent_service.main import create_app
from tests.helpers import build_test_llm_service, build_test_tool_executor


@pytest.fixture()
def app(tmp_path: Path) -> Generator[FastAPI, None, None]:
    database_path = tmp_path / "agent-platform-test.db"
    application = create_app(
        Settings(
            app_env="test",
            database_url=f"sqlite+pysqlite:///{database_path}",
            langgraph_postgres_url=None,
            auto_create_schema=True,
            api_key=None,
            llm_provider="deepseek",
            llm_model="deepseek-chat",
        ),
        llm_service=build_test_llm_service(),
        tool_executor=build_test_tool_executor(),
    )
    yield application
