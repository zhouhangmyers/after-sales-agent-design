# 售后 Agent 后端分层架构设计

## 1. 设计结论

本项目按三层主架构组织：

```text
业务层
  src/after_sales/

智能体层
  src/agent_core/
  src/agent_runtime/
  src/agent_integrations/

应用入口层
  src/app_api/
```

三层职责：

```text
业务层
  提供稳定的售后业务能力，管理业务规则、业务状态和业务事务。

智能体层
  定义 Agent 契约、执行 Agent runtime、接入 LLM/MCP 等外部智能体能力。

应用入口层
  暴露 HTTP API，编排业务层和智能体层，完成业务能力到 Agent 工具的适配，
  并把 Agent 运行事件投影成业务审计数据。
```

核心依赖方向：

```text
app_api -> after_sales
app_api -> agent_core
app_api -> agent_runtime
app_api -> agent_integrations

agent_runtime -> agent_core
agent_integrations -> agent_core

after_sales -> after_sales.*
```

一句话：

```text
业务层沉淀能力；
智能体层负责理解、编排和执行工具；
app_api 层负责入口、适配、编排、装配和投影。
```

---

## 2. 总体调用模型

系统有两类入口。

第一类是普通业务 API：

```text
Client
  -> app_api/routers
  -> AfterSalesService
  -> AfterSalesUnitOfWork
  -> AfterSalesRepository
  -> SQLAlchemy AsyncSession
```

第二类是 Agent API：

```text
Client
  -> app_api/routers
  -> app_api/use_cases
  -> agent_runtime
  -> ToolSpec handler
  -> AfterSalesService
  -> AfterSalesUnitOfWork
  -> AfterSalesRepository
```

两条链路最终都回到同一套售后业务能力。

这说明：

```text
Agent 不是新的业务层。
Agent 是智能入口和执行编排层。
业务能力仍然由 after_sales 提供。
```

---

## 3. 第一层：业务层 after_sales

业务层位于：

```text
src/after_sales/
```

内部结构：

```text
after_sales/
  domain/
  application/
  infrastructure/
```

职责：

```text
domain
  售后领域数据结构和业务概念。

application
  售后业务用例、Repository 端口、Unit of Work 端口。

infrastructure
  SQLAlchemy model、repository、session、Unit of Work 实现。
```

核心入口：

```text
src/after_sales/application/services/after_sales_service.py
```

`AfterSalesService` 当前提供：

```text
get_customer_detail
get_order_detail
get_shipment_detail
get_ticket_detail
search_after_sales_policy
list_audit_logs
create_ticket
submit_refund_request
evaluate_refund_approval
```

业务层边界规则：

```text
1. 不依赖 FastAPI。
2. 不依赖 agent_core。
3. 不依赖 agent_runtime。
4. 不依赖 agent_integrations。
5. 不知道 ToolSpec、AgentDefinition、LangChain、MCP。
```

业务层只回答一个问题：

```text
售后系统本身能做什么，以及这些动作如何保证业务正确性。
```

---

## 4. 第二层：智能体层 agent_*

智能体层由三个包组成：

```text
src/agent_core/
src/agent_runtime/
src/agent_integrations/
```

它们共同负责 Agent 能力，但职责不同。

```text
agent_core
  稳定契约层。

agent_runtime
  执行运行时层。

agent_integrations
  外部智能体能力集成层。
```

智能体层不直接依赖业务层。

它只认识框架无关的 Agent 契约，不认识订单、物流、退款、工单这些业务语义。

---

## 5. agent_core：智能体契约层

`agent_core` 位于：

```text
src/agent_core/
```

核心文件：

```text
src/agent_core/contracts/agent_definition.py
src/agent_core/contracts/tool_spec.py
src/agent_core/contracts/run_events.py
src/agent_core/contracts/run_state.py
src/agent_core/registry.py
```

核心契约：

```text
AgentDefinition
  描述一个 Agent 能力，包括 capability_id、名称、描述、system prompt 和工具列表。

ToolSpec
  项目内部统一工具定义。

RunEvent
  Agent runtime 输出给应用层的事件流。

RunState
  从 runtime checkpoint 派生出来的运行状态查询视图。

AgentRegistry
  AgentDefinition 注册表，用于 API 查询和 runtime 调用。
```

`ToolSpec` 是智能体层最关键的契约。

