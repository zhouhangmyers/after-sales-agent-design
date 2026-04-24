from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from decimal import Decimal
from typing import Literal

from agent_service.contracts.events import (
    ActionCompletedEvent,
    ActionRequiredEvent,
    ActionStartedEvent,
    RunEvent,
    RunFailedEvent,
)
from agent_service.contracts.models import AgentPendingAction
from business_service.after_sales.application.ports import (
    AfterSalesUnitOfWork,
)


class AfterSalesRunProjector:
    def __init__(
        self,
        *,
        unit_of_work_factory: Callable[
            [],
            AbstractAsyncContextManager[AfterSalesUnitOfWork],
        ],
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._tool_log_ids: dict[tuple[str, str], int] = {}

    async def record_event(self, event: RunEvent) -> None:
        if isinstance(event, ActionStartedEvent):
            async with self._unit_of_work_factory() as uow:
                log_id = await uow.repository.start_tool_call(
                    conversation_id=event.run_id,
                    tool_call_id=event.action_id,
                    tool_name=event.action_name,
                    tool_arguments=event.action_payload,
                )
                await uow.commit()
            self._tool_log_ids[(event.run_id, event.action_id)] = log_id
            return

        if isinstance(event, ActionCompletedEvent):
            log_id = self._tool_log_ids.pop((event.run_id, event.action_id), -1)
            if log_id >= 0:
                async with self._unit_of_work_factory() as uow:
                    await uow.repository.finish_tool_call(
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
                    await uow.commit()
            return

        if isinstance(event, ActionRequiredEvent):
            await self._request_approval(
                conversation_id=event.run_id,
                pending_action=event.pending_action,
            )
            return

        if isinstance(event, RunFailedEvent):
            async with self._unit_of_work_factory() as uow:
                await uow.repository.record_audit_log(
                    conversation_id=event.run_id,
                    event_type="run_failed",
                    payload={
                        "code": event.error.code,
                        "message": event.error.message,
                    },
                )
                await uow.commit()

    async def resolve_approval(
        self,
        *,
        conversation_id: str,
        pending_action: AgentPendingAction,
        decision: Literal["approved", "rejected"],
    ) -> None:
        async with self._unit_of_work_factory() as uow:
            await uow.repository.resolve_approval(
                conversation_id=conversation_id,
                tool_call_id=pending_action.action_id,
                status="approved" if decision == "approved" else "rejected",
            )
            await uow.repository.record_audit_log(
                conversation_id=conversation_id,
                event_type="approval_resolved",
                payload={
                    "action_id": pending_action.action_id,
                    "decision": decision,
                    "display_payload": pending_action.display_payload,
                },
            )
            await uow.commit()

    async def _request_approval(
        self,
        *,
        conversation_id: str,
        pending_action: AgentPendingAction,
    ) -> None:
        amount = pending_action.display_payload.get("amount")
        decimal_amount = Decimal(str(amount)) if isinstance(amount, int | float | str) else None
        order_value = pending_action.display_payload.get("order_id")
        reason_value = pending_action.display_payload.get("reason")
        async with self._unit_of_work_factory() as uow:
            await uow.repository.request_approval(
                conversation_id=conversation_id,
                tool_call_id=pending_action.action_id,
                tool_name=pending_action.action_name,
                order_id=order_value if isinstance(order_value, str) else None,
                amount=decimal_amount,
                reason=reason_value if isinstance(reason_value, str) else None,
                risk_level=pending_action.risk_level,
                display_payload=pending_action.display_payload,
            )
            await uow.repository.record_audit_log(
                conversation_id=conversation_id,
                event_type="approval_requested",
                payload={
                    "action_id": pending_action.action_id,
                    "tool_name": pending_action.action_name,
                    "reason": pending_action.reason,
                    "risk_level": pending_action.risk_level,
                    "display_payload": pending_action.display_payload,
                },
            )
            await uow.commit()
