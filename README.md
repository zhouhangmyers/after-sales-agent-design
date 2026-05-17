# After-Sales Agent Platform

一个教学优先的售后客服 Agent 平台样板工程。项目围绕“电商售后坐席”场景展开，完整串起订单查询、物流查询、售后工单、退款申请、人工审批、工具调用审计和前端工作台。

后端主线使用 `FastAPI + SQLAlchemy + LangChain v1 create_agent + LangGraph checkpoint`，前端使用 `React + Vite + Ant Design`。这个项目的重点不是堆很多框架示例，而是把一个 Agent 应用拆成清晰、可测试、可演进的工程结构。

## 项目能做什么

当前内置一个售后客服 Agent：`after_sales_assistant`。

它可以通过自然语言触发这些业务动作：

- 查询订单详情，例如订单状态、金额、商品摘要。
- 查询物流详情，例如承运商、运单号、最新节点和预计送达时间。
- 创建售后工单，例如破损、退货、换货和其它问题登记。
- 查询工单详情。
- 提交退款申请。
- 搜索售后政策、退款规则和工单 SOP。
- 对高风险退款进行人工审批中断，审批通过后从同一个 `run_id` 恢复执行。

种子数据里可以直接使用这些示例：

- 订单：`ORD123`、`ORD456`、`ORD789`
- 客户：`CUS001`、`CUS002`、`CUS003`
- 政策关键词：`破损`、`退款`、`质量问题`、`换货`
- 审批示例：`用户要退款 200 元，订单 ORD123，原因是商品破损`

## 技术栈

后端：

- `FastAPI`：HTTP API、依赖注入、OpenAPI 文档。
- `SQLAlchemy 2.x`：售后业务数据库访问。
- `Alembic`：数据库迁移。
- `Pydantic v2` / `pydantic-settings`：请求响应模型和配置读取。
- `LangChain v1`：`create_agent`、模型调用、工具调用。
- `LangGraph`：checkpoint、interrupt、resume 和 durable workflow state。
- `sse-starlette`：Agent 流式事件输出。
- `langchain-deepseek` / `langchain-openai`：LLM provider 接入。
- `langchain-mcp-adapters`：可选 MCP server 工具接入。

前端：

- `React 18`
- `Vite`
- `TypeScript`
- `Ant Design`
- `@microsoft/fetch-event-source`：消费 SSE 事件流。

## 目录结构

```text
agent-orchestrator-platform/
  src/
    app_api/
      main.py
      deps.py
      settings.py
      composition/
      projectors/
      routers/
      schemas/
      use_cases/
    after_sales/
      domain/
      application/
      infrastructure/
    agent_core/
      contracts/
      support/
      registry.py
    agent_runtime/
      langchain/
    agent_integrations/
      llm/
      mcp/
  frontend/
    src/
      App.tsx
      api/
      types.ts
      styles.css
  migrations/
  scripts/
    seed.py
  tests/
  docs/
    ARCHITECTURE.md
  compose.yaml
  Makefile
  pyproject.toml
```

核心分层：

- `after_sales` 是纯售后业务层，管理客户、订单、物流、工单、退款、政策和审计日志。
- `agent_core` 是框架无关的 Agent 契约层，定义 `AgentDefinition`、`ToolSpec`、`RunEvent`、`RunState` 等内部语言。
- `agent_runtime` 是执行层，当前主实现是 LangChain/LangGraph runtime。
- `agent_integrations` 收拢外部 SDK 和协议接入，例如 LLM factory、MCP tool provider。
- `app_api` 是应用入口层，负责 HTTP 路由、依赖装配、业务服务到 Agent 工具的适配、运行事件投影。
- `frontend` 是售后工作台，用来演示坐席对话、工具执行状态、审批队列、业务资料和审计信息。

更完整的架构说明见 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)。

## 运行机制

一次普通 Agent run 的主流程：

```text
Client
  -> POST /api/after-sales/runs 或 /runs/stream
  -> AfterSalesAgentUseCase
  -> LangChainAgentRuntime.stream_run()
  -> LangChain create_agent
  -> ToolSpec -> LangChain StructuredTool
  -> AfterSalesService
  -> UnitOfWork / Repository
  -> Business Database
```

