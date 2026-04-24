from __future__ import annotations

from app_api.bootstrap import build_runtime_state_store
from app_api.migrations import upgrade_business_database
from app_api.settings import AppSettings


async def run_migrations(settings: AppSettings | None = None) -> None:
    resolved_settings = settings or AppSettings()
    runtime_state_store = build_runtime_state_store(
        resolved_settings,
        runtime_state_store_override=None,
    )
    try:
        upgrade_business_database(database_url=resolved_settings.business_database_url)
        await runtime_state_store.ensure_initialized()
    finally:
        await runtime_state_store.close()
