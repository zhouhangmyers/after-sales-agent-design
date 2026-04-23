from __future__ import annotations

from agent_service.infrastructure.actions.dispatcher import LangChainActionDispatcher
from agent_service.infrastructure.state_store.in_memory_store import InMemoryStateStore
from agent_service.infrastructure.state_store.langgraph_postgres_store import (
    LangGraphPostgresStateStore,
)
from agent_service.infrastructure.workflow.workflow_engine import WorkflowEngine
from agent_service.llm.bound_client import build_chat_client
from agent_service.llm.types import ChatClient
from app_api.container import AppContainer, DependencyStatus, RuntimeStateStore
from app_api.migrations import upgrade_business_database
from app_api.settings import AppSettings
from business_service.after_sales.application.capability.capability import (
    build_capability,
)
from business_service.after_sales.application.services.assistant_service import (
    AfterSalesAssistantService,
)
from business_service.after_sales.infrastructure.persistence.sqlalchemy.repositories import (
    SqlAlchemyAfterSalesRepository,
)
from business_service.after_sales.infrastructure.persistence.sqlalchemy.session import (
    BusinessDatabase,
)


def build_runtime_state_store(
    settings: AppSettings,
    runtime_state_store_override: RuntimeStateStore | None,
) -> RuntimeStateStore:
    if runtime_state_store_override is not None:
        return runtime_state_store_override
    if settings.agent_runtime_database_url:
        return LangGraphPostgresStateStore(settings.agent_runtime_database_url)
    return InMemoryStateStore()


def build_llm_dependency(
    settings: AppSettings,
    *,
    chat_client_override: ChatClient | None = None,
) -> tuple[ChatClient | None, DependencyStatus]:
    if chat_client_override is not None:
        return chat_client_override, DependencyStatus(ok=True)
    try:
        return (
            build_chat_client(
                llm_provider=settings.llm_provider,
                llm_model=settings.llm_model,
                llm_timeout_seconds=settings.llm_timeout_seconds,
                llm_max_retries=settings.llm_max_retries,
                deepseek_api_key=(
                    settings.deepseek_api_key.get_secret_value()
                    if settings.deepseek_api_key is not None
                    else None
                ),
            ),
            DependencyStatus(ok=True),
        )
    except Exception as exc:
        return None, DependencyStatus(
            ok=False,
            detail=str(exc) or exc.__class__.__name__,
        )


def build_container(
    settings: AppSettings,
    *,
    chat_client_override: ChatClient | None = None,
    runtime_state_store_override: RuntimeStateStore | None = None,
) -> AppContainer:
    if settings.auto_create_schema:
        upgrade_business_database(database_url=settings.business_database_url)

    runtime_state_store = build_runtime_state_store(
        settings,
        runtime_state_store_override,
    )
    business_database = BusinessDatabase(settings.business_database_url)
    repository = SqlAlchemyAfterSalesRepository(business_database.managed_session)
    chat_client, llm_status = build_llm_dependency(
        settings,
        chat_client_override=chat_client_override,
    )
    assistant_service: AfterSalesAssistantService | None = None
    if chat_client is not None:
        capability = build_capability(repository=repository)
        workflow_engine = WorkflowEngine(
            chat_client=chat_client,
            action_dispatcher=LangChainActionDispatcher(),
            state_store=runtime_state_store,
            llm_timeout_seconds=settings.llm_timeout_seconds,
            llm_max_retries=settings.llm_max_retries,
            max_steps=settings.max_steps,
            approval_timeout_seconds=settings.approval_timeout_seconds,
        )
        assistant_service = AfterSalesAssistantService(
            workflow_engine=workflow_engine,
            capability=capability,
            repository=repository,
        )
    container = AppContainer(
        settings=settings,
        business_database=business_database,
        runtime_state_store=runtime_state_store,
        after_sales_repository=repository,
        after_sales_assistant_service=assistant_service,
        llm_status=llm_status,
    )
    return container
