# Agent Orchestrator Platform

一个面向业务系统的通用 Agent 编排平台。

本项目为独立设计与实现的工程项目，不是单纯的“售后客服机器人”，而是在 `LangChain v1` 和 `LangGraph` 之上封装了一层项目自有的 Agent Runtime，用稳定的内部契约管理 Agent 定义、工具执行、审批中断、状态恢复、事件流和审计投影。

当前仓库以电商售后作为落地场景：查订单、查物流、创建工单、退款申请、人工审批、审计记录和坐席工作台。售后业务只是 reference implementation，核心设计可以迁移到财务审批、合同审核、运维处置、招聘匹配、企业知识助手等其它领域。

## Demo

https://github.com/user-attachments/assets/3da5c1fb-d590-4f52-a41f-bb5dc8b6d984

## 项目定位

这个项目重点验证的是 Agent 应用中最容易散落的工程问题：

- 如何让业务工具、本地服务和外部 MCP 工具都通过统一协议暴露给 Agent。
- 如何把 LangChain/LangGraph 的底层事件、checkpoint、interrupt/resume 收敛成项目自己的运行模型。
- 如何在高风险工具调用前暂停，并在人工审批后从同一个 `run_id` 恢复。
- 如何把运行事件投影为业务侧可查询的工具日志、审批记录和审计日志。
- 如何让 HTTP、CLI、前端、业务层和 Runtime 保持清晰边界。

当前版本聚焦 Agent 编排、审批恢复、事件流和审计闭环。售后政策查询保留为轻量检索能力，后续可以在新业务场景中扩展为 RAG 或更完整的知识库能力。

## 核心能力

- 自研 Runtime：封装 `create_agent`、LangGraph checkpoint、interrupt/resume、工具适配、事件映射和结果归一化。
- 框架无关契约：通过 `AgentDefinition`、`ToolSpec`、`RunEvent`、`RunState` 隔离业务层和 LangChain/LangGraph。
- 工具编排：本地业务工具和外部 MCP 工具统一转换为 `ToolSpec`。
- 审批中断：退款等高风险动作可在工具执行前暂停，等待人工审批后恢复。
- 状态分层：`session_id` 管理多轮会话上下文，`run_id` 管理单次可恢复执行。
- SSE 事件流：模型输出、工具调用、审批请求、完成和失败事件统一对外推送。
- 审计投影：Runtime 不直接写业务库，应用层 projector 将事件投影成业务日志。
- 可降级启动：LLM/MCP 依赖失败时应用可 degraded 启动，健康检查展示原因。
- 前后端闭环：FastAPI 后端和 React 坐席工作台覆盖查询、运行、审批和审计。

内置示例数据：

- 订单：`ORD123`、`ORD456`、`ORD789`
- 客户：`CUS001`、`CUS002`、`CUS003`
- 政策关键词：`破损`、`退款`、`质量问题`、`换货`
- 审批场景：`用户要退款 200 元，订单 ORD123，原因是商品破损`

## 技术栈

后端：

- `FastAPI`
- `SQLAlchemy 2.x`
- `Alembic`
- `Pydantic v2` / `pydantic-settings`
- `LangChain v1`
- `LangGraph`
- `sse-starlette`
- `langchain-deepseek` / `langchain-openai`
- `langchain-mcp-adapters`

前端：

- `React 18`
- `Vite`
- `TypeScript`
- `Ant Design`
- `@microsoft/fetch-event-source`

## 架构概览

```text
Client / Frontend
  -> app_api
     -> composition root
     -> use cases / projectors
     -> HTTP routers / CLI
  -> agent_core contracts
     -> AgentDefinition / ToolSpec / RunEvent / RunState
  -> agent_runtime
     -> LangChainAgentRuntime
     -> approval middleware
     -> event/result mapper
     -> checkpoint store
  -> agent_integrations
     -> LLM factory
     -> MCP tool provider
  -> after_sales
     -> domain models
     -> application service
     -> repositories / unit of work
```

主要模块：

