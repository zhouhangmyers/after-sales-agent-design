from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from .base import Base


def _build_connect_args(database_url: str) -> dict[str, object]:
    if database_url.startswith("sqlite"):
        return {"check_same_thread": False}
    return {}


class DatabaseManager:
    def __init__(self, database_url: str) -> None:
        self.database_url = database_url
        # 根据 database_url 创建数据库引擎（engine）。
        # 你可以把 engine 理解成“程序访问数据库的总入口”：
        # 后面建表、创建 session、执行 SQLAlchemy 操作，都会基于这个 engine。
        #
        # database_url 决定连接哪个数据库，例如：
        # - sqlite+pysqlite:///./agent_platform.db
        # - postgresql+psycopg://user:password@host:5432/dbname
        #
        # future=True 表示使用 SQLAlchemy 2.x 风格行为。
        # connect_args 用来给不同数据库补额外连接参数；
        # 当前项目里主要是对 SQLite 做特殊处理。
        self.engine = create_engine(
            database_url,
            future=True,
            connect_args=_build_connect_args(database_url),
        )
        # 基于 engine 创建一个 session factory（session 工厂）。
        # 后面每次需要数据库操作会话时，都统一从这里创建新的 Session。
        #
        # bind=self.engine 表示：工厂创建出来的 session 都绑定到当前数据库引擎。
        # class_=Session 表示：创建出来的是 SQLAlchemy 的 Session 类型。
        #
        # 下面几个参数是在控制 session 的行为：
        # - autoflush=False：不会在查询前自动把内存中的改动刷到数据库，行为更可控
        # - autocommit=False：不会自动提交事务，需要代码显式 commit
        # - expire_on_commit=False：提交后对象属性不会立刻失效，后续访问更直观
        self._session_factory = sessionmaker(
            bind=self.engine,
            class_=Session,
            autoflush=False,
            autocommit=False,
            expire_on_commit=False,
        )

    def create_schema(self) -> None:
        # 按照 Base.metadata 里收集到的 ORM 表结构定义，在 self.engine 对应的数据库里建表。
        # Base.metadata 负责“要建哪些表”，self.engine 负责“去哪个数据库执行建表”。
        # 改数据库中如果要建的表已存在，便跳过创建，而create_all只能补表，不能正确处理表结构变更
        Base.metadata.create_all(self.engine)

    def session(self) -> Session:
        # 调用 session factory，返回一个新的数据库 Session。
        # 这里必须加括号；不加括号返回的是工厂对象本身，不是可直接操作数据库的 session。
        return self._session_factory()

    def dispose(self) -> None:
        self.engine.dispose()
