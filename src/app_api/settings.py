from __future__ import annotations

import os
from difflib import get_close_matches
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class MCPServerConfig(BaseModel):
    transport: Literal["http", "streamable_http", "stdio"]
    url: str | None = None
    command: str | None = None
    args: list[str] = Field(default_factory=list)
    headers: dict[str, str] = Field(default_factory=dict)

    model_config = ConfigDict(extra="forbid")


class AppSettings(BaseSettings):
    app_env: str = "dev"
    cors_allowed_origins: str = ""
    api_key: SecretStr | None = None

    business_database_url: str = "sqlite+pysqlite:///./after_sales_mvp.db"
    agent_runtime_database_url: str | None = None
    auto_create_schema: bool = False

    llm_provider: str = "deepseek"
    llm_model: str = "deepseek-chat"
    llm_timeout_seconds: float = Field(default=5.0, ge=0.1, le=300.0)
    llm_max_retries: int = Field(default=1, ge=0, le=10)
    deepseek_api_key: SecretStr | None = None
    openai_api_key: SecretStr | None = None

    max_steps: int = Field(default=4, ge=1, le=50)
    approval_timeout_seconds: int = Field(default=900, ge=1, le=604800)
    mcp_servers: dict[str, MCPServerConfig] = Field(default_factory=dict)

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @property
    def is_test(self) -> bool:
        return self.app_env.lower() == "test"

    @property
    def is_production(self) -> bool:
        return self.app_env.lower() in {"prod", "production"}

    @property
    def parsed_cors_allowed_origins(self) -> list[str]:
        origins = [item.strip() for item in self.cors_allowed_origins.split(",") if item.strip()]
        if origins:
            return origins
        return ["*"] if not self.is_production else []

    @classmethod
    def expected_env_keys(cls) -> set[str]:
        return {field_name.upper() for field_name in cls.model_fields}

    @classmethod
    def _configured_env_file(cls) -> Path | None:
        env_file = cls.model_config.get("env_file")
        if isinstance(env_file, str) and env_file:
            return Path(env_file)
        return None

    @classmethod
    def _candidate_config_keys(cls) -> set[str]:
        keys = set(os.environ)
        env_file = cls._configured_env_file()
        if env_file is None or not env_file.exists():
            return keys

        for raw_line in env_file.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("export "):
                line = line.removeprefix("export ").strip()
            if "=" not in line:
                continue
            key = line.split("=", 1)[0].strip()
            if key:
                keys.add(key)
        return keys

    def config_warnings(self) -> list[str]:
        expected_keys = self.expected_env_keys()
        warnings: list[str] = []
        for key in sorted(self._candidate_config_keys()):
            if key in expected_keys:
                continue
            suggestion = get_close_matches(key, expected_keys, n=1, cutoff=0.86)
            if suggestion:
                warnings.append(
                    f"unknown config key `{key}`; did you mean `{suggestion[0]}`?"
                )
        return warnings

    @model_validator(mode="after")
    def validate_runtime_requirements(self) -> AppSettings:
        for server_name, server_config in self.mcp_servers.items():
            if server_config.transport in {"http", "streamable_http"} and not server_config.url:
                raise ValueError(
                    f"MCP server `{server_name}` requires `url` when transport is http"
                )
            if server_config.transport == "stdio" and not server_config.command:
                raise ValueError(
                    f"MCP server `{server_name}` requires `command` when transport is stdio"
                )

        if not self.is_production:
            return self

        if self.api_key is None:
            raise ValueError("API_KEY is required when APP_ENV=production")
        if not self.parsed_cors_allowed_origins:
            raise ValueError("CORS_ALLOWED_ORIGINS is required when APP_ENV=production")
        if "*" in self.parsed_cors_allowed_origins:
            raise ValueError("CORS_ALLOWED_ORIGINS cannot include '*' when APP_ENV=production")
        if self.agent_runtime_database_url is None:
            raise ValueError("AGENT_RUNTIME_DATABASE_URL is required when APP_ENV=production")
        if self.llm_provider == "deepseek" and self.deepseek_api_key is None:
            raise ValueError(
                "DEEPSEEK_API_KEY is required when llm_provider=deepseek and APP_ENV=production"
            )
        if self.llm_provider == "openai" and self.openai_api_key is None:
            raise ValueError(
                "OPENAI_API_KEY is required when llm_provider=openai and APP_ENV=production"
            )
        return self
