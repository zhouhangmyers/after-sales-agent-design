from __future__ import annotations

import re

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import BaseTool

from agent_service.conversation.service import ConversationService
from agent_service.llm import dump_payload, text_from_message
from agent_service.llm.service import LLMService
from agent_service.tools.inline import InlineToolExecutor
from tests.sample_tools import build_sample_tool_policies, build_sample_tools


class TestRoutingConversationClient:
    provider = "test"
    model = "test-routing-v1"

    async def ainvoke(
        self,
        messages: list[BaseMessage],
        tools: list[BaseTool],
        config: RunnableConfig | None = None,
    ) -> AIMessage:
        if messages and isinstance(messages[-1], ToolMessage):
            return self._respond_from_tool_message(messages[-1], config=config)

        human_message = self._latest_human_message(messages)
        if human_message is None:
            return self._stream_text("当前测试模型没有拿到用户输入。", config=config)
        return self._plan_from_human_message(human_message, tools=tools, config=config)

    def _latest_human_message(self, messages: list[BaseMessage]) -> HumanMessage | None:
        for message in reversed(messages):
            if isinstance(message, HumanMessage):
                return message
        return None

    def _respond_from_tool_message(
        self,
        message: ToolMessage,
        *,
        config: RunnableConfig | None,
    ) -> AIMessage:
        artifact = getattr(message, "artifact", None) or {}
        if isinstance(artifact, dict) and artifact.get("success") is False:
            error = artifact.get("error") or {}
            error_message = error.get("message") or text_from_message(message) or "unknown error"
            return self._stream_text(
                f"工具 `{message.name or 'tool'}` 执行失败：{error_message}。",
                config=config,
            )

        if isinstance(artifact, dict):
            result_repr = dump_payload(artifact.get("result"))
            tool_name = artifact.get("action") or message.name or "tool"
        else:
            result_repr = text_from_message(message)
            tool_name = message.name or "tool"
        return self._stream_text(
            f"我已经调用 `{tool_name}` 完成处理，结果是 {result_repr}。",
            config=config,
        )

    def _plan_from_human_message(
        self,
        message: HumanMessage,
        *,
        tools: list[BaseTool],
        config: RunnableConfig | None,
    ) -> AIMessage:
        content = text_from_message(message)
        available_tools = {tool.name for tool in tools}

        if not available_tools:
            return self._stream_text(
                "当前没有可调用工具，所以直接回应：" + content,
                config=config,
            )

        if ("divide" in content or "除" in content) and "divide" in available_tools:
            arguments = self._extract_number_arguments(content)
            if arguments is not None:
                return self._tool_call_message("divide", arguments)

        if ("multiply" in content or "乘" in content) and "multiply" in available_tools:
            arguments = self._extract_number_arguments(content)
            if arguments is not None:
                return self._tool_call_message("multiply", arguments)

        if ("add" in content or "加" in content) and "add" in available_tools:
            arguments = self._extract_number_arguments(content)
            if arguments is not None:
                return self._tool_call_message("add", arguments)

        city_code = self._extract_city_code(content)
        if city_code is not None and "get_city" in available_tools:
            return self._tool_call_message("get_city", {"city_code": city_code})

        return self._stream_text(
            "当前模型没找到必须调用工具的场景，所以先直接回应：" + content,
            config=config,
        )

    def _stream_text(self, text: str, *, config: RunnableConfig | None) -> AIMessage:
        del config
        return AIMessage(content=text)

    def _tool_call_message(self, tool_name: str, arguments: dict[str, int] | dict[str, str]) -> AIMessage:
        return AIMessage(
            content="",
            tool_calls=[
                {
                    "name": tool_name,
                    "args": arguments,
                    "id": f"call_{tool_name}",
                    "type": "tool_call",
                }
            ],
        )

    def _extract_number_arguments(self, message: str) -> dict[str, int] | None:
        a_match = re.search(r"a\s*=\s*(-?\d+)", message)
        b_match = re.search(r"b\s*=\s*(-?\d+)", message)
        if a_match and b_match:
            return {"a": int(a_match.group(1)), "b": int(b_match.group(1))}
        return None

    def _extract_city_code(self, message: str) -> str | None:
        city_match = re.search(r"city_code\s*=\s*([a-zA-Z]+)", message)
        if city_match:
            return city_match.group(1).lower()
        city_aliases = {
            "shanghai": "sh",
            "上海": "sh",
            "hangzhou": "hz",
            "杭州": "hz",
            "suzhou": "sz",
            "苏州": "sz",
        }
        lowered = message.lower()
        for alias, code in city_aliases.items():
            if alias in lowered or alias in message:
                return code
        return None


