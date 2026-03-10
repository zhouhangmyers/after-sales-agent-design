from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ValidationError

from .errors import AgentRuntimeError, ToolExecutionError, ToolValidationError, UnknownToolError
from .logging_middleware import Middleware
from .models import ToolCall, ToolResult
from .registry import ToolDefinition, ToolRegistry


class AgentRuntime:
    def __init__(
        self,
        *,#表示后面的参数必须用关键字传递，不能按位置乱传。所以你要这样写AgentRuntime(registry=my_registry,middlewares=[mw1,mw2]),不能写成AgentRuntime(my_registry,[mw1,mw2])
        registry: ToolRegistry | None = None,#传一个工具注册表
        middlewares: list[Middleware] | None = None,#传一个中间件列表
    ) -> None:
        self.registry = registry or ToolRegistry() # 如果你传了工具注册表，就用你传进来的那个，如果你没传，就默认新建一个工具注册表
        self.middlewares = list(middlewares or []) # 如果你穿了中间件列表，就用你传进来的那个，如果你没传，就默认使用空的中间件列表，list包裹避免直接共享外部列表对象，减少后续修改带来的意外影响，list(...) 是为了避免和外部共享同一个列表对象，防止外部后续修改影响 runtime 内部状态。

    def register_tool(#register_tool()就是把一个普通函数，升级成runtime可以识别、校验、调度的正式工具。
        self,
        *,
        name: str,#这是工具名，比如add
        description: str, #工具描述，比如 Add two integers
        args_model: type[BaseModel], #参数模型，也就是这个工具接受什么参数结构，这里传的不是某个模型实例，而是pydantic模型类本身，比如你传的是AddArgs，而不是AddArgs(a=1,b=2),因为runtime后面需要拿这个模型类去做tool.args_model.model_validate(call.arguments)也就是按这个模型规则去校验输入参数
        handler: Any,#真正执行这个工具的函数
    ) -> ToolDefinition:
        tool = ToolDefinition( #把你传进来的4个信息，封装成一个 ToolDefinition对象
            name=name,
            description=description,
            args_model=args_model,
            handler=handler,
        )
        self.registry.register(tool) # 就是把这个工具交给注册表保存起来。也就是说，AgentRuntime负责对外提供注册工具的统一接口，ToolRegistry负责真正存储和管理这些工具，所以职责是分开的。
        return tool #把刚注册好的ToolDefination 返回出去。这样外部如果需要，也可以拿到这个工具定义继续使用。

    def execute(
        self,
        action: str,#要执行哪些工具，比如add
        arguments: dict[str, Any] | None = None,#给工具的参数，比如{"a":3,"b":7}
        *,
        request_id: str | None = None,#这次请求的标识，可用于日志和追踪
        metadata: dict[str, Any] | None = None,#附加上下文信息
    ) -> ToolResult:
        call = ToolCall( #把原始输入装配成统一请求对象ToolCall，这样的话，后面中间件、执行器、日志都围绕这个对象走
            action=action,
            arguments=arguments or {},#如果调用方没传，就给空字典
            request_id=request_id,
            metadata=metadata or {},#如果调用方没传，就给空字典，这样后面代码不用一直判断：metadata is None 吗？
        )
        try:
            return self._dispatch(0, call) #把这次调用交给中间件链和执行链去处理，0表示从第0个中间件开始分发。暂且无需深究_dispatch()细节，只要知道：execute()不直接自己干所有事，而是把请求送进后面的执行链
        except AgentRuntimeError as exc:#这一步是整个工程感非常强的地方，含义是：只要后面执行过程中抛出了runtime可识别的异常，就不要把程序炸掉，而是统一包装成结构化失败结果返回。也就是说，1.不存在工具，2.参数校验失败，3.工具执行失败。这些都不会让调用方拿到一堆乱七八糟的异常，而是拿到统一的ToolResult....，这就实现了内部可以抛异常，对外结果仍然稳定
            return ToolResult(
                success=False,
                action=action,
                request_id=request_id,
                error=exc.to_error_response(),
            )

    def _dispatch(self, index: int, call: ToolCall) -> ToolResult:#把一次请求按顺序交给中间件
        if index >= len(self.middlewares):
            return self._invoke(call)
        middleware = self.middlewares[index]

        #就是说不管经过几轮middleware, next_call在middleware中如果被调用,那么也就是self._dispatch被调用，这个函数的next_call的位置还是call去占位
        return middleware(call, lambda next_call: self._dispatch(index + 1, next_call))# lambda的作用是把是否继续往后传递调用下一个中间件的权利给到当前的中间件middleware

    def _invoke(self, call: ToolCall) -> ToolResult:
        tool = self.registry.get(call.action)#先根据名字查工具
        if tool is None:
            raise UnknownToolError(#如果注册表里找不到这个工具，就抛出runtime自己定义的结构化异常
                f"unknown action: {call.action}",#附带上未知的调用工具名
                details={"available_actions": self.registry.names()},#附带上全部可用的工具名
            )
        #这里有一个小提示：_invoke()负责报告错误，middleware负责观察错误，execute负责把错误统一包装成返回值
        #一句话：先抛异常，是为了让错误沿调用链自然向外传播；最后再在统一出口收口

        try:
            args = tool.args_model.model_validate(call.arguments)#tool 已经找到了，每个工具都有自己的参数模型args_model,现在拿这个模型去校验这次传进来的call.arguments
        except ValidationError as exc:#如果pydantic校验失败，就会抛出ValidationError
            raise ToolValidationError(
                f"invalid arguments for action: {call.action}",
                details={"arguments": call.arguments, "errors": exc.errors()},
            ) from exc #表示这个 ToolValidationError 是由原始的 ValidationError 引起的。现在不用深究细节，只要知道它是在保留原始错误上下文

        try:
            result = tool.handler(args)#先执行真正的工具函数
        except AgentRuntimeError:
            raise #表示如果handler里面抛出来的，本来就是runtime自己认识的异常，那就不要再包一层，原样继续往外抛
        except Exception as exc: #表示如果handler里抛的是普通异常，比如ValueError、RuntimeError、TypeError，就统一转成runtime自己的ToolExecutionError，这样整个系统对外就不会暴露五花八门的异常类型
            raise ToolExecutionError(
                f"tool execution failed: {call.action}",
                details={"arguments": call.arguments, "reason": str(exc)},
            ) from exc

        return ToolResult(#一切都没问题就拿到工具执行结果result，并返回
            success=True,
            action=call.action,
            request_id=call.request_id,
            result=result,
        )
