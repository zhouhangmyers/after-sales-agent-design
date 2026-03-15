from __future__ import annotations

from sqlalchemy.orm import Session

from agent_service.db.models import WorkflowRunRecord


class WorkflowRunRepository:
    # 这个 repository 专门负责操作 workflow_runs 表。
    # 它主要记录一次工作流运行的基础信息，包括输入、输出和当前执行状态。
    def __init__(self, db_session: Session) -> None:
        # 复用外部传入的数据库 session。
        # repository 只负责读写当前事务中的数据，不负责创建或最终提交 session。
        self._db_session = db_session

    def create(
        self,
        *,
        workflow_run_id: str,
        session_id: str,
        run_type: str,
        status: str,
        input_json: str,
        output_json: str = "{}",
    ) -> WorkflowRunRecord:
        # 为一次新的 workflow run 创建 ORM 记录。
        # 这里会保存运行类型、初始状态、输入数据，以及默认的输出占位内容。
        record = WorkflowRunRecord(
            id=workflow_run_id,
            session_id=session_id,
            run_type=run_type,
            status=status,
            input_json=input_json,
            output_json=output_json,
        )
        # 把新记录加入当前数据库 session。
        self._db_session.add(record)
        # 先同步到当前事务，方便后续同一请求中的其他逻辑继续引用这条 run 记录。
        # 这里仍然不直接 commit，提交通常交给更上层统一控制。
        self._db_session.flush()
        # 返回刚创建好的工作流运行记录对象。
        return record

    def update_status(
        self,
        record: WorkflowRunRecord,
        *,
        status: str,
        output_json: str,
    ) -> WorkflowRunRecord:
        # 更新已有 workflow run 的执行状态和最终输出。
        # 一般会在工作流执行完成、失败或进入下一个阶段时调用。
        record.status = status
        record.output_json = output_json
        # 重新加入当前 session，确保变更被 SQLAlchemy 跟踪。
        self._db_session.add(record)
        # 先把状态更新同步到当前事务里，但不在这里直接 commit。
        self._db_session.flush()
        # 返回更新后的记录对象，方便调用方继续使用。
        return record
