from __future__ import annotations

import sys
from collections.abc import AsyncIterator
from types import ModuleType
from typing import Any

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.tools import StructuredTool
from pydantic import BaseModel

from agent_core.contracts.agent_definition import AgentDefinition
from agent_core.contracts.run_events import RunCompletedEvent, RunEvent
from agent_core.contracts.run_state import ActorContext, AgentRunResult
from agent_integrations.mcp import MCPToolProvider
from agent_runtime.langchain.checkpoint.local_memory import (
    InMemoryStateStore,
)
from agent_runtime.langchain.runtime import LangChainAgentRuntime
from app_api.settings import AppSettings, MCPServerConfig
from tests.fake_chat_models import DeterministicToolCallingChatModel


class WeatherArgs(BaseModel):
    location: str


async def get_weather(location: str) -> dict[str, str]:
    return {"location": location, "forecast": "sunny"}


def install_fake_mcp_adapter(monkeypatch: pytest.MonkeyPatch) -> None:
    package = ModuleType("langchain_mcp_adapters")
    package.__path__ = []
    client_module = ModuleType("langchain_mcp_adapters.client")

    class FakeMultiServerMCPClient:
        def __init__(self, server_configs: dict[str, dict[str, object]]) -> None:
            self.server_configs = server_configs

        async def get_tools(self) -> list[StructuredTool]:
            del self
            return [
                StructuredTool.from_function(
                    coroutine=get_weather,
                    name="get_weather",
                    description="Get weather for a location.",
                    args_schema=WeatherArgs,
                )
            ]

    client_module.__dict__["MultiServerMCPClient"] = FakeMultiServerMCPClient
    monkeypatch.setitem(sys.modules, "langchain_mcp_adapters", package)
    monkeypatch.setitem(sys.modules, "langchain_mcp_adapters.client", client_module)


class MCPRoutingChatModel(DeterministicToolCallingChatModel):
    def plan_from_human_message(
        self,
        message: HumanMessage,
        *,
        tools: list[Any],
    ) -> AIMessage:
        del message
        available = {tool.name for tool in tools}
        assert "mcp_weather_get_weather" in available
        return self.tool_call_message(
            "mcp_weather_get_weather",
            {"location": "Shanghai"},
        )

    def respond_from_tool_message(self, message: ToolMessage) -> AIMessage:
        artifact = message.artifact if isinstance(message.artifact, dict) else {}
        result = artifact.get("result")
        assert isinstance(result, dict)
        return AIMessage(content=f"{result['location']} weather is {result['forecast']}.")


async def collect_result(stream: AsyncIterator[RunEvent]) -> tuple[list[RunEvent], AgentRunResult]:
    events: list[RunEvent] = []
    try:
        async for event in stream:
            events.append(event)
            if isinstance(event, RunCompletedEvent):
                return events, event.result
    finally:
        close_stream = getattr(stream, "aclose", None)
        if callable(close_stream):
            await close_stream()
    raise AssertionError("stream finished without RunCompletedEvent")


@pytest.mark.asyncio
async def test_mcp_tool_provider_namespaces_loaded_tools(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_fake_mcp_adapter(monkeypatch)
    settings = AppSettings(
        app_env="test",
        mcp_servers={
            "weather": MCPServerConfig(
                transport="http",
                url="http://localhost:8000/mcp",
            )
        },
    )

    tools = await MCPToolProvider(
        {
            name: config.model_dump(mode="json", exclude_none=True, exclude_defaults=True)
            for name, config in settings.mcp_servers.items()
        }
    ).load_tools()

    assert len(tools) == 1
    assert tools[0].name == "mcp_weather_get_weather"
    assert tools[0].source == "mcp"
    assert tools[0].source_id == "weather"
    assert tools[0].args_schema is WeatherArgs


@pytest.mark.asyncio
async def test_langchain_runtime_executes_mcp_tool(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_fake_mcp_adapter(monkeypatch)
    tools = await MCPToolProvider(
        {
            "weather": {
                "transport": "http",
                "url": "http://localhost:8000/mcp",
            }
        }
    ).load_tools()
    definition = AgentDefinition(
        capability_id="weather_agent",
        name="Weather Agent",
        description="Test MCP-backed weather agent.",
        system_prompt="Use the weather tool.",
        tools=tools,
    )
    runtime = LangChainAgentRuntime(
        model=MCPRoutingChatModel(),
        state_store=InMemoryStateStore(),
        max_steps=4,
    )

    events, result = await collect_result(
        runtime.stream_run(
            definition=definition,
            message="weather please",
            session_id=None,
            actor=ActorContext(),
        )
    )

    assert [type(event).__name__ for event in events] == [
        "RunStartedEvent",
        "ActionStartedEvent",
        "ActionCompletedEvent",
        "OutputDeltaEvent",
        "RunCompletedEvent",
    ]
    assert result.status == "completed"
    assert result.output == "Shanghai weather is sunny."
