from __future__ import annotations

import json
from time import perf_counter
from typing import Any

from langchain_core.messages import ToolMessage
from langchain_core.tools import BaseTool
from pydantic import ValidationError

from agent_service.llm.payloads import dump_payload
from agent_service.tools.models import (
    ErrorResponse,
    ToolExecution,
    ToolPolicy,
    ToolRequest,
    ToolResult,
)


class InlineToolExecutor:
    def __init__(
        self,
        *,
        tools: list[BaseTool] | None = None,
        tool_policies: dict[str, ToolPolicy] | None = None,
    ) -> None:
        self._tools = {tool.name: tool for tool in (tools or [])}
        self._tool_policies = dict(tool_policies or {})

    def close(self) -> None:
        return None

    def get_tools(self) -> list[BaseTool]:
        return list(self._tools.values())

    def execute(
        self,
        *,
        tool_name: str,
        tool_arguments: dict[str, Any],
        tool_call_id: str | None,
        request_id: str,
    ) -> ToolExecution:
        start = perf_counter()
        request = ToolRequest(action=tool_name, arguments=tool_arguments)
        result = self._invoke(
            tool_name=tool_name,
            tool_arguments=tool_arguments,
            request_id=request_id,
            tool_call_id=tool_call_id,
        )
        return ToolExecution(
            request=request,
            result=result,
            latency_ms=(perf_counter() - start) * 1000,
            tool_call_id=tool_call_id,
        )

    def to_tool_message(self, execution: ToolExecution) -> ToolMessage:
        if execution.result.success:
            content = dump_payload(execution.result.result)
            status = "success"
        else:
            error = (
                execution.result.error.model_dump(mode="json")
                if execution.result.error is not None
                else {}
            )
            content = dump_payload(error)
            status = "error"
        return ToolMessage(
            content=content,
            tool_call_id=execution.tool_call_id or execution.request.action,
            name=execution.request.action,
            status=status,
            artifact=execution.result.model_dump(mode="json"),
        )

    def get_tool_policy(self, tool_name: str) -> ToolPolicy:
        return self._tool_policies.get(tool_name, ToolPolicy(tool_name=tool_name))

    def _invoke(
        self,
        *,
        tool_name: str,
        tool_arguments: dict[str, Any],
        request_id: str,
        tool_call_id: str | None,
    ) -> ToolResult:
        tool = self._tools.get(tool_name)
        metadata = {"tool_call_id": tool_call_id}
        if tool is None:
            return ToolResult(
                success=False,
                action=tool_name,
                request_id=request_id,
                error=ErrorResponse(
                    code="unknown_tool",
                    message=f"unknown action: {tool_name}",
                    details={
                        "available_actions": sorted(self._tools),
                        "metadata": metadata,
                    },
                ),
            )

        try:
            raw_result = tool.invoke(tool_arguments)
            normalized_result = json.loads(dump_payload(raw_result))
        except ValidationError as exc:
            return ToolResult(
                success=False,
                action=tool_name,
                request_id=request_id,
                error=ErrorResponse(
                    code="tool_validation_failed",
                    message=f"invalid arguments for action: {tool_name}",
                    details={
                        "arguments": tool_arguments,
                        "errors": exc.errors(),
                        "metadata": metadata,
                    },
                ),
            )
        except Exception as exc:
            return ToolResult(
                success=False,
                action=tool_name,
                request_id=request_id,
                error=ErrorResponse(
                    code="tool_execution_failed",
                    message=f"tool execution failed: {tool_name}",
                    details={
                        "arguments": tool_arguments,
                        "reason": str(exc),
                        "metadata": metadata,
                    },
                ),
            )

        return ToolResult(
            success=True,
            action=tool_name,
            request_id=request_id,
            result=normalized_result,
        )
