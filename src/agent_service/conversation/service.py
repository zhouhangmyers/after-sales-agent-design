from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING, Literal
from uuid import uuid4

from langchain_core.messages import AIMessage, AIMessageChunk
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.types import StreamPart

from agent_service.conversation.events import (
    ConversationApprovalRequired,
    ConversationCompleted,
    ConversationEvent,
    ConversationFailed,
    ConversationStarted,
    ConversationToken,
)
from agent_service.conversation.errors import ConversationErrorCode
from agent_service.conversation.graph import (
    ConversationGraph,
    ConversationResumeUnavailableError,
)
from agent_service.conversation.models import (
    ConversationError,
    ConversationSnapshot,
    ConversationTurn,
    PendingAction,
)
from agent_service.conversation.state import normalize_status, usage_from_state
from agent_service.llm.payloads import text_from_message
from agent_service.llm.service import LLMService
from agent_service.observability.context import get_request_id

if TYPE_CHECKING:
    from agent_service.tools.inline import InlineToolExecutor

logger = logging.getLogger(__name__)


class ConversationNotFoundError(LookupError):
    pass


class ConversationConflictError(RuntimeError):
    pass


class ConversationService:
    def __init__(
        self,
        *,
        llm_service: LLMService,
        tool_executor: "InlineToolExecutor",
        max_steps: int = 4,
        approval_timeout_seconds: int = 900,
        checkpointer: BaseCheckpointSaver | None,
    ) -> None:
        self._llm_service = llm_service
        self._tool_executor = tool_executor
        self._max_steps = max_steps
        self._approval_timeout_seconds = approval_timeout_seconds
        self._graph = ConversationGraph(checkpointer=checkpointer)

    async def send_message(
        self,
        *,
        conversation_id: str | None,
        message: str,
    ) -> ConversationTurn:
        resolved_id = conversation_id or self._new_conversation_id()
        if conversation_id is not None:
            await self._ensure_sendable(conversation_id)

        state = await self._graph.run(
            llm_service=self._llm_service,
            tool_executor=self._tool_executor,
            conversation_id=resolved_id,
            message=message,
            request_id=get_request_id(),
            max_steps=self._max_steps,
            approval_timeout_seconds=self._approval_timeout_seconds,
        )
        return self._to_turn(conversation_id=resolved_id, state=state)

    async def stream_message(
        self,
        *,
        conversation_id: str | None,
        message: str,
    ) -> AsyncIterator[ConversationEvent]:
        resolved_id = conversation_id or self._new_conversation_id()
        if conversation_id is not None:
            await self._ensure_sendable(conversation_id)

        request_id = get_request_id()

        async def _stream() -> AsyncIterator[ConversationEvent]:
            yield ConversationStarted(conversation_id=resolved_id)
            try:
                async for part in self._graph.stream(
                    llm_service=self._llm_service,
                    tool_executor=self._tool_executor,
                    conversation_id=resolved_id,
                    message=message,
                    request_id=request_id,
                    max_steps=self._max_steps,
                    approval_timeout_seconds=self._approval_timeout_seconds,
                ):
                    for event in self._events_from_part(
                        conversation_id=resolved_id,
                        part=part,
                    ):
                        yield event

                state = await self._require_state(resolved_id)
                yield ConversationCompleted(
                    turn=self._to_turn(
                        conversation_id=resolved_id,
                        state=state,
                    )
                )
            except Exception as exc:
                logger.exception(
                    "conversation stream failed conversation_id=%s",
                    resolved_id,
                )
                yield ConversationFailed(
                    conversation_id=resolved_id,
                    error=ConversationError(
                        code=ConversationErrorCode.EXECUTION_FAILED.value,
                        message=str(exc) or "Internal server error",
                    ),
                )

        return _stream()

    async def resume(
        self,
        *,
        conversation_id: str,
        decision: Literal["approved", "rejected"],
    ) -> ConversationTurn:
        await self._require_state(conversation_id)
        try:
            state = await self._graph.resume(
                llm_service=self._llm_service,
                tool_executor=self._tool_executor,
                conversation_id=conversation_id,
                decision=decision,
                request_id=get_request_id(),
                max_steps=self._max_steps,
                approval_timeout_seconds=self._approval_timeout_seconds,
            )
        except ConversationResumeUnavailableError as exc:
            raise ConversationConflictError(str(exc)) from exc
        return self._to_turn(conversation_id=conversation_id, state=state)

    async def get_state(self, *, conversation_id: str) -> ConversationSnapshot:
        state = await self._require_state(conversation_id)
        return self._to_snapshot(conversation_id=conversation_id, state=state)

    def close(self) -> None:
        self._tool_executor.close()
        self._llm_service.close()

    async def _ensure_sendable(self, conversation_id: str) -> None:
        state = await self._require_state(conversation_id)
        if normalize_status(state) == "awaiting_action":
            raise ConversationConflictError(
                "conversation is waiting for approval; use /chat/resume instead"
            )

    async def _require_state(self, conversation_id: str) -> dict[str, object]:
        state = await self._graph.get_state(conversation_id=conversation_id)
        if state is None:
            raise ConversationNotFoundError(f"conversation not found: {conversation_id}")
        return state

    def _to_turn(
        self,
        *,
        conversation_id: str,
        state: dict[str, object],
    ) -> ConversationTurn:
        status = normalize_status(state)
        reply = state.get("last_reply")
        if reply is not None and not isinstance(reply, str):
            reply = str(reply)
        error = None
        if status == "failed":
            error = ConversationError(
                code=str(state.get("error_code") or ConversationErrorCode.EXECUTION_FAILED.value),
                message=str(reply or "conversation failed"),
            )
        return ConversationTurn(
            conversation_id=conversation_id,
            status=status,
            reply=reply,
            pending_action=self._to_pending_action(state.get("pending_action")),
            usage=usage_from_state(state),
            error=error,
        )

    def _to_snapshot(
        self,
        *,
        conversation_id: str,
        state: dict[str, object],
    ) -> ConversationSnapshot:
        reply = state.get("last_reply")
        if reply is not None and not isinstance(reply, str):
            reply = str(reply)
        return ConversationSnapshot(
            conversation_id=conversation_id,
            status=normalize_status(state),
            last_reply=reply,
            pending_action=self._to_pending_action(state.get("pending_action")),
        )

    def _to_pending_action(self, payload: object) -> PendingAction | None:
        if payload is None or not isinstance(payload, dict):
            return None
        return PendingAction.model_validate(payload)

    def _events_from_part(
        self,
        *,
        conversation_id: str,
        part: StreamPart,
    ) -> list[ConversationEvent]:
        events: list[ConversationEvent] = []
        part_type = part.get("type")
        if part_type == "messages":
            chunk = self._message_chunk_from_part(part.get("data"))
            if not isinstance(chunk, (AIMessage, AIMessageChunk)) or chunk.tool_calls:
                return events
            text = text_from_message(chunk)
            if text:
                events.append(ConversationToken(conversation_id=conversation_id, text=text))
            return events

        if part_type == "custom":
            payload = part.get("data")
            if (
                isinstance(payload, dict)
                and payload.get("type") == "approval.required"
                and isinstance(payload.get("pending_action"), dict)
            ):
                pending_action = self._to_pending_action(payload["pending_action"])
                if pending_action is not None:
                    events.append(
                        ConversationApprovalRequired(
                            conversation_id=conversation_id,
                            pending_action=pending_action,
                        )
                    )
        return events

    def _message_chunk_from_part(self, payload: object) -> object | None:
        if isinstance(payload, tuple):
            return payload[0] if payload else None
        if isinstance(payload, list):
            return payload[0] if payload else None
        return payload

    def _new_conversation_id(self) -> str:
        return f"conv-{uuid4()}"
