from __future__ import annotations

from agent_service.tools.catalog import build_default_tool_policies, build_default_tools
from agent_service.tools.inline import InlineToolExecutor


def build_sample_tools():
    return build_default_tools()


def build_sample_tool_policies():
    return build_default_tool_policies()


def build_sample_tool_executor() -> InlineToolExecutor:
    return InlineToolExecutor(
        tools=build_sample_tools(),
        tool_policies=build_sample_tool_policies(),
    )
