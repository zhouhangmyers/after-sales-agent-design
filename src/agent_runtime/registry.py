#__future__ = 提前开启某些更现代的 Python 行为；这里专门是为类型标注服务的。
from __future__ import annotations

# dataclass 适合这种“主要用来装数据”的定义对象。
from dataclasses import dataclass
# Any 表示返回值先不做严格限制；Callable 用来描述 handler 的函数形状。
from typing import Any, Callable

# BaseModel 约束工具参数必须走 Pydantic 模型体系。
from pydantic import BaseModel

# ToolHandler 表示“工具真正执行的函数”的形状：
# 接收一个经过 Pydantic 校验的参数模型对象，返回任意结果。
ToolHandler = Callable[[BaseModel], Any]

# dataclass 让这种“主要装数据的类”少写样板代码；
# frozen=True 表示创建后字段不允许随便改，适合工具定义这类元信息对象。
@dataclass(frozen=True)
class ToolDefinition:
    # 工具名，例如 "add"。
    name: str
    # 给人看的工具描述，也便于后续扩展更多元信息。
    description: str
    # 这里存的是模型类本身，例如 AddArgs，而不是 AddArgs(...) 实例。
    args_model: type[BaseModel]
    # handler 是真正干活的函数，例如 add_handler。
    handler: ToolHandler


class ToolRegistry:
    def __init__(self) -> None:
        # 内部用字典保存所有已注册工具：
        # key 是工具名，value 是完整工具定义。
        # 必须赋值，实例上才会真正创建 _tools 属性。
        self._tools: dict[str, ToolDefinition] = {} #普通python类无需Field，Field是给pydantic用的，也就是类继承了BaseModel如果定义字典的话，需要Filed(default_factory=dict)

    def register(self, tool: ToolDefinition) -> None:
        # 同名工具不允许重复注册，否则行为会变得不确定。
        if tool.name in self._tools:
            raise ValueError(f"tool already registered: {tool.name}")
        self._tools[tool.name] = tool

    def get(self, name: str) -> ToolDefinition | None:
        # 按名字查工具；找不到时返回 None，交给 runtime 决定如何报错。
        return self._tools.get(name)

    def names(self) -> list[str]:
        # 返回全部工具名，排序后更稳定，便于日志、测试和错误提示。
        # sorted(dict) 默认排的是字典的 key，不是整条键值对。
        return sorted(self._tools)
