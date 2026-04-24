from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from sse_starlette.sse import EventSourceResponse

from agent_service.contracts.events import (
    ActionCompletedEvent,
    ActionRequiredEvent,
    ActionStartedEvent,
    OutputDeltaEvent,
    RunCompletedEvent,
    RunFailedEvent,
    RunStartedEvent,
)
from agent_service.contracts.models import ActorContext
from app_api.deps import get_after_sales_assistant_service, require_api_key
from app_api.schemas.runs import CreateRunRequest, RunResponse
from app_api.services.after_sales_assistant import AfterSalesAssistantService

router = APIRouter(prefix="/api/after-sales", tags=["after-sales-runs"])


def _encode_sse(event: str, payload: dict[str, object]) -> dict[str, str]:
    return {
        "event": event,
        "data": json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
    }


def _run_response_payload(
    *,
    run_id: str,
    session_id: str,
    status: str,
    output: str | None,
    pending_action: Any,
    error: Any,
) -> dict[str, object]:
    return {
        "run_id": run_id,
        "session_id": session_id,
        "status": status,
        "output": output,
        "pending_action": pending_action.model_dump(mode="json") if pending_action else None,
        "error": error.model_dump(mode="json") if error else None,
    }


def _map_event(event: object) -> dict[str, str]:
    if isinstance(event, RunStartedEvent):
        return _encode_sse(
            "run.started",
            {
                "run_id": event.run_id,
                "session_id": event.session_id,
            },
        )
    if isinstance(event, OutputDeltaEvent):
        return _encode_sse("output.delta", {"run_id": event.run_id, "delta": event.delta})
    if isinstance(event, ActionStartedEvent):
        return _encode_sse(
            "action.started",
            {
                "run_id": event.run_id,
                "action_id": event.action_id,
                "action_name": event.action_name,
                "action_payload": event.action_payload,
            },
        )
    if isinstance(event, ActionCompletedEvent):
        return _encode_sse(
            "action.completed",
            {
                "run_id": event.run_id,
                "action_id": event.action_id,
                "action_name": event.action_name,
                "action_payload": event.action_payload,
                "success": event.success,
                "latency_ms": event.latency_ms,
                "result": event.result,
                "error": event.error,
            },
        )
    if isinstance(event, ActionRequiredEvent):
        return _encode_sse(
            "action.required",
            {
                "run_id": event.run_id,
                "pending_action": event.pending_action.model_dump(mode="json"),
            },
        )
    if isinstance(event, RunCompletedEvent):
        return _encode_sse(
            "run.completed",
            _run_response_payload(
                run_id=event.result.run_id,
                session_id=event.result.session_id,
                status=event.result.status,
                output=event.result.output,
                pending_action=event.result.pending_action,
                error=event.result.error,
            ),
        )
    if isinstance(event, RunFailedEvent):
        return _encode_sse(
            "run.failed",
            {
                "run_id": event.run_id,
                "error": event.error.model_dump(mode="json"),
            },
        )
    raise TypeError(f"unsupported event type: {type(event).__name__}")


async def _sse_stream(stream: AsyncIterator[object]) -> AsyncIterator[dict[str, str]]:
    try:
        async for event in stream:
            yield _map_event(event)
    finally:
        close_stream = getattr(stream, "aclose", None)
        if callable(close_stream):
            await close_stream()


@router.post("/runs", response_model=RunResponse)
async def create_run(
    payload: CreateRunRequest,
    assistant_service: Annotated[
        AfterSalesAssistantService, Depends(get_after_sales_assistant_service)
    ],
    _: None = Depends(require_api_key),
) -> RunResponse:
    result = await assistant_service.run(
        message=payload.message,
        session_id=payload.session_id,
        actor=ActorContext(actor_id=payload.actor_id, metadata=payload.actor_metadata),
    )
    return RunResponse.model_validate(
        _run_response_payload(
            run_id=result.run_id,
            session_id=result.session_id,
            status=result.status,
            output=result.output,
            pending_action=result.pending_action,
            error=result.error,
        )
    )


@router.post("/runs/stream")
async def stream_run(
    payload: CreateRunRequest,
    assistant_service: Annotated[
        AfterSalesAssistantService, Depends(get_after_sales_assistant_service)
    ],
    _: None = Depends(require_api_key),
) -> EventSourceResponse:
    stream = assistant_service.stream(
        message=payload.message,
        session_id=payload.session_id,
        actor=ActorContext(actor_id=payload.actor_id, metadata=payload.actor_metadata),
    )
    return EventSourceResponse(_sse_stream(stream), media_type="text/event-stream")


@router.get("/runs/{run_id}", response_model=RunResponse)
async def get_run_state(
    run_id: str,
    assistant_service: Annotated[
        AfterSalesAssistantService, Depends(get_after_sales_assistant_service)
    ],
    _: None = Depends(require_api_key),
) -> RunResponse:
    try:
        state = await assistant_service.get_state(run_id=run_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return RunResponse.model_validate(
        _run_response_payload(
            run_id=state.run_id,
            session_id=state.session_id,
            status=state.status,
            output=state.output,
            pending_action=state.pending_action,
            error=state.error,
        )
    )
