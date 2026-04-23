from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Literal

from langchain_core.messages import BaseMessage, HumanMessage
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, StreamPart

from agent_service.conversation import nodes
from agent_service.conversation.state import (
    ConversationContext,
    ConversationState,
    build_conversation_context,
    zero_usage,
)
from agent_service.llm.service import LLMService
from agent_service.tools.inline import InlineToolExecutor


class ConversationResumeUnavailableError(RuntimeError):
    pass


class ConversationGraph:
    def __init__(self, *, checkpointer: BaseCheckpointSaver | None) -> None:
        builder = StateGraph(ConversationState, ConversationContext)
        builder.add_node("plan", nodes.plan_node)
        builder.add_node("approval", nodes.approval_node)
        builder.add_node("tool_execute", nodes.tool_execute_node)
        builder.add_edge(START, "plan")
        builder.add_conditional_edges("plan", nodes.route_after_plan, ["approval", "tool_execute", END])
        builder.add_conditional_edges(
            "approval",
            nodes.route_after_approval,
            ["tool_execute", END],
        )
        builder.add_edge("tool_execute", "plan")
        self._graph = builder.compile(checkpointer=checkpointer)

    @staticmethod
    def _build_config(run_id: str) -> dict[str, dict[str, str]]:
        return {"configurable": {"thread_id": run_id}}

    @staticmethod
    def _build_turn_input(
        *,
        session_id: str,
        history_messages: list[BaseMessage],
        message: str,
    ) -> ConversationState:
        return {
            "session_id": session_id,
            "input_message": message,
            "status": "completed",
            "turn_step": 0,
            "messages": [*history_messages, HumanMessage(content=message)],
            "pending_tool_call": None,
            "pending_action": None,
            "last_reply": None,
            "error_code": None,
            "usage": zero_usage(),
        }

    @staticmethod
    def _build_resume_input(*, decision: Literal["approved", "rejected"]) -> Command:
        return Command(
            update={
                "last_reply": None,
                "error_code": None,
            },
            resume=decision,
        )

    def _build_context(
        self,
        *,
        llm_service: LLMService,
        tool_executor: InlineToolExecutor,
        max_steps: int,
        approval_timeout_seconds: int,
        request_id: str,
        stream_tokens: bool,
    ) -> ConversationContext:
        return build_conversation_context(
            llm_service=llm_service,
            tool_executor=tool_executor,
            max_steps=max_steps,
            approval_timeout_seconds=approval_timeout_seconds,
            request_id=request_id,
            stream_tokens=stream_tokens,
        )

    async def stream(
        self,
        *,
        llm_service: LLMService,
        tool_executor: InlineToolExecutor,
        run_id: str,
        session_id: str,
        history_messages: list[BaseMessage],
        message: str,
        request_id: str,
        max_steps: int,
        approval_timeout_seconds: int,
    ) -> AsyncIterator[StreamPart]:
        async for part in self._graph.astream(
            self._build_turn_input(
                session_id=session_id,
                history_messages=history_messages,
                message=message,
            ),
            config=self._build_config(run_id),
            context=self._build_context(
                llm_service=llm_service,
                tool_executor=tool_executor,
                max_steps=max_steps,
                approval_timeout_seconds=approval_timeout_seconds,
                request_id=request_id,
                stream_tokens=True,
            ),
            stream_mode=["messages", "custom"],
            version="v2",
        ):
            yield part

    async def stream_resume(
        self,
        *,
        llm_service: LLMService,
        tool_executor: InlineToolExecutor,
        run_id: str,
        decision: Literal["approved", "rejected"],
        request_id: str,
        max_steps: int,
        approval_timeout_seconds: int,
    ) -> AsyncIterator[StreamPart]:
        config = await self._validated_resume_config(run_id=run_id)
        async for part in self._graph.astream(
            self._build_resume_input(decision=decision),
            config=config,
            context=self._build_context(
                llm_service=llm_service,
                tool_executor=tool_executor,
                max_steps=max_steps,
                approval_timeout_seconds=approval_timeout_seconds,
                request_id=request_id,
                stream_tokens=True,
            ),
            stream_mode=["messages", "custom"],
            version="v2",
        ):
            yield part

    async def get_state(self, *, run_id: str) -> dict[str, object] | None:
        snapshot = await self._graph.aget_state(self._build_config(run_id))
        return snapshot.values or None

    async def _validated_resume_config(
        self,
        *,
        run_id: str,
    ) -> dict[str, dict[str, str]]:
        config = self._build_config(run_id)
        snapshot = await self._graph.aget_state(config)
        state = snapshot.values or {}
        if (
            not state
            or not snapshot.interrupts
            or state.get("status") != "awaiting_action"
            or state.get("pending_action") is None
        ):
            raise ConversationResumeUnavailableError(
                "conversation is not currently waiting for approval"
            )
        return config