如果工具命中审批策略，例如退款金额超过 100 元或原因包含“破损/质量问题”：

```text
Agent 生成 submit_refund_request tool call
  -> ApprovalMiddleware 检查 approval_policy
  -> 发出 action.required 事件
  -> LangGraph interrupt 暂停 run
  -> 前端/调用方提交 POST /api/after-sales/actions
  -> LangGraph Command(resume=...)
  -> 原 run 从 checkpoint 恢复执行
```

运行过程中，系统会把工具调用、审批请求和审批结果投影到业务库，方便页面展示和后续审计。

## 快速开始

进入项目：

```bash
cd /home/zhouhangmyers/python/agent-orchestrator-platform
```

安装 Python 依赖：

```bash
uv sync --extra dev
```

准备环境变量：

```bash
cp .env.example .env
```

然后编辑 `.env`，至少配置一个可用模型：

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

- Swagger 文档：`http://127.0.0.1:8000/docs`
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

# 写入本地种子数据
make seed

# 检查依赖健康状态
make doctor

# 执行业务数据库迁移/建表
make migrate

# 运行测试
make test
```

也可以直接运行质量检查：

```bash
uv run pytest -q
uv run ruff check src tests scripts
uv run mypy src tests
```

## 环境变量

项目会读取 `.env`。完整示例见 [.env.example](.env.example)。

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

说明：

- `APP_ENV=production` 时必须配置 `API_KEY`、`CORS_ALLOWED_ORIGINS`、`AGENT_RUNTIME_DATABASE_URL` 和对应 provider 的 API key。
- `BUSINESS_DATABASE_URL` 是售后业务库，默认使用本地 SQLite。
- `AGENT_RUNTIME_DATABASE_URL` 是 LangGraph runtime state store。留空时使用内存 checkpointer；配置 PostgreSQL 后可以持久化 run checkpoint 和 session transcript。
- `LLM_PROVIDER` 当前支持 `deepseek` 和 `openai`。
- `MAX_STEPS` 控制单次 Agent 执行的最大步骤数，避免无限工具循环。
- `MCP_SERVERS` 是 JSON 对象，可配置 `http`、`streamable_http` 或 `stdio` transport 的 MCP server。
- `API_KEY` 配置后，业务和 Agent API 需要请求头 `X-API-Key: <value>`。

前端可选环境变量：

```env
VITE_API_BASE_URL=http://127.0.0.1:8000
VITE_API_KEY=replace-me
```

## API 概览

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

## 请求示例

同步调用 Agent：

```bash
curl -X POST http://127.0.0.1:8000/api/after-sales/runs \
  -H "Content-Type: application/json" \
  -d '{
    "message": "帮我查一下订单 ORD123 的状态",
    "actor_id": "agent-user-001"
  }'
```

流式调用 Agent：

```bash
curl -N -X POST http://127.0.0.1:8000/api/after-sales/runs/stream \
  -H "Content-Type: application/json" \
  -d '{
    "message": "用户要退款 200 元，订单 ORD123，原因是商品破损",
    "actor_id": "agent-user-001"
  }'
