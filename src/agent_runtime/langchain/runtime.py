from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any, Literal, cast
from uuid import uuid4

from langchain.agents import create_agent
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.types import Command

from agent_core.contracts.agent_definition import AgentDefinition
from agent_core.contracts.run_events import (
    OutputDeltaEvent,
    RunCompletedEvent,
    RunEvent,
    RunFailedEvent,
    RunStartedEvent,
)
from agent_core.contracts.run_state import (
    ActorContext,
    AgentError,
    AgentRunResult,
    RunState,
)
from agent_core.contracts.tool_spec import ToolContext
from agent_runtime.langchain.approval_middleware import LangChainApprovalMiddleware
from agent_runtime.langchain.event_mapper import ToolInvocation, events_from_stream_part
from agent_runtime.langchain.result_mapper import to_run_result, to_run_state
from agent_runtime.langchain.runtime_state_store import AgentRuntimeStateStore
from agent_runtime.langchain.state import LangChainAgentState, LangChainRuntimeContext
from agent_runtime.langchain.tool_adapter import to_langchain_tool


class LangChainAgentRuntime:
    def __init__(
        self,
        *,
        model: BaseChatModel,
        state_store: AgentRuntimeStateStore,
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

        return to_run_state(
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
                for event in events_from_stream_part(
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
        result = to_run_result(
            definition=definition,
            run_id=run_id,
            state_values=state,
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

            middleware = [LangChainApprovalMiddleware(definition)]
            tools = [to_langchain_tool(tool_spec) for tool_spec in definition.tools]
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

    def _config(self, *, run_id: str) -> dict[str, Any]:
        return {
            "configurable": {"thread_id": run_id},
            "recursion_limit": self._recursion_limit,
        }


def _drain_emitted_events(queue: asyncio.Queue[RunEvent]) -> list[RunEvent]:
    events: list[RunEvent] = []
    while True:
        try:
            events.append(queue.get_nowait())
        except asyncio.QueueEmpty:
            return events
