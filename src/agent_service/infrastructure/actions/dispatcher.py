from __future__ import annotations

from typing import Any

from langchain_core.tools import BaseTool, StructuredTool

from agent_service.contracts.actions import AgentExecutionContext
from agent_service.contracts.capability import AgentCapability
from agent_service.tools.inline import InlineToolExecutor
from agent_service.tools.models import ToolPolicy


class LangChainActionDispatcher:
    def build_tool_executor(
        self,
        *,
        capability: AgentCapability,
        execution_context: AgentExecutionContext,
    ) -> InlineToolExecutor:
        tools = [self._to_tool(action, execution_context) for action in capability.actions]
        policies = {
            action.name: ToolPolicy(
                tool_name=action.name,
                approval_required=False,
                risk_level="low",
                approval_evaluator=action.approval_evaluator,
            )
            for action in capability.actions
        }
        return InlineToolExecutor(tools=tools, tool_policies=policies)

    def _to_tool(
        self,
        action,
        execution_context: AgentExecutionContext,
    ) -> BaseTool:
        def _runner(**kwargs: Any) -> Any:
            return action.handler(kwargs, execution_context)

        return StructuredTool.from_function(
            func=_runner,
            name=action.name,
            description=action.description,
            args_schema=action.args_schema,
        )
