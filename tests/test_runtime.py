from __future__ import annotations

import logging
import unittest

from pydantic import BaseModel

from agent_runtime import AgentRuntime, LoggingMiddleware, ToolRegistry
from agent_runtime.models import ToolCall


class AddArgs(BaseModel):
    a: int
    b: int


class RepeatArgs(BaseModel):
    # 这个模型规定：传给 repeat 工具的参数字典里，默认必须有 value 和 times 这两个 key。
    # 例如 {"value": "ha", "times": 2} 可以通过；如果把 value 写成别的名字，校验就会失败。
    value: str
    times: int


class BoomArgs(BaseModel):
    value: str


def add_handler(args: AddArgs) -> int:
    return args.a + args.b


def repeat_handler(args: RepeatArgs) -> str:
    return args.value * args.times


def boom_handler(args: BoomArgs) -> str:
    raise RuntimeError(f"boom: {args.value}")


class AgentRuntimeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.runtime = AgentRuntime()
        self.runtime.register_tool(
            name="add",
            description="Add two integers.",
            args_model=AddArgs,
            handler=add_handler,
        )
        self.runtime.register_tool(
            name="repeat",
            description="Repeat a value.",
            args_model=RepeatArgs,
            handler=repeat_handler,
        )
    # 方法名必须以test_开头，测试框架才会自动识别并执行
    def test_registry_lists_registered_names(self) -> None:
        #self.runtime这个不是在这里创建的，它来自前面的setUp(),每个测试开始前，setUp()都会先执行一次：创建一个新的AgentRuntime，注册add，注册repeat
        #sorted是按照工具名排序
        self.assertEqual(self.runtime.registry.names(), ["add", "repeat"])

    def test_duplicate_registration_raises_value_error(self) -> None:
        # setUp() 里已经注册过 "add"，再次注册同名工具时应立即报错，而不是静默覆盖。
        with self.assertRaises(ValueError):
            self.runtime.register_tool(
                name="add",
                description="Duplicate add tool.",
                args_model=AddArgs,
                handler=add_handler,
            )

    def test_execute_success_returns_result(self) -> None:
        result = self.runtime.execute("add", {"a": 3, "b": 7}, request_id="req-1")
        self.assertTrue(result.success)
        self.assertEqual(result.result, 10)
        self.assertEqual(result.request_id, "req-1")

    def test_unknown_tool_returns_structured_error(self) -> None:
        result = self.runtime.execute("missing", {"value": 1})
        self.assertFalse(result.success)
        self.assertIsNotNone(result.error)
        error = result.error
        assert error is not None
        self.assertEqual(error.code, "unknown_tool")
        self.assertEqual(error.details["available_actions"], ["add", "repeat"])

    def test_validation_failure_returns_structured_error(self) -> None:
        result = self.runtime.execute("add", {"a": "bad", "b": 2})
        self.assertFalse(result.success)
        self.assertIsNotNone(result.error)
        error = result.error
        assert error is not None
        self.assertEqual(error.code, "tool_validation_failed")
        self.assertEqual(error.details["arguments"], {"a": "bad", "b": 2})

    def test_execution_failure_returns_structured_error(self) -> None:
        self.runtime.register_tool(
            name="boom",
            description="Always fails.",
            args_model=BoomArgs,
            handler=boom_handler,
        )
        result = self.runtime.execute("boom", {"value": "x"})
        self.assertFalse(result.success)
        self.assertIsNotNone(result.error)
        error = result.error
        assert error is not None
        self.assertEqual(error.code, "tool_execution_failed")
        self.assertIn("boom: x", error.details["reason"])

    def test_middleware_chain_runs_in_wrapped_order(self) -> None:
        seen: list[str] = []

        # 这里故意把 middleware 写成最简函数形态：
        # 只要一个函数能按 (call, next_handler) -> ToolResult 这种方式工作，
        # runtime._dispatch(...) 在执行 middleware(call, ...) 时就能直接调用它。
        # next_handler 在这里没有显式类型标注，静态检查会相对宽松；
        # 但运行时真正传进来的，是 _dispatch(...) 封装出的“下一步处理器”，
        # 它会继续往后分发，并最终返回 ToolResult。
        # 01_runtime_demo.py 里用的则是 LoggingMiddleware 实例；
        # 它虽然是类实例，但因为实现了 __call__，所以也能像函数一样作为 middleware 被调用。
        def middleware_a(call: ToolCall, next_handler):
            seen.append("a-before")
            result = next_handler(call)
            seen.append("a-after")
            return result

        def middleware_b(call: ToolCall, next_handler):
            seen.append("b-before")
            result = next_handler(call)
            seen.append("b-after")
            return result

        runtime = AgentRuntime(middlewares=[middleware_a, middleware_b])
        runtime.register_tool(
            name="add",
            description="Add two integers.",
            args_model=AddArgs,
            handler=add_handler,
        )

        result = runtime.execute("add", {"a": 1, "b": 2})
        self.assertTrue(result.success)
        self.assertEqual(seen, ["a-before", "b-before", "b-after", "a-after"])

    def test_middleware_can_modify_arguments_before_execution(self) -> None:
        # 这个测试的重点是：middleware 跑在真正执行工具之前，
        # 所以它有机会先改 call.arguments，再把请求继续交给后面的校验和 handler。
        def inject_default_times(call: ToolCall, next_handler):
            # 这里故意不传 times，模拟“调用方漏传了一个可补默认值的参数”。
            # 如果是 repeat 工具，并且参数里还没有 times，就先补一个默认值 2。
            if call.action == "repeat" and "times" not in call.arguments:
                call.arguments["times"] = 2
            return next_handler(call)

        runtime = AgentRuntime(middlewares=[inject_default_times])
        runtime.register_tool(
            name="repeat",
            description="Repeat a value.",
            args_model=RepeatArgs,
            handler=repeat_handler,
        )

        result = runtime.execute("repeat", {"value": "ha"})
        # runtime.execute(...) 传进来的原始参数只有 {"value": "ha"}，
        # 但中间件已经在校验前补成了 {"value": "ha", "times": 2}，
        # 所以后面 RepeatArgs 校验能通过，repeat_handler 最终返回 "haha"。
        self.assertTrue(result.success)
        self.assertEqual(result.result, "haha")

    def test_logging_middleware_logs_start_and_finish(self) -> None:
        logger = logging.getLogger("agent_runtime_test_success")
        logger.handlers.clear()
        logger.propagate = False

        runtime = AgentRuntime(middlewares=[LoggingMiddleware(logger)])
        runtime.register_tool(
            name="add",
            description="Add two integers.",
            args_model=AddArgs,
            handler=add_handler,
        )

        with self.assertLogs(logger, level="INFO") as captured:
            result = runtime.execute("add", {"a": 4, "b": 5}, request_id="req-log")

        self.assertTrue(result.success)
        # assertLogs(...) 把代码块里产出的日志收集到 captured.output 中；
        # 它是一个“每个元素都是一条完整日志字符串”的列表。
        # 这里用 "\n".join(...) 把多条日志拼成一整段文本，
        # 这样后面就可以直接用 assertIn(...) 判断：
        # 某段关键日志，比如 tool.start / tool.finish，是否确实出现过。
        # 例如：
        # captured.output = [
        #   "INFO:...:tool.start action=add request_id=req-log ...",
        #   "INFO:...:tool.finish action=add request_id=req-log ...",
        # ]
        # join 之后会变成：
        # "INFO:...:tool.start action=add request_id=req-log ...\nINFO:...:tool.finish action=add request_id=req-log ..."
        joined = "\n".join(captured.output)
        self.assertIn("tool.start action=add request_id=req-log", joined)
        self.assertIn("tool.finish action=add request_id=req-log", joined)

    def test_logging_middleware_logs_errors(self) -> None:
        logger = logging.getLogger("agent_runtime_test_error")
        logger.handlers.clear()
        logger.propagate = False

        runtime = AgentRuntime(middlewares=[LoggingMiddleware(logger)])
        runtime.register_tool(
            name="boom",
            description="Always fails.",
            args_model=BoomArgs,
            handler=boom_handler,
        )

        with self.assertLogs(logger, level="INFO") as captured:
            # 这里调用 boom 工具后，真正执行到的 boom_handler(...) 会 raise RuntimeError。
            # LoggingMiddleware 会先记录 tool.start，
            # 然后在 except Exception 里记录 tool.error，
            # 最后 runtime 再把这次异常统一包装成一个 success=False 的 ToolResult 返回。
            result = runtime.execute("boom", {"value": "y"}, request_id="req-error")

        self.assertFalse(result.success)
        # 和上一个日志测试一样，这里先把多条日志拼成一段文本，方便后面直接检查关键片段是否出现。
        joined = "\n".join(captured.output)
        self.assertIn("tool.start action=boom request_id=req-error", joined)
        self.assertIn("tool.error action=boom request_id=req-error", joined)

    def test_runtime_accepts_custom_registry(self) -> None:
        # 这里先自己创建一个独立的 ToolRegistry，模拟“外部已经准备好了注册表，再传给 runtime 使用”的场景。
        registry = ToolRegistry()
        # 如果 AgentRuntime 接收了自定义 registry，它就应该直接复用这个实例，
        # 而不是自己偷偷再 new 一个内容看起来差不多的新注册表。
        runtime = AgentRuntime(registry=registry)
        runtime.register_tool(
            name="add",
            description="Add two integers.",
            args_model=AddArgs,
            handler=add_handler,
        )
        # 这里要验证的是“是不是同一个对象实例”，所以要用 assertIs（对应 is），
        # 而不是 assertEqual（对应 ==）。哪怕两个注册表内容一样，也不代表它们是同一个对象。
        self.assertIs(runtime.registry, registry)
        # 上面验证“对象身份”，这里再验证“对象内容”：
        # 既然 runtime 复用了这个 registry，那么注册 add 之后，外部这个 registry 里也应该能看到它。
        self.assertEqual(registry.names(), ["add"])


if __name__ == "__main__":
    unittest.main()
