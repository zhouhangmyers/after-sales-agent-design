from __future__ import annotations

from collections.abc import Sequence

from langchain_core.messages import BaseMessage
from langgraph.checkpoint.memory import MemorySaver

from agent_core.contracts.run_state import RuntimeStoreStatus
from agent_runtime.langchain.transcript import (
    InMemorySessionTranscriptStore,
)


class InMemoryStateStore:
    def __init__(self) -> None:
        self._checkpointer = MemorySaver()
        self._session_transcripts = InMemorySessionTranscriptStore()

    async def ensure_initialized(self) -> None:
        return None

    async def healthcheck(self) -> RuntimeStoreStatus:
        return RuntimeStoreStatus(ok=True, backend="in-memory", detail=None)

    def get_checkpointer(self) -> MemorySaver:
        return self._checkpointer

    async def get_session_messages(self, *, session_id: str) -> list[BaseMessage]:
        return await self._session_transcripts.get_session_messages(session_id=session_id)

    async def upsert_session_messages(
        self,
        *,
        session_id: str,
        run_id: str,
        messages: Sequence[BaseMessage],
    ) -> None:
        await self._session_transcripts.upsert_session_messages(
            session_id=session_id,
            run_id=run_id,
            messages=messages,
        )

    async def close(self) -> None:
        return None