class StrictToolSequenceConversationClient(TestRoutingConversationClient):
    _ERROR_MESSAGE = (
        "An assistant message with 'tool_calls' must be followed by tool messages "
        "responding to each 'tool_call_id'. (insufficient tool messages following "
        "tool_calls message)"
    )

    async def ainvoke(
        self,
        messages: list[BaseMessage],
        tools: list[BaseTool],
        config: RunnableConfig | None = None,
    ) -> AIMessage:
        self._validate_tool_sequence(messages)
        return await super().ainvoke(messages, tools, config=config)

    def _validate_tool_sequence(self, messages: list[BaseMessage]) -> None:
        pending_tool_call_ids: list[str] = []
        for message in messages:
            if pending_tool_call_ids:
                if isinstance(message, ToolMessage):
                    tool_call_id = getattr(message, "tool_call_id", None)
                    if isinstance(tool_call_id, str) and tool_call_id in pending_tool_call_ids:
                        pending_tool_call_ids.remove(tool_call_id)
                        continue
                raise ValueError(self._ERROR_MESSAGE)

            if isinstance(message, AIMessage) and message.tool_calls:
                for tool_call in message.tool_calls:
                    tool_call_id = tool_call.get("id")
                    if not isinstance(tool_call_id, str) or not tool_call_id:
                        raise ValueError(self._ERROR_MESSAGE)
                    pending_tool_call_ids.append(tool_call_id)

        if pending_tool_call_ids:
            raise ValueError(self._ERROR_MESSAGE)


class MissingToolCallIdConversationClient(StrictToolSequenceConversationClient):
    def _tool_call_message(self, tool_name: str, arguments: dict[str, int] | dict[str, str]) -> AIMessage:
        return AIMessage(
            content="",
            tool_calls=[
                {
                    "name": tool_name,
                    "args": arguments,
                    "id": None,
                    "type": "tool_call",
                }
            ],
        )


class MultiToolCallConversationClient(StrictToolSequenceConversationClient):
    def _plan_from_human_message(
        self,
        message: HumanMessage,
        *,
        tools: list[BaseTool],
        config: RunnableConfig | None,
    ) -> AIMessage:
        content = text_from_message(message)
        available_tools = {tool.name for tool in tools}
        if "multi_tool" in content and {"add", "divide"}.issubset(available_tools):
            return AIMessage(
                content="I need two tools.",
                tool_calls=[
                    {
                        "name": "add",
                        "args": {"a": 2, "b": 3},
                        "id": "call_add",
                        "type": "tool_call",
                    },
                    {
                        "name": "divide",
                        "args": {"a": 8, "b": 2},
                        "id": "call_divide",
                        "type": "tool_call",
                    },
                ],
            )
        return super()._plan_from_human_message(message, tools=tools, config=config)


def build_test_llm_service(*, client: TestRoutingConversationClient | None = None) -> LLMService:
    return LLMService(
        client=client or TestRoutingConversationClient(),
        system_prompt="你是一个测试工具助手。",
        timeout_seconds=0,
        max_retries=0,
    )


def build_test_tool_executor() -> InlineToolExecutor:
    return InlineToolExecutor(
        tools=build_sample_tools(),
        tool_policies=build_sample_tool_policies(),
    )


def build_test_conversation_service(
    *,
    client: TestRoutingConversationClient | None = None,
) -> ConversationService:
    from langgraph.checkpoint.memory import MemorySaver

    return ConversationService(
        capability_id="test-tools",
        llm_service=build_test_llm_service(client=client),
        tool_executor=build_test_tool_executor(),
        checkpointer=MemorySaver(),
    )


def build_strict_test_conversation_service() -> ConversationService:
    return build_test_conversation_service(client=StrictToolSequenceConversationClient())


def build_missing_tool_call_id_conversation_service() -> ConversationService:
    return build_test_conversation_service(client=MissingToolCallIdConversationClient())


def build_multi_tool_call_conversation_service() -> ConversationService:
    return build_test_conversation_service(client=MultiToolCallConversationClient())
