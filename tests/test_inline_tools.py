from __future__ import annotations

from agent_service.tools.inline import InlineToolExecutor
from tests.sample_tools import build_sample_tool_policies, build_sample_tools


def test_inline_tool_executor_executes_registered_tool() -> None:
    executor = InlineToolExecutor(
        tools=build_sample_tools(),
        tool_policies=build_sample_tool_policies(),
    )

    execution = executor.execute(
        tool_name="add",
        tool_arguments={"a": 2, "b": 3},
        tool_call_id="call_add",
        request_id="req-1",
    )

    assert execution.request.action == "add"
    assert execution.result.success is True
    assert execution.result.result == 5


def test_inline_tool_executor_returns_unknown_tool_error() -> None:
    executor = InlineToolExecutor(
        tools=build_sample_tools(),
        tool_policies=build_sample_tool_policies(),
    )

    execution = executor.execute(
        tool_name="missing",
        tool_arguments={},
        tool_call_id="call_missing",
        request_id="req-2",
    )

    assert execution.result.success is False
    assert execution.result.error is not None
    assert execution.result.error.code == "unknown_tool"
