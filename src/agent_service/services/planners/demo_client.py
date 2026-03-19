from __future__ import annotations

import re
from typing import Any

from .base import PlannerDecision, PlannerRequest, TokenUsage, ToolObservation, dump_payload


class DemoPlannerClient:
    provider = "demo"

    def __init__(self, model: str = "demo-structured-planner-v1") -> None:
        self.model = model

    def plan(self, request: PlannerRequest) -> tuple[PlannerDecision, dict[str, Any], TokenUsage]:
        if request.observations:
            decision = self._respond_from_last_observation(request.observations[-1])
        else:
            decision = self._plan_first_step(request.user_message)

        # 把 PlannerDecision 这个 Pydantic 对象导出成普通字典，
        # 这里把它当成 demo planner 的“原始响应内容”。
        raw_response = decision.model_dump()
        usage = TokenUsage.from_texts(request.prompt.content, dump_payload(raw_response))
        return decision, raw_response, usage

    def _respond_from_last_observation(self, observation: ToolObservation) -> PlannerDecision:
        if observation.success:
            result_repr = dump_payload(observation.result)
            return PlannerDecision(
                kind="respond",
                response=f"我已经调用 `{observation.tool_name}` 完成处理，结果是 {result_repr}。",
                rationale="Respond after a successful tool observation.",
            )

        error_message = observation.error_message or "unknown error"
        return PlannerDecision(
            kind="respond",
            response=f"工具 `{observation.tool_name}` 执行失败：{error_message}。",
            rationale="Respond after a failed tool observation.",
        )

    def _plan_first_step(self, message: str) -> PlannerDecision:
        if "divide" in message or "除" in message:
            arguments = self._extract_number_arguments(message)
            if arguments is not None:
                return PlannerDecision(
                    kind="tool_call",
                    tool_name="divide",
                    tool_arguments=arguments,
                    rationale="Use the divide tool for division requests.",
                )

        if "multiply" in message or "乘" in message:
            arguments = self._extract_number_arguments(message)
            if arguments is not None:
                return PlannerDecision(
                    kind="tool_call",
                    tool_name="multiply",
                    tool_arguments=arguments,
                    rationale="Use the multiply tool for multiplication requests.",
                )

        if "add" in message or "加" in message:
            arguments = self._extract_number_arguments(message)
            if arguments is not None:
                return PlannerDecision(
                    kind="tool_call",
                    tool_name="add",
                    tool_arguments=arguments,
                    rationale="Use the add tool for addition requests.",
                )

        city_code = self._extract_city_code(message)
        if city_code is not None:
            return PlannerDecision(
                kind="tool_call",
                tool_name="get_city",
                tool_arguments={"city_code": city_code},
                rationale="Use the get_city tool when a city lookup is requested.",
            )

        return PlannerDecision(
            kind="respond",
            response=(
                "当前 demo planner 没找到必须调用工具的场景，"
                f"所以先直接回应：{message}"
            ),
            rationale="No tool is needed; respond directly.",
        )

    def _extract_number_arguments(self, message: str) -> dict[str, int] | None:
        a_match = re.search(r"a\s*=\s*(-?\d+)", message)
        b_match = re.search(r"b\s*=\s*(-?\d+)", message)
        if a_match and b_match:
            return {"a": int(a_match.group(1)), "b": int(b_match.group(1))}
        return None

    def _extract_city_code(self, message: str) -> str | None:
        city_match = re.search(r"city_code\s*=\s*([a-zA-Z]+)", message)
        if city_match:
            return city_match.group(1).lower()

        city_aliases = {
            "shanghai": "sh",
            "上海": "sh",
            "hangzhou": "hz",
            "杭州": "hz",
            "suzhou": "sz",
            "苏州": "sz",
        }
        lowered = message.lower()
        for alias, code in city_aliases.items():
            if alias in lowered or alias in message:
                return code
        return None
