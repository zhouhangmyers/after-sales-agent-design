from __future__ import annotations

import json


def dump_payload(payload: object) -> str:
    # 统一把结构化 payload 转成稳定 JSON，方便落库和调试。
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)
