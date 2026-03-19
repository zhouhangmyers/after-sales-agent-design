# services 层说明

这一层你可以先粗暴理解成：

`这里放的是智能体后端真正干活的服务。`

API 进来以后，不会直接在路由里把所有事情做完，而是交给这里的一层层 service 去处理。

## 先记住这一句

- `ChatService`：负责收口整次聊天请求
- `OrchestratorService`：负责编排整轮 agent loop
- `RuntimeService`：负责执行工具
- `PlannerService`：负责让“脑子”决定下一步
- `agent_runtime`：负责真正执行工具
- `StreamService`：负责把结果拆成 SSE 事件
- `CacheService`：负责缓存事件

## 每个文件到底在干嘛

### `chat_service.py`

这个文件你可以理解成：

`一次聊天请求的总收口人`

它主要做这些事：

- 创建 `session`
- 写入用户消息
- 创建一条 `workflow_run`
- 调用 `OrchestratorService.run(...)`
- 把这次运行里产生的：
  - `llm_calls`
  - `tool_calls`
  - `assistant message`
  - `workflow_runs`
  全部落库
- 最后返回 `ChatResponse`

所以它不负责“思考”，也不负责“真正执行工具”，它负责的是：

`把整次请求前后收干净。`

### `runtime_service.py`

这个文件你可以理解成：

`工具执行层`

它主要做这些事：

- 告诉 planner 现在有哪些工具可用
- 真正调用底层 `agent_runtime` 执行工具
- 把工具执行结果整理成 observation

最简单的话：

`runtime_service 不负责想，也不负责控整轮流程，它负责把工具真的跑掉。`

### `orchestrator_service.py`

这个文件你可以理解成：

`智能体流程总控`

它主要做这些事：

- 调 planner 想下一步
- 如果需要工具，就调用 `RuntimeService`
- 把工具结果转成 observation
- 再进入下一轮 planner
- 直到拿到最终回复或失败

最简单的话：

`planner 负责出主意，runtime 负责干活，orchestrator 负责把这一整轮串起来。`

### `planner_service.py`

这个文件你可以理解成：

`智能体的脑子接口层`

它主要做这些事：

- 准备 prompt
- 控制 timeout / retry
- 调具体的 planner client
- 返回结构化结果

也就是说，它不直接执行工具，它只负责：

`让模型决定下一步该干嘛。`

### `planners/base.py`

这个文件可以理解成：

`planner 这一层统一说话的格式`

这里定义了：

- `PlannerRequest`
- `PlannerDecision`
- `PlannerCallTrace`
- `ToolObservation`
- `TokenUsage`

你可以把它看成：

`规划层的公共协议文件`

### `planners/demo_client.py`

这个文件可以理解成：

`假装自己是大模型的 demo 脑子`

它不会真的去请求 OpenAI、DeepSeek 这些 provider。  
它只是用本地规则模拟：

- 看到什么消息该调什么工具
- 工具执行完后该怎么回复

它的意义不是长期使用，而是：

`在还没接真实 LLM 之前，先把 Phase 03 整条链跑通。`

### `stream_service.py`

这个文件可以理解成：

`把响应拆成 SSE 事件的人`

当前它做的不是“边生成边输出 token”，而是：

- 先拿到完整 `ChatResponse`
- 再拆成 SSE 事件往外发

所以它现在更像：

`后处理式流式输出`

### `cache_service.py`

这个文件可以理解成：

`事件缓存`

它主要做这些事：

- 缓存最后一条 SSE 事件
- 如果 Redis 可用就走 Redis
- Redis 不可用就回退内存缓存

## 现在这层最重要的理解

你可以把当前 Phase 03 的主链记成：

```text
API
-> ChatService
-> OrchestratorService.run()
-> PlannerService.plan()
-> 如果需要工具，就调 agent_runtime.execute(...)
-> 工具结果变成 observation
-> 再回到 planner
-> 最后得到 reply
-> ChatService 把整次痕迹落库
```

## 规划、执行、编排到底啥区别

### 规划

就是：

`下一步该干嘛？`

比如：

- 直接回复
- 调哪个工具
- 参数是什么

这层主要是 `PlannerService` 和 planner client。

### 执行

就是：

`真的去把工具跑掉`

这层主要是底层 `agent_runtime`。

### 编排

就是：

`把 规划 -> 执行 -> 观察 -> 再规划 这一整轮流程组织起来`

这层主要是 `OrchestratorService` 里的 loop 控制逻辑。

一句最简单的话：

- planner = 脑子
- orchestrator = 流程控制
- runtime = 执行层
- agent_runtime = 干活的手

## 为什么现在不提前做太多

当前是 Phase 03，所以这里只做：

- 最小 agent loop
- tool calling
- structured output
- llm_calls 持久化

还没有提前塞很多 Phase 04 才要长的东西，比如：

- 多 agent orchestration
- HITL
- resume
- LangGraph state graph

这样做的目的是：

`先把最小闭环做顺，再往上长。`
