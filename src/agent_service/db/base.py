from __future__ import annotations

from sqlalchemy.orm import DeclarativeBase


# ORM（Object Relational Mapping，对象关系映射）可以把数据库里的表，
# 映射成 Python 里的类，把表中的一行数据映射成一个对象。
# 所有 SQLAlchemy ORM 模型都继承这个基类，
# 这样项目里的表结构就会统一挂在 Base.metadata 上，后续才能集中建表和管理。
class Base(DeclarativeBase):
    pass
