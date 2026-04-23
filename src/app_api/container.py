from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from agent_service.infrastructure.state_store.in_memory_store import InMemoryStateStore
from agent_service.infrastructure.state_store.langgraph_postgres_store import (
    LangGraphPostgresStateStore,
)

if TYPE_CHECKING:
    from app_api.settings import AppSettings
    from business_service.after_sales.application.services.assistant_service import (
        AfterSalesAssistantService,
    )
    from business_service.after_sales.infrastructure.persistence.sqlalchemy.repositories import (
        SqlAlchemyAfterSalesRepository,
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
    after_sales_repository: SqlAlchemyAfterSalesRepository
    after_sales_assistant_service: AfterSalesAssistantService | None
    llm_status: DependencyStatus = field(default_factory=lambda: DependencyStatus(ok=True))

    def close(self) -> None:
        self.runtime_state_store.close()
        self.business_database.dispose()
