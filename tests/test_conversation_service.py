from __future__ import annotations

import pytest

from agent_service.contracts.events import (
    ActionCompletedEvent,
    ActionStartedEvent,
    OutputDeltaEvent,
    RunCompletedEvent,
    RunStartedEvent,
)
from agent_service.contracts.models import AgentRunResult, RunState
from tests.agent_helpers import (
    build_missing_tool_call_id_conversation_service,
    build_multi_tool_call_conversation_service,
    build_strict_test_conversation_service,
    build_test_conversation_service,
)


async def _collect_result(service, *, conversation_id: str | None, message: str) -> AgentRunResult:
    stream = await service.stream_message(
        session_id=conversation_id,
        message=message,
    )
    async for event in stream:
        if isinstance(event, RunCompletedEvent):
            return event.result
    raise AssertionError("conversation stream finished without RunCompletedEvent")


async def _collect_resume_result(service, *, conversation_id: str, decision: str) -> AgentRunResult:
    stream = await service.stream_resume(
        run_id=conversation_id,
        decision=decision,
    )
    async for event in stream:
        if isinstance(event, RunCompletedEvent):
            return event.result
    raise AssertionError("resume stream finished without RunCompletedEvent")


@pytest.mark.asyncio
async def test_conversation_service_executes_tool_then_responds() -> None:
    service = build_test_conversation_service()

    result = await _collect_result(
        service,
        conversation_id=None,
        message="please add a=2 b=3",
    )

    assert isinstance(result, AgentRunResult)
    assert result.status == "completed"
    assert result.output == "我已经调用 `add` 完成处理，结果是 5。"
    assert result.pending_action is None
    assert result.error is None
    assert result.session_id.startswith("conv-")
    assert result.run_id.startswith("run-")


@pytest.mark.asyncio
async def test_conversation_service_pauses_when_tool_requires_action() -> None:
    service = build_test_conversation_service()

    result = await _collect_result(
        service,
        conversation_id=None,
        message="please multiply a=2 b=3",
    )

    assert result.status == "awaiting_action"
    assert result.pending_action is not None
    assert result.pending_action.action_id == "call_multiply"
    assert result.pending_action.action_name == "multiply"
    assert result.run_id != result.session_id


@pytest.mark.asyncio
async def test_conversation_service_allows_new_run_while_waiting_for_approval() -> None:
    service = build_test_conversation_service()
    first = await _collect_result(
        service,
        conversation_id=None,
        message="please multiply a=2 b=3",
    )
    second = await _collect_result(
        service,
        conversation_id=first.session_id,
        message="please add a=2 b=3",
    )

    assert first.status == "awaiting_action"
    assert second.status == "completed"
    assert second.output == "我已经调用 `add` 完成处理，结果是 5。"
    assert second.session_id == first.session_id
    assert second.run_id != first.run_id


@pytest.mark.asyncio
async def test_conversation_service_resume_rejected_returns_completed() -> None:
    service = build_test_conversation_service()
    created = await _collect_result(
        service,
        conversation_id=None,
        message="please multiply a=2 b=3",
    )

    result = await _collect_resume_result(
        service,
        conversation_id=created.run_id,
        decision="rejected",
    )

    assert result.status == "completed"
    assert result.output == "人工审批已拒绝，本次不会执行工具 `multiply`。"
    assert result.pending_action is None


@pytest.mark.asyncio
async def test_conversation_service_can_continue_same_thread_after_rejection() -> None:
    service = build_strict_test_conversation_service()
    created = await _collect_result(
        service,
        conversation_id=None,
        message="please multiply a=2 b=3",
    )

    rejected = await _collect_resume_result(
        service,
        conversation_id=created.run_id,
        decision="rejected",
    )
    continued = await _collect_result(
        service,
        conversation_id=created.session_id,
        message="please add a=2 b=3",
    )

    assert rejected.status == "completed"
    assert rejected.output == "人工审批已拒绝，本次不会执行工具 `multiply`。"
    assert continued.status == "completed"
    assert continued.output == "我已经调用 `add` 完成处理，结果是 5。"