- `src/agent_core`：框架无关契约层，定义 Agent、工具、事件和状态协议。
- `src/agent_runtime`：通用执行层，当前基于 LangChain/LangGraph 实现。
- `src/agent_integrations`：外部集成层，包含 LLM factory 和 MCP tool provider。
- `src/after_sales`：售后业务层，包含领域模型、服务、仓储和事务边界。
- `src/app_api`：应用装配与入口层，包含 bootstrap、use case、projector、HTTP 路由和 CLI。
- `frontend`：售后坐席工作台。

核心边界：

- 业务层不依赖 FastAPI、LangChain 或 MCP。
- Runtime 不感知订单、退款、工单等售后语义。
- 业务能力通过 `ToolSpec` 接入 Agent。
- 运行状态和业务审计分库存储、分层管理。

## 关键设计

### 1. 通用工具契约

项目内部不直接把业务函数或 MCP 工具塞给 LangChain，而是统一包装成 `ToolSpec`：

```text
ToolSpec
  -> name
  -> description
  -> args_schema
  -> handler(payload, ToolContext)
  -> approval_policy
  -> source / source_id
```

本地售后工具和外部 MCP 工具都遵守这套协议。Runtime 只负责执行 `ToolSpec`，不需要知道工具来自业务服务还是 MCP server。

### 2. 自研 Runtime 封装

`src/agent_runtime/langchain` 没有把 LangChain 原始接口直接暴露给业务层，而是做了一层平台化封装：

- 将 `ToolSpec` 转换成 LangChain `StructuredTool`。
- 注入 `ToolContext`。
- 编译和缓存 Agent。
- 将底层 stream part 映射为稳定 `RunEvent`。
- 使用 LangGraph checkpoint 管理可恢复执行。
- 使用 middleware 在工具执行前处理审批中断。
- 将 checkpoint snapshot 映射成 `RunState`。
- 将最终输出归一化为 `AgentRunResult`。

### 3. 审批中断与恢复

退款工具挂载审批策略：

- 金额大于 `100` 元需要审批。
- 原因包含 `破损` 或 `质量问题` 需要审批。
- 金额和原因同时命中时标记为高风险。

执行链路：

```text
用户请求退款
  -> 模型选择 submit_refund_request
  -> approval_policy.evaluate(payload)
  -> ActionRequiredEvent
  -> LangGraph interrupt
  -> 前端展示待审批动作
  -> POST /api/after-sales/actions
  -> Command(resume={"decision": ...})
  -> Runtime 从 checkpoint 恢复
  -> 继续执行并返回结果
```

### 4. 事件流与审计投影

Runtime 产出统一事件：

- `RunStartedEvent`
- `OutputDeltaEvent`
- `ActionStartedEvent`
- `ActionCompletedEvent`
- `ActionRequiredEvent`
- `RunCompletedEvent`
- `RunFailedEvent`

HTTP 层把这些事件映射为 SSE；projector 把这些事件写入业务库：

- 工具调用日志
- 审批记录
- 审计日志

这让 Agent 执行过程可展示、可恢复、可追踪，而不是只返回一段最终文本。

## 典型流程

普通 Agent run：

```text
POST /api/after-sales/runs
  -> AfterSalesAgentUseCase.run()
  -> LangChainAgentRuntime.stream_run()
  -> AgentDefinition.tools
  -> ToolSpec -> StructuredTool
  -> AfterSalesService
  -> UnitOfWork / Repository
  -> Business Database
  -> RunCompletedEvent
  -> RunResponse
```

流式 Agent run：

```text
POST /api/after-sales/runs/stream
  -> AfterSalesAgentUseCase.stream()
  -> Runtime RunEvent stream
  -> AfterSalesRunProjector.record_event()
  -> after_sales_runs._map_event()
  -> text/event-stream
```

审批恢复：

```text
POST /api/after-sales/actions
  -> AfterSalesAgentUseCase.act()
  -> runtime.stream_action()
  -> projector.resolve_approval()
  -> Runtime resumes from checkpoint
  -> RunCompletedEvent
```

## 快速启动

进入项目目录：

```bash
cd /home/zhouhangmyers/python/agent-orchestrator-platform
```

安装后端依赖：

