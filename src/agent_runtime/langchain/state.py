from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from langchain.agents.middleware.types import AgentState

from agent_core.contracts.run_events import RunEvent
from agent_core.contracts.tool_spec import ToolContext


class LangChainAgentState(AgentState[Any], total=False):
    session_id: str
    input_message: str
    run_error: dict[str, str] | None


@dataclass(slots=True)
class LangChainRuntimeContext:
    tool_context: ToolContext
    emit: Callable[[RunEvent], Awaitable[None]]
    is_resume: bool = False
