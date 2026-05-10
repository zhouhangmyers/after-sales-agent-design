from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

from pydantic import BaseModel

from agent_core.contracts.run_state import ActorContext, RiskLevel


# =============================================================================
# 工具执行契约：ToolSpec.handler
# =============================================================================
@dataclass(slots=True, frozen=True)
class ToolContext:
    """工具执行时由 runtime 注入的上下文，不来自模型生成参数。"""

    capability_id: str  # 当前 Agent 能力 id，用于审计和区分工具归属。
    actor: ActorContext = field(default_factory=ActorContext)  # 触发本次工具调用的操作者。
    dependencies: object | None = None  # 可选依赖容器，复杂工具可从这里取 service。


class ToolHandler(Protocol):
    """所有 ToolSpec handler 都要满足的调用签名。"""

    def __call__(self, payload: dict[str, Any], context: ToolContext) -> Any: ...


# =============================================================================
# 工具审批契约：ToolSpec.approval_policy
# =============================================================================
@dataclass(slots=True, frozen=True)
class ApprovalRequirement:
    """工具执行前需要人工审批时返回的结构化要求。"""

    reason: str  # 需要人工审批的原因。
    risk_level: RiskLevel = "low"  # 风险等级，用于前端提示和审批优先级。
    display_payload: dict[str, object] | None = None  # 展示给审批人的精简业务信息。


class ApprovalPolicy(Protocol):
    """工具执行前的审批策略接口。"""

    def evaluate(self, payload: dict[str, Any]) -> ApprovalRequirement | None: ...


@dataclass(slots=True, frozen=True)
class CallableApprovalPolicy:
    """把普通函数包装成 ApprovalPolicy，避免简单规则也要写完整策略类。"""

    evaluator: Callable[[dict[str, Any]], ApprovalRequirement | None]  # 返回 None 表示无需审批。

    def evaluate(self, payload: dict[str, Any]) -> ApprovalRequirement | None:
        return self.evaluator(payload)


# =============================================================================
# 统一工具定义：组合执行签名和审批策略
# =============================================================================
@dataclass(slots=True, frozen=True)
class ToolSpec:
    """项目内部统一工具定义，供 runtime、API catalog 和 MCP adapter 共同使用。"""

    name: str  # 暴露给模型的工具名，必须稳定且可作为调用标识。
    description: str  # 工具用途说明，影响模型何时选择该工具。
    args_schema: type[BaseModel]  # 工具参数 schema，用于入参校验和 JSON Schema 暴露。
    handler: ToolHandler  # 工具真正执行的函数，接收模型 payload 和系统上下文。
    approval_policy: ApprovalPolicy | None = None  # 可选审批策略；None 表示可直接执行。
    source: Literal["local", "mcp"] = "local"  # 工具来源：本地业务 adapter 或 MCP server。
    source_id: str | None = None  # 外部来源标识，例如 MCP server 名称。
