from __future__ import annotations

from sqlalchemy.orm import Session

from agent_service.db.models import MessageRecord


class MessageRepository:
    # 这个 repository 专门负责操作 messages 表。
    # 当前主要用来把用户消息和助手回复写入数据库。
    def __init__(self, db_session: Session) -> None:
        # 接收外部传进来的数据库 session，后面所有消息写入都基于这个 session 完成。
        self._db_session = db_session

    def create(
        self,
        *,
        message_id: str,
        session_id: str,
        role: str,
        content: str,
        status: str = "completed",
    ) -> MessageRecord:
        # 根据传入参数创建一条消息 ORM 记录。
        # role 一般会是 user / assistant，用来区分这条消息是谁发出的。
        record = MessageRecord(
            id=message_id,
            session_id=session_id,
            role=role,
            content=content,
            status=status,
        )
        # 把消息记录加入当前数据库 session。
        self._db_session.add(record)
        # 先把这次写入同步到当前事务中，但不在这里直接 commit。
        # commit 仍然交给更上层的 service 统一控制。
        self._db_session.flush()
        # 返回创建好的消息记录对象。
        return record
