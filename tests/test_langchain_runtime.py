from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import pytest
from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage, ToolMessage
from langchain_core.outputs import ChatGenerationChunk
from pydantic import BaseModel

from agent_core.contracts.agent_definition import AgentDefinition
from agent_core.contracts.run_events import (
    OutputDeltaEvent,
    RunCompletedEvent,
    RunEvent,
)
from agent_core.contracts.run_state import ActorContext, AgentRunResult
from agent_core.contracts.tool_spec import (
    ApprovalRequirement,
    CallableApprovalPolicy,
    ToolContext,
    ToolSpec,
)
from agent_runtime.langchain.checkpoint.local_memory import (
    InMemoryStateStore,
)
from agent_runtime.langchain.runtime import LangChainAgentRuntime
from tests.fake_chat_models import DeterministicToolCallingChatModel


def add_handler(payload: dict[str, Any], context: ToolContext) -> int:
    del context
    return int(payload["a"]) + int(payload["b"])


def multiply_handler(payload: dict[str, Any], context: ToolContext) -> int:
    del context
    return int(payload["a"]) * int(payload["b"])


def approval_for_multiply(payload: dict[str, Any]) -> ApprovalRequirement | None:
    return ApprovalRequirement(
        reason="乘法工具需要人工审批。",
        risk_level="medium",
        display_payload={"a": payload["a"], "b": payload["b"]},
    )


def build_math_agent_definition() -> AgentDefinition:
    return AgentDefinition(
        capability_id="math_tools",
        system_prompt="你是一个测试数学助手。优先按用户请求调用工具。",
        tools=(
            ToolSpec(
                name="add",
                description="Add two integers.",
                args_schema=AddArgs,
                handler=add_handler,
            ),
            ToolSpec(
                name="multiply",
                description="Multiply two integers.",
                args_schema=MultiplyArgs,
                handler=multiply_handler,
                approval_policy=CallableApprovalPolicy(approval_for_multiply),
            ),
        ),
    )


class AddArgs(BaseModel):
    a: int
    b: int


class MultiplyArgs(BaseModel):
    a: int
    b: int


class MathRoutingChatModel(DeterministicToolCallingChatModel):
    def respond_from_tool_message(self, message: ToolMessage) -> AIMessage:
        artifact = message.artifact if isinstance(message.artifact, dict) else {}
        result = artifact.get("result")
        tool_name = str(artifact.get("action") or message.name or "tool")
        if artifact.get("success") is False:
            error = artifact.get("error")
            error_message = (
                error.get("message")
                if isinstance(error, dict) and isinstance(error.get("message"), str)
                else "unknown error"
            )
            if isinstance(error, dict) and error.get("code") == "approval_rejected":
                return AIMessage(content=error_message)
            return AIMessage(content=f"工具 `{tool_name}` 执行失败：{error_message}。")
        return AIMessage(
            content=f"我已经调用 `{tool_name}` 完成处理，结果是 {result}。"
        )

    def plan_from_human_message(
        self,
        message: HumanMessage,
        *,
        tools: list[Any],
    ) -> AIMessage:
        content = message.content
        assert isinstance(content, str)
        available = {tool.name for tool in tools}
        if "multiply" in content and "multiply" in available:
            arguments = self.extract_number_arguments(content)
            if arguments is not None:
                return self.tool_call_message(
                    "multiply",
                    arguments,
                    tool_call_id="call_multiply",
                )
        if "add" in content and "add" in available:
            arguments = self.extract_number_arguments(content)
            if arguments is not None:
                return self.tool_call_message(
                    "add",
                    arguments,
                    tool_call_id="call_add",
                )
        return AIMessage(content=f"直接回复：{content}")


