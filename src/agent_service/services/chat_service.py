from __future__ import annotations

import json
from uuid import uuid4

from sqlalchemy.orm import Session

from agent_service.repositories.llm_calls import LLMCallRepository
from agent_service.repositories.messages import MessageRepository
from agent_service.repositories.sessions import SessionRepository
from agent_service.repositories.tool_calls import ToolCallRepository
from agent_service.repositories.workflow_runs import WorkflowRunRepository
from agent_service.schemas.chat import ChatRequest, ChatResponse, TokenUsageSummary
from agent_service.services.orchestrator_service import OrchestratorService


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex[:12]}"


def _json_dumps(payload: object) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


class ChatService:
    def __init__(self, db_session: Session, orchestrator_service: OrchestratorService) -> None:
        self._db_session = db_session
        self._orchestrator_service = orchestrator_service
        self._sessions = SessionRepository(db_session)
        self._messages = MessageRepository(db_session)
        self._tool_calls = ToolCallRepository(db_session)
        self._workflow_runs = WorkflowRunRepository(db_session)
        self._llm_calls = LLMCallRepository(db_session)

    def handle_chat(self, payload: ChatRequest) -> ChatResponse:
        user_message_id = _new_id("msg")
        assistant_message_id = _new_id("msg")
        workflow_run_id = _new_id("wf")

        try:
            self._sessions.get_or_create(payload.session_id, title="Week 3 Agent Loop Session")
            self._messages.create(
                message_id=user_message_id,
                session_id=payload.session_id,
                role="user",
                content=payload.message,
            )
            workflow_run = self._workflow_runs.create(
                workflow_run_id=workflow_run_id,
                session_id=payload.session_id,
                run_type="agent_loop_chat",
                status="running",
                #payload.model_dump()是得到Python字典，_json_dumps返回值类型是字符串
                input_json=_json_dumps(payload.model_dump()),
            )
            # 关键一步：把这次任务交给编排层去跑完整的 agent loop。
            # 也就是说，从这里开始，系统会进入：
            # 规划 -> 执行工具 -> observation -> 再规划
            # 直到拿到最终 reply 或失败为止。
            execution = self._orchestrator_service.run(
                session_id=payload.session_id,
                message=payload.message,
                request_id=user_message_id,
            )

            for planner_trace in execution.planner_calls:
                self._llm_calls.create(
                    llm_call_id=_new_id("llm"),
                    session_id=payload.session_id,
                    message_id=user_message_id,
                    workflow_run_id=workflow_run_id,
                    provider=planner_trace.provider,
                    model=planner_trace.model,
                    prompt_name=planner_trace.prompt_name,
                    prompt_version=planner_trace.prompt_version,
                    request_json=_json_dumps(planner_trace.request_payload),
                    response_json=_json_dumps(planner_trace.raw_response or {}),
                    structured_output_json=_json_dumps(
                        planner_trace.decision.model_dump() if planner_trace.decision is not None else {}
                    ),
                    attempts=planner_trace.attempts,
                    prompt_tokens=planner_trace.usage.prompt_tokens,
                    completion_tokens=planner_trace.usage.completion_tokens,
                    total_tokens=planner_trace.usage.total_tokens,
                    latency_ms=planner_trace.latency_ms,
                    success=planner_trace.success,
                    error_json=_json_dumps({"message": planner_trace.error_message} if planner_trace.error_message else {}),
                )

            for tool_execution in execution.tool_executions:
                self._tool_calls.create(
                    tool_call_id=_new_id("tool"),
                    session_id=payload.session_id,
                    message_id=user_message_id,
                    tool_name=tool_execution.request.action,
                    arguments_json=_json_dumps(tool_execution.request.arguments),
                    result_json=_json_dumps(tool_execution.result.model_dump()),
                    success=tool_execution.result.success,
                    latency_ms=tool_execution.latency_ms,
                )

            self._messages.create(
                message_id=assistant_message_id,
                session_id=payload.session_id,
                role="assistant",
                content=execution.reply,
                status="completed" if execution.workflow_status == "completed" else "failed",
            )
            self._workflow_runs.update_status(
                workflow_run,
                status=execution.workflow_status,
                output_json=_json_dumps(
                    {
                        "assistant_message_id": assistant_message_id,
                        "reply": execution.reply,
                        "tool_results": [item.result.model_dump() for item in execution.tool_executions],
                        "llm_call_count": len(execution.planner_calls),
                        "usage": execution.usage.model_dump(),
                    }
                ),
            )
            self._db_session.commit()
        except Exception:
            self._db_session.rollback()
            raise

        tool_results = [item.result for item in execution.tool_executions]
        usage = TokenUsageSummary(
            prompt_tokens=execution.usage.prompt_tokens,
            completion_tokens=execution.usage.completion_tokens,
            total_tokens=execution.usage.total_tokens,
        )
        return ChatResponse(
            session_id=payload.session_id,
            workflow_run_id=workflow_run_id,
            message_id=user_message_id,
            assistant_message_id=assistant_message_id,
            reply=execution.reply,
            tool_result=tool_results[-1] if tool_results else None,
            tool_results=tool_results,
            usage=usage,
        )
