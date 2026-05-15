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
    """一次 run/act 调用结束当前执行段时返回给调用方的结果。

    设计意图：
    Agent 可能一次性完成，也可能因为人工审批等 interrupt 暂停。
    AgentRunResult 表达的是“这次调用跑到当前边界时，应该返回什么”。

    用法：
    - RunCompletedEvent 携带 AgentRunResult 作为流式执行的收尾事件。
    - use case 的 run()/act() 等待 RunCompletedEvent 后，把它作为调用结果返回。
    - 不放查询态扩展信息；需要查询当前 run 快照时使用 RunState。
    """

    run_id: str  # 本次 Agent 运行的唯一 id。
    session_id: str  # 运行所属会话 id，用于串联上下文和前端会话。
    capability_id: str  # 被调用的 Agent 能力 id。
    status: RunStatus  # 运行最终或当前状态。
    output: str | None = None  # 运行成功时返回的文本输出。
    pending_action: AgentPendingAction | None = None  # 需要人工处理时的待处理动作。
    error: AgentError | None = None  # 运行失败时的结构化错误信息。


class RunState(BaseModel):
    """按 run_id 查询出来的当前运行状态快照。

    设计意图：
    调用方可能在 run 结束后、人工审批前后、或页面刷新后查询当前状态。
    RunState 表达的是“这个 run 现在是什么样”，而不是某次调用的返回值。

    用法：
    - get_state() 返回 RunState，用于恢复页面、展示 pending_action、错误和当前输出。
    - 可以携带 metadata，例如 token usage 这类运行级扩展信息。
    - 与 AgentRunResult 字段相似，但语义是查询快照，不是执行流的收尾结果。
    """

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
