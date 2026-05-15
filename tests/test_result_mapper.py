from __future__ import annotations

from typing import cast

import pytest
from langchain_core.messages import AIMessage

from agent_core.contracts.agent_definition import AgentDefinition
from agent_runtime.langchain.result_mapper import to_run_result
from agent_runtime.langchain.state import LangChainAgentState


def test_to_run_result_requires_session_id_in_state() -> None:
    definition = AgentDefinition(
        capability_id="support",
        system_prompt="Help users.",
        tools=(),
    )

    with pytest.raises(RuntimeError, match="session_id is required"):
        to_run_result(
            definition=definition,
            run_id="run-1",
            state_values=cast(
                LangChainAgentState,
                {"messages": [AIMessage(content="done")]},
            ),
            interrupts=(),
        )
