from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Literal

from agent_service.contracts.actions import AgentExecutionContext
from agent_service.contracts.capability import AgentCapability
from agent_service.contracts.events import AgentEvent
from agent_service.contracts.models import ActorContext, RunState
from agent_service.conversation.service import (
    ConversationNotFoundError,
    ConversationService,
)
from agent_service.infrastructure.actions.dispatcher import LangChainActionDispatcher
from agent_service.infrastructure.state_store.in_memory_store import InMemoryStateStore
from agent_service.infrastructure.state_store.langgraph_postgres_store import (
    LangGraphPostgresStateStore,
)
from agent_service.llm.service import LLMService
from agent_service.llm.types import ChatClient

RuntimeStateStore = InMemoryStateStore | LangGraphPostgresStateStore


class WorkflowEngine:
    def __init__(
        self,
        *,
        chat_client: ChatClient,
        action_dispatcher: LangChainActionDispatcher,
        state_store: RuntimeStateStore,
        llm_timeout_seconds: float,
        llm_max_retries: int,
        max_steps: int,
        approval_timeout_seconds: int,
    ) -> None:
        self._chat_client = chat_client
        self._action_dispatcher = action_dispatcher
        self._state_store = state_store
        self._llm_timeout_seconds = llm_timeout_seconds
        self._llm_max_retries = llm_max_retries
        self._max_steps = max_steps
        self._approval_timeout_seconds = approval_timeout_seconds

    async def stream_run(
        self,
        *,
        capability: AgentCapability,
        input: str,
        session_id: str | None,
        actor: ActorContext,
    ) -> AsyncIterator[AgentEvent]:
        await self._ensure_store()
        conversation_service = self._build_conversation_service(
            capability=capability,
            actor=actor,
        )
        return await conversation_service.stream_message(
            session_id=session_id,
            message=input,
        )

    async def stream_action(
        self,
        *,
        capability: AgentCapability,
        run_id: str,
        action_id: str,
        decision: Literal["approved", "rejected"],
        actor: ActorContext,
    ) -> AsyncIterator[AgentEvent]:
        await self._ensure_store()
        conversation_service = self._build_conversation_service(
            capability=capability,
            actor=actor,
        )
        state = await conversation_service.get_state(run_id=run_id)
        pending_action = state.pending_action
        if pending_action is not None:
            if action_id not in {
                pending_action.action_id,
                pending_action.action_name,
            }:
                raise ValueError(
                    f"action_id does not match pending action: {action_id}"
                )
        return await conversation_service.stream_resume(
            run_id=run_id,
            decision=decision,
        )

    async def get_state(self, *, run_id: str, capability: AgentCapability) -> RunState:
        await self._ensure_store()
        conversation_service = self._build_conversation_service(
            capability=capability,
            actor=None,
        )
        try:
            return await conversation_service.get_state(run_id=run_id)
        except ConversationNotFoundError as exc:
            raise LookupError(str(exc)) from exc

    async def _ensure_store(self) -> None:
        await self._state_store.ensure_initialized()

    def _build_conversation_service(
        self,
        *,
        capability: AgentCapability,
        actor: ActorContext | None,
    ) -> ConversationService:
        execution_context = AgentExecutionContext(
            capability_id=capability.capability_id,
            actor_id=actor.actor_id if actor is not None else None,
            metadata=actor.metadata if actor is not None else {},
        )
        tool_executor = self._action_dispatcher.build_tool_executor(
            capability=capability,
            execution_context=execution_context,
        )
        llm_service = LLMService(
            client=self._chat_client,
            system_prompt=self._compile_prompt(capability),
            timeout_seconds=self._llm_timeout_seconds,
            max_retries=self._llm_max_retries,
        )
        return ConversationService(
            capability_id=capability.capability_id,
            llm_service=llm_service,
            tool_executor=tool_executor,
            max_steps=self._max_steps,
            approval_timeout_seconds=self._approval_timeout_seconds,
            checkpointer=self._state_store.get_checkpointer(),
            session_store=self._state_store,
        )

    def _compile_prompt(self, capability: AgentCapability) -> str:
        action_descriptions = "".join(
            f"当需要时可调用 `{action.name}`：{action.description}。"
            for action in capability.actions
        )
        selection_rules = "".join(capability.action_selection_rules)
        response_rules = "".join(capability.response_rules)
        return (
            f"你是{capability.role_title}。"
            f"你的目标是：{capability.domain_objective}。"
            f"{selection_rules}"
            f"{response_rules}"
            f"{action_descriptions}"
            "每轮最多调用一个动作。"
            "如果不需要动作，直接用简洁中文回答。"
        )
