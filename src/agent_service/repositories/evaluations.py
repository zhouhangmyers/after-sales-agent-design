from __future__ import annotations

from sqlalchemy.orm import Session

from agent_service.db.models import EvaluationRecord


class EvaluationRepository:
    # 这个 repository 专门负责操作 evaluations 表。
    # 当前 Week 2 里这张表还没有深度进入主链路，
    # 但后面做 Eval（评测体系）时会用它记录指标结果。
    def __init__(self, db_session: Session) -> None:
        # 这里接收外部传进来的数据库 session。
        # repository 自己不负责创建数据库连接，只负责用已有 session 进行数据操作。
        self._db_session = db_session

    def create(
        self,
        *,
        evaluation_id: str,
        workflow_run_id: str,
        metric_name: str,
        metric_value: float | None,
        note: str = "",
    ) -> EvaluationRecord:
        # 先根据传入参数创建一条 ORM 评测记录对象。
        # 这里记录的是：某次 workflow run 的某个指标名称、指标值和补充说明。
        record = EvaluationRecord(
            id=evaluation_id,
            workflow_run_id=workflow_run_id,
            metric_name=metric_name,
            metric_value=metric_value,
            note=note,
        )
        # 把这条记录加入当前数据库 session。
        self._db_session.add(record)
        # flush() 会先把这次变更同步到当前事务里，
        # 但还不是最终 commit；真正的 commit 通常由更上层的 service 统一控制。
        self._db_session.flush()
        # 返回刚创建好的评测记录对象，方便调用方继续使用。
        return record
