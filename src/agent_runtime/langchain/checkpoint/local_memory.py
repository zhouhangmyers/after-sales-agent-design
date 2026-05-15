from __future__ import annotations

from collections.abc import Sequence

from langchain_core.messages import BaseMessage
from langgraph.checkpoint.memory import MemorySaver

from agent_core.contracts.run_state import RuntimeStoreStatus
from agent_core.support.message_serialization import (
    messages_from_payload,
    messages_payload,
)


class InMemoryStateStore:
    def __init__(self) -> None:
        self._checkpointer = MemorySaver()
        self._sessions: dict[str, dict[str, list[dict[str, object]]]] = {}

    async def ensure_initialized(self) -> None:
        return None

    async def healthcheck(self) -> RuntimeStoreStatus:
        return RuntimeStoreStatus(ok=True, backend="in-memory", detail=None)

    def get_checkpointer(self) -> MemorySaver:
        return self._checkpointer

    async def get_session_messages(self, *, session_id: str) -> list[BaseMessage]:
        session_messages = self._sessions.get(session_id, {})
        payload: list[dict[str, object]] = []
        for run_messages in session_messages.values():
            payload.extend(run_messages)
        return messages_from_payload(payload)

    async def upsert_session_messages(
        self,
        *,
        session_id: str,
        run_id: str,
        messages: Sequence[BaseMessage],
    ) -> None:
        session_messages = self._sessions.setdefault(session_id, {})
        session_messages[run_id] = messages_payload(list(messages))

    async def close(self) -> None:
        return None