@pytest.mark.asyncio
async def test_conversation_service_can_continue_same_thread() -> None:
    service = build_test_conversation_service()
    first = await _collect_result(
        service,
        conversation_id=None,
        message="please add a=2 b=3",
    )

    second = await _collect_result(
        service,
        conversation_id=first.session_id,
        message="please divide a=8 b=2",
    )

    assert second.session_id == first.session_id
    assert second.run_id != first.run_id
    assert second.status == "completed"
    assert second.output == "我已经调用 `divide` 完成处理，结果是 4.0。"


@pytest.mark.asyncio
async def test_conversation_service_supports_multiple_pending_runs_per_session() -> None:
    service = build_test_conversation_service()
    first = await _collect_result(
        service,
        conversation_id=None,
        message="please multiply a=2 b=3",
    )
    second = await _collect_result(
        service,
        conversation_id=first.session_id,
        message="please multiply a=5 b=6",
    )

    first_state = await service.get_state(run_id=first.run_id)
    second_state = await service.get_state(run_id=second.run_id)

    assert first.status == "awaiting_action"
    assert second.status == "awaiting_action"
    assert second.session_id == first.session_id
    assert second.run_id != first.run_id
    assert first_state.status == "awaiting_action"
    assert second_state.status == "awaiting_action"


@pytest.mark.asyncio
async def test_conversation_service_normalizes_missing_tool_call_id() -> None:
    service = build_missing_tool_call_id_conversation_service()

    result = await _collect_result(
        service,
        conversation_id=None,
        message="please add a=2 b=3",
    )

    assert result.status == "completed"
    assert result.output == "我已经调用 `add` 完成处理，结果是 5。"


@pytest.mark.asyncio
async def test_conversation_service_collapses_multiple_tool_calls_to_one_action() -> None:
    service = build_multi_tool_call_conversation_service()

    result = await _collect_result(
        service,
        conversation_id=None,
        message="please multi_tool",
    )

    assert result.status == "completed"
    assert result.output == "我已经调用 `add` 完成处理，结果是 5。"


@pytest.mark.asyncio
async def test_conversation_service_get_state_returns_run_state() -> None:
    service = build_test_conversation_service()
    created = await _collect_result(
        service,
        conversation_id=None,
        message="please multiply a=2 b=3",
    )

    state = await service.get_state(run_id=created.run_id)

    assert isinstance(state, RunState)
    assert state.run_id == created.run_id
    assert state.session_id == created.session_id
    assert state.status == "awaiting_action"
    assert state.pending_action is not None


@pytest.mark.asyncio
async def test_conversation_service_resume_preserves_usage_totals() -> None:
    service = build_test_conversation_service()
    created = await _collect_result(
        service,
        conversation_id=None,
        message="please multiply a=2 b=3",
    )

    pending_state = await service.get_state(run_id=created.run_id)
    pending_usage = pending_state.metadata["usage"]

    result = await _collect_resume_result(
        service,
        conversation_id=created.run_id,
        decision="approved",
    )
    final_state = await service.get_state(run_id=created.run_id)
    final_usage = final_state.metadata["usage"]

    assert created.pending_action is not None
    assert pending_usage["total_tokens"] > 0
    assert result.status == "completed"
    assert final_usage["total_tokens"] >= pending_usage["total_tokens"]


@pytest.mark.asyncio
async def test_conversation_service_stream_returns_agent_events() -> None:
    service = build_test_conversation_service()

    stream = await service.stream_message(
        session_id=None,
        message="please add a=2 b=3",
    )
    events = [event async for event in stream]

    assert isinstance(events[0], RunStartedEvent)
    assert isinstance(events[1], ActionStartedEvent)
    assert isinstance(events[2], ActionCompletedEvent)
    assert isinstance(events[3], OutputDeltaEvent)
    assert isinstance(events[4], RunCompletedEvent)
    assert events[4].result.output == "我已经调用 `add` 完成处理，结果是 5。"
