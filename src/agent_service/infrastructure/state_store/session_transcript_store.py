from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from langchain_core.messages import BaseMessage

from agent_service.llm.payloads import messages_from_payload, messages_payload


class SessionTranscriptStore(Protocol):
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


class InMemorySessionTranscriptStore:
    def __init__(self) -> None:
        self._sessions: dict[str, dict[str, list[dict[str, object]]]] = {}

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
