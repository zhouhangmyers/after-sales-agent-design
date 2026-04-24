from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from agent_service.contracts.actions import ToolSpec
from agent_service.contracts.capability import AgentDefinition
from agent_service.contracts.registry import AgentRegistry
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
        args_schema=tool.args_schema.model_json_schema(),
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
