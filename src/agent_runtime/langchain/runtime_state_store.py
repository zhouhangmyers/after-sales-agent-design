from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Protocol

from langchain_core.messages import BaseMessage
from langgraph.checkpoint.base import BaseCheckpointSaver

from agent_core.contracts.run_state import RuntimeStoreStatus


class AgentRuntimeStateStore(Protocol):
    """Storage port for Agent Runtime state.

    Provides both run-scoped LangGraph checkpoint state and session-scoped
    transcript state.
    """

    async def ensure_initialized(self) -> None:
        ...

    async def healthcheck(self) -> RuntimeStoreStatus:
        ...

    def get_checkpointer(self) -> BaseCheckpointSaver[Any]:
        ...

    async def get_session_messages(self, *, session_id: str) -> list[BaseMessage]:
        ...

    async def upsert_session_messages(
        self,
        *,
        session_id: str,
        run_id: str,
        messages: Sequence[BaseMessage],
    ) -> None:
        ...

    async def close(self) -> None:
        ...
