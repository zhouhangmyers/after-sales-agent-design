from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, Field


class ErrorResponse(BaseModel):
    code: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class ToolResult(BaseModel):
    success: bool
    action: str
    request_id: str | None = None
    result: Any = None
    error: ErrorResponse | None = None


@dataclass(slots=True, frozen=True)
class ApprovalRequirement:
    reason: str
    risk_level: str = "low"
    display_payload: dict[str, object] | None = None


@dataclass(slots=True, frozen=True)
class ToolPolicy:
    tool_name: str
    approval_required: bool = False
    risk_level: str = "low"
    approval_evaluator: Callable[[dict[str, Any]], ApprovalRequirement | None] | None = None


@dataclass(slots=True, frozen=True)
class ToolRequest:
    action: str
    arguments: dict[str, Any]


@dataclass(slots=True, frozen=True)
class ToolExecution:
    request: ToolRequest
    result: ToolResult
    latency_ms: float
    tool_call_id: str | None = None
