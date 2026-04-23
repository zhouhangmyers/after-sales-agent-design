from __future__ import annotations

import logging
from time import perf_counter

from langchain_core.messages import AIMessage, BaseMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import BaseTool

from agent_service.llm.bound_client import (
    InvocationFailedError,
    invoke_chat_model_with_retry,
)
from agent_service.llm.payloads import (
    decision_from_ai_message,
    dump_payload,
    message_payload,
    messages_payload,
    text_from_message,
    token_usage_from_ai_message,
    token_usage_from_texts,
    tool_payloads,
)
from agent_service.llm.types import (
    AssistantDecision,
    ChatClient,
    LLMCallTrace,
    LLMTurn,
)

logger = logging.getLogger(__name__)


class LLMService:
    def __init__(
        self,
        *,
        client: ChatClient,
        system_prompt: str,
        timeout_seconds: float = 5.0,
        max_retries: int = 1,
    ) -> None:
        self._client = client
        self._system_prompt = system_prompt
        self._timeout_seconds = timeout_seconds
        self._max_retries = max_retries

    async def generate_turn(
        self,
        *,
        conversation_id: str,
        messages: list[BaseMessage],
        tools: list[BaseTool],
        runnable_config: RunnableConfig | None = None,
        stream_tokens: bool = False,
    ) -> LLMTurn:
        request_messages = [SystemMessage(content=self._system_prompt), *messages]
        request_payload = {
            "conversation_id": conversation_id,
            "messages": messages_payload(request_messages),
            "tools": tool_payloads(tools),
        }

        logger.debug(
            "llm.invoke conversation_id=%s tools=%s",
            conversation_id,
            [t.name for t in tools],
        )

        start = perf_counter()
        attempts = 1
        last_error: str | None = None

        try:
            invocation = await invoke_chat_model_with_retry(
                self._client,
                request_messages=request_messages,
                tools=tools,
                runnable_config=runnable_config,
                stream_tokens=stream_tokens,
                timeout_seconds=self._timeout_seconds,
                max_retries=self._max_retries,
            )
            assistant_message = invocation.assistant_message
            attempts = invocation.attempts
            decision = decision_from_ai_message(assistant_message)
            usage = token_usage_from_ai_message(assistant_message)
            if usage.total_tokens == 0:
                # provider 部分场景不返回 usage，退而用 tiktoken 本地估算，
                # 保证 trace 里的 token 数据不缺失
                usage = token_usage_from_texts(
                    dump_payload(request_payload),
                    dump_payload(message_payload(assistant_message)),
                    model=self._client.model,
                )
            trace = LLMCallTrace(
                provider=self._client.provider,
                model=self._client.model,
                request_payload=request_payload,
                raw_response=message_payload(assistant_message),
                decision=decision,
                usage=usage,
                latency_ms=(perf_counter() - start) * 1000,
                attempts=attempts,
                success=True,
            )
            logger.info(
                "llm.success conversation_id=%s attempts=%d latency_ms=%.0f tokens=%d",
                conversation_id,
                attempts,
                trace.latency_ms,
                trace.usage.total_tokens,
            )
            return LLMTurn(assistant_message=assistant_message, trace=trace)

        except InvocationFailedError as exc:
            last_error = exc.message
            attempts = exc.attempts
            logger.warning(
                "llm.failed conversation_id=%s attempts=%d error=%s",
                conversation_id,
                attempts,
                last_error,
            )

        # 调用失败不向上抛异常，而是返回一个带错误信息的 fallback AIMessage。
        # 上层 plan_node 通过检查 trace.success 判断是否失败并决定 graph 走向，
        # 这样错误处理逻辑集中在 graph 层，LLMService 本身保持无状态
        fallback_message = AIMessage(content=f"模型调用失败：{last_error or 'unknown error'}。")
        trace = LLMCallTrace(
            provider=self._client.provider,
            model=self._client.model,
            request_payload=request_payload,
            raw_response={"error": last_error},
            decision=AssistantDecision(
                kind="respond",
                response=text_from_message(fallback_message),
            ),
            usage=token_usage_from_texts(
                self._system_prompt,
                last_error or "unknown error",
                model=self._client.model,
            ),
            latency_ms=(perf_counter() - start) * 1000,
            attempts=attempts,
            success=False,
            error_message=last_error,
        )
        return LLMTurn(assistant_message=fallback_message, trace=trace)
