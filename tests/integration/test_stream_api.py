from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
from sse_starlette.sse import AppStatus

from agent_service.api.routers.chat import _event_to_sse_message
from agent_service.conversation.events import (
    ConversationApprovalRequired,
    ConversationCompleted,
    ConversationFailed,
    ConversationStarted,
    ConversationToken,
)
from agent_service.conversation.models import ConversationError, ConversationTurn, PendingAction
from tests.helpers import build_test_app


async def _collect_sse_events(
    client: httpx.AsyncClient,
    payload: dict[str, object],
) -> list[tuple[str, dict[str, object]]]:
    AppStatus.should_exit = False
    AppStatus.should_exit_event = None
    events: list[tuple[str, dict[str, object]]] = []
    event_name: str | None = None
    async with client.stream("POST", "/api/v2/chat/messages/stream", json=payload) as response:
        assert response.status_code == 200
        async for line in response.aiter_lines():
            if not line:
                continue
            if line.startswith("event: "):
                event_name = line.removeprefix("event: ").strip()
                continue
            if line.startswith("data: ") and event_name is not None:
                events.append((event_name, json.loads(line.removeprefix("data: "))))
                event_name = None
    return events


@pytest.mark.asyncio
async def test_stream_emits_conversation_token_and_complete_for_normal_turn(tmp_path: Path) -> None:
    app = build_test_app(f"sqlite+pysqlite:///{tmp_path / 'stream-complete.db'}")
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            events = await _collect_sse_events(
                client,
                {"message": "please add a=2 b=3"},
            )

    assert [name for name, _ in events] == ["conversation", "token", "complete"]
    assert events[0][1]["conversation_id"].startswith("conv-")
    assert events[1][1]["text"] == "我已经调用 `add` 完成处理，结果是 5。"
    assert events[2][1]["status"] == "completed"
    assert events[2][1]["reply"] == "我已经调用 `add` 完成处理，结果是 5。"


@pytest.mark.asyncio
async def test_stream_emits_approval_required_then_complete_for_paused_turn(tmp_path: Path) -> None:
    app = build_test_app(f"sqlite+pysqlite:///{tmp_path / 'stream-approval.db'}")
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            events = await _collect_sse_events(
                client,
                {"message": "please multiply a=2 b=3"},
            )

    assert [name for name, _ in events] == [
        "conversation",
        "approval_required",
        "complete",
    ]
    conversation_id = events[0][1]["conversation_id"]
    assert events[1][1] == {
        "conversation_id": conversation_id,
        "pending_action": {
            "kind": "tool_approval",
            "tool_name": "multiply",
            "tool_arguments": {"a": 2, "b": 3},
            "reason": "工具 `multiply` 当前策略要求人工审批后才能执行。",
            "risk_level": "medium",
        },
    }
    assert events[2][1]["conversation_id"] == conversation_id
    assert events[2][1]["status"] == "awaiting_action"


@pytest.mark.asyncio
async def test_stream_only_emits_current_turn_events(tmp_path: Path) -> None:
    app = build_test_app(f"sqlite+pysqlite:///{tmp_path / 'stream-current-turn.db'}")
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            first_events = await _collect_sse_events(
                client,
                {"message": "please add a=2 b=3"},
            )
            conversation_id = first_events[0][1]["conversation_id"]

            second_events = await _collect_sse_events(
                client,
                {
                    "conversation_id": conversation_id,
                    "message": "please divide a=8 b=2",
                },
            )

    assert [name for name, _ in second_events] == ["conversation", "token", "complete"]
    assert second_events[0][1]["conversation_id"] == conversation_id
    assert second_events[1][1]["text"] == "我已经调用 `divide` 完成处理，结果是 4.0。"
    assert second_events[2][1]["reply"] == "我已经调用 `divide` 完成处理，结果是 4.0。"


def test_event_to_sse_message_preserves_wire_shape() -> None:
    pending_action = PendingAction(
        tool_name="multiply",
        tool_arguments={"a": 2, "b": 3},
        reason="needs approval",
        risk_level="medium",
    )
    turn = ConversationTurn(
        conversation_id="conv-1",
        status="completed",
        reply="done",
    )
    error = ConversationError(
        code="conversation.execution_failed",
        message="boom",
    )

    assert json.loads(_event_to_sse_message(ConversationStarted("conv-1"))["data"]) == {
        "conversation_id": "conv-1"
    }
    assert json.loads(
        _event_to_sse_message(ConversationToken(conversation_id="conv-1", text="chunk"))["data"]
    ) == {
        "conversation_id": "conv-1",
        "text": "chunk",
    }
    assert json.loads(
        _event_to_sse_message(
            ConversationApprovalRequired(
                conversation_id="conv-1",
                pending_action=pending_action,
            )
        )["data"]
    ) == {
        "conversation_id": "conv-1",
        "pending_action": pending_action.model_dump(mode="json"),
    }
    assert json.loads(
        _event_to_sse_message(ConversationCompleted(turn=turn))["data"]
    ) == turn.model_dump(mode="json")
    assert json.loads(
        _event_to_sse_message(
            ConversationFailed(conversation_id="conv-1", error=error)
        )["data"]
    ) == {
        "conversation_id": "conv-1",
        "code": "conversation.execution_failed",
        "message": "boom",
    }
