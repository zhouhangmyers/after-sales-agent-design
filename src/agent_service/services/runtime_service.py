from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel

from agent_runtime import AgentRuntime, LoggingMiddleware, ToolResult, get_logger


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
    return city_map.get(args.city_code.lower(), "Unknown city")


@dataclass(slots=True, frozen=True)
class ParsedToolRequest:
    action: str
    arguments: dict[str, Any]


@dataclass(slots=True, frozen=True)
class RuntimeExecution:
    request: ParsedToolRequest
    result: ToolResult


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
        name="get_city",
        description="Get a city by city code.",
        args_model=CityArgs,
        handler=city_handler,
    )
    return runtime


class RuntimeService:
    def __init__(self, runtime: AgentRuntime | None = None) -> None:
        self._runtime = runtime or build_runtime()

    def parse_message(self, message: str) -> ParsedToolRequest | None:
        if "add" in message:
            a_match = re.search(r"a\s*=\s*(-?\d+)", message)
            b_match = re.search(r"b\s*=\s*(-?\d+)", message)
            if a_match and b_match:
                return ParsedToolRequest(
                    action="add",
                    arguments={
                        "a": int(a_match.group(1)),
                        "b": int(b_match.group(1)),
                    },
                )

        if "get_city" in message or "city_code" in message:
            city_match = re.search(r"city_code\s*=\s*([a-zA-Z]+)", message)
            if city_match:
                return ParsedToolRequest(
                    action="get_city",
                    arguments={"city_code": city_match.group(1).lower()},
                )

        return None

    def execute_from_message(self, message: str, *, request_id: str) -> RuntimeExecution | None:
        parsed_request = self.parse_message(message)
        if parsed_request is None:
            return None

        result = self._runtime.execute(
            parsed_request.action,
            parsed_request.arguments,
            request_id=request_id,
            metadata={"source": "chat_service"},
        )
        return RuntimeExecution(request=parsed_request, result=result)
