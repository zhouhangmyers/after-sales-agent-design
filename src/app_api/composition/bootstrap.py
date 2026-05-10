from __future__ import annotations

from contextlib import AbstractAsyncContextManager
from dataclasses import replace

from langchain_core.language_models.chat_models import BaseChatModel

from after_sales.application.ports import AfterSalesUnitOfWork
from after_sales.application.services.after_sales_service import (
    AfterSalesService,
)
from after_sales.infrastructure.persistence.sqlalchemy.session import (
    BusinessDatabase,
)
from after_sales.infrastructure.persistence.sqlalchemy.unit_of_work import (
    SqlAlchemyAfterSalesUnitOfWork,
)
from agent_core.contracts.agent_definition import AgentDefinition
from agent_core.contracts.tool_spec import ToolSpec
from agent_core.registry import AgentRegistry
from agent_integrations.llm.chat_model_factory import build_chat_model
from agent_integrations.mcp import MCPToolProvider
from agent_runtime.langchain.checkpoint.langgraph_postgres import (
    LangGraphPostgresStateStore,
)
from agent_runtime.langchain.checkpoint.local_memory import (
    InMemoryStateStore,
)
from agent_runtime.langchain.runtime import LangChainAgentRuntime
from app_api.composition.after_sales_agent_factory import (
    build_after_sales_agent_definition,
)
from app_api.composition.container import (
    AppContainer,
    DependencyStatus,
    RuntimeStateStore,
)
from app_api.migrations import upgrade_business_database
from app_api.projectors.after_sales_run_projector import AfterSalesRunProjector
from app_api.settings import AppSettings
from app_api.use_cases.after_sales_agent_use_case import AfterSalesAgentUseCase


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
    chat_model_override: BaseChatModel | None = None,
) -> tuple[BaseChatModel | None, DependencyStatus]:
    if chat_model_override is not None:
        return chat_model_override, DependencyStatus(ok=True)
    try:
        return (
            build_chat_model(
                llm_provider=settings.llm_provider,
                llm_model=settings.llm_model,
                llm_timeout_seconds=settings.llm_timeout_seconds,
                llm_max_retries=settings.llm_max_retries,
                deepseek_api_key=(
                    settings.deepseek_api_key.get_secret_value()
                    if settings.deepseek_api_key is not None
                    else None
                ),
                openai_api_key=(
                    settings.openai_api_key.get_secret_value()
                    if settings.openai_api_key is not None
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


async def load_mcp_tools(settings: AppSettings) -> tuple[tuple[ToolSpec, ...], DependencyStatus]:
    if not settings.mcp_servers:
        return (), DependencyStatus(ok=True)

    server_configs = {
        name: config.model_dump(mode="json", exclude_none=True, exclude_defaults=True)
        for name, config in settings.mcp_servers.items()
    }
    try:
        tools = await MCPToolProvider(server_configs).load_tools()
    except Exception as exc:
        return (), DependencyStatus(
            ok=False,
            detail=str(exc) or exc.__class__.__name__,
        )
    return tools, DependencyStatus(ok=True)


def _definition_with_extra_tools(
    definition: AgentDefinition,
    extra_tools: tuple[ToolSpec, ...],
) -> AgentDefinition:
    if not extra_tools:
        return definition
    return replace(definition, tools=(*definition.tools, *extra_tools))


async def build_container(
    settings: AppSettings,
    *,
    chat_model_override: BaseChatModel | None = None,
    runtime_state_store_override: RuntimeStateStore | None = None,
) -> AppContainer:
    if settings.auto_create_schema:
        upgrade_business_database(database_url=settings.business_database_url)

    runtime_state_store = build_runtime_state_store(
        settings,
        runtime_state_store_override,
    )
    business_database = BusinessDatabase(settings.business_database_url)

    def unit_of_work_factory() -> AbstractAsyncContextManager[AfterSalesUnitOfWork]:
        return SqlAlchemyAfterSalesUnitOfWork(business_database.managed_session)

    after_sales_service = AfterSalesService(
        unit_of_work_factory=unit_of_work_factory,
    )
    mcp_tools, mcp_status = await load_mcp_tools(settings)

    agent_registry = AgentRegistry()
    after_sales_definition = _definition_with_extra_tools(
        build_after_sales_agent_definition(
            after_sales_service=after_sales_service,
        ),
        mcp_tools,
    )
    agent_registry.register(after_sales_definition)

    chat_model, llm_status = build_llm_dependency(
        settings,
        chat_model_override=chat_model_override,
    )
    after_sales_agent_use_case: AfterSalesAgentUseCase | None = None
    if chat_model is not None:
        runtime = LangChainAgentRuntime(
            model=chat_model,
            state_store=runtime_state_store,
            max_steps=settings.max_steps,
        )
        after_sales_agent_use_case = AfterSalesAgentUseCase(
            runtime=runtime,
            definition=after_sales_definition,
            projector=AfterSalesRunProjector(
                unit_of_work_factory=unit_of_work_factory,
            ),
        )
    container = AppContainer(
        settings=settings,
        business_database=business_database,
        runtime_state_store=runtime_state_store,
        after_sales_service=after_sales_service,
        after_sales_agent_use_case=after_sales_agent_use_case,
        agent_registry=agent_registry,
        llm_status=llm_status,
        mcp_status=mcp_status,
    )
    return container
