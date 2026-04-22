from __future__ import annotations

from collections.abc import Awaitable, Callable
from pathlib import Path

from langgraph.checkpoint.memory import MemorySaver

import httpx
import pytest

from tests.helpers import build_test_app


async def _with_client(
    database_path: Path,
    fn: Callable[[httpx.AsyncClient], Awaitable[None]],
) -> None:
    app = build_test_app(f"sqlite+pysqlite:///{database_path}")
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://testserver",
        ) as client:
            await fn(client)


@pytest.mark.asyncio
async def test_post_chat_message_implicitly_creates_conversation_and_completes(tmp_path: Path) -> None:
    async def _run(client: httpx.AsyncClient) -> None:
        response = await client.post(
            "/api/v2/chat/messages",
            json={"message": "please add a=2 b=3"},
        )

        assert response.status_code == 200
        body = response.json()
        assert body["conversation_id"].startswith("conv-")
        assert body["status"] == "completed"
        assert body["reply"] == "我已经调用 `add` 完成处理，结果是 5。"
        assert body["pending_action"] is None
        assert body["error"] is None
        assert sorted(body["usage"]) == [
            "completion_tokens",
            "prompt_tokens",
            "total_tokens",
        ]

    await _with_client(tmp_path / "chat-complete.db", _run)


@pytest.mark.asyncio
async def test_post_chat_message_can_continue_existing_conversation(tmp_path: Path) -> None:
    async def _run(client: httpx.AsyncClient) -> None:
        first = await client.post(
            "/api/v2/chat/messages",
            json={"message": "please add a=2 b=3"},
        )
        conversation_id = first.json()["conversation_id"]

        second = await client.post(
            "/api/v2/chat/messages",
            json={
                "conversation_id": conversation_id,
                "message": "please divide a=8 b=2",
            },
        )

        assert second.status_code == 200
        body = second.json()
        assert body["conversation_id"] == conversation_id
        assert body["status"] == "completed"
        assert body["reply"] == "我已经调用 `divide` 完成处理，结果是 4.0。"

    await _with_client(tmp_path / "chat-continue.db", _run)


@pytest.mark.asyncio
async def test_chat_state_hides_messages_and_reports_pending_action(tmp_path: Path) -> None:
    async def _run(client: httpx.AsyncClient) -> None:
        create = await client.post(
            "/api/v2/chat/messages",
            json={"message": "please multiply a=2 b=3"},
        )
        assert create.status_code == 200
        body = create.json()
        assert body["status"] == "awaiting_action"

        state = await client.get(f"/api/v2/chat/state/{body['conversation_id']}")
        assert state.status_code == 200
        state_body = state.json()
        assert state_body == {
            "conversation_id": body["conversation_id"],
            "status": "awaiting_action",
            "last_reply": "工具 `multiply` 需要人工审批，当前对话已暂停，等待批准后继续。",
            "pending_action": {
                "kind": "tool_approval",
                "tool_name": "multiply",
                "tool_arguments": {"a": 2, "b": 3},
                "reason": "工具 `multiply` 当前策略要求人工审批后才能执行。",
                "risk_level": "medium",
            },
        }
        assert "messages" not in state_body

    await _with_client(tmp_path / "chat-state.db", _run)


@pytest.mark.asyncio
async def test_chat_resume_approved_and_rejected_paths(tmp_path: Path) -> None:
    async def _run(client: httpx.AsyncClient) -> None:
        create = await client.post(
            "/api/v2/chat/messages",
            json={"message": "please multiply a=2 b=3"},
        )
        conversation_id = create.json()["conversation_id"]

        approved = await client.post(
            "/api/v2/chat/resume",
            json={
                "conversation_id": conversation_id,
                "decision": "approved",
            },
        )
        assert approved.status_code == 200
        approved_body = approved.json()
        assert approved_body["status"] == "completed"
        assert approved_body["reply"] == "我已经调用 `multiply` 完成处理，结果是 6。"
        assert approved_body["pending_action"] is None

        rejected_create = await client.post(
            "/api/v2/chat/messages",
            json={"message": "please multiply a=4 b=5"},
        )
        rejected_conversation_id = rejected_create.json()["conversation_id"]
        rejected = await client.post(
            "/api/v2/chat/resume",
            json={
                "conversation_id": rejected_conversation_id,
                "decision": "rejected",
            },
        )
        assert rejected.status_code == 200
        rejected_body = rejected.json()
        assert rejected_body["status"] == "completed"
        assert rejected_body["reply"] == "人工审批已拒绝，本次不会执行工具 `multiply`。"
        assert rejected_body["pending_action"] is None

    await _with_client(tmp_path / "chat-resume.db", _run)


