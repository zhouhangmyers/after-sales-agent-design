from __future__ import annotations

from langchain_core.tools import tool
from pydantic import BaseModel

from agent_service.tools.models import ToolPolicy


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


@tool("add", args_schema=AddArgs, description="Add two integers.")
def add_tool(a: int, b: int) -> int:
    return a + b


@tool("multiply", args_schema=MultiplyArgs, description="Multiply two integers.")
def multiply_tool(a: int, b: int) -> int:
    return a * b


@tool("divide", args_schema=DivideArgs, description="Divide one integer by another integer.")
def divide_tool(a: int, b: int) -> float:
    if b == 0:
        raise ValueError("division by zero is not allowed")
    return a / b


@tool("get_city", args_schema=CityArgs, description="Get a city by city code.")
def get_city_tool(city_code: str) -> str:
    city_map = {
        "sz": "Suzhou",
        "sh": "Shanghai",
        "hz": "Hangzhou",
    }
    return city_map.get(city_code.lower(), "Unknown city")


def build_sample_tools():
    return [add_tool, multiply_tool, divide_tool, get_city_tool]


def build_sample_tool_policies():
    return {
        "multiply": ToolPolicy(
            tool_name="multiply",
            approval_required=True,
            risk_level="medium",
        )
    }

