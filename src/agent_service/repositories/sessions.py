from __future__ import annotations

from sqlalchemy.orm import Session

from agent_service.db.models import SessionRecord


class SessionRepository:
    # SessionRepository 专门负责操作 sessions 表。
    # 这一层的职责是：把“如何查会话、如何创建会话”这种最小数据库操作
    # 从上层 service 里拆出来，避免业务逻辑直接到处写 ORM 细节。
    def __init__(self, db_session: Session) -> None:
        # db_session 由外部传入，通常来自 FastAPI 的依赖注入。
        # repository 自己不负责创建数据库 session，只负责使用它。
        self._db_session = db_session

    def get(self, session_id: str) -> SessionRecord | None:
        # 按主键查询一条 session 记录。
        # 如果存在，就返回对应的 SessionRecord；
        # 如果不存在，就返回 None。
        return self._db_session.get(SessionRecord, session_id)

    def get_or_create(self, session_id: str, *, title: str = "New Session") -> SessionRecord:
        # 先尝试查这条 session 是否已经存在。
        record = self.get(session_id)
        if record is not None:
            # 如果已经存在，直接复用，不再重复创建。
            return record

        # 如果不存在，就创建一条新的会话记录。
        # 当前默认标题是 "New Session"，状态默认设置为 active。
        record = SessionRecord(id=session_id, title=title, status="active")
        # 把新记录加入当前数据库 session。
        self._db_session.add(record)
        # flush() 会先把这条记录同步到当前事务里，
        # 这样后续同一轮请求的其他逻辑就能继续使用这条新会话。
        # 这里仍然不是最终 commit，真正提交通常由更上层 service 统一控制。
        self._db_session.flush()
        # 返回查到或刚创建的会话记录对象。
        return record
