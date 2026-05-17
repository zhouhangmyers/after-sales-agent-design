# Agent Orchestrator Platform

一套面向业务系统的通用 Agent 编排平台。项目核心不是单个售后助手，而是在 `LangChain v1` 和 `LangGraph` 之上二次开发了一层自研 Agent Runtime，用统一的内部契约管理 Agent 定义、工具执行、运行事件、审批中断、状态恢复和审计投影。

当前仓库使用电商售后作为业务落地场景：订单查询、物流追踪、工单处理、退款申请、人工审批和坐席工作台都只是这套 runtime 的一个 reference implementation。换成财务审批、合同审核、运维处置或内部知识助手时，核心 runtime、工具契约和运行事件模型可以复用，业务层只需要替换领域服务和工具适配。

## 效果演示

<video src="./售后智能体示例-github.mp4" controls width="100%"></video>

如果 GitHub 页面没有显示播放器，可以直接打开演示视频：[售后智能体示例-github.mp4](./售后智能体示例-github.mp4)。

## 核心能力

- 自研通用 runtime：封装 `create_agent`、LangGraph checkpoint、interrupt/resume、工具适配、事件映射和运行结果归一化。
- 框架无关契约：通过 `AgentDefinition`、`ToolSpec`、`RunEvent`、`RunState` 建立项目内部稳定协议，避免业务代码直接绑定 LangChain/MCP/FastAPI。
- 工具编排：本地业务能力和外部 MCP 工具统一转换为 `ToolSpec`，runtime 只面向内部工具契约执行。
- 审批中断：高风险工具调用可在执行前暂停，等待人工决策后从同一个 `run_id` 恢复。
- 状态恢复：明确区分 `session_id` 和 `run_id`，分别管理多轮会话上下文和单次可恢复执行。
- 事件流：将模型输出、工具调用、审批请求、运行完成和异常统一映射为 `RunEvent`，对外支持 SSE。
- 审计投影：runtime 不直接写业务库，应用层 projector 将运行事件投影成工具日志、审批记录和审计日志。
- 售后业务样例：内置订单、物流、工单、退款、政策检索和坐席工作台，用来验证 runtime 的完整闭环。

内置示例数据：

- 订单：`ORD123`、`ORD456`、`ORD789`
- 客户：`CUS001`、`CUS002`、`CUS003`
- 政策关键词：`破损`、`退款`、`质量问题`、`换货`
- 审批场景：`用户要退款 200 元，订单 ORD123，原因是商品破损`

## 技术栈

后端：

- `FastAPI`：HTTP API、依赖注入与 OpenAPI 文档。
- `SQLAlchemy 2.x`：业务数据建模和异步数据库访问。
- `Alembic`：数据库迁移。
- `Pydantic v2` / `pydantic-settings`：数据模型与应用配置。
- `LangChain v1`：底层 Agent 创建、模型调用和工具执行能力。
- `LangGraph`：底层 checkpoint、interrupt、resume 和运行状态恢复能力。
- `sse-starlette`：SSE 事件流。
- `langchain-deepseek` / `langchain-openai`：LLM provider 接入。
- `langchain-mcp-adapters`：MCP server 工具接入。

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
     -> 自研 Agent Runtime
        -> agent_core contracts
        -> agent_runtime/langchain
        -> agent_integrations
     -> business domain
        -> after_sales
