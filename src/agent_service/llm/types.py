from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Protocol

from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field


class TokenUsage(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0

    @classmethod
    def combine(cls, usages: list[TokenUsage]) -> TokenUsage:
        return cls(
            prompt_tokens=sum(item.prompt_tokens for item in usages),
            completion_tokens=sum(item.completion_tokens for item in usages),
            total_tokens=sum(item.total_tokens for item in usages),
        )


class AssistantDecision(BaseModel):
    kind: Literal["respond", "tool_call"]
    response: str | None = None
    tool_name: str | None = None
    tool_arguments: dict[str, Any] = Field(default_factory=dict)
    rationale: str = ""


class LLMCallTrace(BaseModel):
    provider: str
    model: str
    request_payload: dict[str, Any] = Field(default_factory=dict)
    raw_response: dict[str, Any] | None = None
    decision: AssistantDecision | None = None
    usage: TokenUsage = Field(default_factory=TokenUsage)
    latency_ms: float = 0.0
    attempts: int = 1
    success: bool = True
    error_message: str | None = None


@dataclass(slots=True, frozen=True)
class LLMTurn:
    assistant_message: AIMessage
    trace: LLMCallTrace


class RunnableMessageModel(Protocol):
    async def ainvoke(
        self,
        messages: list[BaseMessage],
        config: RunnableConfig | None = None,
    ) -> BaseMessage:
        ...


class ToolBindableChatModel(RunnableMessageModel, Protocol):
    def bind_tools(self, tools: list[BaseTool]) -> RunnableMessageModel:
        ...


class ChatClient(Protocol):
    provider: str
    model: str

    async def ainvoke(
        self,
        messages: list[BaseMessage],
        tools: list[BaseTool],
        config: RunnableConfig | None = None,
    ) -> AIMessage:
        ...
