from __future__ import annotations

import json
from collections.abc import Sequence
from contextlib import AsyncExitStack

from langchain_core.messages import BaseMessage
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from agent_service.contracts.models import RuntimeStoreStatus
from agent_service.llm.payloads import messages_from_payload, messages_payload


class LangGraphPostgresStateStore:
    def __init__(self, conn_string: str) -> None:
        self._conn_string = conn_string
        self._exit_stack: AsyncExitStack | None = None
        self._checkpointer: AsyncPostgresSaver | None = None
        self._engine: AsyncEngine | None = None

    async def ensure_initialized(self) -> None:
        await self._ensure_open()

    async def healthcheck(self) -> RuntimeStoreStatus:
        try:
            await self._ensure_open()
        except Exception as exc:
            return RuntimeStoreStatus(
                ok=False,
                backend="langgraph-postgres",
                detail=str(exc) or exc.__class__.__name__,
            )
        return RuntimeStoreStatus(ok=True, backend="langgraph-postgres", detail=None)

    def get_checkpointer(self) -> AsyncPostgresSaver:
        if self._checkpointer is None:
            raise RuntimeError("langgraph checkpointer is not initialized")
        return self._checkpointer

    async def get_session_messages(self, *, session_id: str) -> list[BaseMessage]:
        await self._ensure_open()
        if self._engine is None:
            raise RuntimeError("runtime transcript engine is not initialized")

        async with self._engine.begin() as connection:
            rows = await connection.execute(
                text(
                    """
                    SELECT messages
                    FROM agent_session_transcripts
                    WHERE session_id = :session_id
                    ORDER BY turn_order ASC
                    """
                ),
                {"session_id": session_id},
            )
        payload: list[dict[str, object]] = []
        for row in rows:
            messages = row[0]
            if isinstance(messages, list):
                payload.extend(messages)
            elif isinstance(messages, str):
                payload.extend(json.loads(messages))
        return messages_from_payload(payload)

    async def upsert_session_messages(
        self,
        *,
        session_id: str,
        run_id: str,
        messages: Sequence[BaseMessage],
    ) -> None:
        await self._ensure_open()
        if self._engine is None:
            raise RuntimeError("runtime transcript engine is not initialized")

        payload = json.dumps(messages_payload(list(messages)), ensure_ascii=False)
        async with self._engine.begin() as connection:
            await connection.execute(
                text(
                    """
                    INSERT INTO agent_session_transcripts (session_id, run_id, messages)
                    VALUES (:session_id, :run_id, CAST(:messages AS JSONB))
                    ON CONFLICT (session_id, run_id)
                    DO UPDATE SET
                        messages = EXCLUDED.messages,
                        updated_at = NOW()
                    """
                ),
                {
                    "session_id": session_id,
                    "run_id": run_id,
                    "messages": payload,
                },
            )

    async def close(self) -> None:
        if self._exit_stack is not None:
            await self._exit_stack.aclose()
            self._exit_stack = None
            self._checkpointer = None
        if self._engine is not None:
            await self._engine.dispose()
            self._engine = None

    async def _ensure_open(self) -> None:
        if self._checkpointer is not None and self._engine is not None:
            return
        exit_stack = AsyncExitStack()
        saver = await exit_stack.enter_async_context(
            AsyncPostgresSaver.from_conn_string(self._conn_string)
        )
        await saver.setup()
        engine = create_async_engine(_sqlalchemy_async_url(self._conn_string))
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS agent_session_transcripts (
                        session_id TEXT NOT NULL,
                        run_id TEXT NOT NULL,
                        turn_order BIGSERIAL NOT NULL,
                        messages JSONB NOT NULL,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        PRIMARY KEY (session_id, run_id)
                    )
                    """
                )
            )
            await connection.execute(
                text(
                    """
                    CREATE INDEX IF NOT EXISTS ix_agent_session_transcripts_session_order
                    ON agent_session_transcripts (session_id, turn_order)
                    """
                )
            )
        self._exit_stack = exit_stack
        self._checkpointer = saver
        self._engine = engine


def _sqlalchemy_async_url(conn_string: str) -> str:
    if conn_string.startswith("postgresql://"):
        return conn_string.replace("postgresql://", "postgresql+psycopg://", 1)
    return conn_string
