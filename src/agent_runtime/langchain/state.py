from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from langchain.agents.middleware.types import AgentState

from agent_core.contracts.run_events import RunEvent
from agent_core.contracts.tool_spec import ToolContext


# AgentState[Any]：继承 LangChain 的 state；Any 表示不限制 structured_response 类型。
# total=False：下面额外字段可以不存在，resume/异常场景里的 state 可能不完整。
class LangChainAgentState(AgentState[Any], total=False):
    """LangGraph 的“存档”。

    一句话：它负责让 run 以后还能找回来、继续跑、查状态。

    里面放的是可以保存的数据：
    - messages：LangChain 的对话/工具调用历史。
    - session_id：平台会话 id。
    - input_message：本次用户输入。
    - run_error：失败时存错误，之后 get_state 还能看到失败原因。

    例子：用户申请退款，Agent 跑到“等待人工审批”时暂停。
    这份 state 会被 checkpoint 保存；用户批准后，stream_action 用同一个
    run_id 找回它，然后继续执行退款。
    """

    # 平台会话 ID，用来把 graph run 映射回我们的 session。
    session_id: str
    # 本次用户原始输入，用于会话记录持久化和轻量 token 统计。
    input_message: str
    # 执行失败时写入，便于之后从 checkpoint 映射出 failed 状态。
    run_error: dict[str, str] | None


@dataclass(slots=True)
class LangChainRuntimeContext:
    """当前这次调用的“临时工具包”。

    一句话：它负责让本次运行能调用工具、发事件、知道是不是 resume。

    它不进 checkpoint，因为里面有函数、actor、依赖对象，这些不能长期保存。
    每次 stream_run/stream_action 都会新建一个，调用结束就没用了。

    例子：Agent 要调用退款工具。
    - tool_context 告诉工具“谁在操作、属于哪个 capability”。
    - emit 让 middleware 能发 ActionRequiredEvent 给前端。
    - is_resume=True 表示这是审批后继续跑，不要重复发审批事件。
    """

    # 工具执行需要的平台上下文，例如 capability_id、actor、依赖对象。
    tool_context: ToolContext
    # 异步事件出口，供 middleware/tool 发出平台 RunEvent。
    # 简单理解：emit 就是 async def emit(event: RunEvent) -> None。
    # 类型写成 Callable[..., Awaitable[...]]，是因为字段里存的是函数本身。
    # 调用时要写：await runtime.context.emit(ActionRequiredEvent(...))
    emit: Callable[[RunEvent], Awaitable[None]]
    # 从 LangGraph interrupt 恢复执行时为 True，避免重复发审批事件。
    is_resume: bool = False