它的作用是定义“一个工具在系统内部长什么样”：

```text
name
  暴露给模型的稳定工具名。

description
  工具用途说明，影响模型什么时候选择该工具。

args_schema
  Pydantic 入参模型，用于参数校验和 JSON Schema 暴露。

handler
  工具执行函数，接收模型生成的 payload 和 runtime 注入的 ToolContext。

approval_policy
  可选审批策略，命中后 runtime 暂停工具执行，等待人工动作。

source / source_id
  工具来源，例如 local 或 MCP server。
```

`ToolSpec` 不是 LangChain Tool，也不是 MCP Tool。

转换关系：

```text
本地业务能力 -> ToolSpec
  app_api/composition/after_sales_agent_factory.py

MCP 外部工具 -> ToolSpec
  agent_integrations/mcp/tool_provider.py

ToolSpec -> LangChain Tool
  agent_runtime/langchain/tool_adapter.py
```

这层的设计目标：

```text
让系统内部有一套稳定 Agent 语言，
避免业务层、runtime、MCP、HTTP API 各说各话。
```

---

## 6. agent_runtime：智能体执行层

`agent_runtime` 位于：

```text
src/agent_runtime/
```

当前实现：

```text
src/agent_runtime/langchain/
```

核心文件：

```text
runtime.py
approval_middleware.py
tool_adapter.py
event_mapper.py
result_mapper.py
state.py
checkpoint/local_memory.py
checkpoint/langgraph_postgres.py
transcript.py
```

执行层负责：

```text
1. 创建并缓存 LangChain agent。
2. 调用 chat model。
3. 把 ToolSpec 转成 LangChain tool。
4. 执行工具调用。
5. 处理审批 interrupt / resume。
6. 把 LangChain stream part 映射成 RunEvent。
7. 从 checkpoint / invocation result 映射出 RunState 和 AgentRunResult。
8. 管理 LangGraph checkpoint。
9. 管理 session transcript。
```

Runtime 输入：

```text
AgentDefinition
message
session_id
ActorContext
```

Runtime 输出：

```text
RunStartedEvent
OutputDeltaEvent
ActionStartedEvent
ActionCompletedEvent
ActionRequiredEvent
RunCompletedEvent
RunFailedEvent
```

### 6.1 文件职责

