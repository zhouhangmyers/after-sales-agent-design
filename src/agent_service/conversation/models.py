from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from agent_service.llm.types import TokenUsage

ConversationStatus = Literal["completed", "awaiting_action", "failed"]


class PendingActionModel(BaseModel):
    kind: Literal["tool_approval"] = "tool_approval"
    tool_name: str
    tool_arguments: dict[str, Any] = Field(default_factory=dict)
    reason: str | None = None
    risk_level: str = "low"


PendingAction = PendingActionModel


class ConversationErrorModel(BaseModel):
    code: str
    message: str


ConversationError = ConversationErrorModel


class ConversationTurnResponse(BaseModel):
    conversation_id: str
    status: ConversationStatus
    reply: str | None = None
    pending_action: PendingAction | None = None
    usage: TokenUsage = Field(default_factory=TokenUsage)
    error: ConversationError | None = None


ConversationTurn = ConversationTurnResponse


class ConversationStateResponse(BaseModel):
    conversation_id: str
    status: ConversationStatus
    last_reply: str | None = None
    pending_action: PendingAction | None = None


ConversationSnapshot = ConversationStateResponse

__all__ = [
    "ConversationError",
    "ConversationSnapshot",
    "ConversationStatus",
    "ConversationTurn",
    "PendingAction",
]
