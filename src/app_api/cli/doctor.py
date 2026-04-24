from __future__ import annotations

from app_api.bootstrap import (
    build_llm_dependency,
    build_runtime_state_store,
    load_mcp_tools,
)
from app_api.settings import AppSettings
from business_service.after_sales.infrastructure.persistence.sqlalchemy.session import (
    BusinessDatabase,
)


async def doctor(settings: AppSettings | None = None) -> dict[str, object]:
    resolved_settings = settings or AppSettings()
    runtime_state_store = build_runtime_state_store(
        resolved_settings,
        runtime_state_store_override=None,
    )
    business_database = BusinessDatabase(resolved_settings.business_database_url)
    try:
        runtime_status = await runtime_state_store.healthcheck()
        business_status = await business_database.healthcheck()
        _, llm_status = build_llm_dependency(resolved_settings)
        _, mcp_status = await load_mcp_tools(resolved_settings)
        config_warnings = resolved_settings.config_warnings()
        return {
            "status": (
                "ok"
                if runtime_status.ok
                and business_status.ok
                and llm_status.ok
                and mcp_status.ok
                and not config_warnings
                else "degraded"
            ),
            "runtime_store": runtime_status.model_dump(mode="json"),
            "business_database": {
                "ok": business_status.ok,
                "schema_ready": business_status.schema_ready,
                "detail": business_status.detail,
            },
            "llm": {
                "ok": llm_status.ok,
                "provider": resolved_settings.llm_provider,
                "model": resolved_settings.llm_model,
                "detail": llm_status.detail,
            },
            "mcp": {
                "ok": mcp_status.ok,
                "configured_servers": sorted(resolved_settings.mcp_servers),
                "detail": mcp_status.detail,
            },
            "config_warnings": config_warnings,
        }
    finally:
        await runtime_state_store.close()
        await business_database.dispose()
