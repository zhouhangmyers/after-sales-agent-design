from __future__ import annotations

import json
import re
from typing import Any

from openai import OpenAI

from .base import PlannerDecision, PlannerRequest, TokenUsage


# DeepSeek R1 的响应里可能包含 <think>...</think> 推理块，
# 这里用正则把它整段剥掉，只留最终回答。
_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL)
# 模型有时会把 JSON 用 markdown 代码块包起来，这里把它们去掉。
_CODE_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$")


class DeepSeekPlannerClient:
    provider = "deepseek"

    def __init__(self, *, api_key: str, model: str = "deepseek-reasoner") -> None:
        self.model = model
        self._client = OpenAI(
            api_key=api_key,
            base_url="https://api.deepseek.com",
        )

    def plan(self, request: PlannerRequest) -> tuple[PlannerDecision, dict[str, Any], TokenUsage]:
        messages = [
            {
                "role": "system",
                "content": (
                    "You are a structured planning model for an agent loop. "
                    "Always reply with a single valid JSON object and nothing else — "
                    "no markdown fences, no extra text. "
                    "The JSON must contain exactly these fields:\n"
                    '  "kind": "respond" or "tool_call"\n'
                    '  "response": string when kind=respond, otherwise null\n'
                    '  "tool_name": string when kind=tool_call, otherwise null\n'
                    '  "tool_arguments": object when kind=tool_call, otherwise {}\n'
                    '  "rationale": string explaining your decision'
                ),
            },
            {
                "role": "user",
                "content": request.prompt.content,
            },
        ]

        response = self._client.chat.completions.create(
            model=self.model,
            messages=messages,
        )

        raw_response: dict[str, Any] = response.model_dump()

        content = (response.choices[0].message.content or "").strip()
        # 去掉 R1 的推理块（如果有）
        content = _THINK_RE.sub("", content).strip()
        # 去掉可能的 markdown 代码块包裹
        content = _CODE_FENCE_RE.sub("", content).strip()

        decision = self._parse_decision(content)

        usage = TokenUsage(
            prompt_tokens=response.usage.prompt_tokens if response.usage else 0,
            completion_tokens=response.usage.completion_tokens if response.usage else 0,
            total_tokens=response.usage.total_tokens if response.usage else 0,
        )

        return decision, raw_response, usage

    def _parse_decision(self, content: str) -> PlannerDecision:
        try:
            data = json.loads(content)
        except json.JSONDecodeError as exc:
            # 解析失败时降级为直接回复，把原始内容和报错都透出来，方便排查。
            return PlannerDecision(
                kind="respond",
                response=f"[planner parse error] {content[:300]}",
                rationale=f"JSON parse failed: {exc}",
            )

        kind = data.get("kind", "respond")
        if kind not in ("respond", "tool_call"):
            kind = "respond"

        return PlannerDecision(
            kind=kind,
            response=data.get("response"),
            tool_name=data.get("tool_name"),
            tool_arguments=data.get("tool_arguments") or {},
            rationale=data.get("rationale", ""),
        )
