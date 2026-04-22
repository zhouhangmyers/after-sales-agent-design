from __future__ import annotations

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_env: str = "dev"
    app_host: str = "127.0.0.1"
    app_port: int = 8000
    log_level: str = "INFO"

    database_url: str = "sqlite+pysqlite:///./app.db"
    langgraph_postgres_url: str | None = None
    auto_create_schema: bool = False

    cors_allowed_origins: str = ""
    api_key: SecretStr | None = None

    llm_provider: str = "deepseek"
    llm_model: str = "deepseek-chat"
    llm_timeout_seconds: float = Field(default=5.0, ge=0.1, le=300.0)
    llm_max_retries: int = Field(default=1, ge=0, le=10)
    deepseek_api_key: SecretStr | None = None

    prompt_name: str = "conversation-tools"
    prompt_version: str = "v1"
    max_steps: int = Field(default=4, ge=1, le=50)

    approval_timeout_seconds: int = Field(default=900, ge=1, le=604800)

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
        origins = [
            item.strip()
            for item in self.cors_allowed_origins.split(",")
            if item.strip()
        ]
        if origins:
            return origins
        if self.is_production:
            return []
        return ["*"]

    @model_validator(mode="after")
    def validate_runtime_requirements(self) -> Settings:
        if not self.is_production:
            return self

        if self.api_key is None:
            raise ValueError("API_KEY is required when APP_ENV=production")
        if not self.parsed_cors_allowed_origins:
            raise ValueError("CORS_ALLOWED_ORIGINS is required when APP_ENV=production")
        if "*" in self.parsed_cors_allowed_origins:
            raise ValueError("CORS_ALLOWED_ORIGINS cannot include '*' when APP_ENV=production")
        if self.langgraph_postgres_url is None:
            raise ValueError("LANGGRAPH_POSTGRES_URL is required when APP_ENV=production")
        if self.llm_provider == "deepseek" and self.deepseek_api_key is None:
            raise ValueError(
                "DEEPSEEK_API_KEY is required when llm_provider=deepseek and APP_ENV=production"
            )
        return self
