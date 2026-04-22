from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class ChatMessageRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    conversation_id: str | None = None


MessageRequest = ChatMessageRequest


class ResumeConversationRequest(BaseModel):
    conversation_id: str = Field(min_length=1)
    decision: Literal["approved", "rejected"]


ResumeRequest = ResumeConversationRequest

__all__ = [
    "MessageRequest",
    "ResumeRequest",
]
