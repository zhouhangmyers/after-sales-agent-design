from __future__ import annotations

from dataclasses import dataclass

from agent_service.contracts.actions import AgentActionDefinition


@dataclass(slots=True, frozen=True)
class AgentCapability:
    capability_id: str
    role_title: str
    domain_objective: str
    action_selection_rules: tuple[str, ...]
    response_rules: tuple[str, ...]
    actions: tuple[AgentActionDefinition, ...]
