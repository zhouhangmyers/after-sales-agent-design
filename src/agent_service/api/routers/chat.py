from __future__ import annotations

import json
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, HTTPException
from sse_starlette.sse import EventSourceResponse

from agent_service.api.auth import require_api_key
from agent_service.api.deps import get_conversation_service
from agent_service.api.schemas.conversation import (
    MessageRequest,
    ResumeRequest,
)
from agent_service.conversation.events import (
    ConversationApprovalRequired,
    ConversationCompleted,
    ConversationEvent,
    ConversationFailed,
    ConversationStarted,
    ConversationToken,
)
from agent_service.conversation.models import ConversationSnapshot, ConversationTurn
from agent_service.conversation.service import (
    ConversationConflictError,
    ConversationNotFoundError,
)

router = APIRouter(tags=["chat"])


def _sse_response(stream: AsyncIterator[dict[str, str]]) -> EventSourceResponse:
    return EventSourceResponse(
        stream,
        media_type="text/event-stream",
        sep="\n",
        headers={
            "Cache-Control": "no-store",
            "X-Accel-Buffering": "no",
        },
    )


def _map_error(exc: Exception) -> HTTPException:
    if isinstance(exc, ConversationNotFoundError):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, ConversationConflictError):
        return HTTPException(status_code=409, detail=str(exc))
    raise exc


def _encode_sse(event: str, payload: dict[str, object]) -> dict[str, str]:
    return {
        "event": event,
        "data": json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
    }


def _event_to_sse_message(event: ConversationEvent) -> dict[str, str]:
    if isinstance(event, ConversationStarted):
        return _encode_sse("conversation", {"conversation_id": event.conversation_id})
    if isinstance(event, ConversationToken):
        return _encode_sse(
            "token",
            {
                "conversation_id": event.conversation_id,
                "text": event.text,
            },
        )
    if isinstance(event, ConversationApprovalRequired):
        return _encode_sse(
            "approval_required",
            {
                "conversation_id": event.conversation_id,
                "pending_action": event.pending_action.model_dump(mode="json"),
            },
        )
    if isinstance(event, ConversationCompleted):
        return _encode_sse("complete", event.turn.model_dump(mode="json"))
    if isinstance(event, ConversationFailed):
        return _encode_sse(
            "error",
            {
                "conversation_id": event.conversation_id,
                "code": event.error.code,
                "message": event.error.message,
            },
        )
    raise TypeError(f"unsupported conversation event: {type(event).__name__}")


async def _sse_stream(stream: AsyncIterator[ConversationEvent]) -> AsyncIterator[dict[str, str]]:
    async for event in stream:
        yield _event_to_sse_message(event)


@router.post(
    "/chat/messages",
    response_model=ConversationTurn,
    operation_id="post_chat_message_api_v2_chat_messages_post",
)
async def post_message(
    payload: MessageRequest,
    conversation_service=Depends(get_conversation_service),
    _: None = Depends(require_api_key),
) -> ConversationTurn:
    try:
        return await conversation_service.send_message(
            conversation_id=payload.conversation_id,
            message=payload.message,
        )
    except (ConversationNotFoundError, ConversationConflictError) as exc:
        raise _map_error(exc) from exc


@router.post(
    "/chat/messages/stream",
    operation_id="stream_chat_message_api_v2_chat_messages_stream_post",
)
async def stream_message(
    payload: MessageRequest,
    conversation_service=Depends(get_conversation_service),
    _: None = Depends(require_api_key),
):
    try:
        stream = await conversation_service.stream_message(
            conversation_id=payload.conversation_id,
            message=payload.message,
        )
        return _sse_response(_sse_stream(stream))
    except (ConversationNotFoundError, ConversationConflictError) as exc:
        raise _map_error(exc) from exc


@router.post(
    "/chat/resume",
    response_model=ConversationTurn,
    operation_id="resume_chat_message_api_v2_chat_resume_post",
)
async def resume_conversation(
    payload: ResumeRequest,
    conversation_service=Depends(get_conversation_service),
    _: None = Depends(require_api_key),
) -> ConversationTurn:
    try:
        return await conversation_service.resume(
            conversation_id=payload.conversation_id,
            decision=payload.decision,
        )
    except (ConversationNotFoundError, ConversationConflictError) as exc:
        raise _map_error(exc) from exc


@router.get(
    "/chat/state/{conversation_id}",
    response_model=ConversationSnapshot,
    operation_id="get_chat_state_api_v2_chat_state__conversation_id__get",
)
async def get_conversation_state(
    conversation_id: str,
    conversation_service=Depends(get_conversation_service),
    _: None = Depends(require_api_key),
) -> ConversationSnapshot:
    try:
        return await conversation_service.get_state(conversation_id=conversation_id)
    except (ConversationNotFoundError, ConversationConflictError) as exc:
        raise _map_error(exc) from exc
