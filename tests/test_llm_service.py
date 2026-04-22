from __future__ import annotations

import asyncio
import sys
import types

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.runnables import RunnableConfig
from pydantic import SecretStr
from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_none,
)

from agent_service.config import Settings
from agent_service.llm import LLMService, dump_payload, message_payload
from agent_service.llm.bound_client import BoundChatClient
from agent_service.llm.payloads import token_usage_from_texts
from agent_service.llm.prompts import resolve_prompt
from agent_service.llm.service import build_llm_service


class StubChatClient:
    provider = "test"
    model = "deepseek-chat"

    def __init__(self, responses: list[AIMessage | Exception]) -> None:
        self._responses = list(responses)
        self.calls = 0

    def invoke(  # pragma: no cover - protocol compatibility only
        self,
        messages,
        tools,
        config: RunnableConfig | None = None,
    ) -> AIMessage:
        raise AssertionError("sync invoke should not be used")

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


class NoWaitLLMService(LLMService):
    def _build_retrying(self) -> AsyncRetrying:
        return AsyncRetrying(
            stop=stop_after_attempt(max(1, self._max_retries + 1)),
            wait=wait_none(),
            retry=retry_if_exception_type((TimeoutError,)),
            reraise=True,
        )


class SlowChatClient:
    provider = "test"
    model = "deepseek-chat"

    def invoke(self, messages, tools, config: RunnableConfig | None = None) -> AIMessage:  # pragma: no cover
        raise AssertionError("sync invoke should not be used")

    async def ainvoke(self, messages, tools, config: RunnableConfig | None = None) -> AIMessage:  # type: ignore[no-untyped-def]
        await asyncio.sleep(0.06)
        return AIMessage(content="slow done")


@pytest.mark.asyncio
async def test_generate_turn_does_not_retry_non_timeout_errors() -> None:
    client = StubChatClient([ValueError("bad request")])
    service = LLMService(
        client=client,
        prompt_name="conversation-tools",
        prompt_version="v1",
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
async def test_generate_turn_retries_timeouts_and_tracks_attempts() -> None:
    client = StubChatClient([TimeoutError(), AIMessage(content="done")])
    service = NoWaitLLMService(
        client=client,
        prompt_name="conversation-tools",
        prompt_version="v1",
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
        prompt_name="conversation-tools",
        prompt_version="v1",
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
        prompt_name="conversation-tools",
        prompt_version="v1",
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
async def test_generate_turn_normalizes_legacy_prompt_name() -> None:
    client = StubChatClient([AIMessage(content="done")])
    service = LLMService(
        client=client,
        prompt_name="tool-agent",
        prompt_version="v1",
        timeout_seconds=0,
        max_retries=0,
    )

    turn = await service.generate_turn(
        conversation_id="conv-legacy-prompt",
        messages=[HumanMessage(content="hello")],
        tools=[],
    )

    assert turn.trace.prompt_name == "conversation-tools"
    assert turn.trace.request_payload["conversation_id"] == "conv-legacy-prompt"


def test_resolve_prompt_supports_legacy_aliases() -> None:
    canonical = resolve_prompt("conversation-tools", "v1")
    legacy = resolve_prompt("tool-agent", "v1")
    direct = resolve_prompt("direct-agent", "v1")

    assert legacy == canonical
    assert legacy.name == "conversation-tools"
    assert direct.name == "conversation-direct"


def test_build_llm_service_constructs_chatdeepseek_directly(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    recorded: dict[str, object] = {}

    class RecordingBoundModel:
        async def ainvoke(self, messages, config: RunnableConfig | None = None):  # pragma: no cover
            return AIMessage(content="ok")

        def invoke(self, messages, config: RunnableConfig | None = None):  # pragma: no cover
            return AIMessage(content="ok")

    class RecordingChatDeepSeek:
        def __init__(self, **kwargs) -> None:  # type: ignore[no-untyped-def]
            recorded.update(kwargs)

        def bind_tools(self, tools):  # type: ignore[no-untyped-def]
            return RecordingBoundModel()

        async def ainvoke(self, messages, config: RunnableConfig | None = None):  # pragma: no cover
            return AIMessage(content="ok")

        def invoke(self, messages, config: RunnableConfig | None = None):  # pragma: no cover
            return AIMessage(content="ok")

    fake_module = types.ModuleType("langchain_deepseek")
    fake_module.ChatDeepSeek = RecordingChatDeepSeek
    monkeypatch.setitem(sys.modules, "langchain_deepseek", fake_module)

    settings = Settings(
        llm_provider="deepseek",
        llm_model="deepseek-reasoner",
        llm_timeout_seconds=7.5,
        llm_max_retries=3,
        deepseek_api_key=SecretStr("sk-test"),
    )

    service = build_llm_service(settings)

    assert isinstance(service, LLMService)
    assert isinstance(service._client, BoundChatClient)  # type: ignore[attr-defined]
    assert service._client.provider == "deepseek"  # type: ignore[attr-defined]
    assert service._client.model == "deepseek-reasoner"  # type: ignore[attr-defined]
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

        def invoke(self, messages, config=None):  # pragma: no cover
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
