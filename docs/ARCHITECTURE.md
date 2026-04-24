# 项目架构说明

## 结论

这套架构的长期发展性是强的，但前提是继续守住一个边界：

```text
business_service  不依赖  agent_service
agent_service     不依赖  business_service
```

两者只在 `app_api` 的 composition / adapter 层相遇。这样未来如果不用 LangChain / LangGraph，主要替换 Agent adapter 和 runtime，不需要改售后业务核心。

## 分层

```text
src/
  business_service/
    after_sales/
      domain/
      application/services/
      infrastructure/

  agent_service/
    contracts/
    infrastructure/mcp/
    infrastructure/runtime/
    infrastructure/state_store/
    llm/

  app_api/
    routers/
    services/
    bootstrap.py
```

### `business_service`

负责纯售后业务：

- 订单、物流、工单、退款、政策查询。
- 退款审批规则。
- 领域模型和仓储。
- 业务数据库读写。
- Unit of Work 事务边界。

不负责：

- `ToolSpec` / `AgentDefinition`。
- SSE / `RunEvent`。
- LangChain / LangGraph。
- checkpoint / session transcript。

### `agent_service`

负责当前 Agent 主链能力：

- LangChain `create_agent` runtime。
- middleware、tool call wrapper、审批中断恢复。
- `ToolSpec` / `AgentDefinition` 等窄版 Agent contracts。
- 代码型 Agent registry 和 MCP tool adapter。
- `RunEvent` / `RunState` 的 API 视图模型。
- LangGraph checkpoint 和 session transcript。
- LLM provider factory。

不负责：

- 售后业务规则。
- 订单、工单、退款的领域解释。
- 业务数据库投影。
- 多框架 runtime adapter 平台。

### `app_api`

负责把系统装起来：

- FastAPI 路由。
- dependency container。
- 代码注册当前 agent catalog，并把 MCP tools 合并到当前 agent 定义。
- HTTP request / response schema。
- SSE event mapping。
- tool log、approval、audit log 投影。
- 把 `AfterSalesService` 包装成当前 Agent 主线需要的 `ToolSpec` / `AgentDefinition`。

API 请求链路使用 async 优先：

- FastAPI route 是 `async def`。
- `AfterSalesService` 的 I/O 方法是 async。
- `AfterSalesService` 通过 Unit of Work 显式控制事务提交。
- `SqlAlchemyAfterSalesRepository` 使用 SQLAlchemy `AsyncSession`，不直接 `commit`。
- PostgreSQL runtime transcript 使用 SQLAlchemy async engine。
- Alembic 迁移仍走同步 engine，避免把迁移工具链混入在线请求链路。

关键桥接文件：

- `src/app_api/bootstrap.py`
- `src/app_api/services/after_sales_agent_definition.py`
- `src/app_api/services/after_sales_assistant.py`
- `src/app_api/services/after_sales_run_projector.py`

## 依赖方向

允许：

```text
app_api -> business_service
app_api -> agent_service
business_service -> business_service.*
agent_service -> agent_service.*
```

禁止：

```text
business_service -> agent_service
agent_service -> business_service
```

原因很简单：业务能力应该比 Agent 框架活得更久。Agent 框架可以换，售后业务语义不应该跟着重写。

## 运行链路

一次售后 Agent 请求的大致链路是：

```text
HTTP route
  -> AfterSalesAssistantService
  -> LangChainAgentRuntime
  -> AgentDefinition / ToolSpec
  -> AfterSalesService
  -> AfterSalesUnitOfWork
  -> AfterSalesRepository protocol
  -> SqlAlchemyAfterSalesRepository / AsyncSession
```

其中：

- `AfterSalesService` 是纯业务服务。
- `after_sales_agent_definition.py` 是 Agent adapter。
- MCP tools 在 composition 阶段转换为同一种 `ToolSpec`，命名为 `mcp_{server}_{tool}`。
- `LangChainAgentRuntime` 是当前 runtime 实现。
- `AfterSalesRunProjector` 负责把运行事件投影成 tool log、approval 和 audit log。
- repository 负责业务数据库。

## 公共接口

Agent API：

