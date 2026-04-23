from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langgraph.config import get_config, get_stream_writer
from langgraph.types import interrupt

from agent_service.conversation.approval import resolve_approval_decision
from agent_service.conversation.errors import ConversationErrorCode
from agent_service.conversation.state import (
    ConversationNodeRuntime,
    ConversationState,
    add_usage,
    make_pending_action,
    make_tool_call_intent,
)
from agent_service.llm.payloads import dump_payload, text_from_message

logger = logging.getLogger(__name__)


def _normalize_tool_calls_for_single_action(message: AIMessage) -> AIMessage:
    if not message.tool_calls:
        return message

    normalized_tool_calls: list[dict[str, Any]] = []
    mutated = False
    for tool_call in message.tool_calls:
        normalized_id = tool_call.get("id")
        if not isinstance(normalized_id, str) or not normalized_id:
            tool_name = tool_call.get("name") or "tool"
            normalized_id = f"call_{tool_name}_{uuid4().hex[:12]}"
            mutated = True
        normalized_tool_calls.append({**tool_call, "id": normalized_id})

    if len(normalized_tool_calls) > 1:
        logger.warning(
            "llm returned multiple tool calls; executing first only tool_calls=%s",
            [tool_call.get("name") for tool_call in normalized_tool_calls],
        )
        normalized_tool_calls = normalized_tool_calls[:1]
        mutated = True

    if not mutated:
        return message

    # The graph intentionally executes one action per plan step. If the provider
    # returned raw OpenAI-style tool calls in additional_kwargs, keep it in sync
    # with the normalized single call; otherwise the next LLM request can contain
    # two assistant tool_call_ids but only one following ToolMessage.
    additional_kwargs = dict(message.additional_kwargs)
    additional_kwargs.pop("tool_calls", None)
    return message.model_copy(
        update={
            "additional_kwargs": additional_kwargs,
            "tool_calls": normalized_tool_calls,
        }
    )


def _rejected_tool_message(pending_action: dict[str, Any]) -> ToolMessage:
    tool_name = str(pending_action["tool_name"])
    tool_call_id = pending_action.get("tool_call_id")
    if not isinstance(tool_call_id, str) or not tool_call_id:
        tool_call_id = f"call_{tool_name}_{uuid4().hex[:12]}"

    error_payload = {
        "code": "approval_rejected",
        "message": f"tool execution rejected by human approval: {tool_name}",
        "details": {
            "reason": pending_action.get("reason"),
            "risk_level": pending_action.get("risk_level"),
        },
    }
    return ToolMessage(
        content=dump_payload(error_payload),
        tool_call_id=tool_call_id,
        name=tool_name,
        status="error",
        artifact={
            "success": False,
            "action": tool_name,
            "error": error_payload,
        },
    )


def _make_failed_update(
    *,
    message: str,
    error_code: ConversationErrorCode,
    **extra: Any,
) -> dict[str, Any]:
    return {
        **extra,
        "status": "failed",
        "last_reply": message,
        "error_code": error_code.value,
        "pending_tool_call": None,
        "pending_action": None,
    }


def _conversation_id_from_config(config: RunnableConfig) -> str:
    configurable = config.get("configurable") or {}
    thread_id = configurable.get("thread_id")
    if isinstance(thread_id, str) and thread_id:
        return thread_id
    return "unknown-conversation"


async def plan_node(
    state: ConversationState,
    runtime: ConversationNodeRuntime,
) -> dict[str, Any]:
    logger.info(
        "conversation.plan status=%s turn_step=%s pending_tool_call=%s",
        state.get("status"),
        state.get("turn_step"),
        (state.get("pending_tool_call") or {}).get("tool_name")
        if isinstance(state.get("pending_tool_call"), dict)
        else None,
    )
    llm_service = runtime.context.llm_service
    tool_executor = runtime.context.tool_executor
    max_steps = runtime.context.max_steps
    approval_timeout_seconds = runtime.context.approval_timeout_seconds
    runnable_config: RunnableConfig = get_config()
    writer = get_stream_writer()
    conversation_id = _conversation_id_from_config(runnable_config)

    if state["turn_step"] >= max_steps:
        return _make_failed_update(
            message="agent 已达到最大步数限制，未能在限定步数内完成当前请求。",
            error_code=ConversationErrorCode.MAX_STEPS_EXCEEDED,
        )

    turn = await llm_service.generate_turn(
        conversation_id=conversation_id,
        messages=state["messages"],
        tools=tool_executor.get_tools(),
        runnable_config=runnable_config,
        stream_tokens=runtime.context.stream_tokens,
    )
    assistant_message = _normalize_tool_calls_for_single_action(turn.assistant_message)
    updated_step = state["turn_step"] + 1
    updated_usage = add_usage(state, turn.trace.usage)

    if not turn.trace.success:
        return _make_failed_update(
            message=f"模型调用失败：{turn.trace.error_message or 'unknown error'}。",
            error_code=ConversationErrorCode.LLM_INVOCATION_FAILED,
            messages=[assistant_message],
            turn_step=updated_step,
            usage=updated_usage,
        )

    if assistant_message.tool_calls:
        tool_call = assistant_message.tool_calls[0]
        policy = tool_executor.get_tool_policy(tool_call["name"])
        approval_decision = resolve_approval_decision(
            tool_arguments=tool_call.get("args") or {},
            policy=policy,
        )
        pending_tool_call = make_tool_call_intent(
            tool_call_id=tool_call.get("id"),
            tool_name=tool_call["name"],
            tool_arguments=tool_call.get("args") or {},
            approval_required=approval_decision is not None,
            risk_level=(
                approval_decision.risk_level if approval_decision is not None else policy.risk_level
            ),
        )

        if approval_decision is not None:
            deadline = (
                datetime.now(UTC) + timedelta(seconds=approval_timeout_seconds)
            ).isoformat()
            pending_action = make_pending_action(
                tool_call_id=pending_tool_call["tool_call_id"],
                approval_id=None,
                tool_name=pending_tool_call["tool_name"],
                tool_arguments=pending_tool_call["tool_arguments"],
                reason=approval_decision.reason,
                risk_level=approval_decision.risk_level,
                display_payload=approval_decision.display_payload,
                deadline=deadline,
            )
            writer({"type": "approval.required", "pending_action": pending_action})
            return {
                "messages": [assistant_message],
                "turn_step": updated_step,
                "usage": updated_usage,
                "error_code": None,
                "pending_tool_call": pending_tool_call,
                "pending_action": pending_action,
                "status": "awaiting_action",
                "last_reply": (
                    f"工具 `{pending_tool_call['tool_name']}` 需要人工审批，当前对话已暂停，等待批准后继续。"
                ),
            }

        return {
            "messages": [assistant_message],
            "turn_step": updated_step,
            "usage": updated_usage,
            "error_code": None,
            "pending_tool_call": pending_tool_call,
            "pending_action": None,
            "status": "completed",
            "last_reply": None,
        }

    final_reply = text_from_message(assistant_message) or "模型没有生成最终回复。"
    return {
        "messages": [assistant_message],
        "turn_step": updated_step,
        "usage": updated_usage,
        "error_code": None,
        "pending_tool_call": None,
        "pending_action": None,
        "status": "completed",
        "last_reply": final_reply,
    }


