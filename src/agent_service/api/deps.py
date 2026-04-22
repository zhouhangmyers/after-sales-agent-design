from __future__ import annotations

from fastapi import Request

from agent_service.conversation.service import ConversationService


async def get_conversation_service(request: Request) -> ConversationService:
    return request.app.state.conversation_service
