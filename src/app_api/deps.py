from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request

from app_api.container import AppContainer
from business_service.after_sales.application.services.assistant_service import (
    AfterSalesAssistantService,
)
from business_service.after_sales.infrastructure.persistence.sqlalchemy.repositories import (
    SqlAlchemyAfterSalesRepository,
)


def get_container(request: Request) -> AppContainer:
    return request.app.state.container


def require_api_key(
    request: Request,
    x_api_key: str | None = Header(default=None),
) -> None:
    expected = request.app.state.settings.api_key
    if expected is None:
        return
    if x_api_key != expected.get_secret_value():
        raise HTTPException(status_code=401, detail="invalid api key")


def get_after_sales_repository(
    container: Annotated[AppContainer, Depends(get_container)],
) -> SqlAlchemyAfterSalesRepository:
    return container.after_sales_repository


def get_after_sales_assistant_service(
    container: Annotated[AppContainer, Depends(get_container)],
) -> AfterSalesAssistantService:
    assistant_service = container.after_sales_assistant_service
    if assistant_service is None:
        detail = container.llm_status.detail or "LLM dependency is not ready"
        raise HTTPException(
            status_code=503,
            detail=f"assistant service unavailable: {detail}",
        )
    return assistant_service