```

如果返回 `action.required`，使用其中的 `run_id` 和 `pending_action.action_id` 提交审批：

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

直接查询业务资源：

```bash
curl http://127.0.0.1:8000/api/after-sales/orders/ORD123
curl http://127.0.0.1:8000/api/after-sales/orders/ORD123/shipment
curl "http://127.0.0.1:8000/api/after-sales/policies/search?q=破损"
```

## SSE 事件

`POST /api/after-sales/runs/stream` 返回 `text/event-stream`，主要事件包括：

- `run.started`：一次 run 已创建，返回 `run_id` 和 `session_id`。
- `output.delta`：模型输出增量。
- `action.started`：工具调用开始。
- `action.completed`：工具调用结束，包含结果、错误和耗时。
- `action.required`：需要人工处理，包含 `pending_action`。
- `run.completed`：当前执行段结束，状态可能是 `completed`、`awaiting_action` 或 `failed`。
- `run.failed`：运行异常。

## 数据库与持久化

本项目有两类状态：

- 售后业务数据：客户、订单、物流、工单、退款、政策、审计日志，默认写入 `after_sales_mvp.db`。
- Agent 运行态：LangGraph checkpoint 和 session transcript，默认在内存中；生产或需要恢复执行时建议配置 PostgreSQL。

默认开发模式足够本地试跑：

```env
BUSINESS_DATABASE_URL=sqlite+pysqlite:///./after_sales_mvp.db
AGENT_RUNTIME_DATABASE_URL=
AUTO_CREATE_SCHEMA=true
```

如果要使用 PostgreSQL，可以先启动依赖：

```bash
docker compose up -d postgres
```

然后设置：

```env
AGENT_RUNTIME_DATABASE_URL=postgresql://agent:agent@127.0.0.1:5432/agent_platform
```

## MCP 工具接入

项目内部统一使用 `ToolSpec` 表达工具。售后本地工具和 MCP 外部工具都会被转换成同一种契约，再交给 LangChain runtime。

`MCP_SERVERS` 示例：

```env
MCP_SERVERS={"weather":{"transport":"http","url":"http://localhost:8000/mcp"},"math":{"transport":"stdio","command":"python","args":["./examples/math_server.py"]}}
```

加载成功后，MCP 工具会被追加到当前 Agent 的工具列表中，并带有 `mcp_<server>_<tool>` 风格的命名空间前缀。加载失败时应用仍会启动，`/health` 会返回 `degraded` 并展示错误详情。

## 测试与质量

测试覆盖了配置、模型工厂、MCP registry、事件映射、结果映射、LangChain runtime、FastAPI 集成接口和文档示例一致性。

推荐提交前执行：

```bash
uv run pytest -q
uv run ruff check src tests scripts
uv run mypy src tests
```

文档测试会检查 README、架构文档和 `.env.example` 是否包含公共路由与关键环境变量，所以更新接口或配置时也要同步更新文档。

## 推荐阅读顺序

1. [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
2. [src/app_api/main.py](src/app_api/main.py)
3. [src/app_api/composition/bootstrap.py](src/app_api/composition/bootstrap.py)
4. [src/after_sales/application/services/after_sales_service.py](src/after_sales/application/services/after_sales_service.py)
5. [src/app_api/composition/after_sales_agent_factory.py](src/app_api/composition/after_sales_agent_factory.py)
6. [src/agent_runtime/langchain/runtime.py](src/agent_runtime/langchain/runtime.py)
7. [src/agent_runtime/langchain/approval_middleware.py](src/agent_runtime/langchain/approval_middleware.py)
8. [src/app_api/projectors/after_sales_run_projector.py](src/app_api/projectors/after_sales_run_projector.py)
9. [frontend/src/App.tsx](frontend/src/App.tsx)

## 设计原则

- 业务能力沉淀在 `after_sales`，Agent 只是智能入口，不替代业务层。
- `ToolSpec` 是业务工具、MCP 工具和 LangChain 工具之间的稳定边界。
- `session_id` 表示多轮会话上下文，`run_id` 表示一次可恢复的 Agent 执行。
- 高风险动作通过 LangGraph interrupt 暂停，再通过审批 API resume。
- 业务数据库事务由 Unit of Work 管理，repository 不直接提交事务。
- runtime 不知道订单、退款、工单这些业务语义，只负责执行工具、处理 checkpoint 和映射事件。
- 应用层负责把运行事件投影成工具日志、审批记录和审计日志。

## 官方参考

- LangChain Agents: <https://docs.langchain.com/oss/python/langchain/agents>
- LangGraph Persistence: <https://docs.langchain.com/oss/python/langgraph/persistence>
- FastAPI: <https://fastapi.tiangolo.com/>
- SQLAlchemy ORM: <https://docs.sqlalchemy.org/en/20/orm/>
- SQLAlchemy asyncio: <https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html>
