from __future__ import annotations

import asyncio
import inspect
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from time import perf_counter
from typing import Any, Literal, cast
from uuid import uuid4

from langchain.agents import create_agent
from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import (
    AgentState,
)
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage, ToolMessage
from langchain_core.tools import StructuredTool
from langchain_core.tools.base import BaseTool
from langgraph.runtime import Runtime, get_runtime
from langgraph.types import Command, interrupt
from typing_extensions import TypedDict

from agent_service.contracts.actions import ToolContext, ToolSpec
from agent_service.contracts.capability import AgentDefinition
from agent_service.contracts.events import (
    ActionCompletedEvent,
    ActionRequiredEvent,
    ActionStartedEvent,
    OutputDeltaEvent,
    RunCompletedEvent,
    RunEvent,
    RunFailedEvent,
    RunStartedEvent,
)
from agent_service.contracts.models import (
    ActorContext,
    AgentError,
    AgentPendingAction,
    AgentRunResult,
    RunState,
)
from agent_service.infrastructure.state_store.in_memory_store import InMemoryStateStore
from agent_service.infrastructure.state_store.langgraph_postgres_store import (
    LangGraphPostgresStateStore,
)
from agent_service.llm.payloads import (
    dump_payload,
    text_from_message,
    token_usage_from_texts,
)

RuntimeStateStore = InMemoryStateStore | LangGraphPostgresStateStore


class LangChainAgentState(AgentState[Any], total=False):
    session_id: str
    input_message: str
    run_error: dict[str, str] | None


@dataclass(slots=True)
class LangChainRuntimeContext:
    tool_context: ToolContext
    emit: Callable[[RunEvent], Awaitable[None]]
    is_resume: bool = False


@dataclass(slots=True, frozen=True)
class ToolInvocation:
    action_id: str
    action_name: str
    action_payload: dict[str, Any]
    started_at: float


class ApprovalInterruptPayload(TypedDict):
    pending_action: dict[str, Any]


