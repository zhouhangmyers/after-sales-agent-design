from __future__ import annotations

from langchain_core.messages import ToolMessage

from agent_core.contracts.run_events import ActionCompletedEvent, ActionStartedEvent
from agent_runtime.langchain.event_mapper import ToolInvocation, events_from_stream_part


def test_tool_task_start_and_result_are_correlated_by_task_id() -> None:
    tool_tasks: dict[str, ToolInvocation] = {}

    started = events_from_stream_part(
        run_id="run-1",
        part={
            "type": "tasks",
            "data": {
                "id": "task-1",
                "name": "tools",
                "input": {
                    "tool_call": {
                        "id": "call-1",
                        "name": "add",
                        "args": {"a": 1, "b": 2},
                    }
                },
            },
        },
        tool_tasks=tool_tasks,
    )

    assert started == [
        ActionStartedEvent(
            run_id="run-1",
            action_id="call-1",
            action_name="add",
            action_payload={"a": 1, "b": 2},
        )
    ]
    assert "task-1" in tool_tasks

    completed = events_from_stream_part(
        run_id="run-1",
        part={
            "type": "tasks",
            "data": {
                "id": "task-1",
                "name": "tools",
                "result": {
                    "messages": [
                        ToolMessage(
                            content="3",
                            name="add",
                            tool_call_id="call-1",
                            artifact={"success": True, "result": 3},
                        )
                    ]
                },
            },
        },
        tool_tasks=tool_tasks,
    )

    assert len(completed) == 1
    assert isinstance(completed[0], ActionCompletedEvent)
    assert completed[0].action_id == "call-1"
    assert completed[0].action_name == "add"
    assert completed[0].action_payload == {"a": 1, "b": 2}
    assert completed[0].success is True
    assert completed[0].result == 3
    assert tool_tasks == {}


def test_tool_task_result_without_start_is_ignored() -> None:
    events = events_from_stream_part(
        run_id="run-1",
        part={
            "type": "tasks",
            "data": {
                "id": "task-1",
                "name": "tools",
                "result": {
                    "messages": [
                        ToolMessage(
                            content="3",
                            name="add",
                            tool_call_id="call-1",
                            artifact={"success": True, "result": 3},
                        )
                    ]
                },
            },
        },
        tool_tasks={},
    )

    assert events == []


def test_tool_task_start_without_task_id_is_ignored() -> None:
    tool_tasks: dict[str, ToolInvocation] = {}

    events = events_from_stream_part(
        run_id="run-1",
        part={
            "type": "tasks",
            "data": {
                "name": "tools",
                "input": {
                    "tool_call": {
                        "id": "call-1",
                        "name": "add",
                        "args": {"a": 1, "b": 2},
                    }
                },
            },
        },
        tool_tasks=tool_tasks,
    )

    assert events == []
    assert tool_tasks == {}


def test_tool_task_start_with_malformed_args_is_ignored() -> None:
    tool_tasks: dict[str, ToolInvocation] = {}

    events = events_from_stream_part(
        run_id="run-1",
        part={
            "type": "tasks",
            "data": {
                "id": "task-1",
                "name": "tools",
                "input": {
                    "tool_call": {
                        "id": "call-1",
                        "name": "add",
                        "args": ["not", "a", "dict"],
                    }
                },
            },
        },
        tool_tasks=tool_tasks,
    )

    assert events == []
    assert tool_tasks == {}


def test_tool_task_start_without_tool_call_id_is_ignored() -> None:
    tool_tasks: dict[str, ToolInvocation] = {}

    events = events_from_stream_part(
        run_id="run-1",
        part={
            "type": "tasks",
            "data": {
                "id": "task-1",
                "name": "tools",
                "input": {
                    "tool_call": {
                        "name": "add",
                        "args": {"a": 1, "b": 2},
                    }
                },
            },
        },
        tool_tasks=tool_tasks,
    )

    assert events == []
    assert tool_tasks == {}
