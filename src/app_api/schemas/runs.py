from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class CreateRunRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    session_id: str | None = None
    actor_id: str | None = None
    actor_metadata: dict[str, Any] = Field(default_factory=dict)


class RunResponse(BaseModel):
    run_id: str
    session_id: str
    status: str
    output: str | None = None
    pending_action: dict[str, Any] | None = None
    error: dict[str, Any] | None = None
