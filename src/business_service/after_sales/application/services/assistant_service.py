from __future__ import annotations

from collections.abc import AsyncIterator
from decimal import Decimal
from typing import Literal

from agent_service.contracts.capability import AgentCapability
from agent_service.contracts.events import (
    ActionCompletedEvent,
    ActionRequiredEvent,
    ActionStartedEvent,
    AgentEvent,
    RunCompletedEvent,
    RunFailedEvent,
    RunStartedEvent,
)
from agent_service.contracts.models import (
    ActorContext,
    AgentRunResult,
    RunState,
)
from agent_service.infrastructure.workflow.workflow_engine import WorkflowEngine
from business_service.after_sales.infrastructure.persistence.sqlalchemy.repositories import (
    SqlAlchemyAfterSalesRepository,
)


class AfterSalesAssistantService:
    def __init__(
        self,
        *,
        workflow_engine: WorkflowEngine,
        capability: AgentCapability,
        repository: SqlAlchemyAfterSalesRepository,
    ) -> None:
        self._workflow_engine = workflow_engine
        self._capability = capability
        self._repository = repository
        self._tool_log_ids: dict[tuple[str, str], int] = {}

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
    ) -> AsyncIterator[AgentEvent]:
        stream = await self._workflow_engine.stream_run(
            capability=self._capability,
            input=message,
            session_id=session_id,
            actor=actor,
        )
        async for event in stream:
            self._record_event(event)
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
        stream = await self._workflow_engine.stream_action(
            capability=self._capability,
            run_id=run_id,
            action_id=action_id,
            decision=decision,
            actor=actor,
        )
        approval_projected = False
        async for event in stream:
            if (
                pending_action is not None
                and not approval_projected
                and not isinstance(event, RunStartedEvent)
            ):
                self._resolve_approval(
                    conversation_id=run_id,
                    action_id=pending_action.action_id,
                    decision=decision,
                    display_payload=pending_action.display_payload,
                )
                approval_projected = True
            self._record_event(event)
            if isinstance(event, RunCompletedEvent):
                return event.result
        raise RuntimeError("action stream finished without RunCompletedEvent")

    async def get_state(self, *, run_id: str) -> RunState:
        return await self._workflow_engine.get_state(
            run_id=run_id,
            capability=self._capability,
        )

    def _record_event(self, event: AgentEvent) -> None:
        if isinstance(event, ActionStartedEvent):
            log_id = self._repository.start_tool_call(
                conversation_id=event.run_id,
                tool_call_id=event.action_id,
                tool_name=event.action_name,
                tool_arguments=event.action_payload,
            )
            self._tool_log_ids[(event.run_id, event.action_id)] = log_id
            return

        if isinstance(event, ActionCompletedEvent):
            log_id = self._tool_log_ids.pop((event.run_id, event.action_id), None)
            if log_id is not None:
                self._repository.finish_tool_call(
                    log_id=log_id,
                    success=event.success,
                    latency_ms=event.latency_ms,
                    result=event.result if isinstance(event.result, dict) else None,
                    error_message=(
                        str(event.error.get("message"))
                        if isinstance(event.error, dict) and "message" in event.error
                        else None
                    ),
                )
            return

        if isinstance(event, ActionRequiredEvent):
            self._request_approval(
                conversation_id=event.run_id,
                action_id=event.pending_action.action_id,
                tool_name=event.pending_action.action_name,
                display_payload=event.pending_action.display_payload,
                reason=event.pending_action.reason,
                risk_level=event.pending_action.risk_level,
            )
            return

        if isinstance(event, RunFailedEvent):
            self._repository.record_audit_log(
                conversation_id=event.run_id,
                event_type="run_failed",
                payload={
                    "code": event.error.code,
                    "message": event.error.message,
                },
            )

    def _request_approval(
        self,
        *,
        conversation_id: str,
        action_id: str,
        tool_name: str,
        display_payload: dict[str, object],
        reason: str,
        risk_level: str,
    ) -> None:
        amount = display_payload.get("amount")
        decimal_amount = Decimal(str(amount)) if isinstance(amount, int | float | str) else None
        self._repository.request_approval(
            conversation_id=conversation_id,
            tool_call_id=action_id,
            tool_name=tool_name,
            order_id=display_payload.get("order_id")
            if isinstance(display_payload.get("order_id"), str)
            else None,
            amount=decimal_amount,
            reason=display_payload.get("reason")
            if isinstance(display_payload.get("reason"), str)
            else None,
            risk_level=risk_level,
            display_payload=display_payload,
        )
        self._repository.record_audit_log(
            conversation_id=conversation_id,
            event_type="approval_requested",
            payload={
                "action_id": action_id,
                "tool_name": tool_name,
                "reason": reason,
                "risk_level": risk_level,
                "display_payload": display_payload,
            },
        )

    def _resolve_approval(
        self,
        *,
        conversation_id: str,
        action_id: str,
        decision: str,
        display_payload: dict[str, object],
    ) -> None:
        self._repository.resolve_approval(
            conversation_id=conversation_id,
            tool_call_id=action_id,
            status="approved" if decision == "approved" else "rejected",
        )
        self._repository.record_audit_log(
            conversation_id=conversation_id,
            event_type="approval_resolved",
            payload={
                "action_id": action_id,
                "decision": decision,
                "display_payload": display_payload,
            },
        )
