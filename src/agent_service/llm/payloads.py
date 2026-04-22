from __future__ import annotations

import json
from typing import Any

from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    message_to_dict,
    messages_from_dict,
    messages_to_dict,
)
from langchain_core.tools import BaseTool

from agent_service.llm.types import AssistantDecision, TokenUsage
from agent_service.llm.tokens import estimate_tokens


def dump_payload(payload: object) -> str:
    # 统一把结构化 payload 转成稳定 JSON，方便落库和调试。
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def messages_payload(messages: list[BaseMessage]) -> list[dict[str, Any]]:
    # 把 LangChain message 对象列表转成可序列化 payload。
    #
    # 依据 langchain_core.messages.message_to_dict 的实现，
    # 每条 message 会被转成这种形态：
    # {
    #   "type": "human" | "ai" | "system" | "tool" | ...,
    #   "data": {
    #     "content": str | list[str | dict],
    #     "additional_kwargs": {...},
    #     "response_metadata": {...},
    #     "type": "...",
    #     "name": str | None,
    #     "id": str | None,
    #     # 以及不同 message 子类自己的字段。
    #     # 例如 AIMessage 可能还会有 tool_calls / usage_metadata；
    #     # ToolMessage 可能还会有 tool_call_id / artifact / status。
    #   },
    # }
    return messages_to_dict(messages)


def messages_from_payload(payload: list[dict[str, Any]]) -> list[BaseMessage]:
    # 把持久化后的 payload 还原回 LangChain message 对象。
    return messages_from_dict(payload)


def message_payload(message: BaseMessage) -> dict[str, Any]:
    # 单条 message 的序列化辅助。
    # 结构同 messages_payload() 里的单个元素：
    # {"type": "...", "data": {...}}
    return message_to_dict(message)


def tool_payloads(tools: list[BaseTool]) -> list[dict[str, Any]]:
    # 把工具列表整理成适合 trace / 调试 / 持久化的轻量描述。
    payloads: list[dict[str, Any]] = []
    for tool in tools:
        args_schema = getattr(tool, "args_schema", None)
        payloads.append(
            {
                "name": tool.name,
                "description": tool.description,
                "arguments_json_schema": args_schema.model_json_schema() if args_schema else {},
            }
        )
    return payloads


# ---------- domain 对象构建辅助 ----------

def decision_from_ai_message(message: AIMessage) -> AssistantDecision:
    """从 AIMessage 构造 AssistantDecision，判断模型是要直接回复还是调用工具。"""
    if message.tool_calls:
        tool_call = message.tool_calls[0]
        return AssistantDecision(
            kind="tool_call",
            tool_name=tool_call.get("name"),
            tool_arguments=tool_call.get("args") or {},
        )
    return AssistantDecision(
        kind="respond",
        response=text_from_message(message),
    )


def token_usage_from_ai_message(message: AIMessage) -> TokenUsage:
    """从 AIMessage 的 usage_metadata 提取 token 用量。"""
    usage_metadata = message.usage_metadata or {}
    prompt_tokens = int(usage_metadata.get("input_tokens", 0) or 0)
    completion_tokens = int(usage_metadata.get("output_tokens", 0) or 0)
    total_tokens = int(
        usage_metadata.get("total_tokens", prompt_tokens + completion_tokens) or 0
    )
    return TokenUsage(
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=total_tokens,
    )


def token_usage_from_texts(
    prompt_text: str,
    completion_text: str,
    *,
    model: str = "deepseek-chat",
) -> TokenUsage:
    """根据文本内容估算 token 使用量（没有 API 返回时的 fallback）。"""
    prompt_tokens = estimate_tokens(prompt_text, model=model)
    completion_tokens = estimate_tokens(completion_text, model=model)
    return TokenUsage(
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=prompt_tokens + completion_tokens,
    )


# ---------- 消息序列化辅助 ----------

def text_from_message(message: BaseMessage) -> str:
    # 尽量从不同形态的 message.content 里提取出纯文本。
    #
    # BaseMessage.content 在 langchain_core 里的类型是：
    #   str | list[str | dict]
    #
    # 常见例子：
    # 1) 纯文本 message
    #    "请帮我总结这段话"
    #
    # 2) 分块后的文本/多模态内容
    #    [
    #      "第一段",
    #      {"type": "text", "text": "第二段"},
    #      {"type": "image_url", "image_url": {"url": "https://..."}},
    #    ]
    #
    # 这个 helper 不保留完整块结构，只负责把能提取出来的文本拼成一个 str。
    content = getattr(message, "content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict) and item.get("type") == "text":
                text = item.get("text")
                if isinstance(text, str):
                    parts.append(text)
        return "".join(parts)
    return str(content)
