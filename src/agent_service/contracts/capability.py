from __future__ import annotations

from dataclasses import dataclass

from agent_service.contracts.actions import ToolSpec


@dataclass(slots=True, frozen=True)
class AgentDefinition:
    capability_id: str
    system_prompt: str
    tools: tuple[ToolSpec, ...]
    name: str | None = None
    description: str | None = None