```text
runtime.py
  Runtime 总调度。
  提供 stream_run、stream_action、get_state。
  负责创建/缓存 LangChain agent，驱动 agent.astream，
  输出 RunEvent，保存 transcript，处理运行异常。

  关键方法：
    stream_run()
      普通 Agent run 入口。生成 run_id/session_id，读取历史消息，
      构造 ToolContext，然后进入 _stream_invocation。

    stream_action()
      人工审批恢复入口。校验 pending_action，
      构造 Command(resume={"decision": ...})，然后进入 _stream_invocation。

    get_state()
      查询指定 run_id 的 checkpoint snapshot，
      并通过 result_mapper.to_run_state 转成 RunState。

    _stream_invocation()
      执行主循环。调用 agent.astream，消费 LangChain stream，
      映射 RunEvent，处理异常，最后生成 RunCompletedEvent。

    _get_agent()
      创建或复用已编译的 LangChain agent。
      这里完成 create_agent、tools 转换、middleware 注册和 checkpointer 注入。

    _persist_session_transcript()
      把本轮用户输入和最终 AI 输出写入 session transcript。

state.py
  定义 LangGraph 运行时状态。
  LangChainAgentState 是 checkpoint 中保存的状态结构。
  LangChainRuntimeContext 是执行期间传给工具和 middleware 的上下文。

  关键类型：
    LangChainAgentState
      LangGraph checkpoint 中保存的状态 schema。
      包含 messages、session_id、input_message、run_error 等字段。

    LangChainRuntimeContext
      LangGraph runtime context。
      携带 ToolContext、emit 回调和 is_resume 标记。

tool_adapter.py
  工具适配器。
  把项目内部 ToolSpec 转成 LangChain StructuredTool。
  执行时调用 ToolSpec.handler(payload, ToolContext)，
  并把成功或失败结果包装成统一 envelope。

  关键方法：
    to_langchain_tool()
      把 ToolSpec 包装成 LangChain StructuredTool。
      这是 ToolSpec 进入 LangChain runtime 的入口。

    execute_tool()
      真正执行 ToolSpec.handler。
      从 LangGraph runtime context 中取 ToolContext，
      并把执行结果包装成 success/error envelope。

approval_middleware.py
  审批中断 middleware。
  在模型生成 tool call 后，检查 ToolSpec.approval_policy。
  命中审批时发出 ActionRequiredEvent，并通过 LangGraph interrupt 暂停。
  审批通过后继续执行工具；审批拒绝后返回失败 ToolMessage。

  关键方法：
    LangChainApprovalMiddleware.aafter_model()
      LangChain 模型输出后的 middleware 钩子。
      读取 AIMessage.tool_calls，检查对应 ToolSpec 的 approval_policy。
      命中审批时 emit ActionRequiredEvent，并调用 interrupt 暂停 run。

    _run_id_from_runtime()
      从 LangGraph runtime.execution_info.thread_id 中取 run_id。

event_mapper.py
  运行事件映射器。
  把 LangChain stream part 转成项目内部 RunEvent。
  messages stream 转成 OutputDeltaEvent。
  tools task start / finish 转成 ActionStartedEvent / ActionCompletedEvent。

  关键方法/类型：
    ToolInvocation
      记录一次工具调用的 action_id、action_name、payload 和开始时间。
      用于计算工具耗时。

    events_from_stream_part()
      对外主入口。
      判断 stream part 是 messages 还是 tasks，
      并转成 OutputDeltaEvent 或工具事件。

    _tool_events_from_task_part()
      处理 LangChain tools task。
      task input 转 ActionStartedEvent；
      task result/error 转 ActionCompletedEvent。

result_mapper.py
  运行结果映射器。
  从 LangGraph checkpoint snapshot / invocation result 映射出 AgentRunResult 和 RunState。
  判断 run 当前是 completed、failed，还是 awaiting_action。

  关键方法：
    to_run_result()
      把一次执行结束后的 checkpoint / invocation result
      映射成 AgentRunResult。
      用于 RunCompletedEvent 和同步 run/act 返回。

    to_run_state()
      把 checkpoint snapshot 映射成 RunState。
      用于 GET /api/after-sales/runs/{run_id} 查询。

    pending_action_from_interrupts()
      从 LangGraph interrupts 中解析 AgentPendingAction。

    session_id_from_state()
      从 checkpoint state 中读取 session_id。

    awaiting_action_message()
      为 awaiting_action 状态生成统一提示文案。

transcript.py
  会话 transcript 抽象。
  管理 session 级历史消息，用于后续对话上下文。
  transcript 不是业务数据库，也不是 LangGraph checkpoint。

  关键类型/方法：
    SessionTranscriptStore
      transcript 存储协议。
      规定 get_session_messages 和 upsert_session_messages 两个能力。

    get_session_messages()
      读取某个 session 的历史消息。

    upsert_session_messages()
      写入或更新某个 run 产生的 session 消息。

    InMemorySessionTranscriptStore
      内存版 transcript 实现，用于本地开发和测试。

checkpoint/local_memory.py
  本地内存 state store。
  使用 LangGraph MemorySaver 保存 checkpoint，
  使用 InMemorySessionTranscriptStore 保存 transcript。
  适合本地开发和测试。

  关键方法：
    ensure_initialized()
      内存实现无需初始化，保持统一接口。

    healthcheck()
      返回 runtime state store 健康状态。

    get_checkpointer()
      返回 LangGraph MemorySaver。

    get_session_messages()
      从内存 transcript 读取 session 历史消息。

    upsert_session_messages()
      向内存 transcript 写入本轮消息。

    close()
      内存实现无需释放资源，保持统一接口。

checkpoint/langgraph_postgres.py
  Postgres state store。
  使用 AsyncPostgresSaver 保存 LangGraph checkpoint。
  使用 agent_session_transcripts 表保存 session transcript。
  适合生产或需要持久化恢复的环境。

  关键方法：
    ensure_initialized()
      初始化 Postgres checkpointer 和 transcript 表。

    healthcheck()
      检查 Postgres state store 是否可用。

    get_checkpointer()
      返回 LangGraph AsyncPostgresSaver。

    get_session_messages()
      从 agent_session_transcripts 表读取 session 历史消息。

    upsert_session_messages()
      向 agent_session_transcripts 表写入或更新本轮消息。

    close()
      关闭 AsyncExitStack 和 SQLAlchemy engine。

    _ensure_open()
      懒初始化 Postgres checkpointer、SQLAlchemy engine 和 transcript 表。

    _sqlalchemy_async_url()
      把 postgresql:// 转成 SQLAlchemy async driver URL。
```

