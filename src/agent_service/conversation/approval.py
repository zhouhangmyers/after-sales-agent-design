from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from agent_service.tools.models import ToolPolicy


@dataclass(slots=True, frozen=True)
class ApprovalDecision:
    reason: str
    risk_level: str
    display_payload: dict[str, object]


def resolve_approval_decision(
    *,
    tool_arguments: dict[str, Any],
    policy: ToolPolicy,
) -> ApprovalDecision | None:
    if policy.approval_evaluator is not None:
        requirement = policy.approval_evaluator(tool_arguments)
        if requirement is not None:
            return ApprovalDecision(
                reason=requirement.reason,
                risk_level=requirement.risk_level,
                display_payload=requirement.display_payload or {},
            )

    if not policy.approval_required:
        return None

    return ApprovalDecision(
        reason="工具当前策略要求人工审批后才能执行。",
        risk_level=policy.risk_level,
        display_payload={},
    )
