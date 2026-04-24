from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from agent_service.infrastructure.state_store.in_memory_store import InMemoryStateStore
from agent_service.infrastructure.state_store.langgraph_postgres_store import (
    LangGraphPostgresStateStore,
)

if TYPE_CHECKING:
    from agent_service.contracts.registry import AgentRegistry
    from app_api.services.after_sales_assistant import (
        AfterSalesAssistantService,
    )
    from app_api.settings import AppSettings
    from business_service.after_sales.application.services.after_sales_service import (
        AfterSalesService,
    )
    from business_service.after_sales.infrastructure.persistence.sqlalchemy.session import (
        BusinessDatabase,
    )

RuntimeStateStore = InMemoryStateStore | LangGraphPostgresStateStore


@dataclass(slots=True, frozen=True)
class DependencyStatus:
    ok: bool
    detail: str | None = None


@dataclass(slots=True)
class AppContainer:
    settings: AppSettings
    business_database: BusinessDatabase
    runtime_state_store: RuntimeStateStore
    after_sales_service: AfterSalesService
    after_sales_assistant_service: AfterSalesAssistantService | None
    agent_registry: AgentRegistry
    llm_status: DependencyStatus = field(default_factory=lambda: DependencyStatus(ok=True))
    mcp_status: DependencyStatus = field(default_factory=lambda: DependencyStatus(ok=True))

    async def close(self) -> None:
        await self.runtime_state_store.close()
        await self.business_database.dispose()
