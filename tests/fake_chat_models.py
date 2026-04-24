from __future__ import annotations

import re
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.tools import BaseTool
from pydantic import PrivateAttr

from agent_service.llm.payloads import dump_payload, text_from_message


class DeterministicToolCallingChatModel(BaseChatModel):
    _bound_tools: list[BaseTool] = PrivateAttr(default_factory=list)
    _shared_state: dict[str, Any] = PrivateAttr(default_factory=dict)

    @property
    def _llm_type(self) -> str:
        return "deterministic-test-model"

    def bind_tools(
        self,
        tools: list[BaseTool] | tuple[BaseTool, ...],
        *,
        tool_choice: str | None = None,
        **kwargs: Any,
    ) -> DeterministicToolCallingChatModel:
        del tool_choice, kwargs
        clone = self.model_copy(deep=True)
        clone._bound_tools = list(tools)
        clone._shared_state = self._shared_state
        return clone

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager=None,
        **kwargs: Any,
    ) -> ChatResult:
        raise NotImplementedError("tests use async execution only")

    async def _agenerate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager=None,
        **kwargs: Any,
    ) -> ChatResult:
        del stop, run_manager, kwargs
        if messages and isinstance(messages[-1], ToolMessage):
            message = self.respond_from_tool_message(messages[-1])
        else:
            human_message = self.latest_human_message(messages)
            if human_message is None:
                message = AIMessage(content="当前测试模型没有拿到用户输入。")
            else:
                message = self.plan_from_human_message(
                    human_message,
                    tools=self._bound_tools,
                )
        return ChatResult(generations=[ChatGeneration(message=message)])

    def latest_human_message(
        self,
        messages: list[BaseMessage],
    ) -> HumanMessage | None:
        for message in reversed(messages):
            if isinstance(message, HumanMessage):
                return message
        return None

    def respond_from_tool_message(self, message: ToolMessage) -> AIMessage:
        artifact = message.artifact if isinstance(message.artifact, dict) else {}
        tool_name = message.name or str(artifact.get("action") or "tool")
        if artifact.get("success") is False:
            error = artifact.get("error")
            error_message = (
                error.get("message")
                if isinstance(error, dict) and isinstance(error.get("message"), str)
                else text_from_message(message) or "unknown error"
            )
            return AIMessage(content=f"工具 `{tool_name}` 执行失败：{error_message}。")

        result = artifact.get("result")
        return AIMessage(
            content=f"我已经调用 `{tool_name}` 完成处理，结果是 {dump_payload(result)}。"
        )

    def plan_from_human_message(
        self,
        message: HumanMessage,
        *,
        tools: list[BaseTool],
    ) -> AIMessage:
        del tools
        return AIMessage(content=text_from_message(message))

    def tool_call_message(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        *,
        tool_call_id: str | None = None,
    ) -> AIMessage:
        return AIMessage(
            content="",
            tool_calls=[
                {
                    "name": tool_name,
                    "args": arguments,
                    "id": tool_call_id or f"call_{tool_name}",
                    "type": "tool_call",
                }
            ],
        )

    def extract_number_arguments(self, message: str) -> dict[str, int] | None:
        a_match = re.search(r"a\s*=\s*(-?\d+)", message)
        b_match = re.search(r"b\s*=\s*(-?\d+)", message)
        if a_match and b_match:
            return {"a": int(a_match.group(1)), "b": int(b_match.group(1))}
        return None
