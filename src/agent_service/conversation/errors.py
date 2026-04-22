from __future__ import annotations

from enum import StrEnum


class ConversationErrorCode(StrEnum):
    EXECUTION_FAILED = "conversation.execution_failed"
    RESUME_UNAVAILABLE = "conversation.resume_unavailable"
    MAX_STEPS_EXCEEDED = "conversation.max_steps_exceeded"
    INVALID_APPROVAL = "conversation.invalid_approval"
    MISSING_PENDING_ACTION = "conversation.missing_pending_action"
    MISSING_TOOL_CALL = "conversation.missing_tool_call"
    LLM_INVOCATION_FAILED = "llm.invocation_failed"
