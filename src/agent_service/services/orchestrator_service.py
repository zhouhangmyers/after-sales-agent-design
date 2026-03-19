from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, TYPE_CHECKING

from agent_service.services.planner_service import build_planner_service
from agent_service.services.planners import PlannerCallTrace, TokenUsage, ToolObservation, ToolSchema

if TYPE_CHECKING:
    from agent_service.config import Settings
    from agent_service.services.runtime_service import RuntimeExecution


# 这是编排层跑完整个 agent loop 后，交回给 ChatService 的总结果包。
# 大白话讲：
# ChatService 不需要知道 loop 里面每一步是怎么跑的，
# 它只需要拿到这一整包结果，然后去做后续落库和响应组装。
# 这里面装的是：
# - 最终回复是什么
# - 中间执行过哪些工具
# - planner 一共想了几轮
# - 这次总共用了多少 token
# - 这次 workflow 最后是成功还是失败
@dataclass(slots=True, frozen=True)
class AgentLoopExecution:
    reply: str
    tool_executions: list[RuntimeExecution]
    planner_calls: list[PlannerCallTrace]
    usage: TokenUsage
    workflow_status: str


# 这是编排层眼里对“规划器”的最低要求。
# 大白话讲：
# 只要某个对象能根据“用户消息 + 可用工具 + 前面工具执行后的观察结果”
# 决定下一步动作，它就可以被拿来当 planner 用。
class PlannerLoopEngine(Protocol):
    def plan(
        self,
        *,
        session_id: str,
        user_message: str,
        tool_schemas: list[ToolSchema],
        observations: list[ToolObservation],
    ) -> PlannerCallTrace:
        ...


# 这是编排层眼里对“执行层”的最低要求。
# 编排层自己不执行工具，它只会要求执行层提供：
# 1. 当前可用工具 schema
# 2. 真正执行动作
# 3. 把工具结果翻译成 observation
class LoopRuntime(Protocol):
    def available_tool_schemas(self, allowed_tools: tuple[str, ...] | None = None) -> list[ToolSchema]:
        ...

    def execute_action(
        self,
        action: str,
        arguments: dict[str, object],
        *,
        request_id: str,
        source: str,
    ) -> RuntimeExecution:
        ...

    def build_observation(self, execution: RuntimeExecution) -> ToolObservation:
        ...


# 这是当前 Week 3 的最小 agent loop 控制器。
# 它只负责把“规划 -> 执行 -> observation -> 再规划”这一整轮流程串起来。
@dataclass(slots=True)
class AgentLoopRunner:
    planner_service: PlannerLoopEngine
    max_steps: int = 4

    def run(
        self,
        *,
        runtime: LoopRuntime,
        session_id: str,
        message: str,
        request_id: str,
    ) -> AgentLoopExecution:
        observations: list[ToolObservation] = []
        tool_executions: list[RuntimeExecution] = []
        planner_calls: list[PlannerCallTrace] = []

        for _ in range(self.max_steps):
            # 先进入“规划”阶段：
            # 把当前上下文交给 planner，让它判断这一轮下一步该干嘛。
            # 这里给 planner 的信息包括：
            # - 当前是哪一个 session
            # - 用户最初说了什么
            # - 现在有哪些工具可以用
            # - 前面工具执行后积累下来的 observations
            planner_trace = self.planner_service.plan(
                session_id=session_id,
                user_message=message,
                tool_schemas=runtime.available_tool_schemas(),
                observations=observations,
            )
            # 把这一轮 planner 的思考痕迹记下来，
            # 后面 ChatService 会统一把这些 trace 落库到 llm_calls。
            planner_calls.append(planner_trace)

            if not planner_trace.success or planner_trace.decision is None:
                return AgentLoopExecution(
                    reply=f"规划器调用失败：{planner_trace.error_message or 'unknown error'}。",
                    tool_executions=tool_executions,
                    planner_calls=planner_calls,
                    usage=TokenUsage.combine([trace.usage for trace in planner_calls]),
                    workflow_status="failed",
                )

            decision = planner_trace.decision
            if decision.kind == "respond":
                return AgentLoopExecution(
                    reply=decision.response or "规划器没有生成最终回复。",
                    tool_executions=tool_executions,
                    planner_calls=planner_calls,
                    usage=TokenUsage.combine([trace.usage for trace in planner_calls]),
                    workflow_status="completed",
                )

            if not decision.tool_name:
                return AgentLoopExecution(
                    reply="规划器返回了空的工具名，无法继续执行。",
                    tool_executions=tool_executions,
                    planner_calls=planner_calls,
                    usage=TokenUsage.combine([trace.usage for trace in planner_calls]),
                    workflow_status="failed",
                )

            execution = runtime.execute_action(
                decision.tool_name,
                decision.tool_arguments,
                request_id=request_id,
                source="planner_service",
            )
            tool_executions.append(execution)
            observations.append(runtime.build_observation(execution))

        return AgentLoopExecution(
            reply="agent loop 已达到最大步数限制，未能在限定步数内生成最终回复。",
            tool_executions=tool_executions,
            planner_calls=planner_calls,
            usage=TokenUsage.combine([trace.usage for trace in planner_calls]),
            workflow_status="failed",
        )


class OrchestratorService:
    # 这是当前 Week 3 的编排服务类。
    # 你可以把它理解成：
    # “智能体整轮流程的总控入口”。
    #
    # 它自己不负责想，也不负责真正干活，
    # 它负责把两边串起来：
    # - planner_service：负责决定下一步做什么
    # - runtime_service：负责真正执行工具
    #
    # 所以对外部来说，只要拿到这个类，
    # 就相当于拿到了“跑完整轮 agent loop”的总入口。
    def __init__(
        self,
        *,
        planner_service: PlannerLoopEngine,
        runtime_service: LoopRuntime,
        max_steps: int = 4,
    ) -> None:
        # 记录执行层。
        # 后面 loop 真要调用工具时，会通过它去执行。
        self._runtime_service = runtime_service
        # 在初始化编排服务时，顺手把 loop 控制器也建好。
        # loop 控制器会记住 planner，并在运行时一轮轮去问 planner 下一步该干嘛。
        self._loop_runner = AgentLoopRunner(planner_service=planner_service, max_steps=max_steps)

    @classmethod
    def from_settings(
        cls,
        settings: Settings,
        *,
        runtime_service: LoopRuntime,
    ) -> OrchestratorService:
        # 这是一个“按配置快速构造编排服务”的入口。
        # 大白话讲：
        # 你给我 settings 和一个执行层 runtime，
        # 我就帮你把 planner、最大步数这些都装配好，
        # 最后直接返回一个能跑的 OrchestratorService。
        return cls(
            planner_service=build_planner_service(settings),
            runtime_service=runtime_service,
            max_steps=settings.agent_max_steps,
        )

    def run(
        self,
        *,
        session_id: str,
        message: str,
        request_id: str,
    ) -> AgentLoopExecution:
        # 对外最核心的调用入口。
        # 外部只需要给：
        # - session_id
        # - 用户消息
        # - request_id
        #
        # 剩下的 loop 细节都由编排层内部自己处理：
        # - 问 planner
        # - 调工具
        # - 把结果变成 observation
        # - 再进入下一轮 planner
        #
        # 最后返回一整包 AgentLoopExecution 给 ChatService。
        return self._loop_runner.run(
            runtime=self._runtime_service,
            session_id=session_id,
            message=message,
            request_id=request_id,
        )