### 6.2 运行主流程

一次普通 Agent run 的执行过程：

```text
LangChainAgentRuntime.stream_run()
  # runtime.py：普通 run 的入口方法。

  -> 生成 run_id / session_id
     # runtime.py：为本次执行生成 run 标识；没有 session_id 时创建新 session。

  -> 从 state_store 读取 session 历史消息
     # runtime.py 调用 state_store.get_session_messages。
     # checkpoint/local_memory.py 或 checkpoint/langgraph_postgres.py 负责具体读取。

  -> 构造 ToolContext
     # runtime.py：把 capability_id、actor 等运行上下文传给工具。

  -> _stream_invocation()
     # runtime.py：统一执行入口；stream_run 和 stream_action 最终都进入这里。

  -> _get_agent()
     # runtime.py：创建或复用已编译的 LangChain agent。

  -> create_agent(...)
     # runtime.py：把 model、tools、system_prompt、middleware、state_schema、
     # checkpointer 交给 LangChain/LangGraph。

  -> agent.astream(...)
     # runtime.py：真正驱动 LangChain agent 执行，按 messages/tasks 流式返回。

  -> event_mapper 把 LangChain stream 映射成 RunEvent
     # event_mapper.py：messages -> OutputDeltaEvent；
     # tools task -> ActionStartedEvent / ActionCompletedEvent。

  -> approval_middleware 在工具执行前处理审批中断
     # approval_middleware.py：检查 ToolSpec.approval_policy；
     # 命中时 emit ActionRequiredEvent，并通过 LangGraph interrupt 暂停。

  -> tool_adapter 执行 ToolSpec.handler
     # tool_adapter.py：把 LangChain tool call 转成 ToolSpec.handler(payload, ToolContext)。

  -> result_mapper 从 checkpoint / invocation result 映射出 AgentRunResult
     # result_mapper.py：读取 snapshot.values / interrupts，
     # 映射成 completed / failed / awaiting_action 的 AgentRunResult。

  -> 保存 session transcript
     # runtime.py 调用 state_store.upsert_session_messages。
     # transcript.py 定义 transcript 存储抽象；
     # checkpoint/local_memory.py 或 checkpoint/langgraph_postgres.py 负责具体保存。

  -> 输出 RunCompletedEvent
     # runtime.py：用 AgentRunResult 包装成 RunCompletedEvent 对外输出。
```

一次人工审批恢复的执行过程：

```text
LangChainAgentRuntime.stream_action()
  -> get_state(run_id)
  -> 校验 pending_action
  -> Command(resume={"decision": ...})
  -> _stream_invocation()
  -> LangGraph 从 checkpoint 恢复
  -> 继续执行或返回审批拒绝结果
  -> 输出 RunCompletedEvent
```

Runtime 边界规则：

```text
1. 不 import after_sales。
2. 不 import app_api。
3. 不写业务数据库。
4. 不知道订单、退款、工单的业务含义。
5. 只通过 ToolSpec 执行工具。
6. 只通过 RunEvent / RunState 对外表达运行过程和状态。
```

这使得 runtime 可以替换。

未来如果不用 LangChain，新的 runtime 只要继续：

```text
接收 AgentDefinition / ToolSpec；
输出 RunEvent；
提供 RunState；
支持工具执行和审批恢复。
```

业务层就不需要改变。

---

## 7. agent_integrations：外部智能体能力集成层

`agent_integrations` 位于：

```text
src/agent_integrations/
```

当前包括：

```text
agent_integrations/llm/
agent_integrations/mcp/
```

LLM 集成：

```text
src/agent_integrations/llm/chat_model_factory.py
```

负责根据配置创建 chat model：

```text
LLM_PROVIDER
LLM_MODEL
DEEPSEEK_API_KEY
OPENAI_API_KEY
LLM_TIMEOUT_SECONDS
LLM_MAX_RETRIES
```

MCP 集成：

```text
src/agent_integrations/mcp/tool_provider.py
```

负责：

