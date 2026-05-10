from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

# =============================================================================
# 基础枚举
# =============================================================================
type RunStatus = Literal["completed", "awaiting_action", "failed"]
type RiskLevel = Literal["low", "medium", "high"]


# =============================================================================
# 操作者上下文
# =============================================================================
class ActorContext(BaseModel):
    actor_id: str | None = None  # 触发本次运行的操作者 id；None 表示系统或匿名触发。
    metadata: dict[str, Any] = Field(default_factory=dict)  # 操作者相关扩展信息。


# =============================================================================
# 待处理动作和错误
# =============================================================================
class AgentPendingAction(BaseModel):
    action_id: str  # 待处理动作的唯一 id，用于审批和回调关联。
    action_name: str  # 待执行动作名称，通常对应工具名或业务动作名。
    action_payload: dict[str, Any] = Field(default_factory=dict)  # 真实动作入参，供后续执行使用。
    reason: str  # 需要暂停并等待处理的原因。
    risk_level: RiskLevel = "low"  # 动作风险等级，用于审批提示和优先级判断。
    display_payload: dict[str, Any] = Field(default_factory=dict)  # 展示给操作者的精简业务信息。


class AgentError(BaseModel):
    code: str  # 稳定错误码，便于客户端分类处理。
    message: str  # 面向调用方展示或记录的错误说明。


# =============================================================================
# Run 结果和状态
# =============================================================================
class AgentRunResult(BaseModel):
    run_id: str  # 本次 Agent 运行的唯一 id。
    session_id: str  # 运行所属会话 id，用于串联上下文和前端会话。
    capability_id: str  # 被调用的 Agent 能力 id。
    status: RunStatus  # 运行最终或当前状态。
    output: str | None = None  # 运行成功时返回的文本输出。
    pending_action: AgentPendingAction | None = None  # 需要人工处理时的待处理动作。
    error: AgentError | None = None  # 运行失败时的结构化错误信息。


class RunState(BaseModel):
    run_id: str  # 本次 Agent 运行的唯一 id。
    session_id: str  # 运行所属会话 id，用于恢复和追踪上下文。
    capability_id: str  # 被调用的 Agent 能力 id。
    status: RunStatus  # 当前运行状态。
    output: str | None = None  # 当前已生成或最终返回的文本输出。
    pending_action: AgentPendingAction | None = None  # 当前等待人工处理的动作。
    error: AgentError | None = None  # 当前运行失败时的结构化错误信息。
    metadata: dict[str, Any] = Field(default_factory=dict)  # 运行级扩展信息，供 runtime 或投影层使用。


# =============================================================================
# 运行存储状态
# =============================================================================
class RuntimeStoreStatus(BaseModel):
    ok: bool  # 存储后端是否可用。
    backend: str  # 当前运行存储后端名称。
    detail: str | None = None  # 可选诊断信息，通常用于健康检查输出。
