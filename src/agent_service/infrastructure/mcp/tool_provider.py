from __future__ import annotations

import json
import re
from typing import Any, cast

from langchain_core.messages import BaseMessage
from langchain_core.tools.base import BaseTool
from pydantic import BaseModel, ConfigDict

from agent_service.contracts.actions import ToolContext, ToolSpec
from agent_service.llm.payloads import message_payload


class MCPToolInput(BaseModel):
    model_config = ConfigDict(extra="allow")


class MCPToolProvider:
    def __init__(self, server_configs: dict[str, dict[str, object]]) -> None:
        self._server_configs = server_configs

    async def load_tools(self) -> tuple[ToolSpec, ...]:
        if not self._server_configs:
            return ()

        try:
            from langchain_mcp_adapters.client import MultiServerMCPClient
        except ImportError as exc:
            raise RuntimeError(
                "MCP support requires the `langchain-mcp-adapters` package."
            ) from exc

        loaded_tools: list[ToolSpec] = []
        for server_name, server_config in self._server_configs.items():
            client = MultiServerMCPClient(cast(Any, {server_name: server_config}))
            tools = await client.get_tools()
            loaded_tools.extend(
                _tool_spec_from_mcp_tool(server_name=server_name, tool=tool)
                for tool in tools
            )
        return tuple(loaded_tools)


def _tool_spec_from_mcp_tool(*, server_name: str, tool: BaseTool) -> ToolSpec:
    original_tool_name = tool.name
    namespaced_name = f"mcp_{_safe_identifier(server_name)}_{_safe_identifier(original_tool_name)}"
    args_schema = _args_schema_from_tool(tool)

    async def handler(
        payload: dict[str, Any],
        context: ToolContext,
        *,
        mcp_tool: BaseTool = tool,
    ) -> object:
        del context
        result = await mcp_tool.ainvoke(payload)
        return _jsonable(result)

    return ToolSpec(
        name=namespaced_name,
        description=tool.description or f"MCP tool `{original_tool_name}` from `{server_name}`.",
        args_schema=args_schema,
        handler=handler,
        source="mcp",
        source_id=server_name,
    )


def _args_schema_from_tool(tool: BaseTool) -> type[BaseModel]:
    args_schema = getattr(tool, "args_schema", None)
    if isinstance(args_schema, type) and issubclass(args_schema, BaseModel):
        return args_schema
    return MCPToolInput


def _safe_identifier(value: str) -> str:
    normalized = re.sub(r"[^0-9A-Za-z_]+", "_", value).strip("_").lower()
    return normalized or "tool"


def _jsonable(value: object) -> object:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, BaseMessage):
        return message_payload(value)
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_jsonable(item) for item in value]
    try:
        json.dumps(value)
    except TypeError:
        return str(value)
    return value
