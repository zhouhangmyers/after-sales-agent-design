from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

from pydantic import BaseModel

from agent_service.tools.models import ApprovalRequirement


@dataclass(slots=True, frozen=True)
class AgentExecutionContext:
    capability_id: str
    actor_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class AgentActionHandler(Protocol):
    def __call__(self, payload: dict[str, Any], context: AgentExecutionContext) -> Any: ...


ActionApprovalEvaluator = Callable[[dict[str, Any]], ApprovalRequirement | None]


@dataclass(slots=True, frozen=True)
class AgentActionDefinition:
    name: str
    description: str
    args_schema: type[BaseModel]
    handler: AgentActionHandler
    approval_evaluator: ActionApprovalEvaluator | None = None
