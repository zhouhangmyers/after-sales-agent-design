from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated, Any, Protocol, TypedDict

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages

from agent_service.llm.service import LLMService
from agent_service.llm.types import TokenUsage
from agent_service.tools.inline import InlineToolExecutor

ConversationStatus = str


class ToolCallIntent(TypedDict):
    tool_call_id: str | None
    tool_name: str
    tool_arguments: dict[str, Any]
    approval_required: bool
    risk_level: str


class PendingAction(TypedDict):
    kind: str
    tool_call_id: str | None
    approval_id: str | None
    tool_name: str
    tool_arguments: dict[str, Any]
    reason: str
    risk_level: str
    display_payload: dict[str, Any]
    deadline: str | None


class UsageSnapshot(TypedDict):
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


class ConversationState(TypedDict):
    session_id: str
    input_message: str | None
    status: ConversationStatus
    turn_step: int
    messages: Annotated[list[BaseMessage], add_messages]
    pending_tool_call: ToolCallIntent | None
    pending_action: PendingAction | None
    last_reply: str | None
    error_code: str | None
    usage: UsageSnapshot


@dataclass(slots=True, frozen=True)
class ConversationContext:
    llm_service: LLMService
    tool_executor: InlineToolExecutor
    max_steps: int
    approval_timeout_seconds: int
    request_id: str
    stream_tokens: bool = False


class ConversationNodeRuntime(Protocol):
    context: ConversationContext


def build_conversation_context(
    *,
    llm_service: LLMService,
    tool_executor: InlineToolExecutor,
    max_steps: int,
    approval_timeout_seconds: int,
    request_id: str,
    stream_tokens: bool,
) -> ConversationContext:
    return ConversationContext(
        llm_service=llm_service,
        tool_executor=tool_executor,
        max_steps=max_steps,
        approval_timeout_seconds=approval_timeout_seconds,
        request_id=request_id,
        stream_tokens=stream_tokens,
    )


def zero_usage() -> UsageSnapshot:
    return {
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
    }


def usage_from_state(state: ConversationState | dict[str, Any]) -> TokenUsage:
    return TokenUsage.model_validate(state.get("usage") or zero_usage())


def add_usage(
    state: ConversationState | dict[str, Any],
    usage: TokenUsage,
) -> UsageSnapshot:
    current = usage_from_state(state)
    return TokenUsage.combine([current, usage]).model_dump(mode="json")


def normalize_status(state: ConversationState | dict[str, Any]) -> str:
    status = state.get("status")
    if status in {"completed", "awaiting_action", "failed"}:
        return status
    return "failed"


def make_tool_call_intent(
    *,
    tool_call_id: str | None,
    tool_name: str,
    tool_arguments: dict[str, Any],
    approval_required: bool,
    risk_level: str,
) -> ToolCallIntent:
    return {
        "tool_call_id": tool_call_id,
        "tool_name": tool_name,
        "tool_arguments": tool_arguments,
        "approval_required": approval_required,
        "risk_level": risk_level,
    }


def make_pending_action(
    *,
    tool_call_id: str | None,
    approval_id: str | None,
    tool_name: str,
    tool_arguments: dict[str, Any],
    reason: str,
    risk_level: str,
    display_payload: dict[str, Any],
    deadline: str | None,
) -> PendingAction:
    return {
        "kind": "tool_approval",
        "tool_call_id": tool_call_id,
        "approval_id": approval_id,
        "tool_name": tool_name,
        "tool_arguments": tool_arguments,
        "reason": reason,
        "risk_level": risk_level,
        "display_payload": display_payload,
        "deadline": deadline,
    }