```text
1. 读取 MCP server 配置。
2. 加载外部 MCP tools。
3. 把外部 MCP tool 转成内部 ToolSpec。
```

集成层边界规则：

```text
1. 外部 SDK 和协议细节停留在 integrations 内。
2. 不把 MCP 协议泄漏给业务层。
3. 不把 LLM provider 细节泄漏给业务层。
4. 最终统一输出项目内部契约。
```

---

## 8. 第三层：应用入口层 app_api

`app_api` 位于：

```text
src/app_api/
```

它不是简单的路由层。

它在本项目中承担五类职责：

```text
1. HTTP 协议适配。
2. 应用用例编排。
3. 业务能力到 Agent 工具的适配。
4. Agent 运行事件到业务审计的投影。
5. 系统依赖装配。
```

内部结构：

```text
app_api/
  routers/
  schemas/
  use_cases/
  projectors/
  composition/
  cli/
```

职责：

```text
routers
  FastAPI endpoint、参数接收、响应返回、HTTP 异常映射。

schemas
  HTTP request / response schema。

use_cases
  应用级编排，连接 HTTP 入口和 Agent runtime。

projectors
  把 runtime event 投影到业务数据库。

composition
  系统装配根，集中创建业务服务、Agent 定义、runtime、外部集成和 use case。

cli
  运维入口，例如迁移和诊断。
```

`app_api` 是唯一允许同时依赖业务层和智能体层的地方。

---

## 9. app_api/routers：HTTP 协议适配

路由位于：

```text
src/app_api/routers/
```

当前路由：

```text
agents.py
after_sales_runs.py
after_sales_approvals.py
after_sales_resources.py
health.py
```

路由职责：

```text
1. 定义 URL。
2. 接收 HTTP request。
3. 调用 service 或 use case。
4. 转换 HTTP response。
5. 映射 HTTPException。
6. 做 API key 依赖校验。
```

路由不负责：

```text
1. 不写业务规则。
2. 不创建 SQLAlchemy session。
3. 不直接编排 LangGraph。
4. 不直接写审计日志。
```

Business API 路由直接调用业务服务：

```text
after_sales_resources.py
  -> AfterSalesService
```

Agent API 路由调用 Agent use case：

```text
after_sales_runs.py
after_sales_approvals.py
  -> AfterSalesAgentUseCase
```

---

## 10. app_api/use_cases：应用用例编排

Agent 用例位于：

```text
src/app_api/use_cases/after_sales_agent_use_case.py
```

它负责：

```text
run()
  同步消费 runtime 事件流，返回最终 AgentRunResult。

stream()
  流式消费 runtime 事件，同时触发 projector。

act()
  提交人工审批动作，恢复等待中的 run。

get_state()
  查询 run 状态。
```

Use case 解决的是应用编排问题：

```text
HTTP route 不需要知道 runtime 怎么 stream。
runtime 不需要知道 HTTP response 怎么组织。
projector 不散落在 route 中手动调用。
```

调用关系：

```text
router
  -> AfterSalesAgentUseCase
  -> LangChainAgentRuntime
  -> AfterSalesRunProjector
```

---

## 11. app_api/composition：装配根和工具适配

`composition` 位于：

```text
src/app_api/composition/
```

核心文件：

```text
bootstrap.py
container.py
after_sales_agent_factory.py
```

### bootstrap.py

`bootstrap.py` 是系统装配根。

装配链路：

```text
AppSettings
  -> BusinessDatabase
  -> SqlAlchemyAfterSalesUnitOfWork
  -> AfterSalesService
  -> MCPToolProvider.load_tools()
  -> build_after_sales_agent_definition()
  -> AgentRegistry
  -> build_chat_model()
  -> LangChainAgentRuntime
  -> AfterSalesRunProjector
  -> AfterSalesAgentUseCase
  -> AppContainer
```

它负责把业务层、智能体层、外部集成和应用入口连接起来。

### after_sales_agent_factory.py

这个文件是业务能力到 Agent 工具的适配器。

它把：

```text
AfterSalesService.get_order_detail
AfterSalesService.get_shipment_detail
AfterSalesService.create_ticket
AfterSalesService.get_ticket_detail
AfterSalesService.submit_refund_request
AfterSalesService.search_after_sales_policy
```

适配成：

```text
ToolSpec
```

职责：

