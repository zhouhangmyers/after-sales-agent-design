from __future__ import annotations

from sqlalchemy import select

from agent_service.api.chat import create_chat_response
from agent_service.schemas.chat import ChatRequest
from agent_service.db.models import MessageRecord, SessionRecord, ToolCallRecord, WorkflowRunRecord


def test_chat_endpoint_executes_runtime_and_persists_records(app, db_session) -> None:
    response = create_chat_response(
        ChatRequest(session_id="sess-001", message="请执行 add 工具，参数 a=3, b=7"),
        db_session,
        app.state.runtime_service,
    )

    assert response.session_id == "sess-001"
    assert response.tool_result is not None
    assert response.tool_result.success is True
    assert response.tool_result.result == 10

    with app.state.db_manager.session() as session:
        assert session.get(SessionRecord, "sess-001") is not None
        messages = session.scalars(select(MessageRecord)).all()
        tool_calls = session.scalars(select(ToolCallRecord)).all()
        workflow_runs = session.scalars(select(WorkflowRunRecord)).all()

    assert len(messages) == 2
    assert len(tool_calls) == 1
    assert len(workflow_runs) == 1


def test_chat_endpoint_handles_plain_message_without_tool(app, db_session) -> None:
    response = create_chat_response(
        ChatRequest(session_id="sess-plain", message="hello runtime"),
        db_session,
        app.state.runtime_service,
    )

    assert response.tool_result is None
    assert "当前 Week 2 骨架只会从消息里解析演示工具" in response.reply
