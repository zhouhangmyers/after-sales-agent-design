from __future__ import annotations

from agent_runtime.models import ToolResult
from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    # 当前这次聊天请求属于哪个会话。
    # 同一个 session_id 下，后端会把用户消息、助手回复、工具调用等数据串到一起。
    session_id: str = Field(min_length=1, max_length=64)
    # 用户输入的原始消息内容。
    # 当前 Week 2 会根据这段文本决定是否解析并执行演示工具。
    message: str = Field(min_length=1, max_length=2000)


class ChatResponse(BaseModel):
    # 这次响应归属的会话 ID。
    session_id: str
    # 用户这条消息对应的消息 ID。
    # 当前设计里由后端生成，而不是要求前端传入。
    message_id: str
    # 助手回复消息对应的消息 ID。
    # 之所以单独保留，是因为“用户消息”和“助手回复”在数据库里是两条不同记录。
    assistant_message_id: str
    # 返回给前端直接展示的人话回复。
    reply: str
    # 如果这次消息触发了工具调用，就把结构化工具结果一起返回。
    # 这样前端和系统既能显示 reply，也能拿到机器可读的执行结果。
    tool_result: ToolResult | None = None
