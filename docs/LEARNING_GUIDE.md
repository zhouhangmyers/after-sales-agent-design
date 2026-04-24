# 从 0 到 1 开发售后 Agent 后端

这份指南不是代码评审，也不是简单解释现有目录。它把当前项目反向拆成一门实战课程，目标是让有基础代码经验、但没有系统 Python 后端和 Agent 开发经验的学习者，从空目录开始，一步一步开发出一个接近当前仓库主线的售后客服 Agent 后端。

课程主线采用当前项目风格：

```text
FastAPI
  -> app_api 负责 HTTP API 和依赖装配
  -> business_service.after_sales 负责售后业务
  -> agent_service 负责 Agent contract、LLM、runtime、state store、MCP adapter
  -> SQLAlchemy + Alembic 负责业务数据
  -> LangChain v1 create_agent + LangGraph checkpoint 负责 Agent 执行、暂停和恢复
```

学习时要守住一个核心边界：

```text
business_service 不依赖 agent_service
agent_service 不依赖 business_service
两者只在 app_api 的 adapter/composition 层相遇
```

这样做的意义是：售后业务能力可以独立作为普通后端 API 使用，Agent 只是这些业务能力的一种智能入口。

---

## 项目反向拆解

### 1. 这个项目最终要做成什么

项目一句话介绍：

> 这是一个教学优先的售后客服 Agent 后端，用 `FastAPI + SQLAlchemy + LangChain + LangGraph` 实现查订单、查物流、建工单、退款申请和人工审批恢复执行。

用户会如何使用它：

- 运营或客服可以通过前端工作台输入自然语言，例如“帮我查一下订单 ORD123 的状态”。
- 后端也可以直接被 curl、Postman 或其他系统调用。
- 普通业务查询可以直接走 REST API。
- 自然语言任务走 Agent API，由 Agent 判断要不要调用工具。
- 高风险退款会先返回 `awaiting_action`，由人工审批后继续执行。

后端提供的能力：

- 健康检查：`GET /health`
- Agent 目录：`GET /api/agents`
- 工具目录：`GET /api/agents/{capability_id}/tools`
- 同步 Agent 运行：`POST /api/after-sales/runs`
- 流式 Agent 运行：`POST /api/after-sales/runs/stream`
- 审批动作：`POST /api/after-sales/actions`
- 运行状态查询：`GET /api/after-sales/runs/{run_id}`
- 售后资源 API：订单、物流、客户、政策、工单、退款、审计日志。

Agent 扮演的角色：

- 理解用户自然语言。
- 根据系统提示词和工具描述选择一个工具。
- 把用户输入整理成工具参数。
- 读取工具返回结果，组织成简洁的中文回复。
- 遇到需要审批的工具时暂停执行，等待人工动作。

Tool 扮演的角色：

- Tool 不负责“思考”，只负责执行确定的业务动作。
- 本项目中的本地工具包括 `get_order_detail`、`get_shipment_detail`、`create_ticket`、`get_ticket_detail`、`submit_refund_request`、`search_after_sales_policy`。
- 可选 MCP 工具会被适配成同一种 `ToolSpec`，并命名成 `mcp_{server}_{tool}`。

项目完成后的最终效果：

- 学习者可以启动后端，访问 `http://127.0.0.1:8000/docs`。
- 可以调用 `/api/after-sales/orders/ORD123` 获取订单。
- 可以调用 `/api/after-sales/runs` 让 Agent 自动查单。
- 可以调用 `/api/after-sales/runs/stream` 看到 SSE 事件。
- 可以发起高风险退款，看到 `action.required`。
- 可以调用 `/api/after-sales/actions` 审批后恢复执行。

### 2. 从 0 开发应该分成哪些阶段

推荐拆成 12 个阶段：

1. 开发前准备：安装 Python 3.12、uv、Git、Docker、curl/Postman、IDE。
2. 创建项目骨架：使用 `src` layout，建好后端、业务、Agent、测试、迁移目录。
3. 搭建 FastAPI 服务：实现 `create_app()`、lifespan、CORS、`/health`。
4. 设计配置系统：用 `pydantic-settings` 读取 `.env`，集中管理 DB、LLM、MCP、API key。
5. 售后业务领域建模：定义订单、客户、物流、工单、退款、审批和审计日志 schema。
6. Repository + Unit of Work：用协议隔离业务服务和 SQLAlchemy，用 UoW 管事务。
7. 普通业务 API：先把售后业务作为传统 REST API 跑通。
8. LLM Client 封装：支持 DeepSeek/OpenAI，并保留 mock 模型用于测试。
9. Agent Contract 和 ToolSpec：定义 runtime 和业务工具之间的窄接口。
10. 售后 Agent Definition：把业务服务包装成工具，并设计 prompt。
11. LangChain/LangGraph Runtime：实现工具调用、审批暂停、恢复、SSE、session transcript。
12. API 集成、测试、部署与复盘：补齐路由、pytest、ruff、mypy、seed、Alembic、compose、面试表达。

### 3. 最小可运行版本 MVP 是什么

MVP 只做四件事：

- 启动一个 FastAPI 服务。
- 暴露 `GET /health`。
- 暴露 `POST /api/after-sales/runs`。
- 先用 mock LLM 或 deterministic chat model 调用一个本地工具 `get_order_detail`。

MVP 推荐只用 SQLite 和一条订单假数据。不要一开始就实现完整审批、SSE、MCP、PostgreSQL checkpoint 和前端。

为什么先做 MVP：

- 新手最容易卡在“装了很多库，但不知道请求怎么跑起来”。
- MVP 可以最快跑通 `HTTP -> schema -> service -> tool -> agent response`。
- 先得到一个正反馈，再逐步引入数据库、审批和 LangGraph checkpoint，学习成本更可控。

---

## 第 0 章：开发前准备

### 本章目标

准备好从 0 开发项目所需的工具和基础概念。学完后，学习者能创建虚拟环境、安装依赖、运行 Python 命令、理解 `.env`、理解后端服务和 Agent 的关系。

### 为什么要做这一步

Python 后端和 Agent 项目会同时涉及依赖管理、环境变量、HTTP 服务、数据库、LLM API key 和本地开发工具。如果前置环境不稳定，后面每一章都会被安装问题打断。

### 本章要创建或修改哪些文件

本章暂时不写业务代码，只准备这些文件：

```text
agent-orchestrator-platform/
  .env.example
  README.md
  pyproject.toml
```

### 推荐目录结构

开发前先知道最终项目会长成这样：

```text
agent-orchestrator-platform/
  src/
    app_api/
    agent_service/
    business_service/
  tests/
  migrations/
  scripts/
  docs/
  frontend/
  .env.example
  pyproject.toml
  Makefile
  compose.yaml
```

### 关键概念讲解

后端服务：运行在服务器上的程序，接收请求，处理业务，返回结果。

API：系统对外暴露的调用入口。比如 `GET /health` 是健康检查 API。

HTTP request / response：客户端发送 request，服务端返回 response。request 里有路径、方法、header、body；response 里有状态码和 JSON。

JSON：前后端常用的数据格式，例如 `{"message": "hello"}`。

环境变量：不写死在代码里的配置，例如 API key、数据库地址。

虚拟环境：给一个项目隔离 Python 依赖，避免多个项目依赖互相污染。

依赖管理：记录项目需要哪些第三方包。本项目使用 `uv` 和 `pyproject.toml`。

LLM API：大模型服务接口，例如 DeepSeek 或 OpenAI 的 chat model。

Agent：能根据目标选择工具并组织执行流程的智能体。

Tool：Agent 可以调用的确定性函数，本项目中就是售后业务能力的包装。

### 开发步骤

1. 安装 Python 3.12。
2. 安装 `uv`。
3. 安装 Git。
4. 安装 Docker Desktop 或 Docker Engine。
5. 准备 VS Code 或 Cursor。
6. 准备 curl 或 Postman。
7. 确认命令可用。

### 示例代码

```bash
python --version
uv --version
git --version
docker --version
curl --version
```

创建 `.env.example`：

```env
APP_ENV=dev
CORS_ALLOWED_ORIGINS=http://127.0.0.1:5173,http://localhost:5173
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

### 如何运行或验证

```bash
mkdir agent-orchestrator-platform
cd agent-orchestrator-platform
python -c "print('python ok')"
```

如果能输出 `python ok`，说明 Python 可运行。

### 常见错误

- Python 版本低于 3.12：后续类型语法可能报错。
- 没有激活虚拟环境：命令使用了系统 Python。
- `.env` 里写了真实 key 但提交到 Git：这是安全问题，真实项目必须避免。
- Docker 没启动：后面启动 PostgreSQL 会失败。

### 面试时怎么讲

可以这样说：

> 我会先把运行环境标准化，项目使用 Python 3.12 和 uv 管理依赖，敏感配置通过 `.env` 注入。这样代码、配置和运行环境分离，方便本地、测试和生产环境使用同一套代码。

---

## 第 1 章：从空目录创建项目骨架

### 本章目标

从空文件夹创建项目基本结构，明确 API 层、业务层、Agent 层、测试和部署文件的位置。

### 为什么要做这一步

新手常见问题是所有代码都堆在一个 `main.py`。这个项目需要同时处理 HTTP、业务、Agent runtime、数据库和测试，所以必须从一开始把边界摆好。

### 本章要创建或修改哪些文件

```text
pyproject.toml
README.md
.env.example
Makefile
src/app_api/__init__.py
src/agent_service/__init__.py
src/business_service/__init__.py
tests/__init__.py
```

### 推荐目录结构

```text
agent-orchestrator-platform/
  src/
    app_api/
      __init__.py
      main.py
      routers/
      schemas/
      services/
    agent_service/
      __init__.py
      contracts/
      infrastructure/
      llm/
    business_service/
      __init__.py
      after_sales/
        domain/
        application/
        infrastructure/
  tests/
    __init__.py
  scripts/
  migrations/
  docs/
  .env.example
  pyproject.toml
  Makefile
