from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

from pydantic import BaseModel

from agent_service.contracts.models import ActorContext, RiskLevel


@dataclass(slots=True, frozen=True)
class ApprovalRequirement:
    reason: str
    risk_level: RiskLevel = "low"
    display_payload: dict[str, object] | None = None


@dataclass(slots=True, frozen=True)
class ToolContext:
    capability_id: str
    actor: ActorContext = field(default_factory=ActorContext)
    dependencies: object | None = None


class ToolHandler(Protocol):
    def __call__(self, payload: dict[str, Any], context: ToolContext) -> Any: ...


class ApprovalPolicy(Protocol):
    def evaluate(self, payload: dict[str, Any]) -> ApprovalRequirement | None: ...


@dataclass(slots=True, frozen=True)
class CallableApprovalPolicy:
    evaluator: Callable[[dict[str, Any]], ApprovalRequirement | None]

    def evaluate(self, payload: dict[str, Any]) -> ApprovalRequirement | None:
        return self.evaluator(payload)


@dataclass(slots=True, frozen=True)
class ToolSpec:
    name: str
    description: str
    args_schema: type[BaseModel]
    handler: ToolHandler
    approval_policy: ApprovalPolicy | None = None
    source: Literal["local", "mcp"] = "local"
    source_id: str | None = None
