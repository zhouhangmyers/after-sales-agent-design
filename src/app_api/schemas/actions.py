from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class ActionRequest(BaseModel):
    run_id: str = Field(min_length=1)
    action_id: str = Field(min_length=1)
    decision: Literal["approved", "rejected"]
    actor_id: str | None = None
    actor_metadata: dict[str, Any] = Field(default_factory=dict)
