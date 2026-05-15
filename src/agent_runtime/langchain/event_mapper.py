from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter
from typing import Any, cast

from langchain_core.messages import AIMessage, AIMessageChunk, ToolMessage

from agent_core.contracts.run_events import (
    ActionCompletedEvent,
    ActionStartedEvent,
    OutputDeltaEvent,
    RunEvent,
)
from agent_core.support.message_serialization import text_from_message


@dataclass(slots=True, frozen=True)
class ToolInvocation:
    action_id: str
    action_name: str
    action_payload: dict[str, Any]
    started_at: float


def events_from_stream_part(
    *,
    run_id: str,
    part: object,
    tool_tasks: dict[str, ToolInvocation],
) -> list[RunEvent]:
    if not isinstance(part, dict):
        return []
    part_type = part.get("type")
    if part_type == "messages":
        message = _message_from_stream_part(part.get("data"))
        if not isinstance(message, (AIMessage, AIMessageChunk)):
            return []
        if _message_has_tool_call(message):
            return []
        text = text_from_message(message)
        if not text:
            return []
        return [OutputDeltaEvent(run_id=run_id, delta=text)]
    if part_type == "tasks":
        return _tool_events_from_task_part(
            run_id=run_id,
            payload=part.get("data"),
            tool_tasks=tool_tasks,
        )
    return []


def _message_from_stream_part(payload: object) -> object | None:
    if isinstance(payload, tuple):
        return payload[0] if payload else None
    if isinstance(payload, list):
        return payload[0] if payload else None
    return payload


def _tool_events_from_task_part(
    *,
    run_id: str,
    payload: object,
    tool_tasks: dict[str, ToolInvocation],
) -> list[RunEvent]:
    if not isinstance(payload, dict) or payload.get("name") != "tools":
        return []

    task_id = payload.get("id")
    if not isinstance(task_id, str) or not task_id:
        return []

    if "input" in payload and "result" not in payload and "error" not in payload:
        invocation = _tool_invocation_from_task_input(payload["input"])
        if invocation is None:
            return []
        tool_tasks[task_id] = invocation
        return [
            ActionStartedEvent(
                run_id=run_id,
                action_id=invocation.action_id,
                action_name=invocation.action_name,
                action_payload=invocation.action_payload,
            )
        ]

    invocation = tool_tasks.pop(task_id, None)
    tool_message = _tool_message_from_task_result(payload.get("result"))
    if invocation is None:
        return []

    artifact = tool_message.artifact if tool_message is not None else None
    if not isinstance(artifact, dict):
        artifact = {}
    task_error = payload.get("error")
    error = cast(dict[str, Any] | None, artifact.get("error"))
    if error is None:
        error = _task_error_payload(task_error)
    success = bool(artifact.get("success")) if "success" in artifact else task_error is None
    return [
        ActionCompletedEvent(
            run_id=run_id,
            action_id=invocation.action_id,
            action_name=invocation.action_name,
            action_payload=invocation.action_payload,
            success=success,
            latency_ms=(perf_counter() - invocation.started_at) * 1000,
            result=artifact.get("result"),
            error=error,
        )
    ]


def _tool_invocation_from_task_input(payload: object) -> ToolInvocation | None:
    if not isinstance(payload, dict):
        return None
    tool_call = payload.get("tool_call")
    if not isinstance(tool_call, dict):
        tool_call = payload

    action_name = tool_call.get("name")
    if not isinstance(action_name, str):
        return None
    tool_arguments = tool_call.get("args")
    if not isinstance(tool_arguments, dict):
        return None
    tool_call_id = tool_call.get("id")
    if not isinstance(tool_call_id, str) or not tool_call_id:
        return None
    return ToolInvocation(
        action_id=tool_call_id,
        action_name=action_name,
        action_payload=tool_arguments,
        started_at=perf_counter(),
    )


def _tool_message_from_task_result(payload: object) -> ToolMessage | None:
    if isinstance(payload, ToolMessage):
        return payload
    if not isinstance(payload, dict):
        return None
    messages = payload.get("messages")
    if not isinstance(messages, list):
        return None
    for message in messages:
        if isinstance(message, ToolMessage):
            return message
    return None


def _task_error_payload(error: object) -> dict[str, Any] | None:
    if error is None:
        return None
    if isinstance(error, dict):
        return error
    return {"code": "tool_execution_failed", "message": str(error)}


def _message_has_tool_call(message: AIMessage | AIMessageChunk) -> bool:
    tool_calls = getattr(message, "tool_calls", None)
    if tool_calls:
        return True
    tool_call_chunks = getattr(message, "tool_call_chunks", None)
    if tool_call_chunks:
        return True
    invalid_tool_calls = getattr(message, "invalid_tool_calls", None)
    return bool(invalid_tool_calls)
