from __future__ import annotations

from typing import Any, Literal

from langchain_core.messages import AIMessage

from agent_core.contracts.agent_definition import AgentDefinition
from agent_core.contracts.run_state import (
    AgentError,
    AgentPendingAction,
    AgentRunResult,
    RunState,
)
from agent_core.support.message_serialization import text_from_message
from agent_core.support.token_usage import token_usage_from_texts
from agent_runtime.langchain.state import LangChainAgentState


def to_run_result(
    *,
    definition: AgentDefinition,
    run_id: str,
    state_values: LangChainAgentState,
    invocation_result: dict[str, Any],
    interrupts: tuple[Any, ...],
) -> AgentRunResult:
    pending_action = pending_action_from_interrupts(interrupts)
    if pending_action is not None:
        return AgentRunResult(
            run_id=run_id,
            session_id=session_id_from_state(state_values, default=run_id),
            capability_id=definition.capability_id,
            status="awaiting_action",
            output=awaiting_action_message(pending_action),
            pending_action=pending_action,
        )

    error_payload = state_values.get("run_error")
    if isinstance(error_payload, dict):
        error = AgentError.model_validate(error_payload)
        return AgentRunResult(
            run_id=run_id,
            session_id=session_id_from_state(state_values, default=run_id),
            capability_id=definition.capability_id,
            status="failed",
            output=error.message,
            error=error,
        )

    messages = invocation_result.get("messages")
    output = _latest_ai_text(messages) or _latest_ai_text(state_values.get("messages"))
    return AgentRunResult(
        run_id=run_id,
        session_id=session_id_from_state(state_values, default=run_id),
        capability_id=definition.capability_id,
        status="completed",
        output=output,
    )


def to_run_state(
    *,
    definition: AgentDefinition,
    run_id: str,
    state_values: LangChainAgentState,
    interrupts: tuple[Any, ...],
) -> RunState:
    pending_action = pending_action_from_interrupts(interrupts)
    output: str | None
    error: AgentError | None = None
    if pending_action is not None:
        output = awaiting_action_message(pending_action)
        status: Literal["awaiting_action", "completed", "failed"] = "awaiting_action"
    else:
        error_payload = state_values.get("run_error")
        if isinstance(error_payload, dict):
            error = AgentError.model_validate(error_payload)
            output = error.message
            status = "failed"
        else:
            output = _latest_ai_text(state_values.get("messages"))
            status = "completed"

    usage = _usage_from_messages(
        state_values.get("messages"),
        input_message=state_values.get("input_message"),
    )
    return RunState(
        run_id=run_id,
        session_id=session_id_from_state(state_values, default=run_id),
        capability_id=definition.capability_id,
        status=status,
        output=output,
        pending_action=pending_action,
        error=error,
        metadata={"usage": usage},
    )


def pending_action_from_interrupts(
    interrupts: tuple[Any, ...],
) -> AgentPendingAction | None:
    if not interrupts:
        return None
    first_interrupt = interrupts[0]
    value = getattr(first_interrupt, "value", None)
    if not isinstance(value, dict):
        return None
    pending_action = value.get("pending_action")
    if not isinstance(pending_action, dict):
        return None
    return AgentPendingAction.model_validate(pending_action)


def session_id_from_state(state_values: LangChainAgentState, *, default: str) -> str:
    session_id = state_values.get("session_id")
    if isinstance(session_id, str) and session_id:
        return session_id
    return default


def awaiting_action_message(pending_action: AgentPendingAction) -> str:
    return (
        f"工具 `{pending_action.action_name}` 需要人工审批，"
        "当前对话已暂停，等待批准后继续。"
    )


def _latest_ai_text(messages: object) -> str | None:
    if not isinstance(messages, list):
        return None
    for message in reversed(messages):
        if isinstance(message, AIMessage) and not message.tool_calls:
            text = text_from_message(message).strip()
            if text:
                return text
    return None


def _usage_from_messages(
    messages: object,
    *,
    input_message: object,
) -> dict[str, int]:
    prompt_text = input_message if isinstance(input_message, str) else ""
    completion_parts: list[str] = []
    if isinstance(messages, list):
        for message in messages:
            if isinstance(message, AIMessage):
                completion_parts.append(text_from_message(message))
    usage = token_usage_from_texts(
        prompt_text,
        "\n".join(completion_parts),
    )
    return usage.model_dump(mode="json")
