from __future__ import annotations

import pytest

from app_api.settings import AppSettings


def test_test_env_allows_missing_runtime_database_url() -> None:
    settings = AppSettings(
        app_env="test",
        agent_runtime_database_url=None,
        api_key=None,
    )

    assert settings.is_test is True
    assert settings.agent_runtime_database_url is None


def test_production_settings_require_api_key_cors_and_runtime_database() -> None:
    with pytest.raises(ValueError, match="API_KEY is required when APP_ENV=production"):
        AppSettings(
            app_env="production",
            agent_runtime_database_url="postgresql://localhost/agent-runtime",
            api_key=None,
        )


def test_settings_default_business_database_url_points_to_local_sqlite() -> None:
    assert AppSettings(app_env="test").business_database_url.endswith("after_sales_mvp.db")


def test_settings_config_warnings_detect_close_match_typo(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AUTO_REATE_SCHEMA", "true")

    warnings = AppSettings(app_env="test").config_warnings()

    assert "unknown config key `AUTO_REATE_SCHEMA`; did you mean `AUTO_CREATE_SCHEMA`?" in warnings
