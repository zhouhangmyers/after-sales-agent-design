from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel


class AgentSummary(BaseModel):
    capability_id: str
    name: str
    description: str
    tool_count: int


class ToolSummary(BaseModel):
    name: str
    description: str
    source: Literal["local", "mcp"]
    source_id: str | None = None
    args_schema: dict[str, Any]
    requires_approval: bool


class AgentToolsResponse(BaseModel):
    capability_id: str
    name: str
    description: str
    tools: list[ToolSummary]
