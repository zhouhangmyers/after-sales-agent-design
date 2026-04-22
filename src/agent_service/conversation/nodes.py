from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from langchain_core.runnables import RunnableConfig
from langgraph.config import get_config, get_stream_writer
from langgraph.types import interrupt

from agent_service.conversation.errors import ConversationErrorCode
from agent_service.conversation.state import (
    ConversationNodeRuntime,
    ConversationState,
    add_usage,
    make_pending_action,
    make_tool_call_intent,
)
from agent_service.llm.payloads import text_from_message

logger = logging.getLogger(__name__)


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

    if state["turn_step"] >= max_steps:
        return _make_failed_update(
            message="agent 已达到最大步数限制，未能在限定步数内完成当前请求。",
            error_code=ConversationErrorCode.MAX_STEPS_EXCEEDED,
        )

    turn = await llm_service.generate_turn(
        conversation_id=_conversation_id_from_config(runnable_config),
        messages=state["messages"],
        tools=tool_executor.get_tools(),
        runnable_config=runnable_config,
        stream_tokens=runtime.context.stream_tokens,
    )
    assistant_message = turn.assistant_message
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
        pending_tool_call = make_tool_call_intent(
            tool_call_id=tool_call.get("id"),
            tool_name=tool_call["name"],
            tool_arguments=tool_call.get("args") or {},
            approval_required=policy.approval_required,
            risk_level=policy.risk_level,
        )

        if policy.approval_required:
            deadline = (
                datetime.now(UTC) + timedelta(seconds=approval_timeout_seconds)
            ).isoformat()
            pending_action = make_pending_action(
                tool_call_id=pending_tool_call["tool_call_id"],
                tool_name=pending_tool_call["tool_name"],
                tool_arguments=pending_tool_call["tool_arguments"],
                reason=f"工具 `{pending_tool_call['tool_name']}` 当前策略要求人工审批后才能执行。",
                risk_level=policy.risk_level,
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
        }
    )

    if decision not in {"approved", "rejected"}:
        return _make_failed_update(
            message="对话收到了无效的审批决定，无法恢复执行。",
            error_code=ConversationErrorCode.INVALID_APPROVAL,
        )

    if decision == "rejected":
        return {
            "pending_action": None,
            "pending_tool_call": None,
            "status": "completed",
            "last_reply": f"人工审批已拒绝，本次不会执行工具 `{pending_action['tool_name']}`。",
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
    pending_tool_call = state.get("pending_tool_call")
    if pending_tool_call is None:
        return _make_failed_update(
            message="对话缺少待执行工具信息，无法继续执行。",
            error_code=ConversationErrorCode.MISSING_TOOL_CALL,
        )

    execution = tool_executor.execute(
        tool_name=pending_tool_call["tool_name"],
        tool_arguments=pending_tool_call["tool_arguments"],
        tool_call_id=pending_tool_call["tool_call_id"],
        request_id=runtime.context.request_id,
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
