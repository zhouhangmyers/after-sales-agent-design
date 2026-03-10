# 让类型标注的处理更顺手；工程项目里很常见。
from __future__ import annotations

# Any 表示 details 里允许放多种类型的上下文数据。
from typing import Any

# ErrorResponse 是我们在 models.py 里定义的“统一错误响应对象”。
# 这个文件里的异常类，最后都会被转换成它。
from .models import ErrorResponse


# AgentRuntimeError 是 runtime 自己定义的“异常基类”。
# 它继承自 Python 内置的 Exception，所以它本质上仍然是一个标准异常。
# 之所以单独定义这一层，是为了让 runtime 有一个统一的错误体系。
class AgentRuntimeError(Exception):
    # code 是机器更容易识别的错误码。
    # 默认值写成 runtime_error，子类可以覆盖成更具体的错误码。
    code = "runtime_error"

    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        # 这一句会调用父类 Exception 的初始化逻辑。
        # 也就是：虽然我们扩展了自己的异常类，但仍然保留 Python 标准异常的基本行为。
        super().__init__(message)
        # message 适合给人看，说明这次错误大致发生了什么。
        self.message = message
        # details 用来放更细的上下文信息。
        # 如果外面没传，就默认给一个新的空字典，保证结构稳定。
        self.details = details or {}

    def to_error_response(self) -> ErrorResponse:
        # 把“异常对象”转换成“统一错误响应对象”。
        # 这样 execute() 最外层就能把内部异常稳定地包装成 ToolResult(error=...)。
        return ErrorResponse(code=self.code, message=self.message, details=self.details)


# UnknownToolError 表示：调用了一个根本没有注册过的工具。
# 例如 action 写成了 missing_tool。
class UnknownToolError(AgentRuntimeError):
    code = "unknown_tool"


# ToolValidationError 表示：工具是存在的，但传进来的参数不合法。
# 例如 add 工具要求 a 和 b 都是 int，但你传了 {"a": "bad", "b": 2}。
class ToolValidationError(AgentRuntimeError):
    code = "tool_validation_failed"


# ToolExecutionError 表示：工具存在、参数也过了校验，但真正执行 handler 时内部出错了。
# 例如 handler 里抛了 ValueError、访问外部资源失败等。
class ToolExecutionError(AgentRuntimeError):
    code = "tool_execution_failed"
