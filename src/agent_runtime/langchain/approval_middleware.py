from __future__ import annotations

from typing import Any, cast

from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import AIMessage, ToolMessage
from langgraph.runtime import Runtime
from langgraph.types import interrupt
from typing_extensions import TypedDict

from agent_core.contracts.agent_definition import AgentDefinition
from agent_core.contracts.run_events import ActionRequiredEvent
from agent_core.contracts.run_state import AgentPendingAction
from agent_runtime.langchain.state import LangChainAgentState, LangChainRuntimeContext


class ApprovalInterruptPayload(TypedDict):
    pending_action: dict[str, Any]


class LangChainApprovalMiddleware(
    AgentMiddleware[LangChainAgentState, LangChainRuntimeContext, Any]
):
    state_schema = LangChainAgentState

    def __init__(self, definition: AgentDefinition) -> None:
        self._tool_specs = {tool.name: tool for tool in definition.tools}

    async def aafter_model(
        self,
        state: LangChainAgentState,
        runtime: Runtime[LangChainRuntimeContext],
    ) -> dict[str, Any] | None:
        messages = state["messages"]
        if not messages:
            return None

        last_ai_message = next(
            (message for message in reversed(messages) if isinstance(message, AIMessage)),
            None,
        )
        if last_ai_message is None or not last_ai_message.tool_calls:
            return None

        # LangGraph 的 messages 使用 add_messages 合并；相同 id 的消息会替换旧消息。
        # 这里保留原 AIMessage.id，只把 tool_calls 收敛成一个，避免拒绝审批后
        # 追加 ToolMessage 时留下未配对的多余 tool_call。
        first_tool_call = last_ai_message.tool_calls[0]
        last_ai_message.tool_calls = [first_tool_call]

        tool_name = first_tool_call.get("name")
        tool_arguments = first_tool_call.get("args")
        if not isinstance(tool_name, str) or not isinstance(tool_arguments, dict):
            return None
        tool_call_id = first_tool_call.get("id")
        if not isinstance(tool_call_id, str) or not tool_call_id:
            raise RuntimeError("tool_call id is required for approval interrupts")

        tool_spec = self._tool_specs.get(tool_name)
        if tool_spec is None or tool_spec.approval_policy is None:
            return None

        approval_requirement = tool_spec.approval_policy.evaluate(tool_arguments)
        if approval_requirement is None:
            return None

        pending_action = AgentPendingAction(
            action_id=tool_call_id,
            action_name=tool_name,
            action_payload=tool_arguments,
            reason=approval_requirement.reason,
            risk_level=approval_requirement.risk_level,
            display_payload=(
                dict(approval_requirement.display_payload)
                if approval_requirement.display_payload is not None
                else {}
            ),
        )
        if not runtime.context.is_resume:
            await runtime.context.emit(
                ActionRequiredEvent(
                    run_id=_run_id_from_runtime(runtime),
                    pending_action=pending_action,
                )
            )

        payload = cast(
            ApprovalInterruptPayload,
            interrupt({"pending_action": pending_action.model_dump(mode="json")}),
        )
        decision = str(payload.get("decision") or "rejected")
        if decision == "approved":
            return None

        tool_message = ToolMessage(
            content=f"人工审批已拒绝，本次不会执行工具 `{tool_name}`。",
            name=tool_name,
            tool_call_id=pending_action.action_id,
            status="error",
            artifact={
                "success": False,
                "action": tool_name,
                "error": {
                    "code": "approval_rejected",
                    "message": f"人工审批已拒绝，本次不会执行工具 `{tool_name}`。",
                },
            },
        )
        return {"messages": [last_ai_message, tool_message]}


def _run_id_from_runtime(runtime: Any) -> str:
    execution_info = runtime.execution_info
    if execution_info is None or execution_info.thread_id is None:
        raise RuntimeError("thread_id is required for the runtime execution")
    return cast(str, execution_info.thread_id)
