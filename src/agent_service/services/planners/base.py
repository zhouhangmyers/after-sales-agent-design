from __future__ import annotations

import json
from math import ceil
from typing import Any, Literal, Protocol

from pydantic import BaseModel, Field


def estimate_tokens(text: str) -> int:
    stripped = text.strip()
    if not stripped:
        return 0
    return max(1, ceil(len(stripped) / 4))


# 把一个 Python 对象转成 JSON 格式的字符串，方便写日志、存 trace、放进 prompt。
def dump_payload(payload: object) -> str:
    # ensure_ascii=False 表示中文直接保留，不要转成 \uXXXX。
    # sort_keys=True 表示把字典的 key 排序，这样输出更稳定，调试和对比更方便。
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


class TokenUsage(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0

    @classmethod
    def from_texts(cls, prompt_text: str, completion_text: str) -> TokenUsage:
        prompt_tokens = estimate_tokens(prompt_text)
        completion_tokens = estimate_tokens(completion_text)
        return cls(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=prompt_tokens + completion_tokens,
        )

    @classmethod
    def combine(cls, usages: list[TokenUsage]) -> TokenUsage:
        return cls(
            prompt_tokens=sum(item.prompt_tokens for item in usages),
            completion_tokens=sum(item.completion_tokens for item in usages),
            total_tokens=sum(item.total_tokens for item in usages),
        )

# ToolSchema 表示“一个工具长什么样”。
# 这里装的不是执行结果，而是工具的定义信息。
# planner 在决定要不要调工具时，会先看这些信息。
class ToolSchema(BaseModel):
    # 工具名字，例如 add、divide、get_city。
    name: str
    # 工具说明，告诉 planner 这个工具是干什么的。
    description: str
    # 这个工具的参数 schema。
    # 里面通常会写这个工具有哪些参数、参数类型是什么、哪些参数必填。
    arguments_json_schema: dict[str, Any] = Field(default_factory=dict)


# ToolObservation 表示“工具执行完以后观察到了什么”。
# 这不是工具定义，而是一次工具调用后的结果记录。
class ToolObservation(BaseModel):
    # 这次调用的是哪个工具。
    tool_name: str
    # 调这个工具时传了什么参数。
    arguments: dict[str, Any] = Field(default_factory=dict)
    # 这次工具调用是否成功。
    success: bool
    # 工具执行成功或失败后拿到的结果。
    result: Any = None
    # 如果失败了，这里记录错误信息；没错就可能是 None。
    error_message: str | None = None


# PromptRender 表示“最终渲染出来的 prompt 成品”。
# 前面的 ToolSchema、ToolObservation、user_message 等信息，
# 最后会被整理成这里的 content，交给 planner 模型看。
class PromptRender(BaseModel):
    # 这份 prompt 用的是哪个模板名字。
    name: str
    # 这份 prompt 用的是哪个模板版本。
    version: str
    # 真正拼好的 prompt 正文。
    content: str

# PlannerRequest 表示“一次 planner 调用的完整输入包”。
# 也就是这一轮在调用 planner/LLM 之前，
# 系统要交给它看的所有上下文信息。
class PlannerRequest(BaseModel):
    # 当前会话 id，用来标识这是哪个 session 的请求。
    session_id: str | None = None
    # 用户原始消息，也就是这轮任务最初的问题或指令。
    user_message: str
    # 当前有哪些工具可用。
    tool_schemas: list[ToolSchema] = Field(default_factory=list)
    # 前面工具执行后积累下来的 observation 列表。
    observations: list[ToolObservation] = Field(default_factory=list)
    # 根据上面这些上下文最终渲染出来的 prompt 成品。
    prompt: PromptRender

# PlannerDecision 表示“planner 这一轮最后做出的决定”。
# 它回答的是：下一步到底要直接回复，还是去调用工具。
class PlannerDecision(BaseModel):
    # 决策类型：
    # respond = 直接回复用户
    # tool_call = 调用某个工具
    kind: Literal["respond", "tool_call"]
    # 如果 kind 是 respond，这里放最终回复内容。
    response: str | None = None
    # 如果 kind 是 tool_call，这里放要调用的工具名。
    tool_name: str | None = None
    # 如果 kind 是 tool_call，这里放工具参数。
    tool_arguments: dict[str, Any] = Field(default_factory=dict)
    # 这次决策的理由，也就是“为什么这么决定”。
    # 它主要用于调试、trace 和排查问题，通常不是直接给用户看的。
    rationale: str = ""

# PlannerCallTrace 表示“一次 planner 调用的完整记录”。
# 你可以把它理解成 planner 这一轮的 trace / 调用痕迹。
# 它主要用于：
# - 持久化到 llm_calls
# - 排查问题
# - 做观测和调试
class PlannerCallTrace(BaseModel):
    # 这次调用使用的是哪个 provider，例如 demo / openai / deepseek。
    provider: str
    # 这次调用使用的是哪个模型。
    model: str
    # 这次调用用的是哪套 prompt 模板名字。
    prompt_name: str
    # 这次调用用的是哪套 prompt 模板版本。
    prompt_version: str
    # 发给 planner 的完整请求内容。
    request_payload: dict[str, Any] = Field(default_factory=dict)
    # planner 返回的原始响应内容。
    raw_response: dict[str, Any] | None = None
    # 从原始响应里整理出来的结构化决策结果。
    decision: PlannerDecision | None = None
    # 这次调用消耗的 token 统计。
    usage: TokenUsage = Field(default_factory=TokenUsage)
    # 这次调用耗时多少毫秒。
    latency_ms: float = 0.0
    # 这次调用一共尝试了几次（包含重试）。
    attempts: int = 1
    # 这次调用是否成功。
    success: bool = True
    # 如果失败了，这里记录错误信息。
    error_message: str | None = None


# PlannerModelClient 是一个“协议接口”。
# 你可以把它理解成：
# 只要某个 planner client 满足这里规定的字段和方法，
# 它就可以被 PlannerService 当成可用的 planner 实现来调用。
class PlannerModelClient(Protocol):
    # provider 名字，例如 demo / openai / deepseek。
    provider: str
    # model 名字，例如 demo-structured-planner-v1 / deepseek-reasoner。
    model: str

    # plan(...) 表示真正执行一次 planner 调用。
    # 输入是 PlannerRequest，
    # 输出是：
    # 1. PlannerDecision：结构化决策
    # 2. dict[str, Any]：原始响应
    # 3. TokenUsage：token 使用情况
    def plan(self, request: PlannerRequest) -> tuple[PlannerDecision, dict[str, Any], TokenUsage]:
        ...
