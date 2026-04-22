from __future__ import annotations

import pytest

from agent_service.config import Settings
from agent_service.main import build_langgraph_checkpointer


def test_settings_test_env_allows_missing_langgraph_postgres_url() -> None:
    settings = Settings(
        app_env="test",
        langgraph_postgres_url=None,
        api_key=None,
    )

    assert settings.is_test is True
    assert settings.langgraph_postgres_url is None


def test_build_langgraph_checkpointer_requires_postgres_outside_test() -> None:
    settings = Settings(
        app_env="dev",
        langgraph_postgres_url=None,
        api_key=None,
    )

    with pytest.raises(RuntimeError, match="LANGGRAPH_POSTGRES_URL is required when APP_ENV is not test"):
        build_langgraph_checkpointer(settings)


def test_production_settings_require_api_key_and_cors() -> None:
    with pytest.raises(ValueError, match="API_KEY is required when APP_ENV=production"):
        Settings(
            app_env="production",
            langgraph_postgres_url="postgresql://localhost/langgraph",
            api_key=None,
        )


def test_settings_default_prompt_name_is_conversation_tools() -> None:
    assert Settings().prompt_name == "conversation-tools"
