from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from agent_service.contracts.models import AgentError, AgentPendingAction, RunStatus


class CreateRunRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    session_id: str | None = None
    actor_id: str | None = None
    actor_metadata: dict[str, Any] = Field(default_factory=dict)


class RunResponse(BaseModel):
    run_id: str
    session_id: str
    status: RunStatus
    output: str | None = None
    pending_action: AgentPendingAction | None = None
    error: AgentError | None = None