- `GET /api/agents`
- `GET /api/agents/{capability_id}/tools`
- `POST /api/after-sales/runs`
- `POST /api/after-sales/runs/stream`
- `POST /api/after-sales/actions`
- `GET /api/after-sales/runs/{run_id}`

Business API：

- `GET /api/after-sales/orders/{order_id}`
- `GET /api/after-sales/orders/{order_id}/shipment`
- `GET /api/after-sales/customers/{customer_id}`
- `GET /api/after-sales/policies/search?q=...`
- `POST /api/after-sales/tickets`
- `GET /api/after-sales/tickets/{ticket_id}`
- `POST /api/after-sales/refund-requests`
- `GET /api/after-sales/audit-logs?run_id=...`

## 关键环境变量

- `LLM_PROVIDER`
- `LLM_MODEL`
- `DEEPSEEK_API_KEY`
- `OPENAI_API_KEY`
- `BUSINESS_DATABASE_URL`
- `AGENT_RUNTIME_DATABASE_URL`
- `MCP_SERVERS`

## 状态边界

系统里有三类状态，不要混成一套：

```text
业务数据库
  订单、物流、工单、退款、approval record、audit log、tool call log

LangGraph checkpoint
  run 级 durable execution state，用于中断和恢复

session transcript
  session 级对话历史，用于后续上下文
```

`RunEvent` 只作为 API / SSE 输出模型。  
`RunState` 只作为从 LangGraph checkpoint 派生的查询视图。  
二者都不是事实源，也不应该发展成 event sourcing / replay 平台。

业务数据库的一致性由 SQLAlchemy Unit of Work 负责。LangSmith 可以记录 agent trace、tool call、模型调用、评测和监控数据，但它不是事务管理器，不能替代业务数据库 commit / rollback 边界。

## 为什么长期发展性强

强在这几个点：

- 业务层和智能体层双向不依赖。
- 业务能力以普通 service 方法表达，不绑定 LangChain tool。
- Agent tool catalog 是 adapter，不是业务核心。
- durable state 使用 LangGraph checkpointer，不自研第二套 runtime state。
- 业务 service 依赖 repository protocol，不直接依赖 SQLAlchemy 实现。
- 写入用例通过 Unit of Work 聚合提交，repository 只做数据访问。
- MCP 外部工具被适配到现有 `ToolSpec`，不会把 MCP 协议泄漏到业务层。
- API 到 repository 保持全链路 async，不在请求链路里混用同步 DB I/O。
- 当前不自建 observability 抽象；生产观测优先采用 FastAPI middleware、structured logging、LangSmith 或 OpenTelemetry。

这意味着未来替换 Agent 框架时，优先改：

- `src/app_api/services/after_sales_agent_definition.py`
- `src/agent_service/infrastructure/runtime/`
- 必要时新增新的主线 runtime 实现

尽量不改：

- `src/business_service/after_sales/domain/`
- `src/business_service/after_sales/application/services/`
- `src/business_service/after_sales/infrastructure/`
- 现有售后业务 API 语义

## 演进规则

新增售后业务能力时：

1. 先加到 `business_service.after_sales` 的 domain / service / repository。
2. 再在 `app_api.services.after_sales_agent_definition` 里包装成工具。
3. 最后按需要调整 prompt、测试和 HTTP 投影。

替换主 runtime 时：

1. 保留业务服务不动。
2. 保留 HTTP API 语义不动。
3. 新 runtime 只承接 tool calling、审批中断、状态恢复、事件输出。
4. 不引入框架无关 `AgentRuntime` 平台层。

## 反模式

这些方向应该避免：

- 在 `business_service` 中 import `agent_service`。
- 在 `agent_service` 中 import 售后业务模块。
- 把 `ToolSpec` 扩展成 OpenAI / PydanticAI / AutoGen / ADK / CrewAI 的大一统 schema。
- 在 LangGraph checkpoint 外再做一套完整 run state store。
- 把 `RunEvent` 存成事实日志，再做 replay / projection 平台。
- 在主工程里维护多 Agent 框架示例，再反向设计主线抽象。

## 一句话

这个项目不是框架无关 Agent 平台。它是一个业务边界清晰的售后 Agent 后端：业务层稳定，Agent 层可替换，二者通过 app/API adapter 组合。