@pytest.mark.asyncio
async def test_chat_rejects_new_message_while_conversation_waits_for_approval(tmp_path: Path) -> None:
    async def _run(client: httpx.AsyncClient) -> None:
        create = await client.post(
            "/api/v2/chat/messages",
            json={"message": "please multiply a=2 b=3"},
        )
        conversation_id = create.json()["conversation_id"]

        conflict = await client.post(
            "/api/v2/chat/messages",
            json={
                "conversation_id": conversation_id,
                "message": "hello again",
            },
        )
        assert conflict.status_code == 409
        assert conflict.json() == {
            "detail": "conversation is waiting for approval; use /chat/resume instead"
        }

    await _with_client(tmp_path / "chat-conflict.db", _run)


@pytest.mark.asyncio
async def test_chat_unknown_conversation_returns_not_found(tmp_path: Path) -> None:
    async def _run(client: httpx.AsyncClient) -> None:
        response = await client.get("/api/v2/chat/state/conv-missing")
        assert response.status_code == 404
        assert response.json() == {"detail": "conversation not found: conv-missing"}

    await _with_client(tmp_path / "chat-missing.db", _run)


@pytest.mark.asyncio
async def test_chat_resume_survives_app_restart_with_same_checkpointer(tmp_path: Path) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'chat-restart.db'}"
    checkpointer = MemorySaver()

    first_app = build_test_app(database_url, checkpointer=checkpointer)
    async with first_app.router.lifespan_context(first_app):
        transport = httpx.ASGITransport(app=first_app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            create = await client.post(
                "/api/v2/chat/messages",
                json={"message": "please multiply a=2 b=3"},
            )
            assert create.status_code == 200
            conversation_id = create.json()["conversation_id"]

    second_app = build_test_app(database_url, checkpointer=checkpointer)
    async with second_app.router.lifespan_context(second_app):
        transport = httpx.ASGITransport(app=second_app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            resumed = await client.post(
                "/api/v2/chat/resume",
                json={
                    "conversation_id": conversation_id,
                    "decision": "approved",
                },
            )

    assert resumed.status_code == 200
    resumed_body = resumed.json()
    assert resumed_body["conversation_id"] == conversation_id
    assert resumed_body["status"] == "completed"
    assert resumed_body["reply"] == "我已经调用 `multiply` 完成处理，结果是 6。"


def test_chat_openapi_contract_stays_stable(tmp_path: Path) -> None:
    app = build_test_app(f"sqlite+pysqlite:///{tmp_path / 'chat-openapi.db'}")
    openapi = app.openapi()

    assert openapi["paths"]["/api/v2/chat/messages"]["post"]["operationId"] == (
        "post_chat_message_api_v2_chat_messages_post"
    )
    assert openapi["paths"]["/api/v2/chat/messages"]["post"]["tags"] == ["chat"]
    assert openapi["paths"]["/api/v2/chat/messages/stream"]["post"]["operationId"] == (
        "stream_chat_message_api_v2_chat_messages_stream_post"
    )
    assert openapi["paths"]["/api/v2/chat/resume"]["post"]["operationId"] == (
        "resume_chat_message_api_v2_chat_resume_post"
    )
    assert openapi["paths"]["/api/v2/chat/state/{conversation_id}"]["get"]["operationId"] == (
        "get_chat_state_api_v2_chat_state__conversation_id__get"
    )

    schema_names = set(openapi["components"]["schemas"])
    assert {
        "ChatMessageRequest",
        "ConversationErrorModel",
        "ConversationStateResponse",
        "ConversationTurnResponse",
        "PendingActionModel",
        "ResumeConversationRequest",
    }.issubset(schema_names)
