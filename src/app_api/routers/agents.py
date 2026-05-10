from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from agent_core.contracts.agent_definition import AgentDefinition
from agent_core.contracts.tool_spec import ToolSpec
from agent_core.registry import AgentRegistry
from app_api.deps import get_agent_registry, require_api_key
from app_api.schemas.agents import AgentSummary, AgentToolsResponse, ToolSummary

router = APIRouter(prefix="/api/agents", tags=["agents"])


def _agent_name(definition: AgentDefinition) -> str:
    return definition.name or definition.capability_id


def _agent_description(definition: AgentDefinition) -> str:
    return definition.description or ""


def _tool_summary(tool: ToolSpec) -> ToolSummary:
    return ToolSummary(
        name=tool.name,
        description=tool.description,
        source=tool.source,
        source_id=tool.source_id,
        # 把工具的 Pydantic 入参模型转成 JSON Schema，供前端/调用方理解参数结构。
        args_schema=tool.args_schema.model_json_schema(),
        # 这是工具目录的静态标识：有 approval_policy 表示运行时会先评估审批策略；
        # 具体某次调用是否暂停审批，取决于 approval_policy.evaluate(payload) 是否返回要求。
        requires_approval=tool.approval_policy is not None,
    )


@router.get("", response_model=list[AgentSummary])
async def list_agents(
    registry: Annotated[AgentRegistry, Depends(get_agent_registry)],
    _: None = Depends(require_api_key),
) -> list[AgentSummary]:
    return [
        AgentSummary(
            capability_id=definition.capability_id,
            name=_agent_name(definition),
            description=_agent_description(definition),
            tool_count=len(definition.tools),
        )
        for definition in registry.list_definitions()
    ]


@router.get("/{capability_id}/tools", response_model=AgentToolsResponse)
async def list_agent_tools(
    capability_id: str,
    registry: Annotated[AgentRegistry, Depends(get_agent_registry)],
    _: None = Depends(require_api_key),
) -> AgentToolsResponse:
    definition = registry.get(capability_id)
    if definition is None:
        raise HTTPException(status_code=404, detail=f"agent not found: {capability_id}")
    return AgentToolsResponse(
        capability_id=definition.capability_id,
        name=_agent_name(definition),
        description=_agent_description(definition),
        tools=[_tool_summary(tool) for tool in definition.tools],
    )