async def route_after_plan(state: ConversationState) -> str:
    if state["status"] == "awaiting_action":
        return "approval"
    if state.get("pending_tool_call") is not None:
        return "tool_execute"
    return "__end__"


async def approval_node(
    state: ConversationState,
    runtime: ConversationNodeRuntime,
) -> dict[str, Any]:
    logger.info("conversation.approval status=%s", state.get("status"))
    del runtime

    pending_action = state.get("pending_action")
    if pending_action is None:
        return _make_failed_update(
            message="对话缺少待审批信息，无法继续执行。",
            error_code=ConversationErrorCode.MISSING_PENDING_ACTION,
        )

    decision = interrupt(
        {
            "kind": pending_action["kind"],
            "tool_name": pending_action["tool_name"],
            "tool_arguments": pending_action["tool_arguments"],
            "reason": pending_action["reason"],
            "risk_level": pending_action["risk_level"],
            "display_payload": pending_action.get("display_payload") or {},
        }
    )

    if decision not in {"approved", "rejected"}:
        return _make_failed_update(
            message="对话收到了无效的审批决定，无法恢复执行。",
            error_code=ConversationErrorCode.INVALID_APPROVAL,
        )

    if decision == "rejected":
        reply = f"人工审批已拒绝，本次不会执行工具 `{pending_action['tool_name']}`。"
        return {
            "messages": [
                _rejected_tool_message(pending_action),
                AIMessage(content=reply),
            ],
            "pending_action": None,
            "pending_tool_call": None,
            "status": "completed",
            "last_reply": reply,
            "error_code": None,
        }

    return {
        "pending_tool_call": make_tool_call_intent(
            tool_call_id=pending_action["tool_call_id"],
            tool_name=pending_action["tool_name"],
            tool_arguments=pending_action["tool_arguments"],
            approval_required=True,
            risk_level=pending_action["risk_level"],
        ),
        "pending_action": None,
        "status": "completed",
        "last_reply": None,
        "error_code": None,
    }


async def route_after_approval(state: ConversationState) -> str:
    if state.get("pending_tool_call") is not None:
        return "tool_execute"
    return "__end__"


async def tool_execute_node(
    state: ConversationState,
    runtime: ConversationNodeRuntime,
) -> dict[str, Any]:
    logger.info(
        "conversation.tool_execute tool=%s",
        (state.get("pending_tool_call") or {}).get("tool_name")
        if isinstance(state.get("pending_tool_call"), dict)
        else None,
    )
    tool_executor = runtime.context.tool_executor
    writer = get_stream_writer()
    pending_tool_call = state.get("pending_tool_call")
    if pending_tool_call is None:
        return _make_failed_update(
            message="对话缺少待执行工具信息，无法继续执行。",
            error_code=ConversationErrorCode.MISSING_TOOL_CALL,
        )

    writer(
        {
            "type": "tool.started",
            "tool_name": pending_tool_call["tool_name"],
            "tool_arguments": pending_tool_call["tool_arguments"],
            "tool_call_id": pending_tool_call["tool_call_id"],
        }
    )
    execution = tool_executor.execute(
        tool_name=pending_tool_call["tool_name"],
        tool_arguments=pending_tool_call["tool_arguments"],
        tool_call_id=pending_tool_call["tool_call_id"],
        request_id=runtime.context.request_id,
    )
    writer(
        {
            "type": "tool.finished",
            "tool_name": pending_tool_call["tool_name"],
            "tool_arguments": pending_tool_call["tool_arguments"],
            "tool_call_id": pending_tool_call["tool_call_id"],
            "success": execution.result.success,
            "latency_ms": execution.latency_ms,
            "result": execution.result.result,
            "error": (
                execution.result.error.model_dump(mode="json")
                if execution.result.error is not None
                else None
            ),
        }
    )
    tool_message = tool_executor.to_tool_message(execution)

    return {
        "messages": [tool_message],
        "pending_tool_call": None,
        "pending_action": None,
        "status": "completed",
        "last_reply": None,
        "error_code": None,
    }
