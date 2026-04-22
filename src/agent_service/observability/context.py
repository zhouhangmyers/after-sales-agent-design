"""请求级上下文：request_id 的存取 + 日志自动注入。

核心思路：
- 用 `contextvars.ContextVar` 存储当前请求的 request_id。
  contextvars 天然支持 asyncio task 和 threading（copy_context），
  所以无论是 async handler 还是后台线程（如 SSE 桥接线程），
  只要在正确的上下文里 set 过，就能 get 到。
- `RequestIdLogFilter` 是一个 `logging.Filter`，
  它在每条 LogRecord 上自动填充 `request_id` 字段，
  这样 Formatter 里写 `%(request_id)s` 就能输出。
"""

from __future__ import annotations

import logging
from contextvars import ContextVar

request_id_var: ContextVar[str] = ContextVar("request_id", default="-")


def get_request_id() -> str:
    return request_id_var.get()


def set_request_id(value: str) -> None:
    request_id_var.set(value)


class RequestIdLogFilter(logging.Filter):
    """把 contextvars 里的 request_id 注入到每条 LogRecord。"""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get()  # type: ignore[attr-defined]
        return True
