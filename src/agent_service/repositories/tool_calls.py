from __future__ import annotations

from sqlalchemy.orm import Session

from agent_service.db.models import ToolCallRecord


class ToolCallRepository:
    # 这个 repository 专门负责操作 tool_calls 表。
    # 它的职责是把一次工具调用的输入、输出、是否成功以及耗时落到数据库里。
    def __init__(self, db_session: Session) -> None:
        # 复用外部传入的数据库 session。
        # repository 只负责执行持久化动作，不负责创建或提交数据库连接。
        self._db_session = db_session

    def create(
        self,
        *,
        tool_call_id: str,
        session_id: str,
        message_id: str,
        tool_name: str,
        arguments_json: str,
        result_json: str,
        success: bool,
        latency_ms: float,
    ) -> ToolCallRecord:
        # 根据一次工具调用的上下文，构造对应的 ORM 记录。
        # 这里既保存工具名称和参数，也保存执行结果、成功状态与耗时，方便后续排查和分析。
        record = ToolCallRecord(
            id=tool_call_id,
            session_id=session_id,
            message_id=message_id,
            tool_name=tool_name,
            arguments_json=arguments_json,
            result_json=result_json,
            success=success,
            latency_ms=latency_ms,
        )
        # 把工具调用记录加入当前数据库 session。
        self._db_session.add(record)
        # 先同步到当前事务，确保后续同一请求内的逻辑可以继续使用这条记录。
        # 这里不直接 commit，最终提交仍然交给更上层统一控制。
        self._db_session.flush()
        # 返回刚创建好的工具调用记录对象。
        return record