```

主要模块：

- `src/app_api`：应用入口层，负责 HTTP 路由、依赖装配、应用用例、运行事件投影和 API schema。
- `src/after_sales`：售后业务层，管理客户、订单、物流、工单、退款、政策和审计数据。
- `src/agent_core`：通用 Agent 契约层，定义 `AgentDefinition`、`ToolSpec`、`RunEvent`、`RunState`。
- `src/agent_runtime`：自研 Agent runtime 层，当前以 LangChain/LangGraph 为底座实现。
- `src/agent_integrations`：外部能力集成层，包括 LLM factory 和 MCP tool provider。
- `frontend`：售后坐席工作台。

业务层不依赖 Agent runtime，runtime 也不感知订单、退款、工单等业务语义。两者通过 `ToolSpec` 和应用层 composition 连接。这个边界保证 runtime 是通用基础设施，售后只是当前接入的一套业务能力。

## 自研 Runtime

`src/agent_runtime/langchain` 不是直接把 LangChain 暴露给业务层，而是在 LangChain/LangGraph 之上做了一层平台化封装。

它负责把底层框架能力整理成项目自己的运行时模型：

- 编译和缓存 Agent。
- 将 `ToolSpec` 转换为 LangChain `StructuredTool`。
- 注入 `ToolContext`，让工具执行时拿到统一运行上下文。
- 将 LangChain stream part 映射为稳定的 `RunEvent`。
- 使用 LangGraph checkpoint 管理 `run_id` 级运行状态。
- 使用 session transcript 管理 `session_id` 级多轮上下文。
- 通过 middleware 处理工具执行前审批。
- 将 checkpoint snapshot 映射为可查询的 `RunState`。
- 将单次执行结果归一化为 `AgentRunResult`。

这层 runtime 的目标是把 Agent 应用里最容易散落的部分收拢起来：工具协议、审批恢复、事件流、状态查询、错误结构和会话历史。业务模块只需要提供领域服务和工具定义，不需要关心 LangChain stream 格式、LangGraph interrupt 细节或 checkpoint 存储实现。

## 通用契约

平台内部以四个核心契约作为稳定边界：

- `AgentDefinition`：描述一个 Agent 能力，包括能力 ID、名称、system prompt 和工具集合。
- `ToolSpec`：描述一个可被模型调用的工具，包括参数 schema、handler、来源和审批策略。
- `RunEvent`：描述 runtime 输出的运行事件，用于 SSE、前端展示和审计投影。
- `RunState`：描述从 checkpoint 派生出的运行状态，用于页面刷新、审批恢复和状态查询。

这些契约让 runtime 不依赖具体业务，也让业务层不依赖 LangChain。未来如果底层从 LangChain/LangGraph 切到其它执行引擎，只要继续接收 `AgentDefinition` / `ToolSpec` 并输出 `RunEvent` / `RunState`，业务层和 API 层就不需要重写。

## 运行流程

普通 Agent run：

```text
POST /api/after-sales/runs
  -> AfterSalesAgentUseCase
  -> 自研 LangChainAgentRuntime.stream_run()
  -> 编译/复用 LangChain agent
  -> ToolSpec -> LangChain StructuredTool
  -> AfterSalesService
  -> UnitOfWork / Repository
  -> Business Database
```

审批恢复流程：

```text
submit_refund_request tool call
  -> approval_policy 命中风险规则
  -> ActionRequiredEvent
  -> runtime 触发 LangGraph interrupt
  -> POST /api/after-sales/actions
  -> runtime 提交 Command(resume={"decision": ...})
  -> 从 checkpoint 恢复并继续执行
```

系统当前的退款审批规则：

- 退款金额大于 `100` 元需要审批。
- 退款原因包含 `破损` 或 `质量问题` 需要审批。
- 金额和原因同时命中时标记为高风险。

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

# 执行业务数据库迁移或建表
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

关键配置说明：

- `APP_ENV`：应用环境。生产环境会启用更严格的配置校验。
- `API_KEY`：配置后，受保护 API 需要请求头 `X-API-Key`。
- `BUSINESS_DATABASE_URL`：售后业务库，默认使用本地 SQLite。
- `AGENT_RUNTIME_DATABASE_URL`：Agent runtime 状态库。留空时使用内存 checkpointer；配置 PostgreSQL 后可持久化 checkpoint 和 session transcript。
- `LLM_PROVIDER`：当前支持 `deepseek` 和 `openai`。
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

runtime 将这两类状态明确隔离：checkpoint 只服务于 Agent 执行恢复，业务数据库只保存业务事实和审计投影。这样不会把 LangGraph 的内部状态泄漏到业务模型里，也不会让业务事务依赖模型执行过程。

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
- FastAPI 集成接口。
- README 和 `.env.example` 的公共接口一致性。

运行：

```bash
uv run pytest -q
```

## 推荐阅读路径

1. [src/agent_core/contracts/agent_definition.py](src/agent_core/contracts/agent_definition.py)
2. [src/agent_core/contracts/tool_spec.py](src/agent_core/contracts/tool_spec.py)
3. [src/agent_runtime/langchain/runtime.py](src/agent_runtime/langchain/runtime.py)
4. [src/agent_runtime/langchain/approval_middleware.py](src/agent_runtime/langchain/approval_middleware.py)
5. [src/agent_runtime/langchain/event_mapper.py](src/agent_runtime/langchain/event_mapper.py)
6. [src/app_api/composition/bootstrap.py](src/app_api/composition/bootstrap.py)
7. [src/app_api/composition/after_sales_agent_factory.py](src/app_api/composition/after_sales_agent_factory.py)
8. [src/app_api/projectors/after_sales_run_projector.py](src/app_api/projectors/after_sales_run_projector.py)
9. [src/after_sales/application/services/after_sales_service.py](src/after_sales/application/services/after_sales_service.py)
10. [frontend/src/App.tsx](frontend/src/App.tsx)

## 设计边界

- `after_sales` 负责业务规则和事务边界，不依赖 FastAPI、LangChain 或 MCP。
- `agent_runtime` 是通用执行层，负责 Agent 执行、checkpoint、interrupt/resume、事件映射和结果归一化。
- `app_api` 是 composition root，负责把业务能力适配为 Agent 工具。
- `agent_core` 保持框架无关，作为业务工具、MCP 工具和运行时之间的稳定契约。
- 审批和审计是业务投影，不混入 LangGraph checkpoint。
- `session_id` 用于多轮对话上下文，`run_id` 用于单次可恢复执行。
