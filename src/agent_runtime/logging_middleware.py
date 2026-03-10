from __future__ import annotations

# logging 是 Python 标准库里的日志模块。
# 这个文件后面用到的 Logger / StreamHandler / Formatter 都来自这里。
import logging
# perf_counter 用来计算一段逻辑执行花了多久。
from time import perf_counter
# Callable 在这里用来描述“函数应该长什么样”。
from typing import Callable

# LoggingMiddleware 处理的是一次工具调用的“输入”和“输出”，
# 所以这里要导入 runtime 统一的请求对象 ToolCall 和结果对象 ToolResult。
from .models import ToolCall, ToolResult


# NextHandler 是“下一步处理器”的类型声明：
# 接收 ToolCall，返回 ToolResult。
# 这里是“声明函数签名”，不是在实现具体函数。
# 真正传进来的 next_handler，来自 runtime.py 里的 _dispatch(...) 封装。
NextHandler = Callable[[ToolCall], ToolResult] #这就是runtime.py中的lambda next_call: self._dispatch(index + 1, next_call)
# Middleware 是“中间件”的类型声明：
# 接收当前请求和下一步处理器，最后也返回 ToolResult。
# 所以 middleware 的本质就是：
# 先拿到当前请求，再决定要不要把它交给 next_handler 继续往后执行。
Middleware = Callable[[ToolCall, NextHandler], ToolResult]


def get_logger(name: str = "agent_runtime") -> logging.Logger:
    # 按名字拿一个 logger；agent_runtime 只是默认名字，不是固定关键字。
    # 你完全可以改成别的名字，例如 "tool_runtime"、"agent_runtime1"。
    logger = logging.getLogger(name)
    # 只有还没配置过 handler 时才添加，避免重复打印同一条日志。
    # 如果每次都无脑 addHandler，同一条日志可能会重复打印多遍。
    if not logger.handlers:
        # StreamHandler 表示把日志输出到控制台/标准输出这类“流”里。
        handler = logging.StreamHandler()
        # Formatter 决定日志长什么样。
        # 这里的格式是：logger名字 + 日志级别 + 日志正文。
        handler.setFormatter(logging.Formatter("%(name)s %(levelname)s %(message)s"))
        logger.addHandler(handler)
    # INFO 及以上级别的日志会被输出。
    logger.setLevel(logging.INFO)
    # 不再向上层 logger 继续传播，减少重复输出。
    # 不然同一条日志可能既在当前 logger 打一次，又在父 logger 再打一次。
    logger.propagate = False
    return logger


class LoggingMiddleware:
    def __init__(self, logger: logging.Logger | None = None) -> None:
        # 允许外部传入 logger；不传就使用默认配置。
        self._logger = logger or get_logger()

    def __call__(self, call: ToolCall, next_handler: NextHandler) -> ToolResult:
        # 之所以实现 __call__，是为了让 LoggingMiddleware 的实例也能像函数一样被调用：
        # middleware(call, next_handler)
        # 这样它就能直接放进 runtime 的 middlewares 列表里。

        # 记录开始时间，后面用来计算本次工具调用耗时。
        start = perf_counter()
        # request_id 可能为空，为了日志输出稳定，这里给一个占位符。
        request_id = call.request_id or "-"
        # 先记录开始日志，再把请求交给下一步处理器。
        # 这里记录的是“进入工具调用链”时的信息。
        self._logger.info(
            "tool.start action=%s request_id=%s arguments=%s",
            call.action,
            request_id,
            call.arguments,
        )
        try:
            # next_handler 本质上就是 runtime 交给 middleware 的“继续执行按钮”。
            # middleware 这里看不到 index，不是因为 index 不重要，
            # 而是 runtime 已经把“下一层要用的 index + 1”封装进 next_handler 里了。
            # 所以这里一旦调用 next_handler(call)，背后就会继续流向下一个 middleware，
            # 或者在中间件链走完后最终进入 _invoke(...)。
            result = next_handler(call)
        except Exception:
            # 失败场景也要记录耗时，所以这里要单独算一次 duration_ms。
            duration_ms = (perf_counter() - start) * 1000
            # exception 会把 traceback 一起打出来，便于排查问题。
            # 这也是为什么示例里你会看到完整错误栈，而不只是简单一行报错。
            self._logger.exception(
                "tool.error action=%s request_id=%s duration_ms=%.2f",
                call.action,
                request_id,
                duration_ms,
            )
            # 日志记完以后继续把异常往外抛，交给 runtime 统一收口。
            # 也就是：middleware 负责“观察并记录错误”，execute() 负责“统一包装错误返回值”。
            # 这里的 raise 表示“把当前捕获到的同一个异常原样继续抛出去”，不是新造一个异常。
            raise
        # 成功场景下，同样计算一次耗时。
        duration_ms = (perf_counter() - start) * 1000
        # 成功执行后记录结束日志，包括耗时和 success 状态。
        # result.success 来自 ToolResult，所以这里记录的是 runtime 最终视角下的成功/失败。
        self._logger.info(
            "tool.finish action=%s request_id=%s duration_ms=%.2f success=%s",
            call.action,
            request_id,
            duration_ms,
            result.success,
        )
        return result
