from __future__ import annotations

from functools import lru_cache
from math import ceil
from typing import Any

import tiktoken


def _heuristic_token_count(text: str) -> int:
    # 在拿不到 tiktoken 编码器时，用一个粗略规则估算 token 数。
    return max(1, ceil(len(text) / 4))


@lru_cache(maxsize=16)
def _encoding_for_model(model: str) -> Any | None:
    # 根据模型名选择 tiktoken 编码器，并做一个很小的缓存，
    # 避免同一模型重复解析编码器。
    resolved_model = model or "deepseek-chat"
    try:
        # 这里是项目里的兼容策略，不是 tiktoken 的强制规定：
        # DeepSeek 系列先统一按 cl100k_base 估算 token；
        # 其他模型优先走 tiktoken 提供的官方模型映射。
        if resolved_model.lower().startswith("deepseek"):
            return tiktoken.get_encoding("cl100k_base")
        return tiktoken.encoding_for_model(resolved_model)
    except Exception:
        try:
            return tiktoken.get_encoding("cl100k_base")
        except Exception:
            return None


def estimate_tokens(text: str, *, model: str = "deepseek-chat") -> int:
    # 对一段文本做 token 数估算。
    # 优先使用真实编码器，失败时退回到启发式估算。
    stripped = text.strip()
    if not stripped:
        return 0
    encoding = _encoding_for_model(model)
    if encoding is None:
        return _heuristic_token_count(stripped)
    try:
        return len(encoding.encode(stripped, disallowed_special=()))
    except Exception:
        return _heuristic_token_count(stripped)
