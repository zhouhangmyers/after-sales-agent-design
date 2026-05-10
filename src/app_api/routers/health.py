from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from app_api.composition.container import AppContainer
from app_api.deps import get_container

router = APIRouter(tags=["health"])


@router.get("/health")
async def health(
    container: Annotated[AppContainer, Depends(get_container)],
) -> dict[str, object]:
    runtime_status = await container.runtime_state_store.healthcheck()
    business_status = await container.business_database.healthcheck()
    llm_status = container.llm_status
    mcp_status = container.mcp_status
    return {
        "status": (
            "ok"
            if runtime_status.ok and business_status.ok and llm_status.ok and mcp_status.ok
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
            "provider": container.settings.llm_provider,
            "model": container.settings.llm_model,
            "detail": llm_status.detail,
        },
        "mcp": {
            "ok": mcp_status.ok,
            "configured_servers": sorted(container.settings.mcp_servers),
            "detail": mcp_status.detail,
        },
    }
