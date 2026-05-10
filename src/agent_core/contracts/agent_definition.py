from __future__ import annotations

from dataclasses import dataclass

from agent_core.contracts.tool_spec import ToolSpec


@dataclass(slots=True, frozen=True)
class AgentDefinition:
    """Framework-independent definition of an agent capability."""

    capability_id: str
    system_prompt: str
    tools: tuple[ToolSpec, ...]
    name: str | None = None
    description: str | None = None
