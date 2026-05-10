from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from agent_core.contracts.run_state import (
    AgentError,
    AgentPendingAction,
    AgentRunResult,
)


# =============================================================================
# Run 生命周期事件
# =============================================================================
@dataclass(slots=True, frozen=True)
class RunStartedEvent:
    run_id: str
    session_id: str
    capability_id: str


@dataclass(slots=True, frozen=True)
class RunCompletedEvent:
    result: AgentRunResult


@dataclass(slots=True, frozen=True)
class RunFailedEvent:
    run_id: str
    error: AgentError


# =============================================================================
# 模型输出事件
# =============================================================================
@dataclass(slots=True, frozen=True)
class OutputDeltaEvent:
    run_id: str
    delta: str


# =============================================================================
# 工具和人工动作事件
# =============================================================================
@dataclass(slots=True, frozen=True)
class ActionStartedEvent:
    run_id: str
    action_id: str
    action_name: str
    action_payload: dict[str, Any]


@dataclass(slots=True, frozen=True)
class ActionCompletedEvent:
    run_id: str
    action_id: str
    action_name: str
    action_payload: dict[str, Any]
    success: bool
    latency_ms: float
    result: Any = None
    error: dict[str, Any] | None = None


@dataclass(slots=True, frozen=True)
class ActionRequiredEvent:
    run_id: str
    pending_action: AgentPendingAction


# =============================================================================
# 统一事件类型
# =============================================================================
type RunEvent = (
    RunStartedEvent
    | OutputDeltaEvent
    | ActionStartedEvent
    | ActionCompletedEvent
    | ActionRequiredEvent
    | RunCompletedEvent
    | RunFailedEvent
)