```text
1. 定义售后 Agent prompt。
2. 定义本地业务工具目录。
3. 用 Pydantic 校验工具参数。
4. 调用 AfterSalesService。
5. 返回可序列化结果。
6. 给高风险工具绑定 approval_policy。
```

这个文件可以同时 import `after_sales` 和 `agent_core`。

原因是它属于 app_api 层的适配边界。

它不应该下沉到业务层，也不应该放进 agent_runtime。

---

## 12. app_api/projectors：运行事件投影

投影器位于：

```text
src/app_api/projectors/after_sales_run_projector.py
```

Runtime 输出的是执行事件：

```text
ActionStartedEvent
ActionCompletedEvent
ActionRequiredEvent
RunFailedEvent
```

Projector 把这些事件写成业务可追踪记录：

```text
ActionStartedEvent
  -> start_tool_call

ActionCompletedEvent
  -> finish_tool_call

ActionRequiredEvent
  -> request_approval
  -> approval_requested audit log

RunFailedEvent
  -> run_failed audit log

approval decision
  -> resolve_approval
  -> approval_resolved audit log
```

设计边界：

```text
runtime 只负责执行过程；
projector 负责把执行过程中的关键事件落到业务审计；
业务数据库写入仍然通过 Unit of Work。
```

---

## 13. API Surface

Agent discovery：

```text
GET /api/agents
GET /api/agents/{capability_id}/tools
```

Agent run lifecycle：

```text
POST /api/after-sales/runs
POST /api/after-sales/runs/stream
POST /api/after-sales/actions
GET /api/after-sales/runs/{run_id}
```

Business resources：

```text
GET /api/after-sales/orders/{order_id}
GET /api/after-sales/orders/{order_id}/shipment
GET /api/after-sales/customers/{customer_id}
GET /api/after-sales/policies/search?q=...
POST /api/after-sales/tickets
GET /api/after-sales/tickets/{ticket_id}
POST /api/after-sales/refund-requests
GET /api/after-sales/audit-logs?run_id=...
```

API 分组对应入口职责：

```text
Business resources
  确定性业务入口。

Agent run lifecycle
  智能体运行入口。

Agent discovery
  Agent 和工具目录查询入口。
```

---

## 14. 状态模型

系统有三类状态。

### 业务数据库

归属：

```text
after_sales
```

内容：

```text
customers
orders
shipments
tickets
refund requests
approval records
tool call logs
audit logs
```

配置：

```text
BUSINESS_DATABASE_URL
AUTO_CREATE_SCHEMA
```

### Runtime Checkpoint

归属：

```text
agent_runtime
```

内容：

```text
run execution state
LangGraph interrupt state
pending approval action
resume state
runtime error state
```

配置：

```text
AGENT_RUNTIME_DATABASE_URL
```

### Session Transcript

归属：

```text
agent_runtime
```

内容：

```text
session-level human and assistant messages
```

用途：

```text
为后续对话提供上下文。
```

边界规则：

```text
业务事实进入业务数据库。
执行恢复状态进入 runtime checkpoint。
对话上下文进入 session transcript。
RunEvent 是输出事件和投影输入。
RunState 是 checkpoint 派生出的查询视图。
```

---

## 15. 退款审批链路

审批涉及业务层、智能体层和 app_api 层。

规则判断：

```text
AfterSalesService.evaluate_refund_approval
```

工具审批策略：

```text
submit_refund_request ToolSpec
  -> approval_policy
```

执行中断：

```text
LangChainApprovalMiddleware
  -> ActionRequiredEvent
  -> LangGraph interrupt
```

人工动作：

```text
POST /api/after-sales/actions
  -> AfterSalesAgentUseCase.act
  -> LangChainAgentRuntime.stream_action
  -> Command(resume={"decision": ...})
```

业务投影：

```text
AfterSalesRunProjector
  -> request_approval
  -> resolve_approval
  -> audit log
```

职责分布：

```text
业务层
  定义退款风险规则和退款状态。

智能体层
  执行工具前暂停和恢复。

app_api 层
  负责审批 API、用例编排和审计投影。
```

---

## 16. 配置与生产约束

关键环境变量：

