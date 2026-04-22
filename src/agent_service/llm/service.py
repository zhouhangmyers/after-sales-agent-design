from __future__ import annotations

import logging
from time import perf_counter

from langchain_core.messages import AIMessage, BaseMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import BaseTool

from agent_service.config import Settings
from agent_service.llm.types import (
    AssistantDecision,
    ChatClient,
    LLMCallTrace,
    LLMTurn,
)
from agent_service.llm.bound_client import (
    InvocationFailedError,
    build_chat_client,
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
from agent_service.llm.prompts import resolve_prompt

logger = logging.getLogger(__name__)


class LLMService:
    def __init__(
        self,
        *,
        client: ChatClient,
        prompt_name: str,              # system prompt 的名称，用于从 prompts 模块解析
        prompt_version: str,           # prompt 版本，支持多版本管理和 A/B 测试
        timeout_seconds: float = 5.0,  # 单次 LLM 调用的超时上限
        max_retries: int = 1,          # 最大重试次数（不含首次调用）
    ) -> None:
        self._client = client
        self._prompt = resolve_prompt(prompt_name, prompt_version)
        self._timeout_seconds = timeout_seconds
        self._max_retries = max_retries

    def _resolve_prompt(
        self,
        *,
        prompt_name: str | None = None,
        prompt_version: str | None = None,
    ):
        # 不传则使用初始化时绑定的默认 prompt，
        # 传了就必须 name 和 version 同时提供，防止只改一个导致版本对不上
        if prompt_name is None and prompt_version is None:
            return self._prompt
        if prompt_name is None or prompt_version is None:
            raise ValueError("prompt_name and prompt_version must be provided together")
        return resolve_prompt(prompt_name, prompt_version)

    async def generate_turn(
        self,
        *,
        conversation_id: str,
        messages: list[BaseMessage],           # 当前对话历史（不含 system prompt）
        tools: list[BaseTool],
        runnable_config: RunnableConfig | None = None,
        stream_tokens: bool = False,           # 是否启用 token 流式输出
        prompt_name: str | None = None,        # 覆盖默认 prompt，供运行时动态切换
        prompt_version: str | None = None,
    ) -> LLMTurn:
        prompt = self._resolve_prompt(
            prompt_name=prompt_name,
            prompt_version=prompt_version,
        )
        # system prompt 置顶，后接对话历史
        request_messages = [SystemMessage(content=prompt.system_instructions), *messages]

        # request_payload 用于写入 trace，方便事后复现和调试
        request_payload = {
            "conversation_id": conversation_id,
            "prompt_name": prompt.name,
            "prompt_version": prompt.version,
            "messages": messages_payload(request_messages),
            "tools": tool_payloads(tools),
        }

        logger.debug(
            "llm.invoke conversation_id=%s prompt=%s@%s tools=%s",
            conversation_id,
            prompt.name,
            prompt.version,
            [t.name for t in tools],
        )

        start = perf_counter()
        attempts = 1

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
                prompt_name=prompt.name,
                prompt_version=prompt.version,
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
            prompt_name=prompt.name,
            prompt_version=prompt.version,
            request_payload=request_payload,
            raw_response={"error": last_error},
            decision=AssistantDecision(
                kind="respond",
                response=text_from_message(fallback_message),
            ),
            usage=token_usage_from_texts(
                prompt.system_instructions,
                last_error or "unknown error",
                model=self._client.model,
            ),
            latency_ms=(perf_counter() - start) * 1000,
            attempts=attempts,
            success=False,
            error_message=last_error,
        )
        return LLMTurn(assistant_message=fallback_message, trace=trace)

    def close(self) -> None:
        return None


def build_llm_service(settings: Settings) -> LLMService:
    client: ChatClient = build_chat_client(settings)
    return LLMService(
        client=client,
        prompt_name=settings.prompt_name,
        prompt_version=settings.prompt_version,
        timeout_seconds=settings.llm_timeout_seconds,
        max_retries=settings.llm_max_retries,
    )
