from __future__ import annotations

from agent_service.config import Settings
from agent_service.services.orchestrator_service import OrchestratorService
from agent_service.services.planner_service import build_planner_service
from agent_service.services.planners import PlannerCallTrace, PlannerDecision, TokenUsage
from agent_service.services.runtime_service import RuntimeService


class StubPlannerService:
    def __init__(self, traces: list[PlannerCallTrace]) -> None:
        self._traces = list(traces)

    def plan(self, **_: object) -> PlannerCallTrace:
        return self._traces.pop(0)


def _trace(
    *,
    decision: PlannerDecision | None = None,
    success: bool = True,
    error_message: str | None = None,
) -> PlannerCallTrace:
    return PlannerCallTrace(
        provider="demo",
        model="demo-structured-planner-v1",
        prompt_name="tool-planner",
        prompt_version="v1",
        request_payload={"user_message": "hello"},
        raw_response=(decision.model_dump() if decision is not None else {"error": error_message}),
        decision=decision,
        usage=TokenUsage(prompt_tokens=4, completion_tokens=1, total_tokens=5),
        latency_ms=10.0,
        attempts=1,
        success=success,
        error_message=error_message,
    )


def _demo_orchestrator_service() -> OrchestratorService:
    return OrchestratorService(
        planner_service=build_planner_service(Settings()),
        runtime_service=RuntimeService(),
    )


def test_orchestrator_service_executes_tool_then_responds() -> None:
    service = _demo_orchestrator_service()

    execution = service.run(
        session_id="sess-week3",
        message="please add a=3 b=7",
        request_id="req-week3",
    )

    assert execution.workflow_status == "completed"
    assert len(execution.tool_executions) == 1
    assert len(execution.planner_calls) == 2
    assert execution.tool_executions[0].request.action == "add"
    assert execution.tool_executions[0].result.success is True
    assert execution.tool_executions[0].result.result == 10
    assert execution.usage.total_tokens > 0


def test_orchestrator_service_returns_direct_reply_when_no_tool_is_needed() -> None:
    service = _demo_orchestrator_service()

    execution = service.run(
        session_id="sess-plain",
        message="hello runtime",
        request_id="req-plain",
    )

    assert execution.workflow_status == "completed"
    assert execution.tool_executions == []
    assert len(execution.planner_calls) == 1
    assert "当前 demo planner 没找到必须调用工具的场景" in execution.reply


def test_orchestrator_service_returns_failed_status_when_planner_fails() -> None:
    failing_trace = _trace(success=False, error_message="timeout")
    service = OrchestratorService(
        planner_service=StubPlannerService([failing_trace]),
        runtime_service=RuntimeService(),
    )

    execution = service.run(
        session_id="sess-fail",
        message="hello",
        request_id="req-fail",
    )

    assert execution.workflow_status == "failed"
    assert "规划器调用失败" in execution.reply
    assert execution.tool_executions == []
    assert execution.usage.total_tokens == 5
