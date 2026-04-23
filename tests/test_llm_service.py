from __future__ import annotations

import asyncio
import sys
import types

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.runnables import RunnableConfig
from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_none,
)

import agent_service.llm.bound_client as bound_client_module
from agent_service.llm import LLMService, dump_payload, message_payload
from agent_service.llm.bound_client import BoundChatClient, build_chat_client
from agent_service.llm.payloads import token_usage_from_texts


class StubChatClient:
    provider = "test"
    model = "deepseek-chat"

    def __init__(self, responses: list[AIMessage | Exception]) -> None:
        self._responses = list(responses)
        self.calls = 0

    async def ainvoke(  # type: ignore[no-untyped-def]
        self,
        messages,
        tools,
        config: RunnableConfig | None = None,
    ) -> AIMessage:
        self.calls += 1
        if not self._responses:
            raise AssertionError("no more responses configured")
        item = self._responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


class SlowChatClient:
    provider = "test"
    model = "deepseek-chat"

    async def ainvoke(self, messages, tools, config: RunnableConfig | None = None) -> AIMessage:  # type: ignore[no-untyped-def]
        await asyncio.sleep(0.06)
        return AIMessage(content="slow done")


@pytest.mark.asyncio
async def test_generate_turn_does_not_retry_non_timeout_errors() -> None:
    client = StubChatClient([ValueError("bad request")])
    service = LLMService(
        client=client,
        system_prompt="你是一个测试助手。",
        timeout_seconds=0,
        max_retries=3,
    )

    turn = await service.generate_turn(
        conversation_id="conv-non-retry",
        messages=[HumanMessage(content="hello")],
        tools=[],
    )

    assert client.calls == 1
    assert turn.trace.success is False
    assert turn.trace.attempts == 1
    assert turn.trace.error_message == "bad request"
    assert "模型调用失败" in turn.assistant_message.content


@pytest.mark.asyncio
async def test_generate_turn_retries_timeouts_and_tracks_attempts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def build_no_wait_retrying(max_retries: int) -> AsyncRetrying:
        return AsyncRetrying(
            stop=stop_after_attempt(max(1, max_retries + 1)),
            wait=wait_none(),
            retry=retry_if_exception_type((TimeoutError, asyncio.TimeoutError)),
            reraise=True,
        )

    monkeypatch.setattr(bound_client_module, "_build_retrying", build_no_wait_retrying)

    client = StubChatClient([TimeoutError(), AIMessage(content="done")])
    service = LLMService(
        client=client,
        system_prompt="你是一个测试助手。",
        timeout_seconds=0,
        max_retries=2,
    )

    turn = await service.generate_turn(
        conversation_id="conv-timeout-retry",
        messages=[HumanMessage(content="hello")],
        tools=[],
    )

    assert client.calls == 2
    assert turn.trace.success is True
    assert turn.trace.attempts == 2
    assert turn.assistant_message.content == "done"


@pytest.mark.asyncio
async def test_generate_turn_uses_tiktoken_for_usage_fallback() -> None:
    client = StubChatClient([AIMessage(content="你好，世界")])
    service = LLMService(
        client=client,
        system_prompt="你是一个测试助手。",
        timeout_seconds=0,
        max_retries=0,
    )

    turn = await service.generate_turn(
        conversation_id="conv-token-fallback",
        messages=[HumanMessage(content="你好")],
        tools=[],
    )

    expected_usage = token_usage_from_texts(
        dump_payload(turn.trace.request_payload),
        dump_payload(message_payload(turn.assistant_message)),
        model=client.model,
    )
    assert turn.trace.success is True
    assert turn.trace.usage == expected_usage
    assert turn.trace.usage.total_tokens > 0


@pytest.mark.asyncio
async def test_generate_turn_marks_timeout_failures() -> None:
    service = LLMService(
        client=SlowChatClient(),
        system_prompt="你是一个测试助手。",
        timeout_seconds=0.01,
        max_retries=0,
    )

    turn = await service.generate_turn(
        conversation_id="conv-timeout",
        messages=[HumanMessage(content="hello")],
        tools=[],
    )

    assert turn.trace.success is False
    assert "timed out" in (turn.trace.error_message or "")


@pytest.mark.asyncio
async def test_generate_turn_includes_system_prompt_in_request_payload() -> None:
    client = StubChatClient([AIMessage(content="done")])
    service = LLMService(
        client=client,
        system_prompt="你是一个测试助手。",
        timeout_seconds=0,
        max_retries=0,
    )

    turn = await service.generate_turn(
        conversation_id="conv-system-prompt",
        messages=[HumanMessage(content="hello")],
        tools=[],
    )

    request_messages = turn.trace.request_payload["messages"]
    assert "system" in dump_payload(request_messages[0])
    assert "你是一个测试助手。" in dump_payload(request_messages[0])


def test_build_chat_client_constructs_chatdeepseek_directly(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    recorded: dict[str, object] = {}

    class RecordingBoundModel:
        async def ainvoke(self, messages, config: RunnableConfig | None = None):  # pragma: no cover
            return AIMessage(content="ok")

    class RecordingChatDeepSeek:
        def __init__(self, **kwargs) -> None:  # type: ignore[no-untyped-def]
            recorded.update(kwargs)

        def bind_tools(self, tools):  # type: ignore[no-untyped-def]
            return RecordingBoundModel()

        async def ainvoke(self, messages, config: RunnableConfig | None = None):  # pragma: no cover
            return AIMessage(content="ok")

    fake_module = types.ModuleType("langchain_deepseek")
    fake_module.ChatDeepSeek = RecordingChatDeepSeek
    monkeypatch.setitem(sys.modules, "langchain_deepseek", fake_module)

    client = build_chat_client(
        llm_provider="deepseek",
        llm_model="deepseek-reasoner",
        llm_timeout_seconds=7.5,
        llm_max_retries=3,
        deepseek_api_key="sk-test",
    )

    assert isinstance(client, BoundChatClient)
    assert client.provider == "deepseek"
    assert client.model == "deepseek-reasoner"
    assert recorded == {
        "api_key": "sk-test",
        "model": "deepseek-reasoner",
        "temperature": 0,
        "streaming": True,
        "timeout": 7.5,
        "max_retries": 3,
    }


def test_bound_chat_client_caps_bound_model_cache() -> None:
    class FakeBoundModel:
        async def ainvoke(self, messages, config=None):  # pragma: no cover
            return AIMessage(content="ok")

    class FakeChatModel:
        def __init__(self) -> None:
            self.bound_keys: list[tuple[str, ...]] = []

        def bind_tools(self, tools):  # type: ignore[no-untyped-def]
            self.bound_keys.append(tuple(tool.name for tool in tools))
            return FakeBoundModel()

    class FakeTool:
        def __init__(self, name: str) -> None:
            self.name = name

    client = BoundChatClient(
        chat_model=FakeChatModel(),
        provider="deepseek",
        model="deepseek-chat",
        bound_model_cache_size=2,
    )

    client._get_bound_model([FakeTool("alpha")])  # type: ignore[arg-type]
    client._get_bound_model([FakeTool("beta")])  # type: ignore[arg-type]
    client._get_bound_model([FakeTool("gamma")])  # type: ignore[arg-type]

    assert list(client._bound_models) == [("beta",), ("gamma",)]  # type: ignore[attr-defined]
