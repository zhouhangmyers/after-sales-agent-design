from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

type RunStatus = Literal["completed", "awaiting_action", "failed"]
type RiskLevel = Literal["low", "medium", "high"]


class ActorContext(BaseModel):
    actor_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class AgentPendingAction(BaseModel):
    action_id: str
    action_name: str
    action_payload: dict[str, Any] = Field(default_factory=dict)
    reason: str
    risk_level: RiskLevel = "low"
    display_payload: dict[str, Any] = Field(default_factory=dict)


class AgentError(BaseModel):
    code: str
    message: str


class AgentRunResult(BaseModel):
    run_id: str
    session_id: str
    capability_id: str
    status: RunStatus
    output: str | None = None
    pending_action: AgentPendingAction | None = None
    error: AgentError | None = None


class RunState(BaseModel):
    run_id: str
    session_id: str
    capability_id: str
    status: RunStatus
    output: str | None = None
    pending_action: AgentPendingAction | None = None
    error: AgentError | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class RuntimeStoreStatus(BaseModel):
    ok: bool
    backend: str
    detail: str | None = None
