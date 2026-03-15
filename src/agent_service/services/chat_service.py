from __future__ import annotations

import json
from time import perf_counter
from uuid import uuid4

from sqlalchemy.orm import Session

from agent_service.repositories.messages import MessageRepository
from agent_service.repositories.sessions import SessionRepository
from agent_service.repositories.tool_calls import ToolCallRepository
from agent_service.repositories.workflow_runs import WorkflowRunRepository
from agent_service.schemas.chat import ChatRequest, ChatResponse
from agent_service.services.runtime_service import RuntimeExecution, RuntimeService


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex[:12]}"


def _json_dumps(payload: object) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


class ChatService:
    def __init__(self, db_session: Session, runtime_service: RuntimeService) -> None:
        self._db_session = db_session
        self._runtime_service = runtime_service
        self._sessions = SessionRepository(db_session)
        self._messages = MessageRepository(db_session)
        self._tool_calls = ToolCallRepository(db_session)
        self._workflow_runs = WorkflowRunRepository(db_session)

    def handle_chat(self, payload: ChatRequest) -> ChatResponse:
        user_message_id = _new_id("msg")
        assistant_message_id = _new_id("msg")
        workflow_run_id = _new_id("wf")

        try:
            self._sessions.get_or_create(payload.session_id, title="Week 2 Demo Session")
            self._messages.create(
                message_id=user_message_id,
                session_id=payload.session_id,
                role="user",
                content=payload.message,
            )
            workflow_run = self._workflow_runs.create(
                workflow_run_id=workflow_run_id,
                session_id=payload.session_id,
                run_type="chat_request",
                status="running",
                input_json=_json_dumps(payload.model_dump()),
            )

            execution, latency_ms = self._execute_message(payload.message, user_message_id)
            reply = self._build_reply(payload.message, execution)

            if execution is not None:
                self._tool_calls.create(
                    tool_call_id=_new_id("tool"),
                    session_id=payload.session_id,
                    message_id=user_message_id,
                    tool_name=execution.request.action,
                    arguments_json=_json_dumps(execution.request.arguments),
                    result_json=_json_dumps(execution.result.model_dump()),
                    success=execution.result.success,
                    latency_ms=latency_ms,
                )

            self._messages.create(
                message_id=assistant_message_id,
                session_id=payload.session_id,
                role="assistant",
                content=reply,
            )
            self._workflow_runs.update_status(
                workflow_run,
                status="completed",
                output_json=_json_dumps(
                    {
                        "assistant_message_id": assistant_message_id,
                        "tool_result": execution.result.model_dump() if execution else None,
                    }
                ),
            )
            # 走到这里说明这次聊天请求涉及的数据库写入都成功了，
            # 现在统一 commit，把本次事务真正提交落库。
            self._db_session.commit()
        except Exception:
            # 只要中间任意一步报错，就回滚这次事务，
            # 避免数据库里留下只写了一半的脏状态。
            self._db_session.rollback()
            # 回滚后继续把原始异常抛出去，让上层知道这次请求失败了。
            raise

        return ChatResponse(
            session_id=payload.session_id,
            message_id=user_message_id,
            assistant_message_id=assistant_message_id,
            reply=reply,
            tool_result=execution.result if execution else None,
        )

    def _execute_message(
        self,
        message: str,
        request_id: str,
    ) -> tuple[RuntimeExecution | None, float]:
        start = perf_counter()
        execution = self._runtime_service.execute_from_message(message, request_id=request_id)
        duration_ms = (perf_counter() - start) * 1000
        return execution, duration_ms

    def _build_reply(self, message: str, execution: RuntimeExecution | None) -> str:
        if execution is None:
            return (
                "已记录消息，但当前 Week 2 骨架只会从消息里解析演示工具。"
                " 你可以发送类似 `add a=3 b=7` 或 `get_city city_code=sh` 的内容。"
            )

        result = execution.result
        if result.success:
            return f"工具 `{result.action}` 执行成功，结果是 {result.result!r}。"

        error_message = result.error.message if result.error is not None else "unknown error"
        return f"工具 `{result.action}` 执行失败：{error_message}。原始消息：{message}"
