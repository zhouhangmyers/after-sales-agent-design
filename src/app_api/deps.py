from __future__ import annotations

from typing import Annotated, cast

from fastapi import Depends, Header, HTTPException, Request

from after_sales.application.services.after_sales_service import (
    AfterSalesService,
)
from agent_core.registry import AgentRegistry
from app_api.composition.container import AppContainer
from app_api.use_cases.after_sales_agent_use_case import (
    AfterSalesAgentUseCase,
)


async def get_container(request: Request) -> AppContainer:
    return cast(AppContainer, request.app.state.container)


async def require_api_key(
    request: Request,
    x_api_key: str | None = Header(default=None),
) -> None:
    expected = request.app.state.settings.api_key
    if expected is None:
        return
    if x_api_key != expected.get_secret_value():
        raise HTTPException(status_code=401, detail="invalid api key")


async def get_after_sales_service(
    container: Annotated[AppContainer, Depends(get_container)],
) -> AfterSalesService:
    return container.after_sales_service


async def get_after_sales_agent_use_case(
    container: Annotated[AppContainer, Depends(get_container)],
) -> AfterSalesAgentUseCase:
    agent_use_case = container.after_sales_agent_use_case
    if agent_use_case is None:
        detail = container.llm_status.detail or "LLM dependency is not ready"
        raise HTTPException(
            status_code=503,
            detail=f"assistant service unavailable: {detail}",
        )
    return agent_use_case


async def get_agent_registry(
    container: Annotated[AppContainer, Depends(get_container)],
) -> AgentRegistry:
    return container.agent_registry
