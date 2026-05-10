from __future__ import annotations

from typing import Any

from langchain_core.messages import (
    BaseMessage,
    message_to_dict,
    messages_from_dict,
    messages_to_dict,
)


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
