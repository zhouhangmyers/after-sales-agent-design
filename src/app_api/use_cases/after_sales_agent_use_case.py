from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Literal

from agent_core.contracts.agent_definition import AgentDefinition
from agent_core.contracts.run_events import (
    RunCompletedEvent,
    RunEvent,
)
from agent_core.contracts.run_state import (
    ActorContext,
    AgentRunResult,
    RunState,
)
from agent_runtime.langchain.runtime import LangChainAgentRuntime
from app_api.projectors.after_sales_run_projector import AfterSalesRunProjector


class AfterSalesAgentUseCase:
    def __init__(
        self,
        *,
        runtime: LangChainAgentRuntime,
        definition: AgentDefinition,
        projector: AfterSalesRunProjector,
    ) -> None:
        self._runtime = runtime
        self._definition = definition
        self._projector = projector

    async def run(
        self,
        *,
        message: str,
        session_id: str | None,
        actor: ActorContext,
    ) -> AgentRunResult:
        stream = self.stream(message=message, session_id=session_id, actor=actor)
        async for event in stream:
            if isinstance(event, RunCompletedEvent):
                return event.result
        raise RuntimeError("run finished without RunCompletedEvent")

    async def stream(
        self,
        *,
        message: str,
        session_id: str | None,
        actor: ActorContext,
    ) -> AsyncIterator[RunEvent]:
        async for event in self._runtime.stream_run(
            definition=self._definition,
            message=message,
            session_id=session_id,
            actor=actor,
        ):
            await self._projector.record_event(event)
            yield event

    async def act(
        self,
        *,
        run_id: str,
        action_id: str,
        decision: Literal["approved", "rejected"],
        actor: ActorContext,
    ) -> AgentRunResult:
        state = await self.get_state(run_id=run_id)
        pending_action = state.pending_action
        approval_projected = False
        async for event in self._runtime.stream_action(
            definition=self._definition,
            run_id=run_id,
            action_id=action_id,
            decision=decision,
            actor=actor,
        ):
            if pending_action is not None and not approval_projected:
                await self._projector.resolve_approval(
                    conversation_id=run_id,
                    pending_action=pending_action,
                    decision=decision,
                )
                approval_projected = True
            await self._projector.record_event(event)
            if isinstance(event, RunCompletedEvent):
                return event.result
        raise RuntimeError("action stream finished without RunCompletedEvent")

    async def get_state(self, *, run_id: str) -> RunState:
        return await self._runtime.get_state(
            run_id=run_id,
            definition=self._definition,
        )
