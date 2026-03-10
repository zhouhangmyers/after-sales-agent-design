from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from agent_runtime import AgentRuntime, LoggingMiddleware, get_logger


class AddArgs(BaseModel):
    a: int
    b: int


class CityArgs(BaseModel):
    city_code: str


def add_handler(args: AddArgs) -> int:
    return args.a + args.b


def city_handler(args: CityArgs) -> str:
    city_map = {
        "sz": "Suzhou",
        "sh": "Shanghai",
        "hz": "Hangzhou",
    }
    return city_map.get(args.city_code, "Unknown city")


def build_runtime() -> AgentRuntime:
    logger = get_logger("week1.runtime_demo")
    runtime = AgentRuntime(middlewares=[LoggingMiddleware(logger)])
    runtime.register_tool(
        name="add",
        description="Add two integers.",
        args_model=AddArgs,
        handler=add_handler,
    )
    runtime.register_tool(
        name="get_city",
        description="Get a city by city code.",
        args_model=CityArgs,
        handler=city_handler,
    )
    return runtime


def main() -> None:
    runtime = build_runtime()

    cases: list[tuple[str, dict[str, Any], str]] = [
        ("add", {"a": 3, "b": 7}, "req-add-1"),
        ("get_city", {"city_code": "sz"}, "req-city-1"),
        ("add", {"a": "bad", "b": 2}, "req-bad-1"),
        ("missing_tool", {"value": 1}, "req-missing-1"),
    ]

    for action, arguments, request_id in cases:
        result = runtime.execute(action, arguments, request_id=request_id)
        print(result.model_dump()) #打印普通的python字典

# 只有在直接运行当前文件时，才执行 main()；
# 如果这个文件是被别的模块导入的，就不会自动执行。
if __name__ == "__main__":
    main()