```text
APP_ENV
API_KEY
CORS_ALLOWED_ORIGINS

BUSINESS_DATABASE_URL
AGENT_RUNTIME_DATABASE_URL
AUTO_CREATE_SCHEMA

LLM_PROVIDER
LLM_MODEL
DEEPSEEK_API_KEY
OPENAI_API_KEY
LLM_TIMEOUT_SECONDS
LLM_MAX_RETRIES

MAX_STEPS
APPROVAL_TIMEOUT_SECONDS
MCP_SERVERS
```

生产环境要求：

```text
API_KEY
CORS_ALLOWED_ORIGINS
AGENT_RUNTIME_DATABASE_URL
对应 provider 的 LLM API key
```

状态存储选择：

```text
配置 AGENT_RUNTIME_DATABASE_URL
  使用 LangGraph Postgres state store。

未配置 AGENT_RUNTIME_DATABASE_URL
  使用内存 state store，适合本地开发和测试。
```

---

## 17. 分层扩展规则

新增业务能力：

```text
1. 先进入 after_sales。
2. 如需 HTTP 入口，补 app_api/routers 和 app_api/schemas。
3. 如需 Agent 调用，补 app_api/composition/after_sales_agent_factory.py。
```

新增本地 Agent 工具：

```text
1. 如果它是业务能力，先实现到 after_sales。
2. 再通过 ToolSpec 暴露。
3. 需要人工确认时，绑定 approval_policy。
```

新增外部 MCP 工具：

```text
1. 在 MCP_SERVERS 配置 server。
2. agent_integrations/mcp 加载工具。
3. 转换成 ToolSpec。
4. bootstrap 阶段合并进 AgentDefinition。
```

替换 Agent runtime：

```text
1. 保留 agent_core contracts。
2. 新增 agent_runtime/{runtime_name}/。
3. 接收 AgentDefinition 和 ToolSpec。
4. 输出 RunEvent，提供 RunState。
5. 在 app_api/composition/bootstrap.py 切换装配。
6. after_sales 不变。
```

新增业务上下文：

```text
src/{new_context}/
  domain/
  application/
  infrastructure/
```

---

## 18. 分层检查清单

业务层：

```text
1. after_sales 是否不 import app_api？
2. after_sales 是否不 import agent_core / agent_runtime / agent_integrations？
3. 业务写入是否通过 Unit of Work？
```

智能体层：

```text
1. agent_core 是否不 import FastAPI / LangChain / SQLAlchemy / 业务模块？
2. agent_runtime 是否只依赖 agent_core？
3. agent_runtime 是否不写业务数据库？
4. agent_integrations 是否不依赖业务层和 app_api？
5. 工具是否统一表示为 ToolSpec？
6. 运行输出是否统一表示为 RunEvent / RunState？
```

app_api 层：

```text
1. routers 是否只做 HTTP 适配？
2. use_cases 是否承接应用编排？
3. composition 是否是唯一装配根？
4. after_sales_agent_factory 是否只做业务能力到 ToolSpec 的适配？
5. projectors 是否负责 runtime event 到业务审计的投影？
```

推荐验证命令：

```bash
uv run ruff check src tests scripts migrations
uv run mypy src tests
uv run pytest -q
```

---

## 尾注：如何把这个项目作为架构学习资料

这份文档不仅用于说明目录结构，也适合配合源码做系统化学习。

推荐学习方式：

```text
1. 先看分层
   判断当前文件属于业务层、智能体层，还是 app_api 层。

2. 再看职责
   判断这个文件负责契约、适配、编排、映射、投影、状态，还是持久化。

3. 再看调用链
   判断它被谁调用，又调用了谁。

4. 再看边界
   判断它不能依赖什么，不能承担什么职责。

5. 最后抽象成规则
   把代码背后的设计沉淀成可迁移的方法论。
```

手记代码时，不只记录“代码是什么意思”，还要记录：

```text
它为什么存在？
它为什么放在这一层？
它保护了哪个边界？
它解决了哪个变化点？
如果没有它，系统会怎么耦合？
下一个项目能不能复用这个设计？
```

这个项目最值得沉淀的不是某个框架 API，而是：

```text
业务能力如何独立沉淀；
Agent runtime 如何被隔离；
内部契约如何保护系统；
外部能力如何通过 adapter 接入；
运行事件如何投影成业务审计；
业务状态、checkpoint、transcript 如何分开管理。
```

这些才是可以迁移到更复杂系统里的复利资产。