```bash
uv sync --extra dev
```

准备环境变量：

```bash
cp .env.example .env
```

至少配置一个可用模型：

```env
LLM_PROVIDER=deepseek
LLM_MODEL=deepseek-chat
DEEPSEEK_API_KEY=replace-me
```

初始化本地业务数据：

```bash
make seed
```

启动后端：

```bash
make backend-start
```

后端默认地址：

- API 文档：`http://127.0.0.1:8000/docs`
- 健康检查：`http://127.0.0.1:8000/health`

启动前端：

```bash
cd frontend
npm install
cd ..
make frontend-start
```

前端默认地址：

- `http://127.0.0.1:5173`

一键同时启动前后端：

```bash
make start
```

## 常用命令

```bash
# 启动后端
make backend-start

# 启动前端
make frontend-start

# 写入示例数据
make seed

# 检查依赖状态
make doctor

# 执行业务数据库迁移和 runtime store 初始化
make migrate

# 运行测试
make test
```

质量检查：

```bash
uv run pytest -q
uv run ruff check src tests scripts
uv run mypy src tests
```

## 配置

项目默认读取 `.env`，完整示例见 [.env.example](.env.example)。

```env
APP_ENV=dev
CORS_ALLOWED_ORIGINS=http://127.0.0.1:5173,http://localhost:5173
API_KEY=

BUSINESS_DATABASE_URL=sqlite+pysqlite:///./after_sales_mvp.db
AGENT_RUNTIME_DATABASE_URL=
AUTO_CREATE_SCHEMA=true

LLM_PROVIDER=deepseek
LLM_MODEL=deepseek-chat
LLM_TIMEOUT_SECONDS=30.0
LLM_MAX_RETRIES=2
DEEPSEEK_API_KEY=replace-me
OPENAI_API_KEY=

MAX_STEPS=4
APPROVAL_TIMEOUT_SECONDS=900
MCP_SERVERS={}
```

关键配置：

- `APP_ENV`：应用环境。生产环境会启用更严格的配置校验。
- `API_KEY`：配置后，受保护 API 需要请求头 `X-API-Key`。
- `BUSINESS_DATABASE_URL`：售后业务库，默认使用本地 SQLite。
- `AGENT_RUNTIME_DATABASE_URL`：Agent runtime 状态库。留空时使用内存 checkpointer；配置 PostgreSQL 后可持久化 checkpoint 和 session transcript。
- `LLM_PROVIDER`：当前支持 `deepseek` 和 `openai`。
- `LLM_MODEL`：模型名称。
- `DEEPSEEK_API_KEY`：DeepSeek provider 使用的 API key。
- `OPENAI_API_KEY`：OpenAI provider 使用的 API key。
- `MAX_STEPS`：限制单次 Agent 执行步骤数。
- `MCP_SERVERS`：可选 MCP server 配置，支持 `http`、`streamable_http` 和 `stdio` transport。

生产环境要求：

- `API_KEY`
- `CORS_ALLOWED_ORIGINS`
- `AGENT_RUNTIME_DATABASE_URL`
- 当前 LLM provider 对应的 API key

前端可选配置：

```env
VITE_API_BASE_URL=http://127.0.0.1:8000
VITE_API_KEY=replace-me
```

## API

健康检查：

- `GET /health`

Agent 目录：

- `GET /api/agents`
- `GET /api/agents/{capability_id}/tools`

Agent run：

- `POST /api/after-sales/runs`
- `POST /api/after-sales/runs/stream`
- `POST /api/after-sales/actions`
- `GET /api/after-sales/runs/{run_id}`

售后业务资源：

- `GET /api/after-sales/orders/{order_id}`
- `GET /api/after-sales/orders/{order_id}/shipment`
- `GET /api/after-sales/customers/{customer_id}`
- `GET /api/after-sales/policies/search?q=...`
- `POST /api/after-sales/tickets`
- `GET /api/after-sales/tickets/{ticket_id}`
- `POST /api/after-sales/refund-requests`
- `GET /api/after-sales/audit-logs?run_id=...`

## 调用示例

同步运行 Agent：

