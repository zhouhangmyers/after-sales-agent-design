from __future__ import annotations

import pytest

from agent_service.conversation.events import (
    ConversationCompleted,
    ConversationStarted,
    ConversationToken,
)
from agent_service.conversation.models import ConversationSnapshot, ConversationTurn
from tests.helpers import build_test_conversation_service


@pytest.mark.asyncio
async def test_conversation_service_executes_tool_then_responds() -> None:
    service = build_test_conversation_service()

    result = await service.send_message(
        conversation_id=None,
        message="please add a=2 b=3",
    )

    assert isinstance(result, ConversationTurn)
    assert result.status == "completed"
    assert result.reply == "我已经调用 `add` 完成处理，结果是 5。"
    assert result.pending_action is None
    assert result.error is None
    assert result.usage.total_tokens > 0
    service.close()


@pytest.mark.asyncio
async def test_conversation_service_pauses_when_tool_requires_action() -> None:
    service = build_test_conversation_service()

    result = await service.send_message(
        conversation_id=None,
        message="please multiply a=2 b=3",
    )

    assert result.status == "awaiting_action"
    assert result.pending_action is not None
    assert result.pending_action.tool_name == "multiply"
    service.close()


@pytest.mark.asyncio
async def test_conversation_service_rejects_new_message_while_waiting_for_approval() -> None:
    from agent_service.conversation.service import ConversationConflictError

    service = build_test_conversation_service()
    created = await service.send_message(
        conversation_id=None,
        message="please multiply a=2 b=3",
    )

    with pytest.raises(
        ConversationConflictError,
        match="conversation is waiting for approval; use /chat/resume instead",
    ):
        await service.send_message(
            conversation_id=created.conversation_id,
            message="hello again",
        )
    service.close()


@pytest.mark.asyncio
async def test_conversation_service_resume_rejected_returns_completed() -> None:
    service = build_test_conversation_service()
    created = await service.send_message(
        conversation_id=None,
        message="please multiply a=2 b=3",
    )

    result = await service.resume(
        conversation_id=created.conversation_id,
        decision="rejected",
    )

    assert result.status == "completed"
    assert result.reply == "人工审批已拒绝，本次不会执行工具 `multiply`。"
    assert result.pending_action is None
    service.close()


@pytest.mark.asyncio
async def test_conversation_service_can_continue_same_thread() -> None:
    service = build_test_conversation_service()
    first = await service.send_message(
        conversation_id=None,
        message="please add a=2 b=3",
    )

    second = await service.send_message(
        conversation_id=first.conversation_id,
        message="please divide a=8 b=2",
    )

    assert second.conversation_id == first.conversation_id
    assert second.status == "completed"
    assert second.reply == "我已经调用 `divide` 完成处理，结果是 4.0。"
    service.close()


@pytest.mark.asyncio
async def test_conversation_service_get_state_returns_snapshot() -> None:
    service = build_test_conversation_service()
    created = await service.send_message(
        conversation_id=None,
        message="please multiply a=2 b=3",
    )

    state = await service.get_state(conversation_id=created.conversation_id)

    assert isinstance(state, ConversationSnapshot)
    assert state.conversation_id == created.conversation_id
    assert state.status == "awaiting_action"
    assert state.pending_action is not None
    service.close()


@pytest.mark.asyncio
async def test_conversation_service_stream_returns_typed_events() -> None:
    service = build_test_conversation_service()

    stream = await service.stream_message(
        conversation_id=None,
        message="please add a=2 b=3",
    )
    events = [event async for event in stream]

    assert isinstance(events[0], ConversationStarted)
    assert isinstance(events[1], ConversationToken)
    assert isinstance(events[2], ConversationCompleted)
    assert events[2].turn.reply == "我已经调用 `add` 完成处理，结果是 5。"
    service.close()