```

### 关键概念讲解

`src` layout：把项目包放在 `src/` 下，避免测试时误用当前目录里的未安装模块。

`app_api`：FastAPI 入口、路由、HTTP schema、依赖注入和 composition root。

`business_service`：业务核心，表达订单、物流、工单、退款、审批规则。

`agent_service`：Agent 通用能力，表达 ToolSpec、AgentDefinition、runtime、LLM 和 state store。

### 开发步骤

1. 创建目录。
2. 创建空的 `__init__.py`。
3. 写 `pyproject.toml`。
4. 写基础 `Makefile`。
5. 写 README 的项目目标。

### 示例代码

`pyproject.toml`：

```toml
[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[project]
name = "agent-orchestrator-platform"
version = "0.1.0"
description = "Teaching-first agent backend built with FastAPI, LangChain, and LangGraph."
readme = "README.md"
requires-python = ">=3.12"
dependencies = [
    "pydantic>=2,<3",
    "pydantic-settings>=2.0",
    "fastapi>=0.115,<1",
    "uvicorn>=0.30,<1",
]

[project.optional-dependencies]
dev = [
    "pytest>=8,<9",
    "pytest-asyncio>=0.24,<1",
    "httpx>=0.27,<1",
    "ruff>=0.9,<1",
    "mypy>=1.11,<2",
]

[tool.setuptools]
package-dir = {"" = "src"}

[tool.setuptools.packages.find]
where = ["src"]

[tool.pytest.ini_options]
pythonpath = ["src"]
testpaths = ["tests"]
```

`Makefile`：

```makefile
PYTHON ?= .venv/bin/python
HOST ?= 127.0.0.1
PORT ?= 8000

.PHONY: start test

start:
	$(PYTHON) -m uvicorn app_api.main:create_app --factory --app-dir src --reload --host $(HOST) --port $(PORT)

test:
	$(PYTHON) -m pytest tests -q
```

### 如何运行或验证

```bash
uv sync --extra dev
find src -maxdepth 3 -type d
uv run python -c "import app_api, agent_service, business_service; print('imports ok')"
```

### 常见错误

- 忘记配置 `pythonpath = ["src"]`，测试里 import 失败。
- 目录建好了但没有 `__init__.py`，包导入不稳定。
- 把业务代码直接放进 `app_api`，后面 Agent 适配会变混乱。

### 面试时怎么讲

可以这样说：

> 我使用 `src` layout，并把系统分为 API 层、业务层和 Agent 层。API 层负责装配，业务层不依赖 Agent 框架，Agent 层也不依赖具体售后业务，这样后续替换 LangChain 或新增业务场景时影响范围更小。

---

## 第 2 章：搭建 FastAPI 服务

### 本章目标

创建一个可启动的 FastAPI 应用，实现 `/health`，为后续业务 API 和 Agent API 提供入口。

### 为什么要做这一步

所有后端功能最终都要通过 HTTP 暴露。先把 API 服务跑起来，可以尽早验证项目启动、路由注册、Swagger 文档和基本健康检查。

### 本章要创建或修改哪些文件

```text
src/app_api/main.py
src/app_api/routers/__init__.py
src/app_api/routers/health.py
```

### 推荐目录结构

```text
src/app_api/
  __init__.py
  main.py
  routers/
    __init__.py
    health.py
```

### 关键概念讲解

FastAPI app：后端应用对象，负责注册路由和中间件。

router：把一组相关接口放在一起，例如健康检查、售后资源、Agent runs。

factory：`create_app()` 返回 app，测试时可以传入不同设置或 fake dependency。

lifespan：应用启动和关闭时执行资源初始化和清理。

### 开发步骤

1. 创建 `health.py`。
2. 创建 `create_app()`。
3. 注册 health router。
4. 用 uvicorn 启动。
5. 打开 `/docs` 和 `/health` 验证。

### 示例代码

`src/app_api/routers/health.py`：

```python
from __future__ import annotations

from fastapi import APIRouter

# router 是一组 API 的集合，tags 会显示在 Swagger UI 中。
router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> dict[str, str]:
    # MVP 阶段先只返回 ok，后续再接数据库、LLM、MCP 状态。
    return {"status": "ok"}
```

`src/app_api/main.py`：

```python
from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app_api.routers.health import router as health_router


def create_app() -> FastAPI:
    # 使用 factory 方便测试时创建隔离 app。
    app = FastAPI(title="After-Sales Agent API", version="1.0.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(health_router)
    return app
```

### 如何运行或验证

```bash
uv run uvicorn app_api.main:create_app --factory --app-dir src --reload
curl http://127.0.0.1:8000/health
```

预期：

```json
{"status":"ok"}
```

### 常见错误

- `Error loading ASGI app`：通常是没有加 `--app-dir src`。
- `/health` 返回 404：忘记 `app.include_router(health_router)`。
- 浏览器跨域失败：前端请求时需要 CORS 中间件。

### 面试时怎么讲

可以这样说：

> 我用 FastAPI factory 创建应用，并把路由拆到独立 router。这样应用启动、测试注入和路由组织都更清晰，后续可以在 lifespan 中初始化数据库、LLM client 和 Agent runtime。

---

## 第 3 章：设计配置系统

### 本章目标

使用 `pydantic-settings` 实现集中配置读取，支持 `.env`、环境变量、生产校验、CORS、API key、数据库地址、LLM provider 和 MCP server 配置。

### 为什么要做这一步

后端项目不能把 API key、数据库地址和运行模式写死在代码里。配置系统让本地、测试和生产可以使用同一套代码，只通过环境变量切换行为。

### 本章要创建或修改哪些文件

```text
src/app_api/settings.py
src/app_api/main.py
.env.example
tests/test_settings.py
```

### 推荐目录结构

```text
src/app_api/
  settings.py
  main.py
tests/
  test_settings.py
.env.example
```

### 关键概念讲解

`BaseSettings`：Pydantic 提供的配置基类，可以从环境变量和 `.env` 读取字段。

`SecretStr`：用于保存 API key，打印时不会泄露真实值。

生产校验：生产环境必须要求 `API_KEY`、明确 CORS、持久化 runtime store 和真实 LLM key。

MCP 配置：用 JSON 对象配置外部工具 server。

### 开发步骤

1. 定义 `MCPServerConfig`。
2. 定义 `AppSettings`。
3. 实现 `is_test`、`is_production`、`parsed_cors_allowed_origins`。
4. 加 `model_validator` 校验生产环境和 MCP server。
5. 在 `main.py` 中接收 settings。
6. 写测试覆盖默认值、生产校验和 MCP JSON。

### 示例代码

`src/app_api/settings.py`：

```python
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class MCPServerConfig(BaseModel):
    # extra="forbid" 可以防止配置写错字段却静默通过。
    transport: Literal["http", "streamable_http", "stdio"]
    url: str | None = None
    command: str | None = None
    args: list[str] = Field(default_factory=list)
    headers: dict[str, str] = Field(default_factory=dict)

    model_config = ConfigDict(extra="forbid")


class AppSettings(BaseSettings):
    app_env: str = "dev"
    cors_allowed_origins: str = ""
    api_key: SecretStr | None = None

    business_database_url: str = "sqlite+pysqlite:///./after_sales_mvp.db"
    agent_runtime_database_url: str | None = None
    auto_create_schema: bool = False

    llm_provider: str = "deepseek"
    llm_model: str = "deepseek-chat"
    llm_timeout_seconds: float = Field(default=30.0, ge=0.1, le=300.0)
    llm_max_retries: int = Field(default=2, ge=0, le=10)
    deepseek_api_key: SecretStr | None = None
    openai_api_key: SecretStr | None = None

    max_steps: int = Field(default=4, ge=1, le=50)
    approval_timeout_seconds: int = Field(default=900, ge=1)
    mcp_servers: dict[str, MCPServerConfig] = Field(default_factory=dict)

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    @property
    def is_test(self) -> bool:
        # 测试环境允许缺少真实 LLM 和 runtime DB。
        return self.app_env.lower() == "test"

    @property
    def is_production(self) -> bool:
        return self.app_env.lower() in {"prod", "production"}

    @property
    def parsed_cors_allowed_origins(self) -> list[str]:
        origins = [item.strip() for item in self.cors_allowed_origins.split(",") if item.strip()]
        return origins or (["*"] if not self.is_production else [])

    @model_validator(mode="after")
    def validate_runtime_requirements(self) -> "AppSettings":
        # MCP http server 必须有 url，stdio server 必须有 command。
        for name, config in self.mcp_servers.items():
            if config.transport in {"http", "streamable_http"} and not config.url:
                raise ValueError(f"MCP server `{name}` requires `url`")
            if config.transport == "stdio" and not config.command:
                raise ValueError(f"MCP server `{name}` requires `command`")

        if not self.is_production:
            return self

        if self.api_key is None:
            raise ValueError("API_KEY is required when APP_ENV=production")
        if not self.parsed_cors_allowed_origins:
            raise ValueError("CORS_ALLOWED_ORIGINS is required when APP_ENV=production")
        if self.agent_runtime_database_url is None:
            raise ValueError("AGENT_RUNTIME_DATABASE_URL is required when APP_ENV=production")
        return self
```

`src/app_api/main.py`：

```python
from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app_api.routers.health import router as health_router
from app_api.settings import AppSettings


def create_app(settings: AppSettings | None = None) -> FastAPI:
    # 允许测试传入 AppSettings(app_env="test")。
    resolved_settings = settings or AppSettings()
    app = FastAPI(title="After-Sales Agent API", version="1.0.0")
    app.state.settings = resolved_settings
    app.add_middleware(
        CORSMiddleware,
        allow_origins=resolved_settings.parsed_cors_allowed_origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(health_router)
    return app
```

### 如何运行或验证

```bash
cp .env.example .env
uv run python -c "from app_api.settings import AppSettings; print(AppSettings().model_dump())"
uv run pytest tests/test_settings.py -q
```

### 常见错误

- `.env` 里写 `llm_provider=deepseek` 但配置字段是大写也没关系，Pydantic 会按字段名匹配环境变量。
- `MCP_SERVERS` 不是合法 JSON，会导致启动时解析失败。
- 生产环境缺少 `API_KEY` 应该主动报错，不要等线上出问题。

### 面试时怎么讲

可以这样说：

> 我用 `pydantic-settings` 统一管理配置，并用 validator 做生产环境约束。API key 用 `SecretStr`，数据库和 LLM provider 通过环境变量注入，既方便本地开发，也能避免生产配置写死在代码里。

---

## 第 4 章：定义请求和响应模型

### 本章目标

定义 HTTP API 和 Agent runtime 会用到的 Pydantic schema，包括创建 run、run 响应、审批动作、Agent 摘要、工具摘要和业务实体。

### 为什么要做这一步

API 的输入输出不能靠字典随便传。Schema 是后端和调用方之间的契约，也是 FastAPI 自动生成 OpenAPI 文档和参数校验的基础。

### 本章要创建或修改哪些文件

```text
src/app_api/schemas/runs.py
src/app_api/schemas/actions.py
src/app_api/schemas/agents.py
src/agent_service/contracts/models.py
src/business_service/after_sales/domain/entities.py
```

### 推荐目录结构

```text
src/app_api/schemas/
  runs.py
  actions.py
  agents.py
src/agent_service/contracts/
  models.py
src/business_service/after_sales/domain/
  entities.py
```

### 关键概念讲解

HTTP schema：只关心请求和响应长什么样。

Domain schema：表达业务实体，例如 `OrderRead`、`TicketCreate`。

Runtime schema：表达 Agent 运行状态，例如 `AgentRunResult`、`AgentPendingAction`。

`Literal`：限制字符串只能取固定值，例如审批 decision 只能是 `approved` 或 `rejected`。

### 开发步骤

1. 先定义 Agent runtime 模型。
2. 定义 run 请求和响应。
3. 定义审批动作请求。
4. 定义 Agent/tool catalog 响应。
5. 定义售后业务实体。

### 示例代码

`src/agent_service/contracts/models.py`：

```python
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

type RunStatus = Literal["completed", "awaiting_action", "failed"]
type RiskLevel = Literal["low", "medium", "high"]


class ActorContext(BaseModel):
    # actor_id 表示当前操作人，可以是客服、主管或系统。
    actor_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class AgentPendingAction(BaseModel):
    # pending action 是 Agent 暂停后等待人工处理的动作。
    action_id: str
    action_name: str
    action_payload: dict[str, Any] = Field(default_factory=dict)
    reason: str
    risk_level: RiskLevel = "low"
    display_payload: dict[str, Any] = Field(default_factory=dict)


class AgentError(BaseModel):
    code: str
    message: str


class AgentRunResult(BaseModel):
    run_id: str
    session_id: str
    capability_id: str
    status: RunStatus
    output: str | None = None
    pending_action: AgentPendingAction | None = None
    error: AgentError | None = None
```

`src/app_api/schemas/runs.py`：

```python
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from agent_service.contracts.models import AgentError, AgentPendingAction, RunStatus


class CreateRunRequest(BaseModel):
    # message 是用户对 Agent 说的话。
    message: str = Field(min_length=1, max_length=4000)
    session_id: str | None = None
    actor_id: str | None = None
    actor_metadata: dict[str, Any] = Field(default_factory=dict)


class RunResponse(BaseModel):
    run_id: str
    session_id: str
    status: RunStatus
    output: str | None = None
    pending_action: AgentPendingAction | None = None
    error: AgentError | None = None
```

`src/app_api/schemas/actions.py`：

```python
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class ActionRequest(BaseModel):
    # run_id 定位哪一次 Agent 执行，action_id 定位哪一个待审批动作。
    run_id: str = Field(min_length=1)
    action_id: str = Field(min_length=1)
    decision: Literal["approved", "rejected"]
    actor_id: str | None = None
    actor_metadata: dict[str, Any] = Field(default_factory=dict)
```

### 如何运行或验证

```bash
uv run python - <<'PY'
from app_api.schemas.runs import CreateRunRequest

payload = CreateRunRequest(message="查一下订单 ORD123")
print(payload.model_dump())
PY
```

再写一个最小测试：

```python
from __future__ import annotations

import pytest

from app_api.schemas.runs import CreateRunRequest


def test_create_run_request_rejects_empty_message() -> None:
    # Pydantic 会根据 Field(min_length=1) 自动校验。
    with pytest.raises(Exception):
        CreateRunRequest(message="")
```

### 常见错误

- 把 `dict` 到处传，导致字段名写错时不能及时发现。
- `Decimal` 直接 JSON 序列化报错，Pydantic 的 `model_dump(mode="json")` 可以处理。
- API schema 和 domain schema 混在一起，后期很难维护。

### 面试时怎么讲

可以这样说：

> 我把 HTTP schema、业务 domain schema 和 Agent runtime schema 分开。这样接口契约清晰，业务实体不会被前端字段污染，Agent 运行状态也能独立演进。

---

## 第 5 章：售后业务领域建模

### 本章目标

用 Pydantic 定义售后业务实体，用 SQLAlchemy 定义数据库表结构，为订单、物流、工单、退款、审批和审计日志打基础。

### 为什么要做这一步

Agent 最终要调用真实业务能力。如果没有清晰的业务模型，Agent 只能聊天，不能完成查单、退款、审批这种实际动作。

### 本章要创建或修改哪些文件

```text
src/business_service/after_sales/domain/entities.py
src/business_service/after_sales/infrastructure/persistence/sqlalchemy/session.py
src/business_service/after_sales/infrastructure/persistence/sqlalchemy/models.py
```

### 推荐目录结构

```text
src/business_service/after_sales/
  domain/
    __init__.py
    entities.py
  infrastructure/
    persistence/
      sqlalchemy/
        __init__.py
        session.py
        models.py
```

### 关键概念讲解

领域模型：业务层用来表达业务对象的数据结构。

ORM model：数据库表对应的 Python 类。

Pydantic `from_attributes=True`：允许从 SQLAlchemy 对象转换成 Pydantic read model。

业务数据库：保存订单、物流、工单、退款、审批、审计日志。它和 LangGraph checkpoint 不是同一类状态。

### 开发步骤

1. 定义 `DomainModel` 基类。
2. 定义 `OrderRead`、`ShipmentRead`、`TicketCreate`、`RefundRequestCreate`。
3. 创建 SQLAlchemy `Base` 和 `BusinessDatabase`。
4. 定义 `Customer`、`Order`、`Shipment`、`Ticket`、`RefundRequest`、`PolicyArticle`。
5. 定义审批和审计相关表。

### 示例代码

`entities.py`：

```python
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class DomainModel(BaseModel):
    # from_attributes=True 允许从 ORM 对象直接 model_validate。
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class OrderRead(DomainModel):
    order_id: str
    customer_id: str
    status: str
    total_amount: Decimal
    currency: str
    item_summary: str
    created_at: datetime


class ShipmentRead(DomainModel):
    shipment_id: str
    order_id: str
    carrier: str
    tracking_no: str
    status: str
    latest_location: str | None = None
    events_json: list[dict[str, Any]] = Field(default_factory=list)
    updated_at: datetime


class TicketCreate(BaseModel):
    order_id: str
    issue_type: Literal["damaged", "return", "exchange", "other"]
    summary: str
    priority: Literal["low", "normal", "high"] = "normal"


class RefundRequestCreate(BaseModel):
    order_id: str
    amount: Decimal
    reason: str
    requires_approval: bool = False
```

`session.py`：

```python
from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    # SQLAlchemy 2.0 的声明式模型基类。
    pass


def _async_database_url(database_url: str) -> str:
    # 本地配置给 Alembic 用同步 sqlite，在线请求用 aiosqlite。
    if database_url.startswith("sqlite+pysqlite://"):
        return database_url.replace("sqlite+pysqlite://", "sqlite+aiosqlite://", 1)
    return database_url


class BusinessDatabase:
    def __init__(self, database_url: str) -> None:
        self.database_url = database_url
        self.sync_engine = create_engine(database_url, future=True)
        self.async_engine = create_async_engine(_async_database_url(database_url), future=True)
        self._session_factory = async_sessionmaker(
            bind=self.async_engine,
            class_=AsyncSession,
            autoflush=False,
            expire_on_commit=False,
        )

    async def create_schema(self) -> None:
        # 教学 MVP 可先用 create_all，后面再升级到 Alembic。
        import business_service.after_sales.infrastructure.persistence.sqlalchemy.models  # noqa: F401

        async with self.async_engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

    @asynccontextmanager
    async def managed_session(self) -> AsyncGenerator[AsyncSession, None]:
        async with self._session_factory() as session:
            yield session

    async def dispose(self) -> None:
        await self.async_engine.dispose()
        self.sync_engine.dispose()
```

### 如何运行或验证

```bash
uv add sqlalchemy aiosqlite
uv run python - <<'PY'
import asyncio
from business_service.after_sales.infrastructure.persistence.sqlalchemy.session import BusinessDatabase

async def main() -> None:
    db = BusinessDatabase("sqlite+pysqlite:///./after_sales_mvp.db")
    await db.create_schema()
    await db.dispose()
    print("schema created")

asyncio.run(main())
PY
```

### 常见错误

- 用同步 SQLAlchemy session 放进 async route，会阻塞请求。
- 忘记 import `models.py`，导致 `Base.metadata.create_all()` 没有表。
- 金额用 `float` 存储，容易出现精度问题。业务金额推荐 `Decimal`。
- 业务数据库和 Agent checkpoint 混在一起，后期审批恢复会变难。

### 面试时怎么讲

可以这样说：

> 我把业务读写状态放在业务数据库，订单、物流、退款和审批记录都用 SQLAlchemy 建模。Pydantic read model 负责 API 输出，ORM model 负责持久化，两者通过 `model_validate` 转换。

---

## 第 6 章：Repository + Unit of Work

### 本章目标

实现 `AfterSalesRepository` 和 `AfterSalesUnitOfWork`，让业务服务不直接依赖 SQLAlchemy session，并把事务提交集中管理。

### 为什么要做这一步

业务服务应该表达“我要查订单、创建工单、提交退款”，而不是到处写 SQLAlchemy 查询和 `commit()`。Repository 负责数据访问，Unit of Work 负责事务边界。

### 本章要创建或修改哪些文件

```text
src/business_service/after_sales/application/ports.py
src/business_service/after_sales/application/services/after_sales_service.py
src/business_service/after_sales/infrastructure/persistence/sqlalchemy/repositories.py
src/business_service/after_sales/infrastructure/persistence/sqlalchemy/unit_of_work.py
```

### 推荐目录结构

```text
src/business_service/after_sales/
  application/
    ports.py
    services/
      after_sales_service.py
  infrastructure/
    persistence/
      sqlalchemy/
        repositories.py
        unit_of_work.py
```

### 关键概念讲解

Repository：封装数据库查询和写入。

Protocol：用结构化类型定义接口，不强制继承。

Unit of Work：一次业务用例中的事务边界，成功时 commit，异常或未提交时 rollback。

依赖倒置：业务服务依赖接口，不依赖 SQLAlchemy 实现。

### 开发步骤

1. 在 `ports.py` 定义 repository 协议。
2. 在 `ports.py` 定义 UoW 协议。
3. 实现 `SqlAlchemyAfterSalesRepository`。
4. 实现 `SqlAlchemyAfterSalesUnitOfWork`。
5. 实现 `AfterSalesService`。
6. 写 rollback 测试。

### 示例代码

`ports.py`：

```python
from __future__ import annotations

from typing import Protocol

from business_service.after_sales.domain.entities import OrderRead, TicketCreate, TicketRead


class AfterSalesRepository(Protocol):
    # Protocol 只描述能力，具体实现可以是 SQLAlchemy，也可以是测试 fake。
    async def get_order(self, order_id: str) -> OrderRead | None: ...

    async def create_ticket(self, payload: TicketCreate) -> TicketRead: ...


class AfterSalesUnitOfWork(Protocol):
    @property
    def repository(self) -> AfterSalesRepository: ...

    async def commit(self) -> None: ...

    async def rollback(self) -> None: ...
```

`unit_of_work.py`：

```python
from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from types import TracebackType

from sqlalchemy.ext.asyncio import AsyncSession

from business_service.after_sales.application.ports import AfterSalesRepository, AfterSalesUnitOfWork
from business_service.after_sales.infrastructure.persistence.sqlalchemy.repositories import SqlAlchemyAfterSalesRepository


class SqlAlchemyAfterSalesUnitOfWork:
    def __init__(
        self,
        session_factory: Callable[[], AbstractAsyncContextManager[AsyncSession]],
    ) -> None:
        self._session_factory = session_factory
        self._session_context: AbstractAsyncContextManager[AsyncSession] | None = None
        self._session: AsyncSession | None = None
        self._repository: AfterSalesRepository | None = None
        self._committed = False

    @property
    def repository(self) -> AfterSalesRepository:
        if self._repository is None:
            raise RuntimeError("unit of work is not active")
        return self._repository

    async def __aenter__(self) -> AfterSalesUnitOfWork:
        # 进入上下文时创建 session 和 repository。
        self._session_context = self._session_factory()
        self._session = await self._session_context.__aenter__()
        self._repository = SqlAlchemyAfterSalesRepository(self._session)
        self._committed = False
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool | None:
        # 未 commit 的写入默认 rollback，避免半成品落库。
        if self._session is not None and not self._committed:
            await self.rollback()
        if self._session_context is not None:
            return await self._session_context.__aexit__(exc_type, exc, traceback)
        return None

    async def commit(self) -> None:
        if self._session is None:
            raise RuntimeError("unit of work is not active")
        await self._session.commit()
        self._committed = True

    async def rollback(self) -> None:
        if self._session is None:
            raise RuntimeError("unit of work is not active")
        await self._session.rollback()
```

`after_sales_service.py`：

```python
from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractAsyncContextManager

from business_service.after_sales.application.ports import AfterSalesUnitOfWork
from business_service.after_sales.domain.entities import OrderRead, TicketCreate, TicketRead


class AfterSalesService:
    def __init__(
        self,
        *,
        unit_of_work_factory: Callable[[], AbstractAsyncContextManager[AfterSalesUnitOfWork]],
    ) -> None:
        # service 只保存 UoW 工厂，不直接持有数据库 session。
        self._unit_of_work_factory = unit_of_work_factory

    async def get_order_detail(self, order_id: str) -> OrderRead:
        async with self._unit_of_work_factory() as uow:
            order = await uow.repository.get_order(order_id)
        if order is None:
            raise ValueError(f"order not found: {order_id}")
        return order

    async def create_ticket(self, payload: TicketCreate) -> TicketRead:
        async with self._unit_of_work_factory() as uow:
            ticket = await uow.repository.create_ticket(payload)
            await uow.commit()
            return ticket
```

### 如何运行或验证

```bash
uv run pytest tests/integration/test_app_api.py -q
```

重点验证：

- 查询不存在订单返回 404。
- 创建工单后能查到。
- 抛异常且未 commit 时不会落库。

### 常见错误

- Repository 里直接 `commit()`：事务边界分散，多个写入难以保证一致性。
- Service 里 import SQLAlchemy model：业务层和基础设施层耦合。
- UoW 退出时不 rollback：异常路径可能留下脏状态。

### 面试时怎么讲

可以这样说：

> 我用 Repository 隔离数据访问，用 Unit of Work 控制事务边界。Repository 不直接提交事务，业务 service 决定什么时候 commit，这样多个仓储操作可以组成一个原子业务用例。

---

## 第 7 章：实现普通业务 API

### 本章目标

先把售后能力作为普通 REST API 暴露出来，不依赖 Agent。包括订单、物流、客户、政策、工单、退款和审计日志。

### 为什么要做这一步

Agent 工具本质上还是业务 API 的另一种入口。先保证业务能力可以独立调用，后面 Agent 出问题时也能判断是业务层问题还是 Agent runtime 问题。

### 本章要创建或修改哪些文件

```text
src/app_api/deps.py
src/app_api/container.py
src/app_api/bootstrap.py
src/app_api/routers/after_sales_resources.py
src/app_api/main.py
```

### 推荐目录结构

```text
src/app_api/
  container.py
  bootstrap.py
  deps.py
  routers/
    after_sales_resources.py
```

### 关键概念讲解

Dependency Injection：FastAPI 的 `Depends` 可以把 service 注入 route。

Container：保存应用启动时创建好的共享对象，例如数据库、业务 service、Agent registry。

Composition root：把所有依赖装配起来的地方。本项目是 `app_api/bootstrap.py`。

API key：本地可选，生产推荐开启。

### 开发步骤

1. 创建 `AppContainer`。
2. 在 `bootstrap.py` 初始化 `BusinessDatabase`、UoW factory、`AfterSalesService`。
3. 在 lifespan 中把 container 放到 `app.state.container`。
4. 写 `deps.py` 获取 container、校验 API key、获取 business service。
5. 写业务 router。
6. 在 `main.py` 注册 router。

### 示例代码

`deps.py`：

```python
from __future__ import annotations

from typing import Annotated, cast

from fastapi import Depends, Header, HTTPException, Request

from app_api.container import AppContainer
from business_service.after_sales.application.services.after_sales_service import AfterSalesService


async def get_container(request: Request) -> AppContainer:
    # app.state.container 在 lifespan 启动时写入。
    return cast(AppContainer, request.app.state.container)


async def require_api_key(
    request: Request,
    x_api_key: str | None = Header(default=None),
) -> None:
    expected = request.app.state.settings.api_key
    if expected is None:
        return
    if x_api_key != expected.get_secret_value():
        raise HTTPException(status_code=401, detail="invalid api key")


async def get_after_sales_service(
    container: Annotated[AppContainer, Depends(get_container)],
) -> AfterSalesService:
    return container.after_sales_service
```

`after_sales_resources.py`：

```python
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from app_api.deps import get_after_sales_service, require_api_key
from business_service.after_sales.application.services.after_sales_service import AfterSalesService
from business_service.after_sales.domain.entities import OrderRead

router = APIRouter(prefix="/api/after-sales", tags=["after-sales-resources"])


@router.get("/orders/{order_id}", response_model=OrderRead)
async def get_order(
    order_id: str,
    service: AfterSalesService = Depends(get_after_sales_service),
    _: None = Depends(require_api_key),
) -> OrderRead:
    try:
        # route 层负责 HTTP 状态码，service 层负责业务语义。
        return await service.get_order_detail(order_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
```

### 如何运行或验证

先写种子数据脚本，插入 `ORD123`，然后：

```bash
make seed
make start
curl http://127.0.0.1:8000/api/after-sales/orders/ORD123
curl http://127.0.0.1:8000/api/after-sales/orders/ORD123/shipment
curl -X POST http://127.0.0.1:8000/api/after-sales/tickets \
  -H "Content-Type: application/json" \
  -d '{"order_id":"ORD123","issue_type":"damaged","summary":"商品坏了","priority":"normal"}'
```

### 常见错误

- route 里直接创建数据库连接：每个接口各管各的，生命周期混乱。
- service 抛 `ValueError` 但 route 没转换成 `HTTPException`，客户端会得到 500。
- `Depends(require_api_key)` 写漏，生产接口可能无保护。
- 没 seed 数据就查 `ORD123`，返回 404 是正常的。

### 面试时怎么讲

可以这样说：

> 我先把售后能力作为普通 REST API 暴露，并通过 FastAPI dependency 注入业务 service。这样业务能力不依赖 Agent，既能被传统系统调用，也能被 Agent 工具复用。

---

## 第 8 章：封装 LLM Client

### 本章目标

封装 chat model 创建逻辑，支持 DeepSeek 和 OpenAI，并让测试可以注入 fake chat model。

### 为什么要做这一步

Agent runtime 不应该关心具体 provider 怎么初始化，也不应该在测试里真的调用外部 LLM。封装 LLM factory 可以把 provider 差异和 API key 校验集中处理。

### 本章要创建或修改哪些文件

```text
src/agent_service/llm/factory.py
src/agent_service/llm/payloads.py
src/agent_service/llm/tokens.py
src/agent_service/llm/types.py
tests/fake_chat_models.py
tests/test_model_factory.py
```

### 推荐目录结构

```text
src/agent_service/llm/
  __init__.py
  factory.py
  payloads.py
  tokens.py
  types.py
tests/
  fake_chat_models.py
  test_model_factory.py
```

### 关键概念讲解

Provider：LLM 服务商，例如 DeepSeek、OpenAI。

Chat model：LangChain 中统一的聊天模型接口。

Streaming：模型一边生成一边返回 token 或 message chunk。

Fake model：测试用模型，不请求网络，按规则返回结果。

Token usage：记录或估算输入输出 token 数，方便调试和成本分析。

### 开发步骤

1. 创建 `build_chat_model()`。
2. 根据 `llm_provider` 分支创建 DeepSeek 或 OpenAI model。
3. API key 缺失时抛出明确错误。
4. 设置 `temperature=0`，提高教学和测试稳定性。
5. 创建 `DeterministicToolCallingChatModel` 作为测试模型。
6. 在 `create_app()` 中支持 `chat_model_override`。

### 示例代码

`factory.py`：

```python
from __future__ import annotations

from langchain_core.language_models.chat_models import BaseChatModel
from pydantic import SecretStr


def build_chat_model(
    *,
    llm_provider: str,
    llm_model: str,
    llm_timeout_seconds: float,
    llm_max_retries: int,
    deepseek_api_key: str | None,
    openai_api_key: str | None,
) -> BaseChatModel:
    # factory 集中处理 provider 分支和 API key 校验。
    if llm_provider == "deepseek":
        if deepseek_api_key is None:
            raise ValueError("DEEPSEEK_API_KEY is required when llm_provider=deepseek")
        from langchain_deepseek import ChatDeepSeek

        return ChatDeepSeek(
            api_key=SecretStr(deepseek_api_key),
            model=llm_model,
            temperature=0,
            streaming=True,
            timeout=llm_timeout_seconds,
            max_retries=llm_max_retries,
        )

    if llm_provider == "openai":
        if openai_api_key is None:
            raise ValueError("OPENAI_API_KEY is required when llm_provider=openai")
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(
            api_key=SecretStr(openai_api_key),
            model=llm_model,
            temperature=0,
            streaming=True,
            timeout=llm_timeout_seconds,
            max_retries=llm_max_retries,
        )

    raise ValueError(f"unsupported llm provider: {llm_provider}")
```

测试模型思路：

```python
from __future__ import annotations

from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.tools import BaseTool
from pydantic import PrivateAttr


class DeterministicToolCallingChatModel(BaseChatModel):
    _bound_tools: list[BaseTool] = PrivateAttr(default_factory=list)

    @property
    def _llm_type(self) -> str:
        # LangChain 要求模型声明自己的类型名称。
        return "deterministic-test-model"

    def bind_tools(
        self,
        tools: list[BaseTool] | tuple[BaseTool, ...],
        **kwargs: Any,
    ) -> "DeterministicToolCallingChatModel":
        # Agent runtime 会调用 bind_tools，把工具绑定到模型上。
        del kwargs
        clone = self.model_copy(deep=True)
        clone._bound_tools = list(tools)
        return clone

    async def _agenerate(
        self,
        messages: list[BaseMessage],
        **kwargs: Any,
    ) -> ChatResult:
        # 测试模型可以根据最后一条消息决定直接回复还是发起工具调用。
        del kwargs
        message = AIMessage(content="测试模型回复")
        if messages and isinstance(messages[-1], ToolMessage):
            message = AIMessage(content=f"工具结果：{messages[-1].content}")
        return ChatResult(generations=[ChatGeneration(message=message)])

    def _generate(self, messages: list[BaseMessage], **kwargs: Any) -> ChatResult:
        # 项目测试只走 async 路径，同步路径显式不实现。
        del messages, kwargs
        raise NotImplementedError("tests use async execution only")
```

### 如何运行或验证

```bash
uv run pytest tests/test_model_factory.py -q
```

本地真实模型验证：

```bash
LLM_PROVIDER=deepseek DEEPSEEK_API_KEY=replace-me uv run python - <<'PY'
from app_api.settings import AppSettings
from agent_service.llm.factory import build_chat_model

settings = AppSettings()
model = build_chat_model(
    llm_provider=settings.llm_provider,
    llm_model=settings.llm_model,
    llm_timeout_seconds=settings.llm_timeout_seconds,
    llm_max_retries=settings.llm_max_retries,
    deepseek_api_key=settings.deepseek_api_key.get_secret_value() if settings.deepseek_api_key else None,
    openai_api_key=None,
)
print(model.__class__.__name__)
PY
```

### 常见错误

- 测试直接调用真实 LLM，导致慢、不稳定、依赖网络和费用。
- provider 缺 key 时错误信息不明确。
- `temperature` 太高，测试结果不可预测。
- 忘记 `streaming=True`，后续 SSE 体验变差。

### 面试时怎么讲

可以这样说：

> 我把 LLM provider 初始化封装成 factory，业务和 runtime 不直接依赖具体模型类。测试通过 fake chat model 注入，避免外部网络和费用，也让 tool calling 流程可重复验证。

---

## 第 9 章：Agent Contract 和 ToolSpec

### 本章目标

定义 Agent runtime 和业务工具之间的窄接口，包括 `ToolSpec`、`ApprovalPolicy`、`AgentDefinition`、`RunEvent` 和 `AgentRegistry`。

### 为什么要做这一步

如果直接把业务服务绑到 LangChain tool，业务层会被框架污染。先定义项目自己的窄 contract，可以让业务工具、MCP 工具和 runtime 通过统一接口连接。

### 本章要创建或修改哪些文件

```text
src/agent_service/contracts/actions.py
src/agent_service/contracts/capability.py
src/agent_service/contracts/events.py
src/agent_service/contracts/registry.py
src/agent_service/contracts/models.py
```

### 推荐目录结构

```text
src/agent_service/contracts/
  __init__.py
  actions.py
  capability.py
  events.py
  models.py
  registry.py
```

### 关键概念讲解

`ToolSpec`：项目内部的工具描述，包含名字、描述、参数 schema、handler 和审批策略。

`ApprovalPolicy`：判断一次工具调用是否需要人工审批。

`AgentDefinition`：一个 agent 的能力定义，包含 capability id、prompt 和 tools。

`RunEvent`：Agent 执行过程中的事件，例如 run started、tool started、approval required、run completed。

`AgentRegistry`：代码型 agent catalog，用于 `/api/agents` 和工具列表接口。

### 开发步骤

1. 定义 `ApprovalRequirement`。
2. 定义 `ToolContext` 和 `ToolHandler`。
3. 定义 `ToolSpec`。
4. 定义 `AgentDefinition`。
5. 定义运行事件。
6. 实现 `AgentRegistry`。

### 示例代码

`actions.py`：

```python
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

from pydantic import BaseModel

from agent_service.contracts.models import ActorContext, RiskLevel


@dataclass(slots=True, frozen=True)
class ApprovalRequirement:
    # 这个对象描述为什么要暂停，以及给人工看的展示信息。
    reason: str
    risk_level: RiskLevel = "low"
    display_payload: dict[str, object] | None = None


@dataclass(slots=True, frozen=True)
class ToolContext:
    capability_id: str
    actor: ActorContext = field(default_factory=ActorContext)
    dependencies: object | None = None


class ToolHandler(Protocol):
    def __call__(self, payload: dict[str, Any], context: ToolContext) -> Any: ...


class ApprovalPolicy(Protocol):
    def evaluate(self, payload: dict[str, Any]) -> ApprovalRequirement | None: ...


@dataclass(slots=True, frozen=True)
class CallableApprovalPolicy:
    evaluator: Callable[[dict[str, Any]], ApprovalRequirement | None]

    def evaluate(self, payload: dict[str, Any]) -> ApprovalRequirement | None:
        return self.evaluator(payload)


@dataclass(slots=True, frozen=True)
class ToolSpec:
    name: str
    description: str
    args_schema: type[BaseModel]
    handler: ToolHandler
    approval_policy: ApprovalPolicy | None = None
    source: Literal["local", "mcp"] = "local"
    source_id: str | None = None
```

`capability.py`：

```python
from __future__ import annotations

from dataclasses import dataclass

from agent_service.contracts.actions import ToolSpec


@dataclass(slots=True, frozen=True)
class AgentDefinition:
    # capability_id 是这个 agent 在 API 和 registry 中的稳定 id。
    capability_id: str
    system_prompt: str
    tools: tuple[ToolSpec, ...]
    name: str | None = None
    description: str | None = None
```

`registry.py`：

```python
from __future__ import annotations

from dataclasses import dataclass, field

from agent_service.contracts.capability import AgentDefinition


@dataclass(slots=True)
class AgentRegistry:
    _definitions: dict[str, AgentDefinition] = field(default_factory=dict)

    def register(self, definition: AgentDefinition) -> None:
        # 后注册的同 id definition 会覆盖旧值，便于测试替换。
        self._definitions[definition.capability_id] = definition

    def get(self, capability_id: str) -> AgentDefinition | None:
        return self._definitions.get(capability_id)

    def list_definitions(self) -> list[AgentDefinition]:
        return [self._definitions[key] for key in sorted(self._definitions)]
```

### 如何运行或验证

```bash
uv run python - <<'PY'
from pydantic import BaseModel
from agent_service.contracts.actions import ToolSpec, ToolContext

class Args(BaseModel):
    order_id: str

def handler(payload: dict, context: ToolContext) -> dict:
    return {"ok": True, "order_id": payload["order_id"]}

tool = ToolSpec(name="get_order_detail", description="查订单", args_schema=Args, handler=handler)
print(tool.name, tool.args_schema.model_json_schema()["title"])
PY
```

### 常见错误

- 把 `ToolSpec` 设计得太像某个厂商的 tool schema，导致后续难以替换 runtime。
- 让 `agent_service` import 售后业务模块，破坏层间边界。
- 工具 handler 不做参数 schema 校验，LLM 生成错误参数时难以定位。

### 面试时怎么讲

可以这样说：

> 我没有让业务层直接依赖 LangChain，而是定义了项目内部的 `ToolSpec` 和 `AgentDefinition`。业务能力先包装成稳定的内部 contract，再由 runtime 适配成 LangChain tool。

---

## 第 10 章：售后 Agent Definition

### 本章目标

把 `AfterSalesService` 包装成 Agent 可调用的工具目录，定义售后 Agent 的系统提示词和审批策略。

### 为什么要做这一步

业务服务只会处理结构化参数，用户输入是自然语言。Agent Definition 负责告诉模型有哪些工具、什么时候用工具、每个工具需要什么参数，以及哪些工具需要审批。

### 本章要创建或修改哪些文件

```text
src/app_api/services/after_sales_agent_definition.py
src/app_api/routers/agents.py
src/app_api/schemas/agents.py
```

### 推荐目录结构

```text
src/app_api/
  services/
    after_sales_agent_definition.py
  routers/
    agents.py
  schemas/
    agents.py
```

### 关键概念讲解

Adapter：把业务服务方法转换成 Agent 工具 handler。

System prompt：告诉模型角色、边界、工具选择规则和输出风格。

Approval policy：在真正执行高风险工具前判断是否暂停。

Tool catalog API：让前端或调用方知道当前 agent 有哪些工具。

### 开发步骤

1. 定义 `build_after_sales_agent_definition()`。
2. 为每个业务 service 方法写 tool handler。
3. handler 内用 Pydantic schema 校验 payload。
4. 将返回值 `model_dump(mode="json")`。
5. 为退款工具加审批策略。
6. 写 `/api/agents` 和 `/api/agents/{capability_id}/tools`。

### 示例代码

`after_sales_agent_definition.py`：

```python
from __future__ import annotations

from typing import Any

from agent_service.contracts.actions import ApprovalRequirement, CallableApprovalPolicy, ToolContext, ToolSpec
from agent_service.contracts.capability import AgentDefinition
from business_service.after_sales.application.services.after_sales_service import AfterSalesService
from business_service.after_sales.domain.entities import OrderLookupInput, RefundRequestCreate


def build_after_sales_agent_definition(
    *,
    after_sales_service: AfterSalesService,
) -> AgentDefinition:
    async def get_order_detail(
        payload: dict[str, Any],
        context: ToolContext,
    ) -> dict[str, Any]:
        # context 里有 actor 信息，本工具暂时不需要。
        del context
        order = await after_sales_service.get_order_detail(
            OrderLookupInput.model_validate(payload)
        )
        return order.model_dump(mode="json")

    async def submit_refund_request(
        payload: dict[str, Any],
        context: ToolContext,
    ) -> dict[str, Any]:
        del context
        refund = await after_sales_service.submit_refund_request(
            RefundRequestCreate.model_validate(payload)
        )
        return refund.model_dump(mode="json")

    def evaluate_refund_approval(payload: dict[str, Any]) -> ApprovalRequirement | None:
        # 把业务层审批规则转换成 Agent runtime 能识别的 ApprovalRequirement。
        requirement = after_sales_service.evaluate_refund_approval(
            RefundRequestCreate.model_validate(payload)
        )
        if requirement is None:
            return None
        return ApprovalRequirement(
            reason=requirement.reason,
            risk_level=requirement.risk_level,
            display_payload=requirement.display_payload,
        )

    system_prompt = "".join(
        (
            "你是售后客服专家。",
            "你的目标是帮助用户完成查单、查物流、建工单、退款申请和售后政策解释。",
            "当用户查询订单状态时，优先调用 get_order_detail。",
            "当用户明确要求退款并提供订单号、金额和原因时，调用 submit_refund_request。",
            "回复必须简洁、专业、中文输出。",
            "如果动作已经返回结果，优先基于结果作答，不要编造业务数据。",
            "每轮最多调用一个工具。",
        )
    )

    return AgentDefinition(
        capability_id="after_sales_assistant",
        name="After-Sales Assistant",
        description="售后客服 agent，支持查单、物流、工单、退款审批和政策查询。",
        system_prompt=system_prompt,
        tools=(
            ToolSpec(
                name="get_order_detail",
                description="获取订单详情，适用于查询订单状态、商品概要和下单信息。",
                args_schema=OrderLookupInput,
                handler=get_order_detail,
            ),
            ToolSpec(
                name="submit_refund_request",
                description="提交退款申请。命中审批策略时会先等待人工动作。",
                args_schema=RefundRequestCreate,
                handler=submit_refund_request,
                approval_policy=CallableApprovalPolicy(evaluate_refund_approval),
            ),
        ),
    )
```

### 如何运行或验证

启动后调用：

```bash
curl http://127.0.0.1:8000/api/agents
curl http://127.0.0.1:8000/api/agents/after_sales_assistant/tools
```

预期工具列表中包含：

```text
get_order_detail
submit_refund_request
```

`submit_refund_request` 的 `requires_approval` 应为 `true`。

### 常见错误

- prompt 写得太泛，模型不知道什么时候调用哪个工具。
- 工具描述不清楚，模型选择工具不稳定。
- handler 里不做 `model_validate`，LLM 参数错误时会在更深层才爆。
- 审批规则写在 runtime 里，导致业务规则和 Agent 执行逻辑耦合。

### 面试时怎么讲

可以这样说：

> 我把售后业务服务包装成 Agent Definition。工具 handler 是 adapter，负责参数校验和结果序列化；审批规则仍来自业务服务，Agent 层只负责根据审批结果暂停或继续执行。

---

## 第 11 章：LangChain/LangGraph Runtime

### 本章目标

使用 LangChain `create_agent` 和 LangGraph checkpoint 实现 Agent 执行、工具调用事件、审批中断、恢复执行、session transcript 和运行状态查询。

### 为什么要做这一步

前面已经有业务工具和 Agent Definition，但还缺少真正执行 Agent 的 runtime。Runtime 的职责是把内部 `ToolSpec` 转成 LangChain tool，把运行过程转成项目自己的 `RunEvent`，并在需要审批时暂停。

### 本章要创建或修改哪些文件

```text
src/agent_service/infrastructure/runtime/langchain_runtime.py
src/agent_service/infrastructure/state_store/in_memory_store.py
src/agent_service/infrastructure/state_store/langgraph_postgres_store.py
src/agent_service/infrastructure/state_store/session_transcript_store.py
src/app_api/services/after_sales_assistant.py
src/app_api/services/after_sales_run_projector.py
```

### 推荐目录结构

```text
src/agent_service/infrastructure/
  runtime/
    langchain_runtime.py
  state_store/
    in_memory_store.py
    langgraph_postgres_store.py
    session_transcript_store.py
src/app_api/services/
  after_sales_assistant.py
  after_sales_run_projector.py
```

### 关键概念讲解

LangChain `create_agent`：根据模型、工具、prompt 创建可执行 agent。

LangGraph checkpointer：保存 thread/run 状态，支持中断和恢复。

`interrupt`：LangGraph 中让执行暂停并等待外部 resume 的机制。

`RunEvent`：项目自己的事件模型，避免 API 层直接暴露 LangChain 内部事件。

`session_id` 和 `run_id`：`session_id` 是对话上下文，`run_id` 是一次执行线程。一个 session 下可以有多个 run，其中某个 run 可以等待审批，另一个 run 仍可执行。

### 开发步骤

1. 实现 `InMemoryStateStore`，用于本地和测试。
2. 实现 `SessionTranscriptStore`，保存 session 级对话历史。
3. 实现 `LangChainAgentRuntime.stream_run()`。
4. 将 `ToolSpec` 转成 `StructuredTool`。
5. 用 middleware 在模型准备调用高风险工具后触发 `interrupt`。
6. 实现 `stream_action()`，通过 `Command(resume=...)` 恢复执行。
7. 将 LangChain stream part 映射成 `OutputDeltaEvent`、`ActionStartedEvent`、`ActionCompletedEvent`。
8. 实现 `get_state()` 查询 run 状态。
9. 用 `AfterSalesRunProjector` 把事件投影到 tool log、approval record 和 audit log。

### 示例代码

简化版 `_to_langchain_tool()`：

```python
from __future__ import annotations

from typing import Any

from langchain_core.tools import StructuredTool
from langchain_core.tools.base import BaseTool

from agent_service.contracts.actions import ToolContext, ToolSpec


def to_langchain_tool(tool_spec: ToolSpec) -> BaseTool:
    async def runner(**kwargs: Any) -> tuple[str, dict[str, Any]]:
        # LangChain tool 的 kwargs 来自模型生成的工具参数。
        result = await tool_spec.handler(
            kwargs,
            ToolContext(capability_id="after_sales_assistant"),
        )
        envelope = {"success": True, "action": tool_spec.name, "result": result}
        return str(envelope), envelope

    return StructuredTool.from_function(
        coroutine=runner,
        name=tool_spec.name,
        description=tool_spec.description,
        args_schema=tool_spec.args_schema,
        response_format="content_and_artifact",
    )
```

简化版审批中断逻辑：

```python
from __future__ import annotations

from langgraph.types import interrupt

from agent_service.contracts.models import AgentPendingAction


def maybe_interrupt_for_approval(
    *,
    tool_name: str,
    tool_arguments: dict,
    action_id: str,
    requirement,
) -> object | None:
    # requirement 来自 ToolSpec.approval_policy.evaluate。
    if requirement is None:
        return None

    pending_action = AgentPendingAction(
        action_id=action_id,
        action_name=tool_name,
        action_payload=tool_arguments,
        reason=requirement.reason,
        risk_level=requirement.risk_level,
        display_payload=requirement.display_payload or {},
    )

    # interrupt 会把当前 run 暂停，后续通过 Command(resume=...) 恢复。
    return interrupt({"pending_action": pending_action.model_dump(mode="json")})
```

`AfterSalesAssistantService` 的作用：

```python
from __future__ import annotations

from collections.abc import AsyncIterator

from agent_service.contracts.events import RunCompletedEvent, RunEvent
from agent_service.contracts.models import ActorContext, AgentRunResult


class AfterSalesAssistantService:
    def __init__(self, *, runtime, definition, projector) -> None:
        self._runtime = runtime
        self._definition = definition
        self._projector = projector

    async def run(
        self,
        *,
        message: str,
        session_id: str | None,
        actor: ActorContext,
    ) -> AgentRunResult:
        # 同步接口本质上也是消费 stream，直到 RunCompletedEvent。
        async for event in self.stream(message=message, session_id=session_id, actor=actor):
            if isinstance(event, RunCompletedEvent):
                return event.result
        raise RuntimeError("run finished without RunCompletedEvent")

    async def stream(
        self,
        *,
        message: str,
        session_id: str | None,
        actor: ActorContext,
    ) -> AsyncIterator[RunEvent]:
        async for event in self._runtime.stream_run(
            definition=self._definition,
            message=message,
            session_id=session_id,
            actor=actor,
        ):
            await self._projector.record_event(event)
            yield event
```

### 如何运行或验证

单元测试优先：

```bash
uv run pytest tests/test_langchain_runtime.py -q
```

重点验证事件顺序：

```text
RunStartedEvent
ActionStartedEvent
ActionCompletedEvent
OutputDeltaEvent
RunCompletedEvent
```

审批流验证：

```text
RunStartedEvent
ActionRequiredEvent
RunCompletedEvent(status=awaiting_action)
```

然后调用恢复动作，预期完成：

```text
RunStartedEvent
ActionStartedEvent
ActionCompletedEvent
OutputDeltaEvent
RunCompletedEvent(status=completed)
```

### 常见错误

- 把 `session_id` 当成 LangGraph `thread_id`，导致一个 session 里多个待审批 run 相互阻塞。当前项目用 `run_id` 做 thread id。
- 直接把 LangChain stream 原始事件返回给前端，API 契约会跟第三方库强绑定。
- 审批拒绝后没有写 ToolMessage，模型不知道为什么工具没执行。
- 忘记持久化 session transcript，下一轮对话没有上下文。

### 面试时怎么讲

可以这样说：

> Runtime 用 LangChain `create_agent` 执行工具调用，用 LangGraph checkpoint 保存 run 级状态。高风险工具通过 middleware 在执行前触发 interrupt，人工审批后用 resume 恢复。API 层只暴露项目自己的 RunEvent，不暴露 LangChain 内部结构。

---

## 第 12 章：API 集成、测试、部署与复盘

### 本章目标

把 Agent runtime 接入 HTTP API，补齐同步运行、SSE 流、审批动作、状态查询、Agent catalog、测试、迁移、seed、compose 和面试复盘。

### 为什么要做这一步

前面的模块只有组合起来才是一个完整产品。最后一章要把业务数据库、LLM、runtime、Agent definition、projection 和 HTTP router 装配成一个可运行、可测试、可部署的后端。

### 本章要创建或修改哪些文件

```text
src/app_api/bootstrap.py
src/app_api/container.py
src/app_api/deps.py
src/app_api/routers/after_sales_runs.py
src/app_api/routers/after_sales_approvals.py
src/app_api/routers/agents.py
src/app_api/routers/health.py
src/app_api/migrations.py
src/app_api/cli/doctor.py
src/app_api/cli/migrate.py
scripts/seed.py
migrations/
compose.yaml
Makefile
tests/
```

### 推荐目录结构

```text
src/app_api/
  bootstrap.py
  container.py
  deps.py
  migrations.py
  cli/
    doctor.py
    migrate.py
  routers/
    health.py
    agents.py
    after_sales_resources.py
    after_sales_runs.py
    after_sales_approvals.py
scripts/
  seed.py
migrations/
  env.py
  versions/
compose.yaml
Makefile
tests/
```

### 关键概念讲解

同步 run API：后端消费完整 Agent stream，只把最终 `RunResponse` 返回给调用方。

SSE stream API：把每个 `RunEvent` 转成 `event:` 和 `data:` 返回给前端。

Approval action API：提交 `approved` 或 `rejected`，恢复某个 paused run。

Projection：把运行事件投影成业务数据库里的 tool log、approval record 和 audit log。

Alembic：版本化管理数据库 schema。

Compose：本项目现有 `compose.yaml` 提供 PostgreSQL 和 Redis；教学版后端 Dockerfile 可作为扩展新增。

### 开发步骤

1. 在 `bootstrap.py` 创建数据库、UoW、业务 service。
2. 加载 MCP tools，失败时不阻止应用启动，只让 health degraded。
3. 注册售后 Agent Definition 到 `AgentRegistry`。
4. 创建 LLM dependency，失败时让 assistant service unavailable。
5. 创建 `LangChainAgentRuntime` 和 `AfterSalesAssistantService`。
6. 实现 `/api/after-sales/runs`。
7. 实现 `/api/after-sales/runs/stream`。
8. 实现 `/api/after-sales/actions`。
9. 实现 `/api/after-sales/runs/{run_id}`。
10. 实现 `/health` 返回 runtime、business DB、LLM、MCP 状态。
11. 增加 Alembic migration 和 seed 数据。
12. 写 pytest、ruff、mypy 质量门槛。

### 示例代码

`after_sales_runs.py` 核心接口：

```python
from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import APIRouter, Depends
from sse_starlette.sse import EventSourceResponse

from agent_service.contracts.events import OutputDeltaEvent, RunCompletedEvent, RunStartedEvent
from agent_service.contracts.models import ActorContext
from app_api.deps import get_after_sales_assistant_service, require_api_key
from app_api.schemas.runs import CreateRunRequest, RunResponse

router = APIRouter(prefix="/api/after-sales", tags=["after-sales-runs"])


def encode_sse(event: str, payload: dict[str, object]) -> dict[str, str]:
    # SSE 响应必须把 data 编码成字符串。
    return {"event": event, "data": json.dumps(payload, ensure_ascii=False)}


async def sse_stream(stream: AsyncIterator[object]) -> AsyncIterator[dict[str, str]]:
    async for event in stream:
        if isinstance(event, RunStartedEvent):
            yield encode_sse("run.started", {"run_id": event.run_id, "session_id": event.session_id})
        elif isinstance(event, OutputDeltaEvent):
            yield encode_sse("output.delta", {"run_id": event.run_id, "delta": event.delta})
        elif isinstance(event, RunCompletedEvent):
            yield encode_sse("run.completed", event.result.model_dump(mode="json"))


@router.post("/runs", response_model=RunResponse)
async def create_run(
    payload: CreateRunRequest,
    assistant_service: Annotated[object, Depends(get_after_sales_assistant_service)],
    _: None = Depends(require_api_key),
) -> RunResponse:
    result = await assistant_service.run(
        message=payload.message,
        session_id=payload.session_id,
        actor=ActorContext(actor_id=payload.actor_id, metadata=payload.actor_metadata),
    )
    return RunResponse.model_validate(result.model_dump(mode="json"))


@router.post("/runs/stream")
async def stream_run(
    payload: CreateRunRequest,
    assistant_service: Annotated[object, Depends(get_after_sales_assistant_service)],
    _: None = Depends(require_api_key),
) -> EventSourceResponse:
    stream = assistant_service.stream(
        message=payload.message,
        session_id=payload.session_id,
        actor=ActorContext(actor_id=payload.actor_id, metadata=payload.actor_metadata),
    )
    return EventSourceResponse(sse_stream(stream), media_type="text/event-stream")
```

`compose.yaml`：

```yaml
services:
  postgres:
    image: postgres:16
    container_name: agent-postgres
    environment:
      POSTGRES_USER: agent
      POSTGRES_PASSWORD: agent
      POSTGRES_DB: agent_platform
    ports:
      - "5432:5432"
    volumes:
      - pgdata:/var/lib/postgresql/data

  redis:
    image: redis:7
    container_name: agent-redis
    ports:
      - "6379:6379"

volumes:
  pgdata:
```

教学版可选新增 `Dockerfile`：

```dockerfile
FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN pip install uv && uv sync --frozen --no-dev

COPY src ./src
COPY migrations ./migrations
COPY alembic.ini ./alembic.ini

CMD [".venv/bin/python", "-m", "uvicorn", "app_api.main:create_app", "--factory", "--app-dir", "src", "--host", "0.0.0.0", "--port", "8000"]
```

### 如何运行或验证

本地 SQLite 快速验证：

```bash
uv sync --extra dev
make seed
make start
curl http://127.0.0.1:8000/health
```

业务 API：

```bash
curl http://127.0.0.1:8000/api/after-sales/orders/ORD123
```

同步 Agent run：

```bash
curl -X POST http://127.0.0.1:8000/api/after-sales/runs \
  -H "Content-Type: application/json" \
  -d '{"message":"查一下订单 ORD123","session_id":"demo-1"}'
```

SSE run：

```bash
curl -N -X POST http://127.0.0.1:8000/api/after-sales/runs/stream \
  -H "Content-Type: application/json" \
  -d '{"message":"订单 ORD123 退款 200，商品破损","session_id":"refund-demo-1"}'
```

审批恢复：

```bash
curl -X POST http://127.0.0.1:8000/api/after-sales/actions \
  -H "Content-Type: application/json" \
  -d '{"run_id":"run-替换成真实值","action_id":"call_submit_refund_request","decision":"approved"}'
```

质量门槛：

```bash
uv run pytest -q
uv run ruff check src tests scripts
uv run mypy src
```

### 常见错误

- LLM key 缺失：`/health` 会显示 degraded，`/api/after-sales/runs` 返回 503。
- 数据库缺表：运行 `make migrate` 或本地设置 `AUTO_CREATE_SCHEMA=true`。
- SSE 没有事件：确认客户端使用 `curl -N`，不要被缓冲。
- 审批 action_id 错误：接口应返回 409，approval record 仍保持 pending。
- PostgreSQL runtime URL 写成同步驱动：项目会把 `postgresql://` 转成 `postgresql+psycopg://` 给 SQLAlchemy async 使用。
- MCP server 连接失败：应用可以继续启动，`/health` 的 `mcp.ok` 为 `false`。

### 面试时怎么讲

可以这样说：

> 这个项目的最终请求链路是 FastAPI route 进入 assistant service，assistant service 调用 LangChain runtime，runtime 根据 AgentDefinition 调用 ToolSpec，ToolSpec handler 再调用售后业务 service，业务 service 通过 Unit of Work 操作数据库。运行过程会投影成 tool log、approval record 和 audit log。高风险退款通过 LangGraph interrupt 暂停，审批后 resume 同一个 run。

---

## 课程最终验收清单

学习者完成本项目后，应能独立做到：

- 从空目录创建 `src` layout Python 后端项目。
- 用 uv 管理依赖和虚拟环境。
- 用 FastAPI 创建 app、router、schema 和 dependency。
- 用 `pydantic-settings` 管理 `.env`。
- 用 SQLAlchemy 建模业务表。
- 用 Repository 和 Unit of Work 管理数据访问和事务。
- 写普通售后 REST API。
- 封装 DeepSeek/OpenAI chat model。
- 定义 Agent contract、ToolSpec 和 AgentDefinition。
- 把业务 service 适配成 Agent tool。
- 用 LangChain `create_agent` 执行工具调用。
- 用 LangGraph checkpoint 支持审批中断和恢复。
- 用 SSE 输出运行事件。
- 写 pytest、ruff、mypy 质量门槛。
- 用 seed、migration、compose 支持本地开发和部署。

最终必须能通过：

```bash
uv run pytest -q
uv run ruff check src tests scripts
uv run mypy src
```

---

## 项目总结与面试表达

一句话项目介绍：

> 我做的是一个售后客服 Agent 后端，使用 FastAPI 暴露 API，用 SQLAlchemy 管理售后业务数据，用 LangChain 和 LangGraph 实现工具调用、审批中断和恢复执行。

架构亮点：

- 业务层和 Agent 层双向不依赖。
- Agent 工具只是业务服务的 adapter。
- 普通 REST API 和 Agent API 共用同一套售后业务能力。
- 高风险退款用业务审批规则判断，用 LangGraph interrupt 暂停。
- `run_id` 和 `session_id` 分离，支持同一 session 下多个 run。
- 业务数据库、LangGraph checkpoint、session transcript 三类状态分开。
- 测试用 deterministic model，不依赖真实 LLM。

可以展开讲的请求链路：

```text
POST /api/after-sales/runs
  -> CreateRunRequest
  -> AfterSalesAssistantService
  -> LangChainAgentRuntime
  -> AgentDefinition / ToolSpec
  -> AfterSalesService
  -> AfterSalesUnitOfWork
  -> SqlAlchemyAfterSalesRepository
  -> business database
```

可以展开讲的审批链路：

```text
用户要求高风险退款
  -> Agent 计划调用 submit_refund_request
  -> ApprovalPolicy 判断需要人工审批
  -> LangGraph interrupt 暂停 run
  -> API 返回 awaiting_action
  -> 人工调用 /api/after-sales/actions
  -> runtime resume
  -> 工具真正执行
  -> refund request、tool log、approval record、audit log 落库
```

不要把这个项目说成通用 Agent 平台。更准确的说法是：

> 它是一个业务边界清晰的售后 Agent 后端。业务层稳定，Agent runtime 可替换，二者通过 app/API adapter 组合。
