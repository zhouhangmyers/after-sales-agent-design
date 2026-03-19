from __future__ import annotations

from sqlalchemy.orm import Session

from agent_service.db.models import LLMCallRecord


class LLMCallRepository:
    # 这个 repository 专门负责操作 llm_calls 表。
    # 它的职责是把每次模型规划调用的输入、结构化输出、token 使用和错误信息落库。
    def __init__(self, db_session: Session) -> None:
        self._db_session = db_session

    def create(
        self,
        *,
        llm_call_id: str,
        session_id: str,
        message_id: str,
        workflow_run_id: str,
        provider: str,
        model: str,
        prompt_name: str,
        prompt_version: str,
        request_json: str,
        response_json: str,
        structured_output_json: str,
        attempts: int,
        prompt_tokens: int,
        completion_tokens: int,
        total_tokens: int,
        latency_ms: float,
        success: bool,
        error_json: str,
    ) -> LLMCallRecord:
        record = LLMCallRecord(
            id=llm_call_id,
            session_id=session_id,
            message_id=message_id,
            workflow_run_id=workflow_run_id,
            provider=provider,
            model=model,
            prompt_name=prompt_name,
            prompt_version=prompt_version,
            request_json=request_json,
            response_json=response_json,
            structured_output_json=structured_output_json,
            attempts=attempts,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            latency_ms=latency_ms,
            success=success,
            error_json=error_json,
        )
        self._db_session.add(record)
        self._db_session.flush()
        return record
