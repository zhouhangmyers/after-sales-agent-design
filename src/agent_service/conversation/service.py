from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING, Literal
from uuid import uuid4

from langchain_core.messages import (
    AIMessage,
    AIMessageChunk,
    BaseMessage,
    HumanMessage,
)
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.types import StreamPart

from agent_service.contracts.events import (
    ActionCompletedEvent,
    ActionRequiredEvent,
    ActionStartedEvent,
    AgentEvent,
    OutputDeltaEvent,
    RunCompletedEvent,
    RunFailedEvent,
    RunStartedEvent,
)
from agent_service.contracts.models import (
    AgentError,
    AgentPendingAction,
    AgentRunResult,
    RunState,
)
from agent_service.conversation.errors import ConversationErrorCode
from agent_service.conversation.graph import (
    ConversationGraph,
    ConversationResumeUnavailableError,
)
from agent_service.conversation.state import normalize_status, usage_from_state
from agent_service.infrastructure.state_store.session_transcript_store import (
    InMemorySessionTranscriptStore,
    SessionTranscriptStore,
)
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
        capability_id: str,
        llm_service: LLMService,
        tool_executor: InlineToolExecutor,
        max_steps: int = 4,
        approval_timeout_seconds: int = 900,
        checkpointer: BaseCheckpointSaver | None,
        session_store: SessionTranscriptStore | None = None,
    ) -> None:
        self._capability_id = capability_id
        self._llm_service = llm_service
        self._tool_executor = tool_executor
        self._max_steps = max_steps
        self._approval_timeout_seconds = approval_timeout_seconds
        self._graph = ConversationGraph(checkpointer=checkpointer)
        self._session_store = session_store or InMemorySessionTranscriptStore()

    async def stream_message(
        self,
        *,
        session_id: str | None,
        message: str,
    ) -> AsyncIterator[AgentEvent]:
        resolved_session_id = session_id or self._new_session_id()
        run_id = self._new_run_id()
        history_messages = await self._session_store.get_session_messages(
            session_id=resolved_session_id
        )
        request_id = get_request_id()

        async def _stream() -> AsyncIterator[AgentEvent]:
            await self._persist_session_messages(
                run_id=run_id,
                session_id=resolved_session_id,
                messages=[HumanMessage(content=message)],
            )
            yield RunStartedEvent(
                run_id=run_id,
                session_id=resolved_session_id,
                capability_id=self._capability_id,
            )
            try:
                async for part in self._graph.stream(
                    llm_service=self._llm_service,
                    tool_executor=self._tool_executor,
                    run_id=run_id,
                    session_id=resolved_session_id,
                    history_messages=history_messages,
                    message=message,
                    request_id=request_id,
                    max_steps=self._max_steps,
                    approval_timeout_seconds=self._approval_timeout_seconds,
                ):
                    for event in self._events_from_part(
                        run_id=run_id,
                        part=part,
                    ):
                        yield event

                state = await self._require_state(run_id)
                await self._persist_session_transcript(
                    run_id=run_id,
                    session_id=resolved_session_id,
                    state=state,
                )
                yield RunCompletedEvent(
                    result=self._to_run_result(
                        run_id=run_id,
                        state=state,
                    )
                )
            except Exception as exc:
                logger.exception(
                    "conversation stream failed run_id=%s session_id=%s",
                    run_id,
                    resolved_session_id,
                )
                error_message = str(exc) or "Internal server error"
                await self._persist_session_messages(
                    run_id=run_id,
                    session_id=resolved_session_id,
                    messages=[
                        HumanMessage(content=message),
                        AIMessage(content=error_message),
                    ],
                )
                yield RunFailedEvent(
                    run_id=run_id,
                    error=AgentError(
                        code=ConversationErrorCode.EXECUTION_FAILED.value,
                        message=error_message,
                    ),
                )

        return _stream()

    async def stream_resume(
        self,
        *,
        run_id: str,
        decision: Literal["approved", "rejected"],
    ) -> AsyncIterator[AgentEvent]:
        initial_state = await self._require_state(run_id)
        session_id = self._session_id_from_state(initial_state, default=run_id)
        request_id = get_request_id()

        async def _stream() -> AsyncIterator[AgentEvent]:
            yield RunStartedEvent(
                run_id=run_id,
                session_id=session_id,
                capability_id=self._capability_id,
            )
            try:
                async for part in self._graph.stream_resume(
                    llm_service=self._llm_service,
                    tool_executor=self._tool_executor,
                    run_id=run_id,
                    decision=decision,
                    request_id=request_id,
                    max_steps=self._max_steps,
                    approval_timeout_seconds=self._approval_timeout_seconds,
                ):
                    for event in self._events_from_part(
                        run_id=run_id,
                        part=part,
                    ):
                        yield event

                state = await self._require_state(run_id)
                await self._persist_session_transcript(
                    run_id=run_id,
                    session_id=session_id,
                    state=state,
                )
                yield RunCompletedEvent(
                    result=self._to_run_result(
                        run_id=run_id,
                        state=state,
                    )
                )
            except ConversationResumeUnavailableError as exc:
                raise ConversationConflictError(str(exc)) from exc
            except Exception as exc:
                logger.exception(
                    "conversation resume stream failed run_id=%s",
                    run_id,
                )
                yield RunFailedEvent(
                    run_id=run_id,
                    error=AgentError(
                        code=ConversationErrorCode.EXECUTION_FAILED.value,
                        message=str(exc) or "Internal server error",
                    ),
                )

        return _stream()

    async def get_state(self, *, run_id: str) -> RunState:
        state = await self._require_state(run_id)
        return self._to_run_state(run_id=run_id, state=state)

    async def _require_state(self, run_id: str) -> dict[str, object]:
        state = await self._graph.get_state(run_id=run_id)
        if state is None:
            raise ConversationNotFoundError(f"conversation not found: {run_id}")
        return state

    def _to_run_result(
        self,
        *,
        run_id: str,
        state: dict[str, object],
    ) -> AgentRunResult:
        status = normalize_status(state)
        output = state.get("last_reply")
        if output is not None and not isinstance(output, str):
            output = str(output)
        error = None
        if status == "failed":
            error = AgentError(
                code=str(state.get("error_code") or ConversationErrorCode.EXECUTION_FAILED.value),
                message=str(output or "conversation failed"),
            )
        return AgentRunResult(
            run_id=run_id,
            session_id=self._session_id_from_state(state, default=run_id),
            capability_id=self._capability_id,
            status=status,
            output=output,
            pending_action=self._to_pending_action(state.get("pending_action")),
            error=error,
        )

    def _to_run_state(
        self,
        *,
        run_id: str,
        state: dict[str, object],
    ) -> RunState:
        output = state.get("last_reply")
        if output is not None and not isinstance(output, str):
            output = str(output)
        return RunState(
            run_id=run_id,
            session_id=self._session_id_from_state(state, default=run_id),
            capability_id=self._capability_id,
            status=normalize_status(state),
            output=output,
            pending_action=self._to_pending_action(state.get("pending_action")),
            metadata={"usage": usage_from_state(state).model_dump(mode="json")},
        )

    def _to_pending_action(self, payload: object) -> AgentPendingAction | None:
        if payload is None or not isinstance(payload, dict):
            return None
        tool_call_id = payload.get("tool_call_id")
        tool_name = payload.get("tool_name")
        tool_arguments = payload.get("tool_arguments")
        if not isinstance(tool_name, str) or not isinstance(tool_arguments, dict):
            return None
        return AgentPendingAction(
            action_id=tool_call_id if isinstance(tool_call_id, str) and tool_call_id else tool_name,
            action_name=tool_name,
            action_payload=tool_arguments,
            reason=str(payload.get("reason") or ""),
            risk_level=str(payload.get("risk_level") or "low"),
            display_payload=(
                payload.get("display_payload")
                if isinstance(payload.get("display_payload"), dict)
                else {}
            ),
        )

    def _events_from_part(
        self,
        *,
        run_id: str,
        part: StreamPart,
    ) -> list[AgentEvent]:
        events: list[AgentEvent] = []
        part_type = part.get("type")
        if part_type == "messages":
            chunk = self._message_chunk_from_part(part.get("data"))
            if not isinstance(chunk, (AIMessage, AIMessageChunk)) or chunk.tool_calls:
                return events
            text = text_from_message(chunk)
            if text:
                events.append(OutputDeltaEvent(run_id=run_id, delta=text))
            return events

        if part_type != "custom":
            return events

        payload = part.get("data")
        if isinstance(payload, dict) and payload.get("type") == "tool.started":
            tool_name = payload.get("tool_name")
            tool_arguments = payload.get("tool_arguments")
            if isinstance(tool_name, str) and isinstance(tool_arguments, dict):
                action_id = self._optional_str(payload.get("tool_call_id")) or tool_name
                events.append(
                    ActionStartedEvent(
                        run_id=run_id,
                        action_id=action_id,
                        action_name=tool_name,
                        action_payload=tool_arguments,
                    )
                )
        if isinstance(payload, dict) and payload.get("type") == "tool.finished":
            tool_name = payload.get("tool_name")
            tool_arguments = payload.get("tool_arguments")
            success = payload.get("success")
            latency_ms = payload.get("latency_ms")
            if (
                isinstance(tool_name, str)
                and isinstance(tool_arguments, dict)
                and isinstance(success, bool)
                and isinstance(latency_ms, (int, float))
            ):
                action_id = self._optional_str(payload.get("tool_call_id")) or tool_name
                error = payload.get("error")
                events.append(
                    ActionCompletedEvent(
                        run_id=run_id,
                        action_id=action_id,
                        action_name=tool_name,
                        action_payload=tool_arguments,
                        success=success,
                        latency_ms=float(latency_ms),
                        result=payload.get("result"),
                        error=error if isinstance(error, dict) else None,
                    )
                )
        if (
            isinstance(payload, dict)
            and payload.get("type") == "approval.required"
            and isinstance(payload.get("pending_action"), dict)
        ):
            pending_action = self._to_pending_action(payload["pending_action"])
            if pending_action is not None:
                events.append(
                    ActionRequiredEvent(
                        run_id=run_id,
                        pending_action=pending_action,
                    )
                )
        return events

    async def _persist_session_transcript(
        self,
        *,
        run_id: str,
        session_id: str,
        state: dict[str, object],
    ) -> None:
        messages = self._session_messages_from_state(state)
        await self._persist_session_messages(
            session_id=session_id,
            run_id=run_id,
            messages=messages,
        )

    async def _persist_session_messages(
        self,
        *,
        run_id: str,
        session_id: str,
        messages: list[BaseMessage],
    ) -> None:
        await self._session_store.upsert_session_messages(
            session_id=session_id,
            run_id=run_id,
            messages=messages,
        )

    def _session_messages_from_state(self, state: dict[str, object]) -> list[BaseMessage]:
        input_message = state.get("input_message")
        output_message = state.get("last_reply")
        messages: list[BaseMessage] = []
        if isinstance(input_message, str) and input_message:
            messages.append(HumanMessage(content=input_message))
        if isinstance(output_message, str) and output_message:
            messages.append(AIMessage(content=output_message))
        return messages

    def _session_id_from_state(self, state: dict[str, object], *, default: str) -> str:
        session_id = state.get("session_id")
        if isinstance(session_id, str) and session_id:
            return session_id
        return default

    def _message_chunk_from_part(self, payload: object) -> object | None:
        if isinstance(payload, tuple):
            return payload[0] if payload else None
        if isinstance(payload, list):
            return payload[0] if payload else None
        return payload

    def _optional_str(self, payload: object) -> str | None:
        if isinstance(payload, str):
            return payload
        return None

    def _new_session_id(self) -> str:
        return f"conv-{uuid4()}"

    def _new_run_id(self) -> str:
        return f"run-{uuid4()}"