class LangChainRuntimeMiddleware(
    AgentMiddleware[LangChainAgentState, LangChainRuntimeContext, Any]
):
    state_schema = LangChainAgentState

    def __init__(self, definition: AgentDefinition) -> None:
        self._definition = definition
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

        first_tool_call = last_ai_message.tool_calls[0]
        last_ai_message.tool_calls = [first_tool_call]

        tool_name = first_tool_call.get("name")
        tool_arguments = first_tool_call.get("args")
        if not isinstance(tool_name, str) or not isinstance(tool_arguments, dict):
            return None

        tool_spec = self._tool_specs.get(tool_name)
        if tool_spec is None or tool_spec.approval_policy is None:
            return None

        approval_requirement = tool_spec.approval_policy.evaluate(tool_arguments)
        if approval_requirement is None:
            return None

        pending_action = AgentPendingAction(
            action_id=first_tool_call.get("id") or tool_name,
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


class LangChainAgentRuntime:
    def __init__(
        self,
        *,
        model: BaseChatModel,
        state_store: RuntimeStateStore,
        max_steps: int,
    ) -> None:
        self._model = model
        self._state_store = state_store
        self._max_steps = max_steps
        self._recursion_limit = max(max_steps * 4, 8)
        self._compiled_agents: dict[str, Any] = {}
        self._compile_lock = asyncio.Lock()

    async def stream_run(
        self,
        *,
        definition: AgentDefinition,
        message: str,
        session_id: str | None,
        actor: ActorContext,
    ) -> AsyncIterator[RunEvent]:
        resolved_session_id = session_id or f"session-{uuid4()}"
        run_id = f"run-{uuid4()}"
        history_messages = await self._state_store.get_session_messages(
            session_id=resolved_session_id
        )
        context = ToolContext(
            capability_id=definition.capability_id,
            actor=actor,
            dependencies=None,
        )
        async for event in self._stream_invocation(
            definition=definition,
            input_state=cast(
                LangChainAgentState,
                {
                    "messages": [*history_messages, HumanMessage(content=message)],
                    "session_id": resolved_session_id,
                    "input_message": message,
                },
            ),
            command=None,
            run_id=run_id,
            session_id=resolved_session_id,
            tool_context=context,
        ):
            yield event

    async def stream_action(
        self,
        *,
        definition: AgentDefinition,
        run_id: str,
        action_id: str,
        decision: Literal["approved", "rejected"],
        actor: ActorContext,
    ) -> AsyncIterator[RunEvent]:
        state = await self.get_state(run_id=run_id, definition=definition)
        pending_action = state.pending_action
        if pending_action is None:
            raise LookupError(f"run has no pending action: {run_id}")
        if action_id not in {pending_action.action_id, pending_action.action_name}:
            raise ValueError(f"action_id does not match pending action: {action_id}")

        context = ToolContext(
            capability_id=definition.capability_id,
            actor=actor,
            dependencies=None,
        )
        async for event in self._stream_invocation(
            definition=definition,
            input_state=None,
            command=Command(resume={"decision": decision}),
            run_id=run_id,
            session_id=state.session_id,
            tool_context=context,
        ):
            yield event

    async def get_state(
        self,
        *,
        run_id: str,
        definition: AgentDefinition,
    ) -> RunState:
        agent = await self._get_agent(definition)
        snapshot = await agent.aget_state(self._config(run_id=run_id))
        if not snapshot.values:
            raise LookupError(f"run not found: {run_id}")

        return self._to_run_state(
            definition=definition,
            run_id=run_id,
            state_values=cast(LangChainAgentState, snapshot.values),
            interrupts=snapshot.interrupts,
        )

    async def _stream_invocation(
        self,
        *,
        definition: AgentDefinition,
        input_state: LangChainAgentState | None,
        command: Command[Any] | None,
        run_id: str,
        session_id: str,
        tool_context: ToolContext,
    ) -> AsyncIterator[RunEvent]:
        queue: asyncio.Queue[RunEvent] = asyncio.Queue()
        agent = await self._get_agent(definition)

        async def emit(event: RunEvent) -> None:
            await queue.put(event)

        context = LangChainRuntimeContext(
            tool_context=tool_context,
            emit=emit,
            is_resume=command is not None,
        )
        invocation_input: dict[str, Any] | Command[Any]
        if command is None:
            invocation_input = cast(dict[str, Any], input_state)
        else:
            invocation_input = command

        yield RunStartedEvent(
            run_id=run_id,
            session_id=session_id,
            capability_id=definition.capability_id,
        )

        tool_tasks: dict[str, ToolInvocation] = {}
        output_delta_emitted = False
        try:
            async for part in agent.astream(
                invocation_input,
                config=self._config(run_id=run_id),
                context=context,
                stream_mode=["messages", "tasks"],
                version="v2",
            ):
                for event in _events_from_stream_part(
                    run_id=run_id,
                    part=part,
                    tool_tasks=tool_tasks,
                ):
                    if isinstance(event, OutputDeltaEvent):
                        output_delta_emitted = True
                    yield event
                for event in _drain_emitted_events(queue):
                    yield event
        except Exception as exc:
            error = AgentError(code="execution_failed", message=str(exc) or "unknown error")
            await agent.aupdate_state(
                self._config(run_id=run_id),
                {"run_error": error.model_dump(mode="json")},
            )
            for event in _drain_emitted_events(queue):
                yield event
            yield RunFailedEvent(run_id=run_id, error=error)
            return

        for event in _drain_emitted_events(queue):
            yield event

        snapshot = await agent.aget_state(self._config(run_id=run_id))
        state = cast(LangChainAgentState, snapshot.values)
        result = self._to_run_result(
            definition=definition,
            run_id=run_id,
            state_values=state,
            invocation_result=cast(dict[str, Any], state),
            interrupts=snapshot.interrupts,
        )
        await self._persist_session_transcript(run_result=result, state_values=state)

        if result.status == "completed" and result.output and not output_delta_emitted:
            yield OutputDeltaEvent(run_id=run_id, delta=result.output)
        yield RunCompletedEvent(result=result)

    async def _get_agent(self, definition: AgentDefinition) -> Any:
        await self._state_store.ensure_initialized()
        compiled = self._compiled_agents.get(definition.capability_id)
        if compiled is not None:
            return compiled

        async with self._compile_lock:
            compiled = self._compiled_agents.get(definition.capability_id)
            if compiled is not None:
                return compiled

            middleware = [LangChainRuntimeMiddleware(definition)]
            tools = [self._to_langchain_tool(tool_spec) for tool_spec in definition.tools]
            compiled = create_agent(
                model=self._model,
                tools=tools,
                system_prompt=definition.system_prompt,
                middleware=middleware,
                state_schema=LangChainAgentState,
                context_schema=LangChainRuntimeContext,
                checkpointer=self._state_store.get_checkpointer(),
                interrupt_before=None,
                interrupt_after=None,
                debug=False,
            )
            self._compiled_agents[definition.capability_id] = compiled
            return compiled

    def _to_langchain_tool(self, tool_spec: ToolSpec) -> BaseTool:
        async def _runner(**kwargs: Any) -> tuple[str, dict[str, Any]]:
            result_envelope = await _execute_tool(tool_spec=tool_spec, payload=kwargs)
            return dump_payload(result_envelope), result_envelope

        return StructuredTool.from_function(
            coroutine=_runner,
            name=tool_spec.name,
            description=tool_spec.description,
            args_schema=tool_spec.args_schema,
            response_format="content_and_artifact",
        )

    async def _persist_session_transcript(
        self,
        *,
        run_result: AgentRunResult,
        state_values: LangChainAgentState,
    ) -> None:
        input_message = state_values.get("input_message")
        if not isinstance(input_message, str) or not run_result.output:
            return
        await self._state_store.upsert_session_messages(
            session_id=run_result.session_id,
            run_id=run_result.run_id,
            messages=[
                HumanMessage(content=input_message),
                AIMessage(content=run_result.output),
            ],
        )

    def _to_run_result(
        self,
        *,
        definition: AgentDefinition,
        run_id: str,
        state_values: LangChainAgentState,
        invocation_result: dict[str, Any],
        interrupts: tuple[Any, ...],
    ) -> AgentRunResult:
        pending_action = self._pending_action_from_interrupts(interrupts)
        if pending_action is not None:
            return AgentRunResult(
                run_id=run_id,
                session_id=_session_id_from_state(state_values, default=run_id),
                capability_id=definition.capability_id,
                status="awaiting_action",
                output=_awaiting_action_message(pending_action),
                pending_action=pending_action,
            )

        error_payload = state_values.get("run_error")
        if isinstance(error_payload, dict):
            error = AgentError.model_validate(error_payload)
            return AgentRunResult(
                run_id=run_id,
                session_id=_session_id_from_state(state_values, default=run_id),
                capability_id=definition.capability_id,
                status="failed",
                output=error.message,
                error=error,
            )

        messages = invocation_result.get("messages")
        output = _latest_ai_text(messages) or _latest_ai_text(state_values.get("messages"))
        return AgentRunResult(
            run_id=run_id,
            session_id=_session_id_from_state(state_values, default=run_id),
            capability_id=definition.capability_id,
            status="completed",
            output=output,
        )

    def _to_run_state(
        self,
        *,
        definition: AgentDefinition,
        run_id: str,
        state_values: LangChainAgentState,
        interrupts: tuple[Any, ...],
    ) -> RunState:
        pending_action = self._pending_action_from_interrupts(interrupts)
        output: str | None
        error: AgentError | None = None
        if pending_action is not None:
            output = _awaiting_action_message(pending_action)
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

        usage = _usage_from_messages(state_values.get("messages"), input_message=state_values.get("input_message"))
        return RunState(
            run_id=run_id,
            session_id=_session_id_from_state(state_values, default=run_id),
            capability_id=definition.capability_id,
            status=status,
            output=output,
            pending_action=pending_action,
            error=error,
            metadata={"usage": usage},
        )

    def _pending_action_from_interrupts(
        self,
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

    def _config(self, *, run_id: str) -> dict[str, Any]:
        return {
            "configurable": {"thread_id": run_id},
            "recursion_limit": self._recursion_limit,
        }


async def _execute_tool(
    *,
    tool_spec: ToolSpec,
    payload: dict[str, Any],
) -> dict[str, Any]:
    runtime = get_runtime(LangChainRuntimeContext)
    try:
        result = tool_spec.handler(
            payload,
            ToolContext(
                capability_id=runtime.context.tool_context.capability_id,
                actor=runtime.context.tool_context.actor,
                dependencies=runtime.context.tool_context.dependencies,
            ),
        )
        if inspect.isawaitable(result):
            result = await result
    except Exception as exc:
        return {
            "success": False,
            "action": tool_spec.name,
            "error": {
                "code": "tool_execution_failed",
                "message": str(exc) or exc.__class__.__name__,
            },
        }

    return {
        "success": True,
        "action": tool_spec.name,
        "result": result,
    }


def _events_from_stream_part(
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
    if not isinstance(task_id, str):
        task_id = ""

    if "input" in payload and "result" not in payload and "error" not in payload:
        invocation = _tool_invocation_from_task_input(payload["input"])
        if invocation is None:
            return []
        if task_id:
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
    if invocation is None and tool_message is not None:
        action_name = tool_message.name or tool_message.tool_call_id
        invocation = ToolInvocation(
            action_id=tool_message.tool_call_id or action_name,
            action_name=action_name,
            action_payload={},
            started_at=perf_counter(),
        )
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
        tool_arguments = {}
    tool_call_id = tool_call.get("id")
    action_id = tool_call_id if isinstance(tool_call_id, str) and tool_call_id else action_name
    return ToolInvocation(
        action_id=action_id,
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


def _drain_emitted_events(queue: asyncio.Queue[RunEvent]) -> list[RunEvent]:
    events: list[RunEvent] = []
    while True:
        try:
            events.append(queue.get_nowait())
        except asyncio.QueueEmpty:
            return events


def _run_id_from_runtime(runtime: Any) -> str:
    execution_info = runtime.execution_info
    if execution_info is None or execution_info.thread_id is None:
        raise RuntimeError("thread_id is required for the runtime execution")
    return cast(str, execution_info.thread_id)


def _require_runtime_context(runtime: Any) -> LangChainRuntimeContext:
    context = getattr(runtime, "context", None)
    if not isinstance(context, LangChainRuntimeContext):
        raise RuntimeError("runtime context is not initialized")
    return context


def _session_id_from_state(state_values: LangChainAgentState, *, default: str) -> str:
    session_id = state_values.get("session_id")
    if isinstance(session_id, str) and session_id:
        return session_id
    return default


def _latest_ai_text(messages: object) -> str | None:
    if not isinstance(messages, list):
        return None
    for message in reversed(messages):
        if isinstance(message, AIMessage) and not message.tool_calls:
            text = text_from_message(message).strip()
            if text:
                return text
    return None


def _message_has_tool_call(message: AIMessage | AIMessageChunk) -> bool:
    tool_calls = getattr(message, "tool_calls", None)
    if tool_calls:
        return True
    tool_call_chunks = getattr(message, "tool_call_chunks", None)
    if tool_call_chunks:
        return True
    invalid_tool_calls = getattr(message, "invalid_tool_calls", None)
    return bool(invalid_tool_calls)


def _awaiting_action_message(pending_action: AgentPendingAction) -> str:
    return (
        f"工具 `{pending_action.action_name}` 需要人工审批，"
        "当前对话已暂停，等待批准后继续。"
    )


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
