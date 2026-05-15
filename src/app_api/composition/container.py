from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from agent_runtime.langchain.runtime_state_store import AgentRuntimeStateStore

if TYPE_CHECKING:
    from after_sales.application.services.after_sales_service import (
        AfterSalesService,
    )
    from after_sales.infrastructure.persistence.sqlalchemy.session import (
        BusinessDatabase,
    )
    from agent_core.registry import AgentRegistry
    from app_api.settings import AppSettings
    from app_api.use_cases.after_sales_agent_use_case import (
        AfterSalesAgentUseCase,
    )


@dataclass(slots=True, frozen=True)
class DependencyStatus:
    ok: bool
    detail: str | None = None


@dataclass(slots=True)
class AppContainer:
    settings: AppSettings
    business_database: BusinessDatabase
    runtime_state_store: AgentRuntimeStateStore
    after_sales_service: AfterSalesService
    after_sales_agent_use_case: AfterSalesAgentUseCase | None
    agent_registry: AgentRegistry
    llm_status: DependencyStatus = field(default_factory=lambda: DependencyStatus(ok=True))
    mcp_status: DependencyStatus = field(default_factory=lambda: DependencyStatus(ok=True))

    async def close(self) -> None:
        await self.runtime_state_store.close()
        await self.business_database.dispose()
