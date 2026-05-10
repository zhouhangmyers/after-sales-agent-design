from __future__ import annotations

import inspect
from typing import Any

from langchain_core.tools import StructuredTool
from langchain_core.tools.base import BaseTool
from langgraph.runtime import get_runtime

from agent_core.contracts.tool_spec import ToolContext, ToolSpec
from agent_core.support.json_payload import dump_payload
from agent_runtime.langchain.state import LangChainRuntimeContext


def to_langchain_tool(tool_spec: ToolSpec) -> BaseTool:
    async def _runner(**kwargs: Any) -> tuple[str, dict[str, Any]]:
        result_envelope = await execute_tool(tool_spec=tool_spec, payload=kwargs)
        return dump_payload(result_envelope), result_envelope

    return StructuredTool.from_function(
        coroutine=_runner,
        name=tool_spec.name,
        description=tool_spec.description,
        args_schema=tool_spec.args_schema,
        response_format="content_and_artifact",
    )


async def execute_tool(
    *,
    tool_spec: ToolSpec,
    payload: dict[str, Any],
) -> dict[str, Any]:
    runtime = get_runtime(LangChainRuntimeContext)
    try:
        result = tool_spec.handler(
            payload,
            ToolContext(
                capability_id=runtime.context.tool_context.capability_id,
                actor=runtime.context.tool_context.actor,
                dependencies=runtime.context.tool_context.dependencies,
            ),
        )
        if inspect.isawaitable(result):
            result = await result
    except Exception as exc:
        return {
            "success": False,
            "action": tool_spec.name,
            "error": {
                "code": "tool_execution_failed",
                "message": str(exc) or exc.__class__.__name__,
            },
        }

    return {
        "success": True,
        "action": tool_spec.name,
        "result": result,
    }