```bash
curl -X POST http://127.0.0.1:8000/api/after-sales/runs \
  -H "Content-Type: application/json" \
  -d '{
    "message": "帮我查一下订单 ORD123 的状态",
    "actor_id": "agent-user-001"
  }'
```

流式运行 Agent：

```bash
curl -N -X POST http://127.0.0.1:8000/api/after-sales/runs/stream \
  -H "Content-Type: application/json" \
  -d '{
    "message": "用户要退款 200 元，订单 ORD123，原因是商品破损",
    "actor_id": "agent-user-001"
  }'
```

提交审批决策：

```bash
curl -X POST http://127.0.0.1:8000/api/after-sales/actions \
  -H "Content-Type: application/json" \
  -d '{
    "run_id": "run-xxxx",
    "action_id": "submit_refund_request",
    "decision": "approved",
    "actor_id": "supervisor-001"
  }'
```

查询业务资源：

```bash
curl http://127.0.0.1:8000/api/after-sales/orders/ORD123
curl http://127.0.0.1:8000/api/after-sales/orders/ORD123/shipment
curl "http://127.0.0.1:8000/api/after-sales/policies/search?q=破损"
```

## SSE 事件

`POST /api/after-sales/runs/stream` 返回 `text/event-stream`。

主要事件：

- `run.started`：run 已创建。
- `output.delta`：模型输出增量。
- `action.started`：工具调用开始。
- `action.completed`：工具调用完成。
- `action.required`：需要人工审批或处理。
- `run.completed`：当前执行段结束。
- `run.failed`：运行失败。

`run.completed` 的状态可能是：

- `completed`
- `awaiting_action`
- `failed`

## 数据与持久化

系统包含两类状态：

- 业务数据：客户、订单、物流、工单、退款、政策、工具日志、审批记录和审计日志。
- Agent 运行态：LangGraph checkpoint 与 session transcript。

这两类状态明确隔离：

```text
Business Database
  -> 业务事实
  -> 工具调用日志
  -> 审批记录
  -> 审计日志

Runtime State Store
  -> LangGraph checkpoint
  -> session transcript
```

本地开发默认配置：

```env
BUSINESS_DATABASE_URL=sqlite+pysqlite:///./after_sales_mvp.db
AGENT_RUNTIME_DATABASE_URL=
AUTO_CREATE_SCHEMA=true
```

使用 PostgreSQL 持久化 Agent runtime 状态：

```bash
docker compose up -d postgres
```

```env
AGENT_RUNTIME_DATABASE_URL=postgresql://agent:agent@127.0.0.1:5432/agent_platform
```

## MCP 工具接入

平台通过 `ToolSpec` 统一管理本地工具和外部 MCP 工具。MCP 工具加载后会追加到当前 Agent 的工具列表中，并使用 `mcp_<server>_<tool>` 格式生成命名空间前缀。

配置示例：

```env
MCP_SERVERS={"weather":{"transport":"http","url":"http://localhost:8000/mcp"},"math":{"transport":"stdio","command":"python","args":["./examples/math_server.py"]}}
```

如果 MCP 加载失败，应用仍会启动，`/health` 会返回 `degraded` 并展示错误详情。

## 测试

测试覆盖：

- 配置读取与生产环境校验。
- LLM provider factory。
- MCP tool registry。
- LangChain runtime。
- 事件映射与结果映射。
- 审批中断与恢复。
- FastAPI 集成接口。
- README 和 `.env.example` 的公共接口一致性。

运行：

```bash
uv run pytest -q
```

## 当前状态

当前版本已经完成一条完整的 Agent 业务闭环：

- 本地业务工具与外部 MCP 工具统一接入 `ToolSpec`。
- Runtime 支持工具调用、审批中断、状态恢复、SSE 事件流和结果归一化。
- 应用层将运行事件投影为工具调用日志、审批记录和审计日志。
- HTTP API、CLI、React 前端和测试用例覆盖核心使用路径。

后续扩展方向包括：新业务领域接入、RAG/知识库能力、多租户权限、运行观测、评测体系和更细粒度的工具权限控制。
