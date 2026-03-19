from __future__ import annotations

from sqlalchemy import select

from agent_service.api.chat import create_chat_response
from agent_service.db.models import LLMCallRecord, MessageRecord, SessionRecord, ToolCallRecord, WorkflowRunRecord
from agent_service.schemas.chat import ChatRequest


def test_chat_endpoint_executes_runtime_and_persists_records(app, db_session) -> None:
    response = create_chat_response(
        ChatRequest(session_id="sess-001", message="请执行 add 工具，参数 a=3, b=7"),
        db_session,
        app.state.orchestrator_service,
    )

    assert response.session_id == "sess-001"
    assert response.workflow_run_id.startswith("wf-")
    assert response.tool_result is not None
    assert response.tool_result.success is True
    assert response.tool_result.result == 10
    assert len(response.tool_results) == 1
    assert response.usage is not None
    assert response.usage.total_tokens > 0
    assert "我已经调用 `add` 完成处理" in response.reply

    with app.state.db_manager.session() as session:
        assert session.get(SessionRecord, "sess-001") is not None
        messages = session.scalars(select(MessageRecord)).all()
        tool_calls = session.scalars(select(ToolCallRecord)).all()
        workflow_runs = session.scalars(select(WorkflowRunRecord)).all()
        llm_calls = session.scalars(select(LLMCallRecord)).all()

    assert len(messages) == 2
    assert len(tool_calls) == 1
    assert len(workflow_runs) == 1
    assert len(llm_calls) == 2


def test_chat_endpoint_handles_plain_message_without_tool(app, db_session) -> None:
    response = create_chat_response(
        ChatRequest(session_id="sess-plain", message="hello runtime"),
        db_session,
        app.state.orchestrator_service,
    )

    assert response.workflow_run_id.startswith("wf-")
    assert response.tool_result is None
    assert response.tool_results == []
    assert response.usage is not None
    assert response.usage.total_tokens > 0
    assert "当前 demo planner 没找到必须调用工具的场景" in response.reply

    with app.state.db_manager.session() as session:
        llm_calls = session.scalars(select(LLMCallRecord)).all()
        tool_calls = session.scalars(select(ToolCallRecord)).all()

    assert len(llm_calls) == 1
    assert len(tool_calls) == 0


def test_chat_endpoint_records_failed_tool_and_returns_structured_reply(app, db_session) -> None:
    response = create_chat_response(
        ChatRequest(session_id="sess-fail", message="请执行 divide 工具，参数 a=10, b=0"),
        db_session,
        app.state.orchestrator_service,
    )

    assert response.tool_result is not None
    assert response.tool_result.success is False
    assert len(response.tool_results) == 1
    assert "工具 `divide` 执行失败" in response.reply

    with app.state.db_manager.session() as session:
        tool_calls = session.scalars(select(ToolCallRecord)).all()
        llm_calls = session.scalars(select(LLMCallRecord)).all()

    assert len(tool_calls) == 1
    assert tool_calls[0].success is False
    assert len(llm_calls) == 2
