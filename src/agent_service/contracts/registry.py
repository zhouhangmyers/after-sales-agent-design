from __future__ import annotations

from dataclasses import dataclass, field

from agent_service.contracts.capability import AgentDefinition


@dataclass(slots=True)
class AgentRegistry:
    _definitions: dict[str, AgentDefinition] = field(default_factory=dict)

    def register(self, definition: AgentDefinition) -> None:
        self._definitions[definition.capability_id] = definition

    def get(self, capability_id: str) -> AgentDefinition | None:
        return self._definitions.get(capability_id)

    def list_definitions(self) -> list[AgentDefinition]:
        return [
            self._definitions[key]
            for key in sorted(self._definitions)
        ]
