from __future__ import annotations

import asyncio
from collections import OrderedDict
from dataclasses import dataclass

from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import BaseTool
from tenacity import (
    AsyncRetrying,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

from agent_service.config import Settings
from agent_service.llm.types import ChatClient, ToolBindableChatModel


def _build_retryable_exception_types() -> tuple[type[BaseException], ...]:
    retryable: list[type[BaseException]] = [TimeoutError, asyncio.TimeoutError]
    try:
        import httpx
    except ImportError:
        return tuple(retryable)
    retryable.extend(
        [
            httpx.ConnectError,
            httpx.ConnectTimeout,
            httpx.WriteError,
            httpx.WriteTimeout,
            httpx.ReadError,
            httpx.ReadTimeout,
            httpx.PoolTimeout,
            httpx.RemoteProtocolError,
        ]
    )
    return tuple(retryable)


_RETRYABLE_EXCEPTION_TYPES: tuple[type[BaseException], ...] = _build_retryable_exception_types()


@dataclass(frozen=True)
class InvocationResult:
    assistant_message: AIMessage
    attempts: int


class InvocationFailedError(RuntimeError):
    def __init__(self, *, message: str, attempts: int) -> None:
        super().__init__(message)
        self.message = message
        self.attempts = attempts


class BoundChatClient:
    def __init__(
        self,
        *,
        chat_model: ToolBindableChatModel,
        provider: str,
        model: str,
        bound_model_cache_size: int = 32,
    ) -> None:
        self.provider = provider
        self.model = model
        self._chat_model = chat_model
        self._bound_model_cache_size = max(1, bound_model_cache_size)
        self._bound_models: OrderedDict[tuple[str, ...], object] = OrderedDict()

    def _get_bound_model(self, tools: list[BaseTool]) -> object:
        if not tools:
            return self._chat_model

        tool_key = tuple(tool.name for tool in tools)
        bound_model = self._bound_models.get(tool_key)
        if bound_model is not None:
            self._bound_models.move_to_end(tool_key)
            return bound_model

        bound_model = self._chat_model.bind_tools(tools)
        self._bound_models[tool_key] = bound_model
        self._bound_models.move_to_end(tool_key)
        if len(self._bound_models) > self._bound_model_cache_size:
            self._bound_models.popitem(last=False)
        return bound_model

    def invoke(
        self,
        messages: list[BaseMessage],
        tools: list[BaseTool],
        config: RunnableConfig | None = None,
    ) -> AIMessage:
        response = self._get_bound_model(tools).invoke(messages, config=config)
        if not isinstance(response, AIMessage):
            raise TypeError(
                f"Expected AIMessage from chat model client, got {type(response).__name__}"
            )
        return response

    async def ainvoke(
        self,
        messages: list[BaseMessage],
        tools: list[BaseTool],
        config: RunnableConfig | None = None,
    ) -> AIMessage:
        response = await self._get_bound_model(tools).ainvoke(messages, config=config)
        if not isinstance(response, AIMessage):
            raise TypeError(
                f"Expected AIMessage from chat model client, got {type(response).__name__}"
            )
        return response


def _is_retryable_error(exc: BaseException) -> bool:
    return isinstance(exc, _RETRYABLE_EXCEPTION_TYPES)


def _build_retrying(max_retries: int) -> AsyncRetrying:
    return AsyncRetrying(
        stop=stop_after_attempt(max(1, max_retries + 1)),
        wait=wait_exponential(multiplier=0.5, min=0.5, max=30),
        retry=retry_if_exception(_is_retryable_error),
        reraise=True,
    )


async def invoke_chat_model_with_retry(
    client: ChatClient,
    *,
    request_messages: list[BaseMessage],
    tools: list[BaseTool],
    runnable_config: RunnableConfig | None = None,
    stream_tokens: bool,
    timeout_seconds: float,
    max_retries: int,
) -> InvocationResult:
    attempts = 0
    assistant_message: AIMessage | None = None

    try:
        async for attempt in _build_retrying(max_retries):
            with attempt:
                attempts = attempt.retry_state.attempt_number
                invocation = client.ainvoke(
                    request_messages,
                    tools,
                    config=runnable_config if stream_tokens else None,
                )
                if timeout_seconds > 0:
                    assistant_message = await asyncio.wait_for(
                        invocation,
                        timeout=timeout_seconds,
                    )
                else:
                    assistant_message = await invocation
    except TimeoutError as exc:
        timeout_message = str(exc).strip() or f"model timed out after {timeout_seconds:.2f}s"
        raise InvocationFailedError(
            message=timeout_message,
            attempts=max(1, attempts),
        ) from exc
    except Exception as exc:
        raise InvocationFailedError(
            message=str(exc).strip() or exc.__class__.__name__,
            attempts=max(1, attempts),
        ) from exc

    if assistant_message is None:
        raise InvocationFailedError(message="unknown error", attempts=max(1, attempts))

    return InvocationResult(
        assistant_message=assistant_message,
        attempts=max(1, attempts),
    )


def build_chat_client(settings: Settings) -> BoundChatClient:
    if settings.llm_provider != "deepseek":
        raise ValueError(f"unsupported llm provider: {settings.llm_provider}")
    if settings.deepseek_api_key is None:
        raise ValueError("DEEPSEEK_API_KEY is required when llm_provider=deepseek")
    try:
        from langchain_deepseek import ChatDeepSeek
    except ImportError as exc:
        raise RuntimeError(
            "DeepSeek chat model support requires the LangChain DeepSeek integration package."
        ) from exc
    chat_model = ChatDeepSeek(
        api_key=settings.deepseek_api_key.get_secret_value(),
        model=settings.llm_model,
        temperature=0,
        streaming=True,
        timeout=settings.llm_timeout_seconds,
        max_retries=settings.llm_max_retries,
    )
    return BoundChatClient(
        chat_model=chat_model,
        provider="deepseek",
        model=settings.llm_model,
    )
