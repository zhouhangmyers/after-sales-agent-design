from __future__ import annotations

from dataclasses import dataclass
from typing import TypeAlias

from agent_service.conversation.models import ConversationError, ConversationTurn, PendingAction


@dataclass(slots=True, frozen=True)
class ConversationStarted:
    conversation_id: str


@dataclass(slots=True, frozen=True)
class ConversationToken:
    conversation_id: str
    text: str


@dataclass(slots=True, frozen=True)
class ConversationApprovalRequired:
    conversation_id: str
    pending_action: PendingAction


@dataclass(slots=True, frozen=True)
class ConversationCompleted:
    turn: ConversationTurn


@dataclass(slots=True, frozen=True)
class ConversationFailed:
    conversation_id: str
    error: ConversationError


ConversationEvent: TypeAlias = (
    ConversationStarted
    | ConversationToken
    | ConversationApprovalRequired
    | ConversationCompleted
    | ConversationFailed
)

__all__ = [
    "ConversationApprovalRequired",
    "ConversationCompleted",
    "ConversationEvent",
    "ConversationFailed",
    "ConversationStarted",
    "ConversationToken",
]
