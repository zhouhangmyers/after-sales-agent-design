# After-Sales Agent Platform

教学优先的 Agent 后端样板工程。主线实现使用 `FastAPI + SQLAlchemy + LangChain v1 create_agent + LangGraph checkpointer`，围绕一个售后客服场景展开：查订单、查物流、建工单、提交退款申请、人工审批恢复执行。

## 当前主线

- 保留稳定的 HTTP API 和售后领域模型。
- 主 runtime 改为官方当前推荐的 `create_agent` + middleware + durable checkpointer。
- `session_id` 和 `run_id` 明确分离。
- 高风险退款通过审批中断恢复，支持同一 session 下多个待审批 run。
- 通过代码型 Agent registry 暴露当前 agent/tool catalog，并可选接入 MCP server 工具。
- 售后业务写入通过 Unit of Work 控制事务边界，repository 不直接提交事务。
- 根依赖只保留主线运行所需包；不在主工程里维护多 Agent 框架示例。

## 目录

```text
src/
  app_api/
    main.py
    composition/
    projectors/
    routers/
    schemas/
    use_cases/
  after_sales/
    application/ports.py
    application/services/
    domain/
    infrastructure/
  agent_core/
    contracts/
    support/
  agent_runtime/
    langchain/
  agent_integrations/
    llm/
    mcp/
docs/
  ARCHITECTURE.md
```

## 为什么这样拆

- `app_api` 只做 HTTP schema、路由、composition root、应用用例和投影适配。
- `after_sales` 只关心订单、物流、退款、审批规则和数据库，不依赖 Agent/API 层。
- `after_sales` 的写入用例通过 Unit of Work 显式 `commit`，异常路径自动 rollback。
- HTTP 路由到 business repository 是全链路 async，业务数据库使用 SQLAlchemy `AsyncSession`。
- `agent_core` 只放框架无关契约：`AgentDefinition`、`ToolSpec`、`RunEvent`、`RunState`。
- `agent_runtime` 只放执行实现；当前主实现是 `agent_runtime/langchain`。
- `agent_integrations` 收拢外部 SDK / 协议接入，包括 LLM factory 和 MCP tool provider。
- 售后业务、本地 tool catalog 和可选 MCP tools 在 `app_api` composition 层相遇。
- 运行事件到 tool log、approval、audit log 的投影集中在 `app_api.projectors.after_sales_run_projector`。
- `RunEvent` 只作为 API/SSE 输出模型；`RunState` 只作为 LangGraph checkpoint 派生查询视图。
- 当前不自建 observability 抽象；生产观测优先接 FastAPI middleware、structured logging、LangSmith 或 OpenTelemetry。LangSmith 适合 trace、monitoring 和 eval，不替代业务数据库事务边界。

这让学习顺序更自然：

1. 先看 API。
2. 再看纯售后业务服务和 Agent tool adapter。
3. 最后看 `LangChainAgentRuntime` 怎么把 tool calling、审批中断和持久化串起来。

## 快速开始

```bash
cd /home/zhouhangmyers/python/agent-orchestrator-platform
uv sync --extra dev
make seed
make start
```

打开：

- `http://127.0.0.1:8000/docs`
- `http://127.0.0.1:8000/health`

## 关键环境变量

```env
APP_ENV=dev
BUSINESS_DATABASE_URL=sqlite+pysqlite:///./after_sales_mvp.db
AGENT_RUNTIME_DATABASE_URL=
AUTO_CREATE_SCHEMA=true

LLM_PROVIDER=deepseek
LLM_MODEL=deepseek-chat
DEEPSEEK_API_KEY=replace-me
OPENAI_API_KEY=

LLM_TIMEOUT_SECONDS=30
LLM_MAX_RETRIES=2
MAX_STEPS=4
APPROVAL_TIMEOUT_SECONDS=900
API_KEY=
MCP_SERVERS={}
```

- `LLM_PROVIDER` 目前支持 `deepseek` 和 `openai`。
- `AGENT_RUNTIME_DATABASE_URL` 留空时使用内存 checkpointer；配置 PostgreSQL 后使用 async saver。
- 本地 SQLite 会在业务库内部转换为 `sqlite+aiosqlite` async driver；Alembic 迁移仍使用同步 URL，这是 Alembic 的常见用法。
- `MCP_SERVERS` 是 JSON 对象，支持 `http`/`streamable_http` 和 `stdio` transport。加载失败时应用继续启动，`/health` 返回 degraded。

## 公共 API

### Agent

- `GET /api/agents`
- `GET /api/agents/{capability_id}/tools`
- `POST /api/after-sales/runs`
- `POST /api/after-sales/runs/stream`
- `POST /api/after-sales/actions`
- `GET /api/after-sales/runs/{run_id}`

### Business

- `GET /api/after-sales/orders/{order_id}`
- `GET /api/after-sales/orders/{order_id}/shipment`
- `GET /api/after-sales/customers/{customer_id}`
- `GET /api/after-sales/policies/search?q=...`
- `POST /api/after-sales/tickets`
- `GET /api/after-sales/tickets/{ticket_id}`
- `POST /api/after-sales/refund-requests`
- `GET /api/after-sales/audit-logs?run_id=...`

## 质量门槛

```bash
uv run pytest -q
uv run ruff check src tests scripts
uv run mypy src tests
```

当前仓库要求三项全部通过。

## 学习顺序

先读：

1. [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
2. [src/app_api/composition/bootstrap.py](src/app_api/composition/bootstrap.py)
3. [src/after_sales/application/services/after_sales_service.py](src/after_sales/application/services/after_sales_service.py)
4. [src/app_api/composition/after_sales_agent_factory.py](src/app_api/composition/after_sales_agent_factory.py)
5. [src/agent_runtime/langchain/runtime.py](src/agent_runtime/langchain/runtime.py)
6. [src/agent_runtime/langchain/checkpoint/langgraph_postgres.py](src/agent_runtime/langchain/checkpoint/langgraph_postgres.py)

## 官方参考

- LangChain Agents: <https://docs.langchain.com/oss/python/langchain/agents>
- LangGraph Persistence: <https://docs.langchain.com/oss/python/langgraph/persistence>
- FastAPI: <https://fastapi.tiangolo.com/>
- SQLAlchemy ORM: <https://docs.sqlalchemy.org/en/20/orm/>
- SQLAlchemy asyncio: <https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html>
