from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sse_starlette.sse import EventSourceResponse

from agent_service.api.deps import get_db_session, get_event_cache, get_orchestrator_service
from agent_service.schemas.chat import ChatRequest, ChatResponse
from agent_service.services.cache_service import EventCache
from agent_service.services.chat_service import ChatService
from agent_service.services.orchestrator_service import OrchestratorService
from agent_service.services.stream_service import StreamService

router = APIRouter(tags=["chat"])


@router.post("/chat", response_model=ChatResponse)
def create_chat_response(
    payload: ChatRequest,
    db_session: Session = Depends(get_db_session),
    orchestrator_service: OrchestratorService = Depends(get_orchestrator_service),
) -> ChatResponse:
    service = ChatService(db_session, orchestrator_service)
    return service.handle_chat(payload)


@router.get("/chat/stream")
async def stream_chat_response(
    session_id: str = Query(min_length=1),
    message: str = Query(min_length=1),
    db_session: Session = Depends(get_db_session),
    orchestrator_service: OrchestratorService = Depends(get_orchestrator_service),
    event_cache: EventCache = Depends(get_event_cache),
) -> EventSourceResponse:
    payload = ChatRequest(session_id=session_id, message=message)
    # 当前 Week 3 的流式接口仍然是“先拿完整结果，再拆成 SSE 事件”。
    # 这里保留 /chat/stream 这个外部协议，但内部明确走 post-response SSE。
    response = ChatService(db_session, orchestrator_service).handle_chat(payload)
    stream_service = StreamService(event_cache)
    return EventSourceResponse(stream_service.iter_post_response_events(response))
