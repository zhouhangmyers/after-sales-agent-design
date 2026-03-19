from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter
from typing import Any

from pydantic import BaseModel

from agent_runtime import AgentRuntime, LoggingMiddleware, ToolResult, get_logger
from agent_service.services.planners import ToolObservation, ToolSchema


class AddArgs(BaseModel):
    a: int
    b: int


class MultiplyArgs(BaseModel):
    a: int
    b: int


class DivideArgs(BaseModel):
    a: int
    b: int


class CityArgs(BaseModel):
    city_code: str


def add_handler(args: AddArgs) -> int:
    return args.a + args.b


def multiply_handler(args: MultiplyArgs) -> int:
    return args.a * args.b


def divide_handler(args: DivideArgs) -> float:
    if args.b == 0:
        raise ValueError("division by zero is not allowed")
    return args.a / args.b


def city_handler(args: CityArgs) -> str:
    city_map = {
        "sz": "Suzhou",
        "sh": "Shanghai",
        "hz": "Hangzhou",
    }
    return city_map.get(args.city_code.lower(), "Unknown city")


@dataclass(slots=True, frozen=True)
class ParsedToolRequest:
    action: str
    arguments: dict[str, Any]


@dataclass(slots=True, frozen=True)
class RuntimeExecution:
    request: ParsedToolRequest
    result: ToolResult
    latency_ms: float


def build_runtime() -> AgentRuntime:
    logger = get_logger("agent_service.runtime")
    runtime = AgentRuntime(middlewares=[LoggingMiddleware(logger)])
    runtime.register_tool(
        name="add",
        description="Add two integers.",
        args_model=AddArgs,
        handler=add_handler,
    )
    runtime.register_tool(
        name="multiply",
        description="Multiply two integers.",
        args_model=MultiplyArgs,
        handler=multiply_handler,
    )
    runtime.register_tool(
        name="divide",
        description="Divide one integer by another integer.",
        args_model=DivideArgs,
        handler=divide_handler,
    )
    runtime.register_tool(
        name="get_city",
        description="Get a city by city code.",
        args_model=CityArgs,
        handler=city_handler,
    )
    return runtime


class RuntimeService:
    # 这一层现在只干执行相关的事情：
    # 1. 把已注册工具整理成 schema 给 planner 看
    # 2. 真正调用底层 agent_runtime 去执行工具
    # 3. 把工具结果翻译成 observation，供下一轮规划使用
    def __init__(self, *, runtime: AgentRuntime | None = None) -> None:
        self._runtime = runtime or build_runtime()

    def available_tool_schemas(self, allowed_tools: tuple[str, ...] | None = None) -> list[ToolSchema]:
        allowed = set(allowed_tools or ())
        definitions = [
            tool
            for tool in self._runtime.registry.definitions()
            if not allowed or tool.name in allowed
        ]
        return [
            ToolSchema(
                name=tool.name,
                description=tool.description,
                arguments_json_schema=tool.args_model.model_json_schema(),
            )
            for tool in definitions
        ]

    def execute_action(
        self,
        action: str,
        arguments: dict[str, Any],
        *,
        request_id: str,
        source: str,
    ) -> RuntimeExecution:
        start = perf_counter()
        result = self._runtime.execute(
            action,
            arguments,
            request_id=request_id,
            metadata={"source": source},
        )
        return RuntimeExecution(
            request=ParsedToolRequest(action=action, arguments=arguments),
            result=result,
            latency_ms=(perf_counter() - start) * 1000,
        )

    def build_observation(self, execution: RuntimeExecution) -> ToolObservation:
        error_message = execution.result.error.message if execution.result.error is not None else None
        return ToolObservation(
            tool_name=execution.request.action,
            arguments=execution.request.arguments,
            success=execution.result.success,
            result=execution.result.result,
            error_message=error_message,
        )
