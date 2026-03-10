# 让类型标注的处理更顺手；在工程项目里很常见。
from __future__ import annotations

# Any 表示“这里先不严格限制具体类型”。
from typing import Any

# BaseModel 是 Pydantic 模型基类；
# Field 用来给字段补默认值、约束和元信息。
from pydantic import BaseModel, Field


# ErrorResponse 表示“一次失败结果里的错误部分”应该长什么样。
# 也就是说，以后 runtime 报错时，不只是返回一段字符串，
# 而是返回一个结构稳定的错误对象。
class ErrorResponse(BaseModel):
    # code 适合给程序判断错误类别，例如 unknown_tool / tool_validation_failed。
    code: str
    # message 适合给人看，说明这次错误大致发生了什么。
    message: str
    # details 用来放更细的上下文，例如原始参数、可用工具名、校验错误列表。
    # 这里的意思不是“把默认值直接写成同一个 {}”，
    # 而是“每次新建 ErrorResponse 对象时，都调用一次 dict()，生成一个新的空字典”。
    # 这样每个对象都有自己独立的 details，不会错误地和别的对象共享同一份字典。
    details: dict[str, Any] = Field(default_factory=dict)


# ToolCall 表示“一次工具调用请求”应该长什么样。
# runtime.execute(...) 收到原始参数后，会先把它们装配成 ToolCall，
# 这样后面的中间件、日志、执行器都围绕同一个对象来工作。
class ToolCall(BaseModel):
    # action 表示这次要调用哪个工具，例如 "add"。
    action: str
    # arguments 是这次工具调用的原始参数字典。
    # 它还是“未校验的原始输入”，后面会再交给 args_model.model_validate(...) 做校验。
    arguments: dict[str, Any] = Field(default_factory=dict)
    # request_id 用于日志、追踪、回放；不是每次都必须有。
    # 这里写成 str | None = None，表示：可以是字符串，也可以没有。
    request_id: str | None = None
    # metadata 用来挂附加上下文，例如调用来源、用户信息、调试信息。
    # 这类信息不一定参与真正业务执行，但对日志、追踪、调试很有用。
    metadata: dict[str, Any] = Field(default_factory=dict)


# ToolResult 表示“一次工具调用最终返回给外部的统一结果”。
# 这个类很重要，因为它保证：
# 成功时有统一外壳，失败时也有统一外壳。
# 这样前端、日志、测试、后续 workflow 都不用处理五花八门的返回形状。
class ToolResult(BaseModel):
    # success 表示这次工具调用最终是否成功。
    success: bool
    # action 保留这次执行的工具名，便于日志、前端和调试统一处理。
    action: str
    # request_id 跟请求对象里的 request_id 对应起来，方便追踪同一次调用。
    request_id: str | None = None
    # result 存成功结果；类型写成 Any，是因为不同工具返回值可能不同。
    # 例如 add 可能返回 int，get_city 可能返回 str，别的工具可能返回 dict。
    result: Any = None
    # error 存失败信息；成功时通常为 None，失败时通常为 ErrorResponse。
    # 这就实现了：成功看 result，失败看 error，但外层结构始终还是 ToolResult。
    error: ErrorResponse | None = None