class StreamingEchoChatModel(MathRoutingChatModel):
    async def _astream(
        self,
        messages: list[Any],
        stop: list[str] | None = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> AsyncIterator[ChatGenerationChunk]:
        del stop, run_manager, kwargs
        human_message = self.latest_human_message(messages)
        content = human_message.content if human_message is not None else ""
        assert isinstance(content, str)
        for delta in ("直接", "回复：", content):
            yield ChatGenerationChunk(message=AIMessageChunk(content=delta))


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
async def test_langchain_runtime_executes_tool_and_completes() -> None:
    runtime = LangChainAgentRuntime(
        model=MathRoutingChatModel(),
        state_store=InMemoryStateStore(),
        max_steps=4,
    )

    events, result = await collect_result(
        runtime.stream_run(
            definition=build_math_agent_definition(),
            message="please add a=2 b=3",
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
    assert result.output == "我已经调用 `add` 完成处理，结果是 5。"


@pytest.mark.asyncio
async def test_langchain_runtime_streams_output_deltas_before_completion() -> None:
    runtime = LangChainAgentRuntime(
        model=StreamingEchoChatModel(),
        state_store=InMemoryStateStore(),
        max_steps=4,
    )

    events, result = await collect_result(
        runtime.stream_run(
            definition=build_math_agent_definition(),
            message="hello",
            session_id=None,
            actor=ActorContext(),
        )
    )

    deltas = [event.delta for event in events if isinstance(event, OutputDeltaEvent)]
    assert deltas == ["直接", "回复：", "hello"]
    assert isinstance(events[-1], RunCompletedEvent)
    assert result.status == "completed"
    assert result.output == "直接回复：hello"


@pytest.mark.asyncio
async def test_langchain_runtime_pauses_then_resumes_approved_action() -> None:
    runtime = LangChainAgentRuntime(
        model=MathRoutingChatModel(),
        state_store=InMemoryStateStore(),
        max_steps=4,
    )
    definition = build_math_agent_definition()

    first_events, first_result = await collect_result(
        runtime.stream_run(
            definition=definition,
            message="please multiply a=2 b=3",
            session_id="session-1",
            actor=ActorContext(),
        )
    )

    assert [type(event).__name__ for event in first_events] == [
        "RunStartedEvent",
        "ActionRequiredEvent",
        "RunCompletedEvent",
    ]
    assert first_result.status == "awaiting_action"
    assert first_result.pending_action is not None
    assert first_result.pending_action.action_id == "call_multiply"

    state = await runtime.get_state(run_id=first_result.run_id, definition=definition)
    assert state.status == "awaiting_action"
    assert state.pending_action is not None
    assert state.metadata["usage"]["total_tokens"] > 0

    second_events, second_result = await collect_result(
        runtime.stream_action(
            definition=definition,
            run_id=first_result.run_id,
            action_id="call_multiply",
            decision="approved",
            actor=ActorContext(),
        )
    )

    assert [type(event).__name__ for event in second_events] == [
        "RunStartedEvent",
        "ActionStartedEvent",
        "ActionCompletedEvent",
        "OutputDeltaEvent",
        "RunCompletedEvent",
    ]
    assert second_result.status == "completed"
    assert second_result.output == "我已经调用 `multiply` 完成处理，结果是 6。"


@pytest.mark.asyncio
async def test_langchain_runtime_rejected_action_returns_completed_message() -> None:
    runtime = LangChainAgentRuntime(
        model=MathRoutingChatModel(),
        state_store=InMemoryStateStore(),
        max_steps=4,
    )
    definition = build_math_agent_definition()

    _, pending = await collect_result(
        runtime.stream_run(
            definition=definition,
            message="please multiply a=2 b=3",
            session_id="session-2",
            actor=ActorContext(),
        )
    )

    _, rejected = await collect_result(
        runtime.stream_action(
            definition=definition,
            run_id=pending.run_id,
            action_id="call_multiply",
            decision="rejected",
            actor=ActorContext(),
        )
    )

    assert rejected.status == "completed"
    assert rejected.output == "人工审批已拒绝，本次不会执行工具 `multiply`。"


@pytest.mark.asyncio
async def test_langchain_runtime_supports_multiple_pending_runs_per_session() -> None:
    runtime = LangChainAgentRuntime(
        model=MathRoutingChatModel(),
        state_store=InMemoryStateStore(),
        max_steps=4,
    )
    definition = build_math_agent_definition()

    _, first = await collect_result(
        runtime.stream_run(
            definition=definition,
            message="please multiply a=2 b=3",
            session_id="session-3",
            actor=ActorContext(),
        )
    )
    _, second = await collect_result(
        runtime.stream_run(
            definition=definition,
            message="please add a=2 b=3",
            session_id="session-3",
            actor=ActorContext(),
        )
    )

    assert first.status == "awaiting_action"
    assert second.status == "completed"
    assert second.session_id == first.session_id
    assert second.run_id != first.run_id
