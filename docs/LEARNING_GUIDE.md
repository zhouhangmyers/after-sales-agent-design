# 从 0 到 1 开发售后 Agent 后端

这份指南不是代码评审，也不是简单解释现有目录。它把当前项目反向拆成一门实战课程，目标是让有基础代码经验、但没有系统 Python 后端和 Agent 开发经验的学习者，从空目录开始，一步一步开发出当前仓库主线版售后客服 Agent 后端。

课程主线采用当前项目风格：

```text
FastAPI
  -> agent_1_after_sales.app_api 负责 HTTP API 和依赖装配
  -> agent_1_after_sales.business_service.after_sales 负责售后业务
  -> agent_1_after_sales.agent_service 负责 Agent contract、LLM、runtime、state store、MCP adapter
  -> SQLAlchemy + Alembic 负责业务数据
  -> LangChain v1 create_agent + LangGraph checkpoint 负责 Agent 执行、暂停和恢复
```

学习时要守住一个核心边界：

```text
agent_1_after_sales.business_service 不依赖 agent_1_after_sales.agent_service
agent_1_after_sales.agent_service 不依赖 agent_1_after_sales.business_service
两者只在 agent_1_after_sales.app_api 的 adapter/composition 层相遇
```

这样做的意义是：售后业务能力可以独立作为普通后端 API 使用，Agent 只是这些业务能力的一种智能入口。

目录命名不要为了表面统一而统一。这个项目里同样会出现 Pydantic model，但它们在不同层代表的东西不一样：

```text
agent_1_after_sales.app_api/schemas
  HTTP 请求/响应契约，服务 FastAPI、OpenAPI 和客户端调用。

agent_1_after_sales.agent_service/contracts
  Agent runtime 与 adapter 之间的内部契约，例如 ToolSpec、AgentDefinition、RunEvent。

agent_1_after_sales.business_service/after_sales/domain
  售后业务领域模型，例如订单、物流、工单、退款、政策和审批规则。
```

如果全部叫 `schemas`，目录看起来整齐，但语义会变糊：你分不清哪个对象是 HTTP DTO，哪个是 Agent 子系统契约，哪个是业务领域模型。当前命名故意保留差异，是为了提醒你不要让 HTTP、Agent 框架和售后业务互相污染。

这份文档的学习路线是：

```text
第一遍：按 12 章走完主线
  -> 先会开发一个可运行的售后 Agent 后端

第二遍：进入完整项目扩展篇
  -> 补齐当前仓库里的可选/进阶能力
  -> 包括 MCP、PostgreSQL checkpoint、前端、Dockerfile、完整依赖和 IDE 类型检查
```

所以前 12 章不会一上来“大而全”。每章先解决一个主线问题，让你能跟着跑起来。第 12 章后再进入扩展篇，把当前仓库里更完整、更接近生产的能力逐一补上。

每章的测试按同一个节奏推进：

```text
先列出本章新增的测试文件
  -> 再给可以直接保存的测试代码
  -> 再给单文件 pytest 命令
  -> 最后再跑更大的测试集合
```

不要等第 12 章才补测试。第 1 章先测 import，第 2 章测 `/health`，第 3 章测 settings，第 4 章测 schema。后面每引入一层能力，就补一个对应的单元或集成测试，这样学习者能知道“刚写的代码到底由哪个测试保护”。

示例代码的注释标准也要保持一致：

```text
类和函数：
  用 docstring 说明“它是什么、负责什么、解决什么问题”。

关键参数：
  在参数后用尾注说明“这个参数是什么意思、为什么要这么传”。

关键调用：
  在调用前后说明“为什么需要这一步、少了会出现什么问题”。

测试代码：
  用 Arrange / Act / Assert 说明准备、执行、断言分别验证什么。
```

这份笔记是教程，不是生产代码片段集合。教学代码允许比真实业务代码写更多解释性注释，目标是让学习者看懂每一层设计选择，而不是只复制代码。

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

12 章之后再进入“完整项目扩展篇”：

- 扩展 A：最终版依赖、`pyproject.toml`、`pyrightconfig.json` 和质量工具。
- 扩展 B：MCP 外部工具接入。
- 扩展 C：PostgreSQL durable checkpoint 和 session transcript。
- 扩展 D：Vite/React 前端工作台如何接后端和 SSE。
- 扩展 E：Dockerfile、Docker Compose 和部署口径。

### 3. 最小可运行版本 MVP 是什么

MVP 是学习过程中的第一个检查点，不是课程终点。它只做四件事：

- 启动一个 FastAPI 服务。
- 暴露 `GET /health`。
- 暴露 `POST /api/after-sales/runs`。
- 先用 mock LLM 或 deterministic chat model 调用一个本地工具 `get_order_detail`。

MVP 推荐只用 SQLite 和一条订单假数据。不要一开始就实现完整审批、SSE、MCP、PostgreSQL checkpoint 和前端。后续主线章节先补齐售后 Agent 后端，扩展篇再补齐完整项目能力。

为什么先做 MVP：

- 新手最容易卡在“装了很多库，但不知道请求怎么跑起来”。
- MVP 可以最快跑通 `HTTP -> schema -> service -> tool -> agent response`。
- 先得到一个正反馈，再逐步引入数据库、审批、SSE 和 LangGraph runtime，学习成本更可控。

---

## 第 0 章：开发前准备

### 本章目标

准备好从 0 开发项目所需的工具和基础概念。学完后，学习者能创建虚拟环境、安装依赖、运行 Python 命令、理解 `.env`、理解后端服务和 Agent 的关系。

### 为什么要做这一步

Python 后端和 Agent 项目会同时涉及依赖管理、环境变量、HTTP 服务、数据库、LLM API key 和本地开发工具。如果前置环境不稳定，后面每一章都会被安装问题打断。

### 本章要创建或修改哪些文件

本章暂时不写业务代码，只准备这些文件：

```text
agent-1-after-sales/
  .env.example
  README.md
  pyproject.toml
```

### 推荐目录结构

开发前先知道最终项目会长成这样：

```text
agent-1-after-sales/
  src/
    agent_1_after_sales/
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

1. 在 Windows 上启用 WSL，并安装 Ubuntu。
2. 在 Windows 上安装 Docker Desktop，并打开 WSL integration。
3. 在 WSL Ubuntu 里安装基础命令行工具。
4. 安装 `uv`，并用 `uv` 固定 Python 3.12。
5. 准备 VS Code 或 Cursor，建议从 WSL 目录打开项目。
6. 准备 curl 或 Postman；本教程命令以 WSL bash 和 curl 为主。
7. 确认 Python、uv、Git、Docker、curl 都能在 WSL 里运行。

### WSL/Ubuntu 开发环境准备

先在 Windows PowerShell 里确认 WSL 是否正常。这个命令在 Windows 侧执行，不是在 Ubuntu 终端里执行：

```powershell
wsl --status
wsl -l -v
```

如果看不到 Ubuntu，先安装 Ubuntu：

```powershell
wsl --install -d Ubuntu
```

进入 Ubuntu 后，先更新 apt 并安装基础工具：

```bash
sudo apt update
sudo apt install -y curl git make build-essential ca-certificates
```

安装 `uv`：

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
source "$HOME/.local/bin/env"
uv --version
```

用 `uv` 安装并固定 Python 3.12：

```bash
uv python install 3.12
uv python list | grep 3.12
```

如果你用 Docker Desktop，打开 Docker Desktop 设置里的 WSL integration，并确认 Ubuntu 已启用。然后回到 WSL 里验证：

```bash
docker --version
docker compose version
docker ps
```

项目建议放在 WSL 的 Linux 文件系统里，例如：

```bash
mkdir -p ~/python
cd ~/python
```

不要把主要开发目录放在 `/mnt/c/...`。WSL 访问 Windows 文件系统会慢很多，Python 依赖、node_modules、数据库文件和热更新也更容易出问题。

### 示例代码

```bash
uv python pin 3.12
uv run python --version
uv --version
git --version
docker --version
docker compose version
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
mkdir agent-1-after-sales
cd agent-1-after-sales
uv python pin 3.12
uv run python -c "print('python ok')"
```

如果能输出 `python ok`，说明 Python 可运行。

`.env.example` 是配置模板，真正运行时通常要复制成 `.env`：

```bash
cp .env.example .env
sed -n '1,80p' .env
```

`.env.example` 可以提交到 Git，`.env` 通常保存本机真实配置，不应该提交。当前项目的 `.gitignore` 应该忽略 `.env`。

### 常见错误

- Python 版本低于 3.12：后续类型语法可能报错。
- 没有激活虚拟环境：命令使用了系统 Python。
- `.env` 里写了真实 key 但提交到 Git：这是安全问题，真实项目必须避免。
- Docker 没启动：后面启动 PostgreSQL 会失败。
- 在 `/mnt/c/...` 里开发：依赖安装和热更新会明显变慢，SQLite 文件也更容易被 Windows 工具占用。
- `uv: command not found`：通常是没有执行 `source "$HOME/.local/bin/env"`，或者新终端没有加载 `~/.local/bin`。
- `docker: Cannot connect to the Docker daemon`：通常是 Docker Desktop 没启动，或者没有打开 Ubuntu 的 WSL integration。

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
src/agent_1_after_sales/app_api/__init__.py
src/agent_1_after_sales/agent_service/__init__.py
src/agent_1_after_sales/business_service/__init__.py
tests/__init__.py
tests/test_imports.py
```

### 推荐目录结构

```text
agent-1-after-sales/
  src/
    agent_1_after_sales/
      __init__.py
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
    test_imports.py
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

为什么这里不是三层都叫 `schemas`：

```text
app_api/schemas
  对外 HTTP DTO，字段设计优先考虑客户端和接口文档。

agent_service/contracts
  Agent 内部契约，字段设计优先考虑 runtime、tool calling 和事件流。

business_service/after_sales/domain
  业务领域模型，字段设计优先考虑售后业务语义和规则。
```

三者都可能用 Pydantic，但职责不同。命名不统一，是为了让边界更清楚。

### 开发步骤

1. 创建目录。
2. 创建空的 `__init__.py`。
3. 写 `pyproject.toml`。
4. 写基础 `Makefile`。
5. 写第一个 import smoke test。
6. 写 README 的项目目标。

从空目录开始时，先在 WSL 里执行这些命令：

```bash
cd ~/python
mkdir agent-1-after-sales
cd agent-1-after-sales

mkdir -p src/agent_1_after_sales/app_api/routers
mkdir -p src/agent_1_after_sales/app_api/schemas
mkdir -p src/agent_1_after_sales/app_api/services
mkdir -p src/agent_1_after_sales/agent_service/contracts
mkdir -p src/agent_1_after_sales/agent_service/infrastructure/runtime
mkdir -p src/agent_1_after_sales/agent_service/infrastructure/state_store
mkdir -p src/agent_1_after_sales/agent_service/llm
mkdir -p src/agent_1_after_sales/business_service/after_sales/domain
mkdir -p src/agent_1_after_sales/business_service/after_sales/application/services
mkdir -p src/agent_1_after_sales/business_service/after_sales/infrastructure/persistence/sqlalchemy
mkdir -p tests scripts docs migrations/versions

touch src/agent_1_after_sales/app_api/__init__.py
touch src/agent_1_after_sales/app_api/routers/__init__.py
touch src/agent_1_after_sales/app_api/schemas/__init__.py
touch src/agent_1_after_sales/agent_service/__init__.py
touch src/agent_1_after_sales/agent_service/contracts/__init__.py
touch src/agent_1_after_sales/business_service/__init__.py
touch src/agent_1_after_sales/business_service/after_sales/__init__.py
touch src/agent_1_after_sales/business_service/after_sales/domain/__init__.py
touch tests/__init__.py
touch tests/test_imports.py
```

这里也可以用 `uv init --package` 生成项目，但教学版建议先手写 `pyproject.toml`。原因是你需要看懂每个依赖、`src` layout、pytest 配置和打包配置分别解决什么问题。

下面这个 `pyproject.toml` 是第 1 阶段的轻量版，只够支撑 FastAPI、配置和测试起步。不要把它当成当前仓库的最终版。完整项目依赖会在第 12 章之后的“扩展 A：最终版依赖和质量工具”里对齐当前根目录 `pyproject.toml`。

### 示例代码

第 1 阶段 `pyproject.toml`：

```toml
[build-system]
# setuptools 负责把 src layout 下的 Python 包安装到虚拟环境。
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[project]
# pyproject 里的项目名使用 Python 包名风格，和 import 路径保持一致。
name = "agent_1_after_sales"
version = "0.1.0"
description = "Teaching-first agent backend built with FastAPI, LangChain, and LangGraph."
readme = "README.md"
requires-python = ">=3.12"
dependencies = [
    # Pydantic 负责 schema、配置和数据校验。
    "pydantic>=2,<3",
    "pydantic-settings>=2.0",
    # FastAPI 提供 HTTP API，uvicorn 是本地开发服务器。
    "fastapi>=0.115,<1",
    "uvicorn>=0.30,<1",
]

[project.optional-dependencies]
dev = [
    # pytest/httpx 支撑测试，ruff/mypy 支撑代码质量门槛。
    "pytest>=8,<9",
    "pytest-asyncio>=0.24,<1",
    "httpx>=0.27,<1",
    "ruff>=0.9,<1",
    "mypy>=1.11,<2",
]

[tool.setuptools]
# 告诉 setuptools：包代码不在根目录，而是在 src/ 下面。
package-dir = {"" = "src"}

[tool.setuptools.packages.find]
# 自动发现 src/ 下的 agent_1_after_sales 包。
where = ["src"]

[tool.pytest.ini_options]
# 让 pytest 能直接 import agent_1_after_sales，不需要手工设置 PYTHONPATH。
pythonpath = ["src"]
testpaths = ["tests"]
```

`Makefile`：

```makefile
# 默认使用 uv 创建的项目虚拟环境；也可以通过 PYTHON=... 临时覆盖。
PYTHON ?= .venv/bin/python
HOST ?= 127.0.0.1
PORT ?= 8000

.PHONY: start test

start:
	# --app-dir src 让 uvicorn 从 src/ 目录解析 Python 包。
	$(PYTHON) -m uvicorn agent_1_after_sales.app_api.main:create_app --factory --app-dir src --reload --host $(HOST) --port $(PORT)

test:
	# 统一从 tests/ 目录运行测试，保持本地和 CI 命令一致。
	$(PYTHON) -m pytest tests -q
```

第一个测试文件 `tests/test_imports.py`：

```python
"""
验证项目包可以被 pytest 正确导入。

这个文件解决的问题是：src layout、pyproject 和 pytest pythonpath 配置
如果有任何一处写错，最小导入测试会第一时间失败。
"""

from __future__ import annotations


def test_project_package_can_be_imported() -> None:
    # 这个测试验证 pyproject 的 src layout 和 pytest pythonpath 是否配置正确。
    import agent_1_after_sales

    assert agent_1_after_sales.__name__ == "agent_1_after_sales"
```

### 如何运行或验证

```bash
uv python pin 3.12
uv sync --extra dev
find src -maxdepth 3 -type d
uv run python -c "import agent_1_after_sales; print('imports ok')"
uv run pytest tests/test_imports.py -q
make test
```

如果你想确认 `uv` 当前使用的是项目虚拟环境：

```bash
uv run python -c "import sys; print(sys.executable)"
ls -la .venv
```

### 常见错误

- 忘记配置 `pythonpath = ["src"]`，测试里 import 失败。
- 目录建好了但没有 `__init__.py`，包导入不稳定。
- 把业务代码直接放进 `app_api`，后面 Agent 适配会变混乱。
- 手动创建文件时拼错目录名，例如 `app-api`、`business-services`。Python 包名建议使用下划线，不用短横线。

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
src/agent_1_after_sales/app_api/main.py
src/agent_1_after_sales/app_api/routers/__init__.py
src/agent_1_after_sales/app_api/routers/health.py
tests/test_health.py
```

### 推荐目录结构

```text
src/agent_1_after_sales/app_api/
  __init__.py
  main.py
  routers/
    __init__.py
    health.py
tests/
  test_health.py
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
4. 写 `tests/test_health.py`，不用启动真实端口也能测路由。
5. 用 uvicorn 启动。
6. 打开 `/docs` 和 `/health` 验证。

### 示例代码

`src/agent_1_after_sales/app_api/routers/health.py`：

```python
"""
健康检查路由。

这个文件解决的问题是：提供一个不依赖业务数据的最小探针，
让开发、测试和部署都能快速判断 FastAPI 服务是否存活。
"""

from __future__ import annotations

from fastapi import APIRouter

# router 是一组 API 的集合。
# tags 会显示在 Swagger UI 中，解决接口越来越多后文档难以按模块查找的问题。
router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> dict[str, str]:
    """
    最小健康检查接口。

    这个接口先验证 FastAPI 应用能启动、路由能注册、测试客户端能调用。
    后续章节会把数据库、LLM、MCP 的状态也接进来。

    这解决的问题是：开发或部署时需要一个最小探针判断服务是不是活着。
    没有 health 接口时，只能靠访问业务接口排查，问题会混在业务数据和服务状态里。
    """

    # MVP 阶段先只返回 ok，后续再接数据库、LLM、MCP 状态。
    return {"status": "ok"}
```

`src/agent_1_after_sales/app_api/main.py`：

```python
"""
FastAPI 应用工厂。

这个文件解决的问题是：集中创建 app、注册中间件和路由，
让测试可以直接调用 create_app()，不需要启动真实 uvicorn 进程。
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from agent_1_after_sales.app_api.routers.health import router as health_router


def create_app() -> FastAPI:
    """
    创建 FastAPI 应用实例。

    这里先只注册 CORS 和 health router，后续章节再逐步加入配置、lifespan 和业务路由。

    使用 factory 而不是全局 `app = FastAPI()`，解决测试时无法传入不同配置、
    fake dependency 或临时数据库的问题。
    """

    app = FastAPI(title="After-Sales Agent API", version="1.0.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # 教学起步阶段先放开跨域，解决前端本地调试被浏览器 CORS 拦截的问题。
        allow_methods=["*"],  # 允许常见 HTTP 方法，避免后续新增 POST/PUT 时又被 CORS 预检拦住。
        allow_headers=["*"],  # 允许前端携带 Content-Type、X-API-Key 等请求头。
    )
    # 把 health router 挂到 app 上，否则 /health 会返回 404。
    app.include_router(health_router)
    return app
```

`tests/test_health.py`：

```python
"""
健康检查接口测试。

这个文件解决的问题是：不用启动真实端口，也能验证 app factory、
router 注册和 /health 路径是否正常工作。
"""

from __future__ import annotations

import httpx
import pytest

from agent_1_after_sales.app_api.main import create_app


@pytest.mark.asyncio
async def test_health_returns_ok() -> None:
    # Arrange：用 factory 创建一个独立 app。
    # 这样测试不依赖全局 app，也不需要先启动 uvicorn。
    app = create_app()

    # Act：ASGITransport 直接调用 FastAPI app，不需要先启动 uvicorn。
    # 这解决的问题是：路由测试可以在进程内完成，速度更快，也不会占用真实端口。
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/health")

    # Assert：接口能访问，并且返回最小健康状态。
    # 如果这里失败，说明 app factory、router 注册或路径定义至少有一个环节出问题。
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
```

### 如何运行或验证

```bash
uv run pytest tests/test_health.py -q
uv run uvicorn agent_1_after_sales.app_api.main:create_app --factory --app-dir src --reload
curl http://127.0.0.1:8000/health
```

如果你使用 `Makefile`，也可以这样启动：

```bash
make start
```

另开一个 WSL 终端查看端口：

```bash
ss -ltnp | grep 8000 || true
curl -i http://127.0.0.1:8000/health
```

停止开发服务器时，在运行 uvicorn 的终端按 `Ctrl+C`。如果端口被旧进程占用，可以先查进程：

```bash
ps -ef | grep uvicorn
```

`--app-dir src` 必须保留。因为项目代码放在 `src/` 目录下，uvicorn 默认只从当前目录找包；没有 `--app-dir src` 时，`agent_1_after_sales.app_api.main:create_app` 可能 import 不到。

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
src/agent_1_after_sales/app_api/settings.py
src/agent_1_after_sales/app_api/main.py
.env.example
tests/test_settings.py
```

### 推荐目录结构

```text
src/agent_1_after_sales/app_api/
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

`src/agent_1_after_sales/app_api/settings.py`：

```python
"""
应用配置模型。

这个文件解决的问题是：把环境变量、.env、本地测试和生产校验集中管理，
避免配置读取逻辑散落在 route、service 和 runtime 里。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class MCPServerConfig(BaseModel):
    """
    单个 MCP server 的连接配置。

    MCP server 可能是 HTTP 服务，也可能是本地 stdio 进程。
    这里用一个模型统一描述，后续 registry 初始化时就不用到处解析字典。

    这解决的问题是：外部工具连接配置如果一直用 dict 传递，字段拼错、
    少填 url/command 这类问题会到运行时才暴露。用 Pydantic model 可以在启动阶段校验。
    """

    transport: Literal["http", "streamable_http", "stdio"]  # MCP 连接方式。解决不同 server 启动/连接方式不一致的问题。
    url: str | None = None  # HTTP / streamable_http server 的访问地址。HTTP 模式缺它就无法发起连接。
    command: str | None = None  # stdio server 的启动命令。stdio 模式缺它就无法拉起本地工具进程。
    args: list[str] = Field(default_factory=list)  # stdio command 的参数列表。用 default_factory 解决可变默认值共享的问题。
    headers: dict[str, str] = Field(default_factory=dict)  # HTTP 鉴权头。用 dict 承接不同 MCP server 的认证方式。

    # extra="forbid" 可以防止配置写错字段却静默通过。
    model_config = ConfigDict(extra="forbid")


class AppSettings(BaseSettings):
    """
    应用的集中配置模型。

    所有环境差异都应该收敛到这里，而不是散落在 route、service 或 runtime 里。
    BaseSettings 会自动从环境变量和 `.env` 读取同名字段。

    这解决的问题是：本地、测试、生产使用同一套代码，只通过环境变量切换行为。
    如果配置散落在代码各处，部署时很难确认到底哪些值生效，也容易把密钥写死。
    """

    app_env: str = "dev"  # 运行环境。解决测试、开发、生产需要不同校验强度的问题。
    cors_allowed_origins: str = ""  # 逗号分隔的前端域名列表。解决生产环境不能随便 `*` 放开跨域的问题。
    api_key: SecretStr | None = None  # API 鉴权密钥。SecretStr 解决日志/打印配置时泄露真实 key 的问题。

    business_database_url: str = "sqlite+pysqlite:///./after_sales_mvp.db"  # 售后业务库地址。
    agent_runtime_database_url: str | None = None  # LangGraph checkpoint / runtime 状态库地址。
    auto_create_schema: bool = False  # 本地教学可自动建表，生产应走 Alembic migration。

    llm_provider: str = "deepseek"  # 当前使用的模型供应商。
    llm_model: str = "deepseek-chat"  # 具体模型名。
    llm_timeout_seconds: float = Field(default=30.0, ge=0.1, le=300.0)  # 单次模型请求超时时间。
    llm_max_retries: int = Field(default=2, ge=0, le=10)  # 模型请求失败后的重试次数。
    deepseek_api_key: SecretStr | None = None  # DeepSeek API key。
    openai_api_key: SecretStr | None = None  # OpenAI API key。

    max_steps: int = Field(default=4, ge=1, le=50)  # Agent 每轮最多执行多少步，避免无限循环。
    approval_timeout_seconds: int = Field(default=900, ge=1)  # 人工审批等待超时时间。
    mcp_servers: dict[str, MCPServerConfig] = Field(default_factory=dict)  # MCP server 名称到配置的映射。

    # `.env` 只服务本地开发；生产环境更推荐由部署平台注入环境变量。
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    @property
    def is_test(self) -> bool:
        """
        判断当前是否是测试环境。

        测试环境允许缺少真实 LLM、真实 API key 和 durable runtime DB，
        这解决单元测试不应该依赖外部服务和真实密钥的问题。
        """

        return self.app_env.lower() == "test"

    @property
    def is_production(self) -> bool:
        """
        判断当前是否是生产环境。

        兼容 `prod` 和 `production` 两种常见写法，解决不同部署平台
        环境变量命名习惯不完全一致的问题。
        """

        return self.app_env.lower() in {"prod", "production"}

    @property
    def parsed_cors_allowed_origins(self) -> list[str]:
        """
        把环境变量中的 CORS 字符串转换成 FastAPI 需要的列表。

        环境变量更适合写字符串，例如 `https://a.com,https://b.com`。
        FastAPI middleware 需要 `list[str]`。这里集中转换，避免每次注册中间件时重复处理。
        """

        origins = [item.strip() for item in self.cors_allowed_origins.split(",") if item.strip()]
        return origins or (["*"] if not self.is_production else [])

    @model_validator(mode="after")
    def validate_runtime_requirements(self) -> "AppSettings":
        """
        在配置加载完成后做跨字段校验。

        单字段类型校验只能知道字段是不是字符串或数字，无法判断
        “transport=http 时必须有 url”这种组合规则。model_validator 解决的就是这类问题。
        """

        # MCP http server 必须有 url，stdio server 必须有 command。
        # 这解决外部工具配置错误到真正调用工具时才暴露的问题。
        for name, config in self.mcp_servers.items():
            if config.transport in {"http", "streamable_http"} and not config.url:
                raise ValueError(f"MCP server `{name}` requires `url`")
            if config.transport == "stdio" and not config.command:
                raise ValueError(f"MCP server `{name}` requires `command`")

        if not self.is_production:
            # 非生产环境先放宽要求，解决本地学习阶段没有真实密钥也能启动服务的问题。
            return self

        if self.api_key is None:
            raise ValueError("API_KEY is required when APP_ENV=production")
        if not self.parsed_cors_allowed_origins:
            raise ValueError("CORS_ALLOWED_ORIGINS is required when APP_ENV=production")
        if self.agent_runtime_database_url is None:
            raise ValueError("AGENT_RUNTIME_DATABASE_URL is required when APP_ENV=production")
        return self
```

`src/agent_1_after_sales/app_api/main.py`：

```python
"""
带配置注入能力的 FastAPI 应用工厂。

这个文件解决的问题是：测试可以显式传入 AppSettings，
真实运行时则从环境变量读取配置，二者复用同一个 create_app()。
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from agent_1_after_sales.app_api.routers.health import router as health_router
from agent_1_after_sales.app_api.settings import AppSettings


def create_app(settings: AppSettings | None = None) -> FastAPI:
    """
    创建 FastAPI 应用实例。

    参数 `settings` 允许测试传入隔离配置，例如临时 SQLite 路径或 test 环境。
    真实运行时不传参数，函数会自动从 `.env` 和环境变量读取配置。

    这解决的问题是：测试和生产可以复用同一个 app 创建逻辑。
    测试传入显式 settings，生产从环境读取 settings，不需要维护两套入口。
    """

    resolved_settings = settings or AppSettings()  # 测试可注入配置；真实运行时自动读环境变量。
    app = FastAPI(
        title="After-Sales Agent API",  # OpenAPI 文档标题，解决接口文档无法识别服务名称的问题。
        version="1.0.0",  # API 版本，方便前端和调用方判断契约版本。
    )
    # 把 settings 放到 app.state，后续 dependency、lifespan、router 都能读到同一份配置。
    app.state.settings = resolved_settings
    app.add_middleware(
        CORSMiddleware,
        allow_origins=resolved_settings.parsed_cors_allowed_origins,  # 从配置读取白名单，解决本地和生产跨域策略不同的问题。
        allow_methods=["*"],  # 允许常见 HTTP 方法，避免新增接口时忘记放行预检请求。
        allow_headers=["*"],  # 允许 Content-Type、Authorization、X-API-Key 等请求头。
    )
    app.include_router(health_router)
    return app
```

`tests/test_settings.py`：

```python
"""
应用配置测试。

这个文件解决的问题是：配置错误应该在启动阶段暴露，
尤其是生产 API key、CORS 和 MCP server 组合字段校验。
"""

from __future__ import annotations

import pytest

from agent_1_after_sales.app_api.settings import AppSettings


def test_settings_defaults_are_dev_friendly() -> None:
    # Arrange：test 环境不要求真实 API key 和生产级 CORS。
    settings = AppSettings(app_env="test")

    # Assert：默认值应适合本地开发和单元测试。
    assert settings.is_test is True
    assert settings.parsed_cors_allowed_origins == ["*"]
    assert settings.business_database_url.endswith("after_sales_mvp.db")


def test_production_requires_api_key() -> None:
    # 生产环境缺少 API_KEY 时必须启动失败。
    # 这解决的问题是：部署配置漏填时应该快速失败，而不是把无鉴权接口暴露到线上。
    with pytest.raises(Exception, match="API_KEY"):
        AppSettings(
            app_env="production",
            cors_allowed_origins="https://example.com",
            agent_runtime_database_url="postgresql://agent:agent@localhost:5432/agent",
            deepseek_api_key="fake-key",
        )


def test_mcp_http_server_requires_url() -> None:
    # HTTP MCP server 没有 url 时无法连接，应该在配置阶段提前报错。
    # 这解决的问题是：外部工具配置错误不应该等到用户请求触发工具时才暴露。
    with pytest.raises(Exception, match="requires `url`"):
        AppSettings(
            app_env="test",
            mcp_servers={"weather": {"transport": "http"}},
        )
```

### 如何运行或验证

```bash
cp .env.example .env
sed -n '1,120p' .env
uv run python -c "from agent_1_after_sales.app_api.settings import AppSettings; print(AppSettings().model_dump())"
uv run pytest tests/test_settings.py -q
```

如果只想临时覆盖某个配置，不需要改 `.env`，可以在命令前加环境变量：

```bash
APP_ENV=test LLM_PROVIDER=openai uv run python - <<'PY'
from agent_1_after_sales.app_api.settings import AppSettings

# 这里演示环境变量会覆盖 .env 中的同名配置。
settings = AppSettings()
print(settings.app_env)
print(settings.llm_provider)
PY
```

`.env.example` 是团队共享的模板，`.env` 是你本机真实配置。教学时先复制模板，是为了让你知道项目需要哪些配置；运行时读取的是 `.env` 和当前 shell 环境变量。

### 常见错误

- `.env` 里写 `llm_provider=deepseek` 但配置字段是大写也没关系，Pydantic 会按字段名匹配环境变量。
- `MCP_SERVERS` 不是合法 JSON，会导致启动时解析失败。
- 生产环境缺少 `API_KEY` 应该主动报错，不要等线上出问题。
- 改了 `.env` 但服务没变化：开发服务器通常需要重启，或者确认你是在项目根目录运行命令。
- 在 shell 里设置了同名环境变量：shell 环境变量优先级通常高于 `.env`，可以用 `env | grep LLM_PROVIDER` 检查。

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
src/agent_1_after_sales/app_api/schemas/runs.py
src/agent_1_after_sales/app_api/schemas/actions.py
src/agent_1_after_sales/app_api/schemas/agents.py
src/agent_1_after_sales/agent_service/contracts/models.py
src/agent_1_after_sales/business_service/after_sales/domain/entities.py
tests/test_schemas.py
```

### 推荐目录结构

```text
src/agent_1_after_sales/app_api/schemas/
  runs.py
  actions.py
  agents.py
src/agent_1_after_sales/agent_service/contracts/
  models.py
src/agent_1_after_sales/business_service/after_sales/domain/
  entities.py
tests/
  test_schemas.py
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
6. 写 schema 校验测试，覆盖合法输入和非法输入。

### 示例代码

`src/agent_1_after_sales/agent_service/contracts/models.py`：

```python
"""
Agent runtime 内部契约模型。

这个文件解决的问题是：用统一模型表达 run 状态、错误、待审批动作和操作人上下文，
避免 HTTP 层、SSE 层、审计日志和 runtime 各自定义一套字段。
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

type RunStatus = Literal["completed", "awaiting_action", "failed"]
type RiskLevel = Literal["low", "medium", "high"]


class ActorContext(BaseModel):
    """
    当前操作人的上下文。

    Agent runtime、审批记录和审计日志都需要知道“谁触发了这次动作”。
    这里放在 contracts 里，表示它是内部运行契约，不是某个 HTTP 接口独有的字段。

    这解决的问题是：HTTP、SSE、审计日志、工具调用都可以使用同一种 actor 表达，
    避免每层都自己定义一套 `user_id`、`operator_id`、`metadata`。
    """

    actor_id: str | None = None  # 当前操作人，可以是客服、主管或系统。
    metadata: dict[str, Any] = Field(default_factory=dict)  # 业务侧额外身份信息，例如部门、角色、租户。


class AgentPendingAction(BaseModel):
    """
    Agent 暂停后等待人工处理的动作。

    典型场景是退款金额较高，需要主管点击批准或拒绝后再恢复同一个 run。

    这解决的问题是：Agent 不能在高风险动作上“自己决定自己执行”。
    runtime 可以把待审批动作结构化返回给前端，前端再让人工处理。
    """

    action_id: str  # 本次待处理动作的唯一编号。
    action_name: str  # 工具或动作名称，例如 submit_refund_request。
    action_payload: dict[str, Any] = Field(default_factory=dict)  # 触发动作时的原始参数。
    reason: str  # 为什么需要人工处理。
    risk_level: RiskLevel = "low"  # 风险等级，用于前端展示和审批优先级。
    display_payload: dict[str, Any] = Field(default_factory=dict)  # 给人工审批界面看的精简信息。


class AgentError(BaseModel):
    """
    Agent 执行失败时对外返回的结构化错误。

    不直接返回 Python exception，是为了让 HTTP API、SSE、前端和日志
    都能用统一结构识别失败原因。
    """

    code: str  # 机器可识别的错误码。
    message: str  # 给调用方或前端展示的错误说明。


class AgentRunResult(BaseModel):
    """
    一次 Agent run 的最终结果。

    它是 runtime 层的内部结果模型。HTTP route 会把它转换成 RunResponse，
    这样 Agent runtime 不需要知道 FastAPI response schema。
    """

    run_id: str  # 一次执行的唯一编号。
    session_id: str  # 对话会话编号，同一个会话可以有多次 run。
    capability_id: str  # 使用的是哪个 Agent 能力，例如 after_sales_assistant。
    status: RunStatus  # completed / awaiting_action / failed。
    output: str | None = None  # 完成时返回给用户的文本。
    pending_action: AgentPendingAction | None = None  # 需要人工处理时的挂起动作。
    error: AgentError | None = None  # 失败时的错误详情。
```

`src/agent_1_after_sales/app_api/schemas/runs.py`：

```python
"""
Agent run 的 HTTP 请求和响应 schema。

这个文件解决的问题是：公开 API 入参保持简单扁平，
内部 runtime 结果再在 route 层转换成稳定的 HTTP 响应契约。
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from agent_1_after_sales.agent_service.contracts.models import AgentError, AgentPendingAction, RunStatus


class CreateRunRequest(BaseModel):
    """
    创建 Agent run 的 HTTP 请求体。

    注意这里没有直接复用 ActorContext，因为 HTTP 入参要尽量扁平，
    route 层再把 actor_id / actor_metadata 组装成内部 ActorContext。

    这解决的问题是：API 入参对调用方保持简单，而内部 runtime 仍然能使用
    更明确的 ActorContext 契约。
    """

    message: str = Field(min_length=1, max_length=4000)  # 用户消息。min/max 解决空请求和超长输入拖垮模型的问题。
    session_id: str | None = None  # 会话编号。不传时后端创建新会话，解决首次对话没有上下文 id 的问题。
    actor_id: str | None = None  # 当前操作人 id。
    actor_metadata: dict[str, Any] = Field(default_factory=dict)  # 当前操作人的补充信息。


class RunResponse(BaseModel):
    """
    创建 run 后返回给 HTTP 客户端的响应体。

    它和 AgentRunResult 字段很像，但职责不同：RunResponse 是公开 HTTP 契约，
    AgentRunResult 是内部 runtime 契约。两者分开可以避免内部实现直接绑死 API。
    """

    run_id: str  # 本次执行编号。
    session_id: str  # 所属会话编号。
    status: RunStatus  # 当前执行状态。
    output: str | None = None  # 已完成时的最终回答。
    pending_action: AgentPendingAction | None = None  # 等待审批时的动作信息。
    error: AgentError | None = None  # 失败时的错误信息。
```

`src/agent_1_after_sales/app_api/schemas/actions.py`：

```python
"""
人工审批动作的 HTTP schema。

这个文件解决的问题是：把“批准/拒绝哪个 run 的哪个 action”结构化，
避免审批接口接收任意 dict 后再到业务深处才发现字段错误。
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class ActionRequest(BaseModel):
    """
    人工审批或拒绝 pending action 的 HTTP 请求体。

    它只表达“谁对哪个 run 的哪个 action 做了什么决定”。
    真正恢复 Agent 执行的逻辑在 route/service/runtime 里完成。
    """

    run_id: str = Field(min_length=1)  # 定位哪一次 Agent 执行。
    action_id: str = Field(min_length=1)  # 定位 run 中的哪一个待审批动作。
    decision: Literal["approved", "rejected"]  # 人工决策，只允许批准或拒绝。
    actor_id: str | None = None  # 审批人 id。
    actor_metadata: dict[str, Any] = Field(default_factory=dict)  # 审批人的补充信息。
```

`src/agent_1_after_sales/app_api/schemas/agents.py`：

```python
"""
Agent catalog 的 HTTP schema。

这个文件解决的问题是：前端和外部调用方可以通过稳定响应了解 agent 和工具目录，
而不是直接依赖 Python 内部的 AgentDefinition 或 ToolSpec。
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class AgentSummary(BaseModel):
    """
    Agent catalog 的摘要响应。

    第 10 章会用它实现 `/api/agents`。
    这里先把 schema 建出来，解决后面 router 里 response_model 没有定义的问题。
    """

    capability_id: str  # Agent 能力 id，例如 after_sales_assistant。
    name: str | None = None  # 展示名，允许为空是为了支持早期只有技术 id 的能力。
    description: str | None = None  # 能力说明，供前端或调用方展示。


class ToolSummary(BaseModel):
    """
    Agent 工具摘要响应。

    第 10 章会用它实现 `/api/agents/{capability_id}/tools`。
    它解决的问题是：API 返回稳定的工具摘要，而不是直接暴露 Python ToolSpec 对象。
    """

    name: str  # 工具名。
    description: str  # 工具说明。
    args_schema: dict[str, Any] = Field(default_factory=dict)  # 工具参数 JSON Schema。
    requires_approval: bool = False  # 是否可能触发人工审批。
```

### 如何运行或验证

```bash
uv run python - <<'PY'
from agent_1_after_sales.app_api.schemas.runs import CreateRunRequest

# 这个命令只验证 schema，不需要启动后端服务。
payload = CreateRunRequest(message="查一下订单 ORD123")
print(payload.model_dump())
PY
```

验证错误输入：

```bash
uv run python - <<'PY'
from pydantic import ValidationError
from agent_1_after_sales.app_api.schemas.runs import CreateRunRequest

# 空 message 应该触发 Pydantic 校验错误。
try:
    CreateRunRequest(message="")
except ValidationError as exc:
    print(exc.errors()[0]["msg"])
PY
```

把下面内容保存为 `tests/test_schemas.py`：

```python
"""
HTTP schema 单元测试。

这个文件解决的问题是：请求模型的默认值、必填字段和枚举限制可以独立验证，
不需要启动 FastAPI 或 Agent runtime。
"""

from __future__ import annotations

import pytest

from agent_1_after_sales.app_api.schemas.actions import ActionRequest
from agent_1_after_sales.app_api.schemas.runs import CreateRunRequest


def test_create_run_request_accepts_minimal_message() -> None:
    # Arrange + Act：只传 message 是最小合法请求，session 和 actor 可以由后端补齐。
    # 这解决的问题是：客户端首次调用时不必先创建 session 或用户上下文。
    payload = CreateRunRequest(message="查一下订单 ORD123")

    # Assert：默认 metadata 必须是独立空 dict，不能是所有实例共享的可变默认值。
    assert payload.message == "查一下订单 ORD123"
    assert payload.actor_metadata == {}


def test_create_run_request_rejects_empty_message() -> None:
    # Pydantic 会根据 Field(min_length=1) 自动校验。
    # 这解决的问题是：空请求不应该进入 Agent runtime 浪费模型调用。
    with pytest.raises(Exception):
        CreateRunRequest(message="")


def test_action_request_rejects_unknown_decision() -> None:
    # decision 被 Literal 限定，防止前端传入 skip、cancel 等未定义语义。
    with pytest.raises(Exception):
        ActionRequest(run_id="run-1", action_id="act-1", decision="skip")
```

执行测试：

```bash
uv run pytest tests/test_schemas.py -q
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
src/agent_1_after_sales/business_service/after_sales/domain/entities.py
src/agent_1_after_sales/business_service/after_sales/infrastructure/persistence/sqlalchemy/session.py
src/agent_1_after_sales/business_service/after_sales/infrastructure/persistence/sqlalchemy/models.py
tests/test_business_schema.py
```

### 推荐目录结构

```text
src/agent_1_after_sales/business_service/after_sales/
  domain/
    __init__.py
    entities.py
  infrastructure/
    persistence/
      sqlalchemy/
        __init__.py
        session.py
        models.py
tests/
  test_business_schema.py
```

### 关键概念讲解

领域模型：业务层用来表达业务对象的数据结构。

ORM model：数据库表对应的 Python 类。

Pydantic `from_attributes=True`：允许从 SQLAlchemy 对象转换成 Pydantic read model。

业务数据库：保存订单、物流、工单、退款、审批、审计日志。它和 LangGraph checkpoint 不是同一类状态。

### 开发步骤

1. 安装本章需要的数据库依赖：`sqlalchemy` 和 `aiosqlite`。
2. 定义 `DomainModel` 基类。
3. 定义后续章节会用到的领域模型：`OrderRead`、`ShipmentRead`、`TicketCreate`、`TicketRead`、`RefundRequestCreate`、`RefundRequestRead`、`RefundApprovalRequirement` 和查询输入模型。
4. 创建 SQLAlchemy `Base` 和 `BusinessDatabase`。
5. 定义 `Customer`、`Order`、`Shipment`、`Ticket`、`RefundRequest`、`PolicyArticle`。
6. 定义审批和审计相关表。
7. 写数据库 schema 测试，用 `tmp_path` 创建临时 SQLite 文件。

先安装依赖。否则写到 `session.py` 时，下面这些 import 会直接失败：

```python
from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase
```

执行：

```bash
uv add sqlalchemy aiosqlite
```

`sqlalchemy` 是 ORM 和 engine/session 的核心库。`aiosqlite` 是 SQLite 的异步驱动，因为 FastAPI route 和测试会使用 `AsyncSession`。

### 示例代码

`entities.py`：

```python
"""
售后业务领域模型。

这个文件解决的问题是：用 Pydantic 定义业务层稳定的数据结构，
让 service、repository、HTTP API 和 Agent 工具都围绕明确的业务对象协作。
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

type ApprovalRiskLevel = Literal["low", "medium", "high"]


class DomainModel(BaseModel):
    """
    领域实体的基础模型。

    `from_attributes=True` 用来支持从 ORM 对象创建领域模型。例如从
    SQLAlchemy 查询出来的是 `ticket_orm.id`、`ticket_orm.status` 这种
    对象属性，而不是 `{"id": "...", "status": "..."}` 这种字典。
    开启后可以直接使用 `Ticket.model_validate(ticket_orm)` 做转换。

    `populate_by_name=True` 用来支持字段别名。例如字段定义为
    `ticket_id: str = Field(alias="ticketId")` 时，既可以传
    `ticketId="T001"`，也可以传 `ticket_id="T001"`。
    """

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class CustomerRead(DomainModel):
    """
    客户读取模型，用于对外返回客户基础信息。

    它解决的问题是：接口和业务 service 不直接返回 Customer ORM 对象，
    避免数据库关系、懒加载状态和内部字段泄漏到 API 层。
    """

    customer_id: str  # 客户编号。
    name: str  # 客户姓名。
    email: str  # 客户邮箱。
    phone: str  # 客户手机号。
    created_at: datetime  # 客户创建时间。


class OrderRead(DomainModel):
    """
    订单读取模型，不是数据库 ORM 类。

    它用于承接订单查询结果，并对业务层或接口层输出订单数据。
    因为继承了 `DomainModel`，所以可以直接从 SQLAlchemy 查询出的
    ORM 对象生成。

    如果没有 `from_attributes=True`，通常需要手动从 ORM 对象取值：
    `OrderRead(order_id=order_orm.order_id, status=order_orm.status, ...)`。

    有了 `from_attributes=True`，Pydantic 会自动读取
    `order_orm.order_id`、`order_orm.status` 这类对象属性，因此可以直接写：
    `OrderRead.model_validate(order_orm)`。
    """

    order_id: str  # 订单编号。HTTP API 默认返回 order_id，和后续测试断言保持一致。
    customer_id: str  # 客户编号，用来标识下单用户。
    status: str  # 订单状态，例如已支付、已发货、已完成、已取消。
    total_amount: Decimal  # 订单总金额，使用 Decimal 避免金额计算精度问题。
    currency: str  # 订单金额的币种，例如 CNY、USD。
    item_summary: str  # 订单商品摘要，例如商品名称、数量或组合描述。
    created_at: datetime  # 订单创建时间。


class ShipmentRead(DomainModel):
    """
    物流读取模型，用来返回订单对应的发货和轨迹信息。

    它解决的问题是：接口层不直接返回 ORM 对象，而是返回一个稳定的读取模型。
    后续 ORM 字段、数据库关系怎么调整，不必直接影响 API 输出契约。
    """

    shipment_id: str  # 物流记录编号，用来唯一标识一次发货。
    order_id: str  # 关联的订单编号。
    carrier: str  # 承运商名称，例如顺丰、京东物流、DHL。
    tracking_no: str  # 物流单号。
    status: str  # 物流状态，例如运输中、已签收、异常。
    latest_location: str | None = None  # 最新物流位置，没有物流更新时可以为空。
    events_json: list[dict[str, Any]] = Field(default_factory=list)  # 物流轨迹事件列表。
    updated_at: datetime  # 物流信息最后更新时间。


class TicketCreate(BaseModel):
    """
    创建售后工单时需要的业务输入。

    它解决的问题是：创建工单只需要用户提交的输入字段，不应该要求调用方
    传 `ticket_id`、`status`、`created_at` 这种由后端生成或维护的字段。
    """

    order_id: str  # 需要创建售后工单的订单编号。
    issue_type: Literal["damaged", "return", "exchange", "other"]  # 售后问题类型。
    summary: str  # 售后问题描述摘要。
    priority: Literal["low", "normal", "high"] = "normal"  # 工单优先级，默认普通。


class TicketRead(DomainModel):
    """
    售后工单读取模型。

    第 6 章的 Repository 和 Unit of Work 会返回 `TicketRead`。
    如果这里不先定义，后面的 `ports.py` 就会凭空 import 一个不存在的类型。

    它解决的问题是：创建工单的输入模型和读取工单的输出模型要分开。
    输入模型没有 `ticket_id`、`status`、`created_at`，这些字段由后端生成和维护。
    """

    ticket_id: str  # 工单编号，由后端生成。
    order_id: str  # 工单关联的订单编号。
    customer_id: str  # 工单关联的客户编号。
    issue_type: str  # 售后问题类型。
    summary: str  # 问题摘要。
    priority: str  # 工单优先级。
    status: str  # 工单状态，例如 open、closed。
    created_at: datetime  # 工单创建时间。
    updated_at: datetime  # 工单最后更新时间。


class RefundRequestCreate(BaseModel):
    """
    提交退款申请时需要的业务输入。

    它解决的问题是：退款申请进入业务层前先有结构化校验，金额使用 Decimal，
    避免 float 精度误差影响财务相关判断。
    """

    order_id: str  # 申请退款的订单编号。
    amount: Decimal  # 退款金额，使用 Decimal 避免金额计算精度问题。
    reason: str  # 退款原因。
    requires_approval: bool = False  # 是否需要人工审批，默认不需要。


class RefundRequestRead(DomainModel):
    """
    退款申请读取模型。

    它解决的问题是：退款申请提交后，需要把后端生成的退款申请编号、状态、
    创建时间和更新时间返回给调用方，而这些字段不应该由创建请求传入。
    """

    refund_request_id: str  # 退款申请编号，由后端生成。
    order_id: str  # 关联订单编号。
    amount: Decimal  # 退款金额。
    reason: str  # 退款原因。
    status: str  # 退款状态，例如 pending、approved、rejected。
    requires_approval: bool  # 是否需要人工审批。
    created_at: datetime  # 创建时间。
    updated_at: datetime  # 更新时间。


class RefundApprovalRequirement(BaseModel):
    """
    退款审批要求模型。

    第 10 章的 Agent definition 会把业务层审批要求转换成 Agent runtime 的
    `ApprovalRequirement`。这里先定义业务层自己的审批结果，避免把 Agent
    runtime 的类型泄漏进 business_service。

    它解决的问题是：业务层负责判断退款是否需要审批，Agent 层只负责暂停和恢复执行。
    """

    reason: str  # 需要审批的原因。
    risk_level: ApprovalRiskLevel = "low"  # 风险等级。
    display_payload: dict[str, Any] = Field(default_factory=dict)  # 给审批界面展示的关键信息。


class PolicyArticleRead(DomainModel):
    """
    售后政策读取模型。

    当前项目的政策查询是结构化数据库查询，不是 RAG 知识库。
    这个模型解决的是政策内容如何从业务层稳定输出的问题。
    """

    article_id: str  # 政策文章编号。
    title: str  # 政策标题。
    category: str  # 政策分类。
    keywords: list[str] = Field(default_factory=list)  # 检索关键词。
    content: str  # 政策正文。
    created_at: datetime  # 创建时间。


class AuditLogRead(DomainModel):
    """
    审计日志读取模型。

    它解决的问题是：工具调用、审批、退款等关键事件需要可查询、可追踪，
    但 API 不应该直接暴露 AuditLog ORM 对象。
    """

    id: int  # 审计日志自增编号。
    conversation_id: str | None = None  # 关联会话或执行上下文。
    event_type: str  # 事件类型。
    payload_json: dict[str, Any] = Field(default_factory=dict)  # 事件内容。
    created_at: datetime  # 记录时间。


class OrderLookupInput(BaseModel):
    """
    订单查询工具的输入模型。

    第 10 章的 Agent 工具会使用它校验 LLM 生成的查单参数。
    这解决的问题是：工具 handler 不直接信任模型生成的原始 dict。
    """

    order_id: str  # 要查询的订单编号。


class PolicySearchInput(BaseModel):
    """
    售后政策查询工具的输入模型。

    它解决的问题是：政策查询参数先被结构化，避免工具层收到没有 query 的任意 dict。
    """

    query: str  # 用户要查询的政策关键词或问题。


class TicketLookupInput(BaseModel):
    """
    工单查询工具的输入模型。

    它解决的问题是：查询工单时只允许传入明确的 ticket_id，
    不让工具 handler 自己从任意文本里猜字段。
    """

    ticket_id: str  # 要查询的工单编号。
```

`session.py`：

```python
"""
这个文件是售后业务数据库的 SQLAlchemy 基础设施入口，不负责具体业务查询。

它主要负责三件事：
1. 定义 `Base`，让所有 ORM 模型能注册到同一份 `Base.metadata`。
2. 创建同步 engine 和异步 engine，统一管理数据库连接入口。
3. 提供 `managed_session()`，让 repository / Unit of Work 使用同一个
   AsyncSession 完成一次业务流程里的数据库读写。

具体查订单、创建工单这类业务读写放在 repository 里；
commit / rollback 这类事务最终确认，应该由 Unit of Work 或 service 层统一决定。

这里的 session 不是用户登录 session，而是数据库会话 / 事务上下文。

一次业务操作通常会拿到一个 AsyncSession：
repository 在这个 session 里执行 query、add、flush、refresh；
在 commit 之前，写入只是在当前事务里可见；
commit 后才最终提交，rollback 则可以撤销当前事务里的改动。
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from importlib import import_module

from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """
    所有 SQLAlchemy ORM 模型的基类。

    后面 `models.py` 里的 `Customer`、`Order`、`Ticket` 等 ORM 类都会继承它。
    SQLAlchemy 会把这些表模型注册到 `Base.metadata` 里。

    这解决的问题是：建表、迁移、检查表结构时，不需要手动维护一份表清单。
    只要 ORM 模型被 import，`Base.metadata` 就能知道当前项目有哪些表。
    """

    pass


def _async_database_url(database_url: str) -> str:
    """
    把同步数据库连接地址转换成异步连接地址。

    SQLAlchemy 的同步 engine 和异步 engine 使用不同的数据库驱动。
    例如 SQLite 的同步驱动是 `pysqlite`，异步驱动是 `aiosqlite`。
    这里把 `sqlite+pysqlite://` 转成 `sqlite+aiosqlite://`，这样
    `create_async_engine()` 才能创建异步 engine。

    这解决的问题是：配置文件里通常只想维护一个业务数据库地址，
    但项目运行时既需要同步 engine，也需要异步 engine。通过这个函数，
    外部只传一个 `database_url`，内部自动选择适合异步访问的驱动。

    如果不做转换，直接把 `sqlite+pysqlite://...` 传给 `create_async_engine()`，
    SQLAlchemy 会发现驱动不是异步驱动，后续 `await session.execute(...)`
    就无法正常工作。
    """

    if database_url.startswith("sqlite+pysqlite://"):
        return database_url.replace("sqlite+pysqlite://", "sqlite+aiosqlite://", 1)
    return database_url


class BusinessDatabase:
    """
    售后业务数据库入口。

    这个类统一管理 SQLAlchemy 的 engine 和 session：

    1. `sync_engine` 是同步 engine，适合做迁移、检查等同步场景。
    2. `async_engine` 是异步 engine，适合 FastAPI 等异步接口里执行数据库操作。
    3. `_session_factory` 是异步 session 工厂，每次业务请求都从这里创建
       一个独立的 `AsyncSession`。

    这样做解决两个问题：

    1. 数据库连接创建逻辑集中在一个地方，业务代码不用到处手动创建 engine。
    2. session 生命周期可控，避免连接忘记关闭、事务边界混乱等问题。

    后续 route、repository、Unit of Work 都不直接创建 engine。
    它们只从这个类拿 session 或 session factory。
    这样数据库访问入口是单一的，排查连接、事务、驱动问题时只需要看这里。
    """

    def __init__(self, database_url: str) -> None:
        self.database_url = database_url  # 保存原始数据库地址，方便日志、healthcheck 和排错时确认当前连的是哪个库。

        self.sync_engine = create_engine(
            database_url,  # 同步数据库地址。解决 Alembic、inspect、脚本检查这类同步场景仍然需要同步 engine 的问题。
            future=True,  # 启用 SQLAlchemy 2.x 风格 API。解决旧版 API 隐式行为多、教程和未来升级口径不一致的问题。
        )

        self.async_engine = create_async_engine(
            _async_database_url(database_url),  # 异步数据库地址。解决 FastAPI async route 中不能用同步驱动阻塞事件循环的问题。
            future=True,  # 让 async engine 也使用 SQLAlchemy 2.x 风格 API，解决同步/异步两套 engine 行为不一致的问题。
        )

        # 异步 session 工厂：后续业务代码通过它创建 AsyncSession，而不是到处手动 new session。
        # 这解决的问题是：session 创建参数集中管理，后续要调整事务行为时不用全项目搜索修改。
        self._session_factory = async_sessionmaker(
            bind=self.async_engine,  # 绑定异步 engine。解决 session 不知道该从哪个连接池取连接的问题。
            class_=AsyncSession,  # 指定创建 AsyncSession。解决 async 函数里误用同步 Session 导致事件循环被阻塞的问题。
            autoflush=False,  # 关闭查询前自动 flush。解决“只是查询却把半成品对象写进事务”的隐式副作用。
            expire_on_commit=False,  # commit 后保留字段值。解决提交后再读取对象属性时触发额外 SQL 或懒加载失败的问题。
        )

    async def create_schema(self) -> None:
        """
        根据 ORM 模型创建数据库表结构。

        `Base.metadata.create_all()` 是 SQLAlchemy 的同步 API，用来读取所有
        继承 `Base` 的 ORM 模型，并在数据库中创建还不存在的表。

        当前使用的是异步 engine，不能直接调用同步的 `create_all()`。
        所以这里先通过 `async_engine.begin()` 打开一个异步连接和事务，
        再使用 `connection.run_sync(...)` 把同步的建表函数放到这个异步连接
        里执行。

        这种写法解决的问题是：

        1. 项目主流程使用异步数据库访问。
        2. SQLAlchemy 建表 API 仍然是同步函数。
        3. `run_sync()` 负责把同步建表逻辑桥接到异步连接上。

        注意：这适合教学、测试和本地 MVP 快速建表。真实项目的表结构演进
        应该交给 Alembic migration，否则多人协作和生产数据库版本会失控。
        """

        # 导入 ORM 模型模块，确保所有继承 Base 的模型类都完成注册。
        # 如果不导入，Base.metadata 可能不知道有哪些表需要创建。
        import_module(
            "agent_1_after_sales.business_service.after_sales.infrastructure.persistence.sqlalchemy.models"
        )

        # begin() 会创建连接并开启事务；代码块结束后自动提交或回滚并释放连接。
        # 这解决的问题是：建表过程如果中途失败，事务可以回滚，连接也不会泄漏。
        async with self.async_engine.begin() as connection:
            # create_all 是同步函数；run_sync 让它在当前异步连接上安全执行。
            await connection.run_sync(Base.metadata.create_all)

    @asynccontextmanager
    async def managed_session(self) -> AsyncGenerator[AsyncSession, None]:
        """
        创建一个受上下文管理的异步数据库 session。

        用法示例：

        async with database.managed_session() as session:
            result = await session.execute(statement)

        `@asynccontextmanager` 让这个方法可以被 `async with` 使用。
        进入 `async with` 时创建 `AsyncSession`，`yield session` 把 session
        交给业务代码使用；退出 `async with` 时，SQLAlchemy 会自动关闭 session，
        释放数据库连接。

        这种写法解决的问题是：

        1. 业务代码不需要手动 close session，减少连接泄漏。
        2. 每次请求拿到独立 session，避免不同请求共用同一个事务上下文。
        3. 后续 Unit of Work 可以直接复用这个方法，把事务边界收敛到 service 层。
        """

        # 每次进入上下文都创建一个新的 AsyncSession。
        async with self._session_factory() as session:
            # yield 前是资源创建；yield 后由 async with 负责资源清理。
            yield session

    async def dispose(self) -> None:
        """
        释放数据库 engine 持有的连接池资源。

        应用关闭时调用，避免数据库连接池继续占用连接。

        如果不释放，测试进程或开发服务器反复启动时，可能留下未关闭连接，
        轻则出现资源泄漏警告，重则数据库连接数被耗尽。
        """

        await self.async_engine.dispose()
        self.sync_engine.dispose()
```

`models.py`：

```python
"""
这个文件定义 SQLAlchemy ORM 模型，也就是 Python 类和数据库表之间的映射。

这里的类关注的是“数据怎么存”：
1. 表名是什么，例如 `orders`、`tickets`。
2. 主键、外键、字段类型、是否允许为空是什么。
3. 表和表之间的 relationship 怎么关联。

所以这里的 `Order`、`Ticket` 是数据库模型，不是 API schema，
也不是纯业务层的 domain/entity 对象。

ORM 模型的字段不一定必须和 domain/entities 完全一样。

ORM 模型以数据库存储为准，可能包含外键、关系对象、审计字段、内部字段；
domain/entities 以业务层或接口层需要的稳定数据结构为准，可能只暴露其中一部分字段，
也可能把多个 ORM 字段合并、改名或计算成一个业务字段。

Repository 负责在这两者之间做转换：
数据库查询得到 ORM 对象，然后 repository 把 ORM 对象映射成
domain/entities 里的读取模型再返回给 service 或 API。
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from agent_1_after_sales.business_service.after_sales.infrastructure.persistence.sqlalchemy.session import Base


def utcnow() -> datetime:
    """
    返回带 UTC 时区的当前时间。

    数据库存时间不要用本地时区，否则部署到不同机器后排序和排查问题都会变乱。

    这解决的问题是：本地开发、服务器、数据库可能处在不同时区。
    统一使用 UTC 可以让审计日志、审批记录、物流更新时间的排序语义一致。
    """

    return datetime.now(UTC)


class Customer(Base):
    """
    客户表。

    客户是订单和工单的归属主体。售后系统里查单、建工单、退款审批
    往往都需要知道对应客户是谁。

    这解决的问题是：订单、工单不能只存一堆孤立字段。
    通过客户表和外键关系，可以从客户维度查看订单和售后历史。
    """

    __tablename__ = "customers"

    customer_id: Mapped[str] = mapped_column(String(32), primary_key=True)  # 客户编号。
    name: Mapped[str] = mapped_column(String(120), nullable=False)  # 客户姓名。
    email: Mapped[str] = mapped_column(String(255), nullable=False)  # 邮箱，用于通知或检索。
    phone: Mapped[str] = mapped_column(String(32), nullable=False)  # 手机号，用于售后联系。
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)  # 创建时间。

    orders: Mapped[list[Order]] = relationship(back_populates="customer")  # 该客户的订单列表。
    tickets: Mapped[list[Ticket]] = relationship(back_populates="customer")  # 该客户的售后工单列表。


class Order(Base):
    """
    订单表，售后能力的核心业务对象。

    Agent 查单、退款、工单、物流查询都围绕订单展开。
    独立建订单表解决的问题是：售后动作可以通过 order_id 找到金额、客户、
    商品摘要和订单状态，而不是让每个业务表重复存一遍订单信息。
    """

    __tablename__ = "orders"

    order_id: Mapped[str] = mapped_column(String(32), primary_key=True)  # 订单编号。
    customer_id: Mapped[str] = mapped_column(ForeignKey("customers.customer_id"), nullable=False)  # 所属客户。
    status: Mapped[str] = mapped_column(String(32), nullable=False)  # 订单状态，例如 paid、shipped、completed。
    total_amount: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)  # 订单金额。
    currency: Mapped[str] = mapped_column(String(8), nullable=False, default="CNY")  # 币种。
    item_summary: Mapped[str] = mapped_column(Text, nullable=False)  # 商品摘要。
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)  # 下单时间。

    customer: Mapped[Customer] = relationship(back_populates="orders")  # 订单所属客户。
    shipment: Mapped[Shipment | None] = relationship(back_populates="order", uselist=False)  # 一单一条物流。
    tickets: Mapped[list[Ticket]] = relationship(back_populates="order")  # 订单关联的售后工单。
    refund_requests: Mapped[list[RefundRequest]] = relationship(back_populates="order")  # 订单关联的退款申请。


class Shipment(Base):
    """
    物流表，保存订单发货状态和轨迹。

    它解决的问题是：物流状态变化频繁，不能塞进订单表里的一个简单字段。
    独立建表后，可以记录承运商、单号、轨迹事件和预计送达时间。
    """

    __tablename__ = "shipments"

    shipment_id: Mapped[str] = mapped_column(String(32), primary_key=True)  # 物流记录编号。
    order_id: Mapped[str] = mapped_column(ForeignKey("orders.order_id"), nullable=False, unique=True)  # 关联订单。
    carrier: Mapped[str] = mapped_column(String(64), nullable=False)  # 承运商。
    tracking_no: Mapped[str] = mapped_column(String(64), nullable=False)  # 物流单号。
    status: Mapped[str] = mapped_column(String(32), nullable=False)  # 物流状态。
    latest_location: Mapped[str | None] = mapped_column(String(255))  # 最新位置，可能为空。
    estimated_delivery_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # 预计送达时间。
    events_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)  # 物流轨迹事件。
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)  # 最后更新时间。

    order: Mapped[Order] = relationship(back_populates="shipment")  # 物流所属订单。


class Ticket(Base):
    """
    售后工单表，保存破损、退货、换货等人工处理事项。

    它解决的问题是：不是所有售后问题都能由 Agent 自动闭环。
    需要人工跟进的问题会沉淀成工单，保留优先级、状态和更新时间。
    """

    __tablename__ = "tickets"

    ticket_id: Mapped[str] = mapped_column(String(32), primary_key=True)  # 工单编号。
    order_id: Mapped[str] = mapped_column(ForeignKey("orders.order_id"), nullable=False)  # 关联订单。
    customer_id: Mapped[str] = mapped_column(ForeignKey("customers.customer_id"), nullable=False)  # 关联客户。
    issue_type: Mapped[str] = mapped_column(String(32), nullable=False)  # 问题类型。
    summary: Mapped[str] = mapped_column(Text, nullable=False)  # 问题摘要。
    priority: Mapped[str] = mapped_column(String(16), nullable=False, default="normal")  # 优先级。
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="open")  # 工单状态。
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)  # 创建时间。
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)  # 更新时间。

    order: Mapped[Order] = relationship(back_populates="tickets")  # 工单关联订单。
    customer: Mapped[Customer] = relationship(back_populates="tickets")  # 工单关联客户。


class RefundRequest(Base):
    """
    退款申请表，保存退款金额、原因、状态和是否需要审批。

    它解决的问题是：退款不是一次简单的聊天回复，而是需要持久化状态、
    金额、原因和审批标记的业务流程。
    """

    __tablename__ = "refund_requests"

    refund_request_id: Mapped[str] = mapped_column(String(32), primary_key=True)  # 退款申请编号。
    order_id: Mapped[str] = mapped_column(ForeignKey("orders.order_id"), nullable=False)  # 关联订单。
    amount: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)  # 退款金额。
    reason: Mapped[str] = mapped_column(Text, nullable=False)  # 退款原因。
    status: Mapped[str] = mapped_column(String(32), nullable=False)  # 退款状态。
    requires_approval: Mapped[bool] = mapped_column(nullable=False, default=False)  # 是否需要人工审批。
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)  # 创建时间。
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)  # 更新时间。

    order: Mapped[Order] = relationship(back_populates="refund_requests")  # 退款申请所属订单。


class PolicyArticle(Base):
    """
    售后政策文章表。

    这里是结构化业务数据，不是 RAG 知识库。当前阶段只是按分类、关键词或标题查询政策内容。

    它解决的问题是：政策解释要基于可维护的业务资料，而不是让模型自由编。
    当前阶段先用数据库表保存政策内容，后续如果需要再升级成 RAG。
    """

    __tablename__ = "policy_articles"

    article_id: Mapped[str] = mapped_column(String(32), primary_key=True)  # 政策文章编号。
    title: Mapped[str] = mapped_column(String(255), nullable=False)  # 政策标题。
    category: Mapped[str] = mapped_column(String(64), nullable=False)  # 政策分类，例如 refund、shipment。
    keywords: Mapped[list[str]] = mapped_column(JSON, default=list)  # 检索关键词。
    content: Mapped[str] = mapped_column(Text, nullable=False)  # 政策正文。
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)  # 创建时间。


class ToolCallLog(Base):
    """
    Agent 工具调用日志表，用于排查工具参数、耗时、结果和错误。

    它解决的问题是：Agent 出错时不能只看最终回答。
    需要知道模型调用了哪个工具、传了什么参数、耗时多久、返回了什么结果。
    """

    __tablename__ = "tool_call_logs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)  # 自增主键。
    conversation_id: Mapped[str | None] = mapped_column(String(64))  # 会话编号，早期也可对应 session_id。
    tool_call_id: Mapped[str | None] = mapped_column(String(64))  # 模型或 runtime 生成的工具调用编号。
    tool_name: Mapped[str] = mapped_column(String(128), nullable=False)  # 被调用的工具名。
    tool_arguments_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)  # 工具入参。
    status: Mapped[str] = mapped_column(String(16), nullable=False)  # started、completed、failed 等状态。
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)  # 开始时间。
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # 结束时间。
    latency_ms: Mapped[float | None] = mapped_column(nullable=True)  # 工具耗时，单位毫秒。
    result_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)  # 工具结构化结果。
    error_message: Mapped[str | None] = mapped_column(Text)  # 工具失败时的错误信息。


class ApprovalRecord(Base):
    """
    人工审批记录表，用于保存高风险工具调用的审批状态。

    它解决的问题是：高风险动作暂停后，系统必须知道谁在等审批、
    审批内容是什么、当前是 pending/approved/rejected 哪个状态。
    """

    __tablename__ = "approval_records"

    approval_id: Mapped[str] = mapped_column(String(32), primary_key=True)  # 审批编号。
    conversation_id: Mapped[str] = mapped_column(String(64), nullable=False)  # 所属会话或执行上下文。
    tool_call_id: Mapped[str | None] = mapped_column(String(64))  # 关联工具调用编号。
    tool_name: Mapped[str] = mapped_column(String(128), nullable=False)  # 需要审批的工具名。
    status: Mapped[str] = mapped_column(String(16), nullable=False)  # pending、approved、rejected。
    order_id: Mapped[str | None] = mapped_column(String(32))  # 关联订单，便于审批人判断。
    amount: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))  # 涉及金额。
    reason: Mapped[str | None] = mapped_column(Text)  # 需要审批的原因。
    risk_level: Mapped[str] = mapped_column(String(16), nullable=False, default="low")  # 风险等级。
    display_payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)  # 前端展示用 payload。
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)  # 发起审批时间。
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # 审批完成时间。


class AuditLog(Base):
    """
    审计日志表，记录关键业务事件和 Agent 运行事件。

    它解决的问题是：售后和退款属于需要追踪责任链的业务。
    审计日志让后续排查“什么时候发生了什么、由哪个 run 触发”有据可查。
    """

    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)  # 自增主键。
    conversation_id: Mapped[str | None] = mapped_column(String(64))  # 关联会话。
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)  # 事件类型。
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)  # 事件内容。
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)  # 记录时间。
```

`tests/test_business_schema.py`：

```python
"""
业务数据库 schema 测试。

这个文件解决的问题是：用临时 SQLite 数据库验证 ORM 模型确实能创建出核心表，
避免后续 repository 和 API 测试因为缺表才失败。
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import inspect

from agent_1_after_sales.business_service.after_sales.infrastructure.persistence.sqlalchemy.session import BusinessDatabase


@pytest.mark.asyncio
async def test_business_database_creates_expected_tables(tmp_path: Path) -> None:
    # Arrange：每个测试使用独立 SQLite 文件，避免测试之间互相污染。
    db_path = tmp_path / "after_sales.db"
    db = BusinessDatabase(f"sqlite+pysqlite:///{db_path}")
    try:
        # Act：创建 schema 后读取数据库中的实际表名。
        await db.create_schema()
        async with db.async_engine.connect() as connection:
            tables = await connection.run_sync(
                lambda sync_connection: set(inspect(sync_connection).get_table_names())
            )
    finally:
        await db.dispose()

    # Assert：核心业务表必须都被创建出来。
    assert {
        "customers",
        "orders",
        "shipments",
        "tickets",
        "refund_requests",
        "policy_articles",
        "tool_call_logs",
        "approval_records",
        "audit_logs",
    }.issubset(tables)
```

### 如何运行或验证

```bash
uv run pytest tests/test_business_schema.py -q
uv run python - <<'PY'
import asyncio
from agent_1_after_sales.business_service.after_sales.infrastructure.persistence.sqlalchemy.session import BusinessDatabase

async def main() -> None:
    # 本地教学先用 SQLite 文件，避免一开始就依赖 PostgreSQL。
    db = BusinessDatabase("sqlite+pysqlite:///./after_sales_mvp.db")
    await db.create_schema()
    await db.dispose()
    print("schema created")

asyncio.run(main())
PY
ls -lh after_sales_mvp.db
```

本地先用 SQLite 的原因是它不需要启动数据库服务，适合快速验证表结构、repository 和 API。等业务主链路跑通后，再用 PostgreSQL 承接生产或 durable runtime 状态。

如果你安装了 `sqlite3`，也可以看表：

```bash
sudo apt install -y sqlite3
sqlite3 after_sales_mvp.db ".tables"
```

### 常见错误

- 用同步 SQLAlchemy session 放进 async route，会阻塞请求。
- 忘记 import `models.py`，导致 `Base.metadata.create_all()` 没有表。
- 金额用 `float` 存储，容易出现精度问题。业务金额推荐 `Decimal`。
- 业务数据库和 Agent checkpoint 混在一起，后期审批恢复会变难。
- 把 `create_all()` 当成最终迁移方案：当前项目最终使用 Alembic revision 管理表结构版本，`create_all()` 只适合早期验证或测试辅助。

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
src/agent_1_after_sales/business_service/after_sales/application/ports.py
src/agent_1_after_sales/business_service/after_sales/application/services/after_sales_service.py
src/agent_1_after_sales/business_service/after_sales/infrastructure/persistence/sqlalchemy/repositories.py
src/agent_1_after_sales/business_service/after_sales/infrastructure/persistence/sqlalchemy/unit_of_work.py
tests/integration/test_unit_of_work.py
```

### 推荐目录结构

```text
src/agent_1_after_sales/business_service/after_sales/
  application/
    ports.py
    services/
      after_sales_service.py
  infrastructure/
    persistence/
      sqlalchemy/
        repositories.py
        unit_of_work.py
tests/
  integration/
    test_unit_of_work.py
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
6. 创建 `tests/integration/test_unit_of_work.py`，写 commit/rollback 测试。

### 示例代码

`ports.py`：

```python
"""
售后应用层端口定义。

这个文件解决的问题是：业务 service 只依赖 repository 和 Unit of Work 的抽象能力，
不直接依赖 SQLAlchemy 实现，从而保持应用层和基础设施层解耦。
"""

from __future__ import annotations

from typing import Protocol

from agent_1_after_sales.business_service.after_sales.domain.entities import OrderRead, TicketCreate, TicketRead


class AfterSalesRepository(Protocol):
    """
    售后数据访问能力的抽象。

    Protocol 只描述“能做什么”，不关心“怎么做”。
    具体实现可以是 SQLAlchemy repository，也可以是测试里的 fake repository。
    """

    async def get_order(self, order_id: str) -> OrderRead | None: ...

    async def create_ticket(self, payload: TicketCreate) -> TicketRead: ...


class AfterSalesUnitOfWork(Protocol):
    """
    业务事务边界的抽象。

    Service 通过 UoW 控制一次业务用例什么时候提交、什么时候回滚。
    这样 repository 只负责读写数据，不负责决定事务是否成功。
    """

    @property
    def repository(self) -> AfterSalesRepository: ...

    async def commit(self) -> None: ...

    async def rollback(self) -> None: ...
```

`repositories.py`：

```python
"""
Repository 查询数据库时得到 ORM 对象，
但 repository 不应该把 ORM 对象直接返回出去，
而是在 repository 内部把 ORM 对象转换成 domain/entities 里的对象再返回。

ORM 对象的属性不一定永远要和 domain/entities 对象完全一致。
但如果使用 `OrderRead.model_validate(order)` 这种自动转换写法，
并且 domain 模型开启了 `from_attributes=True`，Pydantic 会按字段名
从 ORM 对象上读取同名属性。

所以规则是：
1. 能同名最好，同名时可以直接 `model_validate(orm_obj)`。
2. 如果 ORM 字段名和 domain 字段名不一致，就不要直接自动转换，
   应该在 repository 里手动映射成 domain/entities 对象。
3. repository 正是处理这种 ORM -> domain 映射差异的地方。

手动映射的核心规则是：以 domain/entities 的字段要求为准。
domain/entities 里没有默认值的字段，创建对象时必须全部提供；
ORM 对象多出来的字段可以忽略。
如果 domain 需要的字段 ORM 没有同名属性，就在 repository 里从别的
ORM 属性取值、改名、计算出来，或者给业务允许的默认值。

例如：
`OrderRead(order_id=order.id, customer_id=order.buyer_id, status=order.order_status, ...)`
就是手动说明 OrderRead 的每个字段分别从 ORM 的哪个属性来。
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from agent_1_after_sales.business_service.after_sales.domain.entities import OrderRead, TicketCreate, TicketRead
from agent_1_after_sales.business_service.after_sales.infrastructure.persistence.sqlalchemy.models import Order, Ticket


def utcnow() -> datetime:
    """
    返回 UTC 当前时间。

    这解决的问题是：工单创建和更新时间需要统一时区，避免本地开发机、
    服务器和数据库时区不同导致排序和审计混乱。
    """

    return datetime.now(UTC)


class SqlAlchemyAfterSalesRepository:
    """
    AfterSalesRepository 的 SQLAlchemy 实现。

    Repository 只负责把数据库 ORM 对象转换成领域 read model，
    不负责 commit/rollback。事务边界交给 Unit of Work。

    这解决的问题是：业务 service 不直接写 SQLAlchemy 查询，
    同时 repository 不偷偷提交事务，多个写操作可以被 UoW 统一控制。
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session  # 当前 UoW 创建的 session，保证本次业务用例共用同一个事务。

    async def get_order(self, order_id: str) -> OrderRead | None:
        """
        根据订单编号查询订单。

        `session.get()` 适合按主键查询。查不到时返回 None，
        由 service 决定是抛业务异常还是做其它处理。
        """

        order = await self._session.get(Order, order_id)
        return OrderRead.model_validate(order) if order is not None else None

    async def create_ticket(self, payload: TicketCreate) -> TicketRead:
        """
        创建售后工单。

        创建工单前先查订单，是因为工单需要 customer_id。
        如果订单不存在，直接抛业务错误，避免生成孤立工单。

        注意这里调用 `flush()`，但不调用 `commit()`：
        `flush()` 让数据库分配/确认当前事务内的数据，`commit()` 仍然由 UoW 控制。
        """

        order = await self._session.get(Order, payload.order_id)
        if order is None:
            raise ValueError(f"order not found: {payload.order_id}")

        ticket = Ticket(
            ticket_id=f"TCK-{uuid4().hex[:8].upper()}",  # 教学版先用短 UUID 生成工单号，避免依赖额外 ID 服务。
            order_id=payload.order_id,
            customer_id=order.customer_id,
            issue_type=payload.issue_type,
            summary=payload.summary,
            priority=payload.priority,
            status="open",
            created_at=utcnow(),
            updated_at=utcnow(),
        )
        self._session.add(ticket)
        await self._session.flush()
        await self._session.refresh(ticket)
        return TicketRead.model_validate(ticket)
```

`unit_of_work.py`：

```python
"""
SQLAlchemy Unit of Work 实现。

这个文件解决的问题是：把一次业务用例里的 session 生命周期和事务提交/回滚
集中管理，避免 repository 方法各自偷偷 commit。
"""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from types import TracebackType

from sqlalchemy.ext.asyncio import AsyncSession

from agent_1_after_sales.business_service.after_sales.application.ports import AfterSalesRepository, AfterSalesUnitOfWork
from agent_1_after_sales.business_service.after_sales.infrastructure.persistence.sqlalchemy.repositories import SqlAlchemyAfterSalesRepository


class SqlAlchemyAfterSalesUnitOfWork:
    """
    基于 SQLAlchemy AsyncSession 的 Unit of Work 实现。

    它负责创建 session、暴露 repository，并决定退出上下文时 commit 还是 rollback。

    这解决的问题是：repository 不需要知道事务什么时候提交，service 可以把
    多个数据库操作包进同一个业务事务里。只要 service 不显式 commit，
    UoW 退出时就会 rollback，避免半成品数据落库。
    """

    def __init__(
        self,
        session_factory: Callable[[], AbstractAsyncContextManager[AsyncSession]],
    ) -> None:
        self._session_factory = session_factory  # 延迟创建 session。解决 UoW 对象创建时就占用数据库连接的问题。
        self._session_context: AbstractAsyncContextManager[AsyncSession] | None = None  # 保存上下文对象，退出时用它关闭 session。
        self._session: AsyncSession | None = None  # 当前事务使用的 session。进入上下文前为 None，避免未激活时误用。
        self._repository: AfterSalesRepository | None = None  # 当前 session 绑定的 repository。解决 repository 和事务 session 不一致的问题。
        self._committed = False  # 标记是否已经显式提交。解决退出上下文时不知道该 rollback 还是直接关闭的问题。

    @property
    def repository(self) -> AfterSalesRepository:
        """
        取当前 UoW 绑定的 repository。

        只有进入 `async with` 后 repository 才可用。未激活时直接报错，
        解决业务代码在事务外误用 repository 的问题。
        """

        if self._repository is None:
            raise RuntimeError("unit of work is not active")
        return self._repository

    async def __aenter__(self) -> AfterSalesUnitOfWork:
        """
        进入 `async with` 时创建数据库 session 和 repository。

        这样每个业务用例都有独立 session，不会把一次请求里的事务状态
        泄漏到另一次请求。
        """

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
        """
        退出 `async with` 时清理事务和 session。

        如果业务 service 没有显式调用 `commit()`，这里默认 rollback。
        这解决了异常路径或遗漏 commit 时“半成品数据落库”的问题。
        """

        if self._session is not None and not self._committed:
            await self.rollback()
        if self._session_context is not None:
            return await self._session_context.__aexit__(exc_type, exc, traceback)
        return None

    async def commit(self) -> None:
        """
        提交当前业务事务。

        只由 service 在业务用例成功完成后调用。
        这解决的问题是：事务提交点集中在业务用例层，而不是散落在 repository 方法里。
        """

        if self._session is None:
            raise RuntimeError("unit of work is not active")
        # commit 只在业务 service 明确调用时发生。
        await self._session.commit()
        self._committed = True

    async def rollback(self) -> None:
        """
        回滚当前业务事务。

        UoW 退出时如果没有 commit，会自动调用它。
        这解决异常路径、校验失败或遗漏 commit 时数据库留下脏数据的问题。
        """

        if self._session is None:
            raise RuntimeError("unit of work is not active")
        # rollback 让未提交写入回到事务开始前的状态。
        await self._session.rollback()
```

`after_sales_service.py`：

```python
"""
售后业务用例服务。

这个文件解决的问题是：把查单、建工单等业务用例集中到 service，
让 HTTP route、Agent tool 和脚本入口复用同一套业务规则。
"""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractAsyncContextManager

from agent_1_after_sales.business_service.after_sales.application.ports import AfterSalesUnitOfWork
from agent_1_after_sales.business_service.after_sales.domain.entities import OrderLookupInput, OrderRead, TicketCreate, TicketRead


class AfterSalesService:
    """
    售后业务用例服务。

    Route、Agent tool、脚本都应该调用 service，而不是直接操作 repository 或 ORM。

    这解决的问题是：业务规则集中在 service，入口可以有 HTTP、Agent tool、
    CLI 脚本，但它们复用同一套业务用例，不会各自写一份数据库逻辑。
    """

    def __init__(
        self,
        *,
        unit_of_work_factory: Callable[[], AbstractAsyncContextManager[AfterSalesUnitOfWork]],
    ) -> None:
        # service 只保存 UoW 工厂，不直接持有数据库 session。
        # 这解决的问题是：service 本身可以长期存在，而数据库 session 必须按请求/用例短生命周期创建。
        self._unit_of_work_factory = unit_of_work_factory

    async def get_order_detail(self, payload: OrderLookupInput) -> OrderRead:
        """
        查询订单详情。

        读操作也通过 UoW，保持所有业务用例的入口一致。
        如果订单不存在，service 抛业务异常，由 HTTP route 转换成 404。

        这里接收 `OrderLookupInput`，不是裸字符串，是为了和后续 Agent tool
        的参数校验模型保持一致。HTTP route 可以把路径参数组装成这个模型。
        """

        async with self._unit_of_work_factory() as uow:
            order = await uow.repository.get_order(payload.order_id)
        if order is None:
            raise ValueError(f"order not found: {payload.order_id}")
        return order

    async def create_ticket(self, payload: TicketCreate) -> TicketRead:
        """
        创建售后工单。

        写操作由 service 决定何时 commit，repository 本身不提交事务。
        这样多个 repository 写入可以被组合成一个原子业务用例。
        """

        async with self._unit_of_work_factory() as uow:
            ticket = await uow.repository.create_ticket(payload)
            await uow.commit()
            return ticket
```

`tests/integration/test_unit_of_work.py` 的最小写法：

```python
"""
Unit of Work 集成测试。

这个文件解决的问题是：用真实临时数据库验证未 commit 会 rollback，
确保事务边界由 UoW 控制，而不是散落在 repository 中。
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import select

from agent_1_after_sales.business_service.after_sales.domain.entities import TicketCreate
from agent_1_after_sales.business_service.after_sales.infrastructure.persistence.sqlalchemy.models import Customer, Order, Ticket
from agent_1_after_sales.business_service.after_sales.infrastructure.persistence.sqlalchemy.session import BusinessDatabase
from agent_1_after_sales.business_service.after_sales.infrastructure.persistence.sqlalchemy.unit_of_work import SqlAlchemyAfterSalesUnitOfWork


async def seed_order(db: BusinessDatabase) -> None:
    """
    准备一条订单数据，让 UoW 测试可以围绕真实外键关系运行。

    这解决的问题是：create_ticket 需要关联真实订单和客户。
    如果测试不先 seed 客户和订单，失败原因会变成外键/数据缺失，而不是 UoW rollback 本身。
    """

    async with db.managed_session() as session:
        session.add(
            Customer(
                customer_id="CUS123",
                name="测试用户",
                email="test@example.com",
                phone="13800000000",
                created_at=datetime.now(UTC),
            )
        )
        session.add(
            Order(
                order_id="ORD123",
                customer_id="CUS123",
                status="paid",
                total_amount=199,
                currency="CNY",
                item_summary="测试商品",
                created_at=datetime.now(UTC),
            )
        )
        await session.commit()


@pytest.mark.asyncio
async def test_unit_of_work_rolls_back_when_not_committed(tmp_path: Path) -> None:
    # Arrange：创建临时业务库并写入一条可关联的订单。
    db = BusinessDatabase(f"sqlite+pysqlite:///{tmp_path / 'uow.db'}")
    try:
        await db.create_schema()
        await seed_order(db)

        # Act：创建工单但故意不 commit。
        async with SqlAlchemyAfterSalesUnitOfWork(db.managed_session) as uow:
            await uow.repository.create_ticket(
                TicketCreate(order_id="ORD123", issue_type="damaged", summary="商品破损")
            )
            # 故意不 commit，退出上下文时应 rollback。

        async with db.managed_session() as session:
            tickets = list(await session.scalars(select(Ticket)))

        # Assert：退出 UoW 后未提交写入应被回滚。
        assert tickets == []
    finally:
        await db.dispose()
```

### 如何运行或验证

```bash
mkdir -p tests/integration
uv run pytest tests/integration/test_unit_of_work.py -q
uv run pytest tests/integration/test_unit_of_work.py -q -k rollback
```

重点验证：

- 未调用 `commit()` 时，UoW 退出会 rollback。
- 调用 `commit()` 后，写入能被后续查询读到。
- repository 不直接提交事务，事务边界由 service / UoW 控制。

### 常见错误

- Repository 里直接 `commit()`：事务边界分散，多个写入难以保证一致性。
- Service 里 import SQLAlchemy model：业务层和基础设施层耦合。
- UoW 退出时不 rollback：异常路径可能留下脏状态。
- 测试失败但数据库文件还在：删除本地临时 SQLite 文件后重新 seed，或者使用 pytest 的 `tmp_path` 隔离测试数据库。

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
src/agent_1_after_sales/app_api/deps.py
src/agent_1_after_sales/app_api/container.py
src/agent_1_after_sales/app_api/bootstrap.py
src/agent_1_after_sales/app_api/routers/after_sales_resources.py
src/agent_1_after_sales/app_api/main.py
tests/integration/test_after_sales_resources_api.py
```

### 推荐目录结构

```text
src/agent_1_after_sales/app_api/
  container.py
  bootstrap.py
  deps.py
  routers/
    after_sales_resources.py
tests/
  integration/
    test_after_sales_resources_api.py
```

### 关键概念讲解

Dependency Injection：FastAPI 的 `Depends` 可以把 service 注入 route。

Container：保存应用启动时创建好的共享对象，例如数据库、业务 service、Agent registry。

Composition root：把所有依赖装配起来的地方。本项目是 `src/agent_1_after_sales/app_api/bootstrap.py`。

API key：本地可选，生产推荐开启。

### 开发步骤

1. 创建 `AppContainer`。
2. 在 `bootstrap.py` 初始化 `BusinessDatabase`、UoW factory、`AfterSalesService`。
3. 在 lifespan 中把 container 放到 `app.state.container`。
4. 写 `deps.py` 获取 container、校验 API key、获取 business service。
5. 写业务 router。
6. 在 `main.py` 注册 router。
7. 写 HTTP 集成测试，用临时 SQLite 库 seed 一条订单。

### 示例代码

`container.py`：

```python
"""
应用运行时依赖容器。

这个文件解决的问题是：把启动时创建的共享依赖集中保存，
route 通过 dependency 取用这些对象，而不是自己创建数据库或 service。
"""

from __future__ import annotations

from dataclasses import dataclass

from agent_1_after_sales.app_api.settings import AppSettings
from agent_1_after_sales.business_service.after_sales.application.services.after_sales_service import AfterSalesService
from agent_1_after_sales.business_service.after_sales.infrastructure.persistence.sqlalchemy.session import BusinessDatabase


@dataclass(slots=True)
class AppContainer:
    """
    应用运行时依赖容器。

    第 7 章先放普通业务 API 需要的依赖：settings、业务数据库、售后业务 service。
    第 12 章会在这个基础上继续加入 Agent runtime、registry、LLM 状态等依赖。

    这解决的问题是：route 不自己创建数据库连接或 service。
    所有共享依赖都由 bootstrap 统一装配，再放进 `app.state.container`。
    """

    settings: AppSettings  # 当前应用配置。
    business_database: BusinessDatabase  # 售后业务数据库入口。
    after_sales_service: AfterSalesService  # 售后业务用例服务。

    async def close(self) -> None:
        """
        关闭容器持有的资源。

        这解决的问题是：应用退出时必须释放数据库连接池，否则测试和开发热重载
        可能留下未关闭连接。
        """

        await self.business_database.dispose()
```

`bootstrap.py`：

```python
"""
应用依赖装配入口。

这个文件解决的问题是：在一个地方创建数据库、Unit of Work factory 和业务 service，
避免依赖创建逻辑散落在各个 router 或测试里。
"""

from __future__ import annotations

from contextlib import AbstractAsyncContextManager

from agent_1_after_sales.app_api.container import AppContainer
from agent_1_after_sales.app_api.settings import AppSettings
from agent_1_after_sales.business_service.after_sales.application.ports import AfterSalesUnitOfWork
from agent_1_after_sales.business_service.after_sales.application.services.after_sales_service import AfterSalesService
from agent_1_after_sales.business_service.after_sales.infrastructure.persistence.sqlalchemy.session import BusinessDatabase
from agent_1_after_sales.business_service.after_sales.infrastructure.persistence.sqlalchemy.unit_of_work import SqlAlchemyAfterSalesUnitOfWork


async def build_container(settings: AppSettings) -> AppContainer:
    """
    创建应用容器。

    这里是 composition root：数据库、UoW factory、service 都在这里组装。
    route 层只从容器里拿 service，不关心这些依赖如何创建。

    这解决的问题是：依赖装配集中在一个地方，后续替换数据库、替换 fake service、
    或加入 Agent runtime 时，不需要到每个 route 里改代码。
    """

    business_database = BusinessDatabase(settings.business_database_url)

    def unit_of_work_factory() -> AbstractAsyncContextManager[AfterSalesUnitOfWork]:
        """
        创建 Unit of Work。

        每次调用都返回新的 UoW，UoW 再通过 `business_database.managed_session`
        创建新的 AsyncSession。这解决请求之间共享 session/事务的问题。
        """

        return SqlAlchemyAfterSalesUnitOfWork(business_database.managed_session)

    after_sales_service = AfterSalesService(unit_of_work_factory=unit_of_work_factory)
    return AppContainer(
        settings=settings,
        business_database=business_database,
        after_sales_service=after_sales_service,
    )
```

`main.py` 在第 7 章需要加入 lifespan，把 container 写入 `app.state`：

```python
"""
带 lifespan 的 FastAPI 应用工厂。

这个文件解决的问题是：应用启动时创建共享容器，关闭时释放资源，
避免每个请求重复创建数据库连接池和业务 service。
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from agent_1_after_sales.app_api.bootstrap import build_container
from agent_1_after_sales.app_api.routers.after_sales_resources import router as after_sales_router
from agent_1_after_sales.app_api.routers.health import router as health_router
from agent_1_after_sales.app_api.settings import AppSettings


def create_lifespan(settings: AppSettings):
    """
    创建 FastAPI lifespan。

    lifespan 负责应用启动时创建共享依赖，关闭时释放资源。
    这解决的问题是：数据库连接池和 service 不应该在每个请求里重复创建。
    """

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
        container = await build_container(settings)
        app.state.settings = settings
        app.state.container = container
        try:
            yield
        finally:
            await container.close()

    return lifespan


def create_app(settings: AppSettings | None = None) -> FastAPI:
    resolved_settings = settings or AppSettings()
    app = FastAPI(
        title="After-Sales Agent API",
        version="1.0.0",
        lifespan=create_lifespan(resolved_settings),
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=resolved_settings.parsed_cors_allowed_origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(health_router)
    app.include_router(after_sales_router)
    return app
```

`deps.py`：

```python
"""
FastAPI dependency 集中定义。

这个文件解决的问题是：router 通过 Depends 获取容器、鉴权和业务 service，
避免 HTTP 处理函数直接读取 app.state 或创建依赖对象。
"""

from __future__ import annotations

from typing import Annotated, cast

from fastapi import Depends, Header, HTTPException, Request

from agent_1_after_sales.app_api.container import AppContainer
from agent_1_after_sales.business_service.after_sales.application.services.after_sales_service import AfterSalesService


async def get_container(request: Request) -> AppContainer:
    """
    从 FastAPI app.state 取出应用容器。

    `app.state.container` 在 lifespan 启动时写入，里面放数据库、service、registry 等共享对象。

    这解决的问题是：route 不需要自己创建依赖，也不需要知道依赖怎么装配。
    所有依赖只在 bootstrap/lifespan 里创建一次，再通过 request.app.state 取出。
    """

    return cast(AppContainer, request.app.state.container)


async def require_api_key(
    request: Request,
    x_api_key: str | None = Header(default=None),
) -> None:
    """
    可选 API key 鉴权。

    本地开发可以不配置 API_KEY；一旦配置了，就要求请求头 `X-API-Key` 匹配。

    这解决的问题是：本地教学阶段不用被鉴权配置卡住，生产环境又可以通过
    同一段 dependency 开启接口保护。
    """

    expected = request.app.state.settings.api_key
    if expected is None:
        return
    if x_api_key != expected.get_secret_value():
        raise HTTPException(status_code=401, detail="invalid api key")


async def get_after_sales_service(
    container: Annotated[AppContainer, Depends(get_container)],
) -> AfterSalesService:
    """
    从应用容器中取出售后业务 service。

    这样 route 层只依赖 service，不直接依赖数据库、repository 或 UoW。
    后续测试也可以通过替换 container 来注入 fake service。
    """

    return container.after_sales_service
```

`after_sales_resources.py`：

```python
"""
售后资源 REST API。

这个文件解决的问题是：先把查单等售后能力作为普通 HTTP 接口暴露出来，
后续 Agent tool 也可以复用同一套业务 service。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from agent_1_after_sales.app_api.deps import get_after_sales_service, require_api_key
from agent_1_after_sales.business_service.after_sales.application.services.after_sales_service import AfterSalesService
from agent_1_after_sales.business_service.after_sales.domain.entities import OrderLookupInput, OrderRead

router = APIRouter(prefix="/api/after-sales", tags=["after-sales-resources"])


@router.get("/orders/{order_id}", response_model=OrderRead)
async def get_order(
    order_id: str,  # 路径参数，表示要查询的订单编号。
    service: AfterSalesService = Depends(get_after_sales_service),  # 从容器注入售后业务服务。
    _: None = Depends(require_api_key),  # 只关心鉴权是否通过，不需要返回值。
) -> OrderRead:
    """
    查询单个订单详情的 HTTP 接口。

    route 的职责是处理 HTTP 语义：参数来自路径，返回模型给 FastAPI 生成响应，
    业务异常要转换成合适的 HTTP 状态码。

    这解决的问题是：service 不需要 import FastAPI，也不需要知道 404/500；
    HTTP 状态码只在 app_api 层处理，业务层保持纯业务语义。
    """

    try:
        # route 层负责 HTTP 状态码，service 层负责业务语义。
        return await service.get_order_detail(OrderLookupInput(order_id=order_id))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
```

`tests/integration/test_after_sales_resources_api.py` 的测试骨架：

```python
"""
售后资源 API 集成测试。

这个文件解决的问题是：验证 FastAPI route、lifespan、container、service、
repository 和数据库能串成一条可运行链路。
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from agent_1_after_sales.app_api.main import create_app
from agent_1_after_sales.app_api.settings import AppSettings
from agent_1_after_sales.business_service.after_sales.infrastructure.persistence.sqlalchemy.models import Customer, Order
from agent_1_after_sales.business_service.after_sales.infrastructure.persistence.sqlalchemy.session import BusinessDatabase


async def seed_order(database_url: str) -> None:
    """
    为 HTTP 集成测试准备一条订单。

    这解决的问题是：HTTP 测试应该验证 route、container、service、repository
    能串起来，而不是因为数据库里没有 ORD123 导致只能测到 404。
    """

    db = BusinessDatabase(database_url)
    try:
        await db.create_schema()
        async with db.managed_session() as session:
            session.add(
                Customer(
                    customer_id="CUS123",
                    name="测试用户",
                    email="test@example.com",
                    phone="13800000000",
                    created_at=datetime.now(UTC),
                )
            )
            session.add(
                Order(
                    order_id="ORD123",
                    customer_id="CUS123",
                    status="paid",
                    total_amount=199,
                    currency="CNY",
                    item_summary="测试商品",
                    created_at=datetime.now(UTC),
                )
            )
            await session.commit()
    finally:
        await db.dispose()


@pytest.mark.asyncio
async def test_get_order_route_returns_seeded_order(tmp_path: Path) -> None:
    # Arrange：用临时 SQLite 数据库创建测试 app。
    database_url = f"sqlite+pysqlite:///{tmp_path / 'api.db'}"
    await seed_order(database_url)

    app = create_app(AppSettings(app_env="test", business_database_url=database_url))
    async with app.router.lifespan_context(app):
        # Act：通过 ASGITransport 直接调用 FastAPI，不需要启动真实端口。
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            response = await client.get("/api/after-sales/orders/ORD123")

    # Assert：HTTP 层和业务层应一起返回种子订单。
    assert response.status_code == 200
    assert response.json()["order_id"] == "ORD123"
```

### 如何运行或验证

先执行 HTTP 集成测试，确认路由、container、service 和 repository 串起来：

```bash
mkdir -p tests/integration
uv run pytest tests/integration/test_after_sales_resources_api.py -q
```

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

如果你设置了 `API_KEY`，curl 要带 `X-API-Key`：

```bash
curl http://127.0.0.1:8000/api/after-sales/orders/ORD123 \
  -H "X-API-Key: replace-with-your-key"
```

如果只想看 HTTP 状态码和响应头：

```bash
curl -i http://127.0.0.1:8000/api/after-sales/orders/ORD123
curl -i http://127.0.0.1:8000/api/after-sales/orders/NOT_FOUND
```

`make seed` 会写入演示订单和政策数据；没有 seed 数据时，业务 API 返回 404 是正常的，不代表路由坏了。

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
src/agent_1_after_sales/agent_service/llm/factory.py
src/agent_1_after_sales/agent_service/llm/payloads.py
src/agent_1_after_sales/agent_service/llm/tokens.py
src/agent_1_after_sales/agent_service/llm/types.py
tests/fake_chat_models.py
tests/test_model_factory.py
```

### 推荐目录结构

```text
src/agent_1_after_sales/agent_service/llm/
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

1. 安装 LangChain provider 依赖。
2. 创建 `build_chat_model()`。
3. 根据 `llm_provider` 分支创建 DeepSeek 或 OpenAI model。
4. API key 缺失时抛出明确错误。
5. 设置 `temperature=0`，提高教学和测试稳定性。
6. 创建 `DeterministicToolCallingChatModel` 作为测试模型。
7. 在 `create_app()` 中支持 `chat_model_override`。
8. 写 `tests/test_model_factory.py`，验证 provider、API key 和错误信息。

先安装依赖，否则 `factory.py` 和 fake model 里的 LangChain import 会失败：

```bash
uv add langchain-core langchain-deepseek langchain-openai
```

这里先只安装 chat model 需要的依赖。LangGraph runtime、checkpoint 和 MCP adapter 会在后续章节再安装，避免一开始把依赖一次性堆太多。

### 示例代码

`factory.py`：

```python
"""
LangChain chat model 工厂。

这个文件解决的问题是：把 DeepSeek/OpenAI 等 provider 的创建细节集中处理，
runtime 和业务层只依赖 BaseChatModel，不关心具体 SDK 构造方式。
"""

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
    """
    根据配置创建 LangChain chat model。

    这里把 provider 分支、API key 校验和通用参数集中到 factory，
    业务代码和 runtime 就不需要知道 DeepSeek/OpenAI 的具体构造细节。

    这解决的问题是：模型供应商切换不会扩散到业务服务、runtime、route。
    测试时也可以绕过这个 factory，直接注入 fake model，避免网络和费用依赖。
    """

    if llm_provider == "deepseek":
        if deepseek_api_key is None:
            raise ValueError("DEEPSEEK_API_KEY is required when llm_provider=deepseek")
        from langchain_deepseek import ChatDeepSeek

        return ChatDeepSeek(
            api_key=SecretStr(deepseek_api_key),  # SecretStr 避免日志里直接泄露 key。
            model=llm_model,  # 模型名来自配置，便于切换版本。
            temperature=0,  # 教学和测试阶段优先确定性。
            streaming=True,  # 后续 SSE 需要流式输出。
            timeout=llm_timeout_seconds,  # 避免请求长期挂起。
            max_retries=llm_max_retries,  # 网络抖动时允许有限重试。
        )

    if llm_provider == "openai":
        if openai_api_key is None:
            raise ValueError("OPENAI_API_KEY is required when llm_provider=openai")
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(
            api_key=SecretStr(openai_api_key),  # OpenAI API key。
            model=llm_model,  # OpenAI 模型名。
            temperature=0,  # 保持输出稳定。
            streaming=True,  # 保持和 DeepSeek 分支一致。
            timeout=llm_timeout_seconds,  # 单次请求超时。
            max_retries=llm_max_retries,  # 失败重试次数。
        )

    raise ValueError(f"unsupported llm provider: {llm_provider}")
```

测试模型思路：

```python
"""
测试用确定性 ChatModel。

这个文件解决的问题是：Agent runtime 测试不访问真实 LLM，
从而避免网络、额度、模型版本和随机输出影响测试稳定性。
"""

from __future__ import annotations

from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.tools import BaseTool
from pydantic import PrivateAttr


class DeterministicToolCallingChatModel(BaseChatModel):
    """
    用于测试的确定性 ChatModel。

    它不访问真实模型服务，避免单元测试依赖网络、额度和模型版本。

    这解决的问题是：Agent runtime 的测试需要稳定复现 tool calling 流程，
    不能每次都让真实模型自由发挥，也不能让测试依赖外部 provider 可用性。
    """

    _bound_tools: list[BaseTool] = PrivateAttr(default_factory=list)  # 保存 bind_tools 注入的工具。

    @property
    def _llm_type(self) -> str:
        """
        返回测试模型类型名称。

        LangChain 要求每个模型声明自己的类型，调试日志和序列化时会用到。
        """

        return "deterministic-test-model"

    def bind_tools(
        self,
        tools: list[BaseTool] | tuple[BaseTool, ...],
        **kwargs: Any,
    ) -> "DeterministicToolCallingChatModel":
        """
        接收 runtime 绑定进来的工具列表。

        真实模型会把工具 schema 发给 provider。测试模型不访问 provider，
        所以这里只保存工具列表，方便后续根据测试规则模拟 tool calling。
        """

        del kwargs
        clone = self.model_copy(deep=True)
        clone._bound_tools = list(tools)
        return clone

    async def _agenerate(
        self,
        messages: list[BaseMessage],
        **kwargs: Any,
    ) -> ChatResult:
        """
        异步生成模型回复。

        这里用固定规则返回结果，让 runtime 测试稳定可重复。
        如果最后一条消息是 ToolMessage，就把工具结果包装成最终回答；
        否则返回一个普通测试回复。
        """

        del kwargs
        message = AIMessage(content="测试模型回复")
        if messages and isinstance(messages[-1], ToolMessage):
            message = AIMessage(content=f"工具结果：{messages[-1].content}")
        return ChatResult(generations=[ChatGeneration(message=message)])

    def _generate(self, messages: list[BaseMessage], **kwargs: Any) -> ChatResult:
        """
        同步生成路径。

        项目 runtime 走 async 执行。这里显式抛错，是为了避免测试不小心
        走到同步路径却没有被发现。
        """

        del messages, kwargs
        raise NotImplementedError("tests use async execution only")
```

`tests/test_model_factory.py`：

```python
"""
LLM factory 单元测试。

这个文件解决的问题是：provider 缺 key、provider 写错等配置问题
应该在模型创建阶段得到明确错误，而不是等到第一次请求外部服务时才失败。
"""

from __future__ import annotations

import pytest

from agent_1_after_sales.agent_service.llm.factory import build_chat_model


def test_deepseek_requires_api_key() -> None:
    # DeepSeek 分支没有 key 时应给出明确错误，而不是在底层 SDK 里失败。
    with pytest.raises(ValueError, match="DEEPSEEK_API_KEY"):
        build_chat_model(
            llm_provider="deepseek",
            llm_model="deepseek-chat",
            llm_timeout_seconds=5,
            llm_max_retries=0,
            deepseek_api_key=None,
            openai_api_key=None,
        )


def test_unknown_provider_is_rejected() -> None:
    # provider 写错时应该快速失败，避免创建出不可预期的模型对象。
    with pytest.raises(ValueError, match="unsupported llm provider"):
        build_chat_model(
            llm_provider="unknown",
            llm_model="fake",
            llm_timeout_seconds=5,
            llm_max_retries=0,
            deepseek_api_key=None,
            openai_api_key=None,
        )
```

### 如何运行或验证

```bash
uv run pytest tests/test_model_factory.py -q
```

本地真实模型验证：

```bash
LLM_PROVIDER=deepseek DEEPSEEK_API_KEY=replace-me uv run python - <<'PY'
from agent_1_after_sales.app_api.settings import AppSettings
from agent_1_after_sales.agent_service.llm.factory import build_chat_model

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

测试优先用 fake LLM。原因是单元测试要稳定、快速、可重复；真实 LLM 会受到网络、额度、模型版本和温度影响，不适合作为基础质量门槛。

真实模型验证前，先确认 `.env` 里有 key：

```bash
grep -n "DEEPSEEK_API_KEY\\|OPENAI_API_KEY\\|LLM_PROVIDER\\|LLM_MODEL" .env
```

### 常见错误

- 测试直接调用真实 LLM，导致慢、不稳定、依赖网络和费用。
- provider 缺 key 时错误信息不明确。
- `temperature` 太高，测试结果不可预测。
- 忘记 `streaming=True`，后续 SSE 体验变差。
- 在 WSL 里无法访问外网：先用 `curl https://api.deepseek.com` 或访问对应 provider 文档域名确认网络。

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
src/agent_1_after_sales/agent_service/contracts/actions.py
src/agent_1_after_sales/agent_service/contracts/capability.py
src/agent_1_after_sales/agent_service/contracts/events.py
src/agent_1_after_sales/agent_service/contracts/registry.py
src/agent_1_after_sales/agent_service/contracts/models.py
tests/test_agent_contracts.py
```

### 推荐目录结构

```text
src/agent_1_after_sales/agent_service/contracts/
  __init__.py
  actions.py
  capability.py
  events.py
  models.py
  registry.py
tests/
  test_agent_contracts.py
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
7. 写 registry 和 approval policy 的单元测试。

### 示例代码

`actions.py`：

```python
"""
Agent 工具动作契约。

这个文件解决的问题是：用项目自己的 ToolSpec、ToolContext 和 ApprovalPolicy
描述工具能力，避免业务工具直接绑定到 LangChain 的内部类型。
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

from pydantic import BaseModel

from agent_1_after_sales.agent_service.contracts.models import ActorContext, RiskLevel


@dataclass(slots=True, frozen=True)
class ApprovalRequirement:
    """
    一次工具调用需要人工审批时返回的要求。

    它不执行审批，只描述为什么要暂停以及前端应该展示什么。
    """

    reason: str  # 需要人工审批的原因。
    risk_level: RiskLevel = "low"  # 风险等级，决定审批提示强度。
    display_payload: dict[str, object] | None = None  # 展示给审批人的关键信息。


@dataclass(slots=True, frozen=True)
class ToolContext:
    """
    工具执行时的上下文，不属于模型生成的参数。

    这解决的问题是：模型只能生成业务参数，不能自己伪造 actor、capability_id
    或内部依赖。系统上下文由 runtime 注入，和 LLM payload 分开管理。
    """

    capability_id: str  # 当前 Agent 能力 id。
    actor: ActorContext = field(default_factory=ActorContext)  # 当前操作人。
    dependencies: object | None = None  # 可选依赖容器，复杂场景可传 service bundle。


class ToolHandler(Protocol):
    """
    工具处理函数的签名约束。

    handler 接收模型生成的 payload 和系统提供的 ToolContext。
    这样工具参数和运行上下文分开，模型不能伪造 actor、capability 等内部信息。
    """

    def __call__(self, payload: dict[str, Any], context: ToolContext) -> Any: ...


class ApprovalPolicy(Protocol):
    """
    工具执行前的审批策略接口。

    evaluate 返回 None 表示可直接执行；返回 ApprovalRequirement 表示
    runtime 必须先暂停并等待人工动作。
    """

    def evaluate(self, payload: dict[str, Any]) -> ApprovalRequirement | None: ...


@dataclass(slots=True, frozen=True)
class CallableApprovalPolicy:
    """
    把普通函数包装成 ApprovalPolicy，便于在业务层复用审批规则。

    这解决的问题是：很多审批规则天然就是一个函数。
    用这个包装类后，不需要为每个简单规则都手写一个完整策略类。
    """

    evaluator: Callable[[dict[str, Any]], ApprovalRequirement | None]  # 返回 None 表示不需要审批。

    def evaluate(self, payload: dict[str, Any]) -> ApprovalRequirement | None:
        return self.evaluator(payload)


@dataclass(slots=True, frozen=True)
class ToolSpec:
    """
    项目内部的工具定义。

    Runtime 会把它转换成 LangChain tool；API 也可以用它生成工具目录。
    """

    name: str  # 工具名，模型会按这个名字发起 tool call。
    description: str  # 工具描述，影响模型什么时候选择它。
    args_schema: type[BaseModel]  # 工具参数 schema，用于校验和暴露 JSON Schema。
    handler: ToolHandler  # 工具真正执行的函数。
    approval_policy: ApprovalPolicy | None = None  # 可选审批策略。
    source: Literal["local", "mcp"] = "local"  # 工具来源：本地代码或 MCP server。
    source_id: str | None = None  # MCP 工具可记录 server id。
```

`capability.py`：

```python
"""
Agent 能力定义。

这个文件解决的问题是：把一个 agent 的 capability_id、system prompt 和工具集合
打包成稳定定义，供 registry、runtime 和 API catalog 共同使用。
"""

from __future__ import annotations

from dataclasses import dataclass

from agent_1_after_sales.agent_service.contracts.actions import ToolSpec


@dataclass(slots=True, frozen=True)
class AgentDefinition:
    """
    一个 Agent 能力的完整定义。

    它把 prompt 和工具集合打包成一个可注册能力。runtime 不需要知道
    这些工具来自售后业务、MCP 还是其它 adapter，只处理统一的 ToolSpec。
    """

    capability_id: str  # 这个 agent 在 API 和 registry 中的稳定 id。
    system_prompt: str  # 注入给模型的系统提示词。
    tools: tuple[ToolSpec, ...]  # 这个 agent 可以调用的工具集合。
    name: str | None = None  # 给前端展示的人类可读名称。
    description: str | None = None  # 给前端或工具目录展示的能力说明。
```

`registry.py`：

```python
"""
Agent 能力注册表。

这个文件解决的问题是：集中管理系统当前有哪些 AgentDefinition，
让 API 和 runtime 不需要硬编码所有 capability_id。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from agent_1_after_sales.agent_service.contracts.capability import AgentDefinition


@dataclass(slots=True)
class AgentRegistry:
    """
    代码型 Agent catalog。

    它解决“系统里有哪些 agent 能力”的发现问题。
    API 可以从这里生成 `/api/agents`，测试也可以注册临时 definition。
    """

    _definitions: dict[str, AgentDefinition] = field(default_factory=dict)  # capability_id 到定义的映射。

    def register(self, definition: AgentDefinition) -> None:
        # 后注册的同 id definition 会覆盖旧值，便于测试替换。
        self._definitions[definition.capability_id] = definition

    def get(self, capability_id: str) -> AgentDefinition | None:
        # 不存在时返回 None，由 route 决定是否转成 404。
        return self._definitions.get(capability_id)

    def list_definitions(self) -> list[AgentDefinition]:
        # 排序后返回，保证 API 和测试输出稳定。
        return [self._definitions[key] for key in sorted(self._definitions)]
```

`events.py`：

```python
"""
Agent run 事件契约。

这个文件解决的问题是：把 runtime 执行过程转换成项目自己的事件模型，
API、SSE、审计日志和测试都围绕这些稳定事件协作。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from agent_1_after_sales.agent_service.contracts.models import AgentError, AgentPendingAction, AgentRunResult


@dataclass(slots=True, frozen=True)
class RunStartedEvent:
    """
    Agent run 开始事件。

    这解决的问题是：SSE 前端或日志系统需要先知道本次执行的 run_id、
    session_id 和 capability_id，后续事件才能归属到同一次执行。
    """

    run_id: str
    session_id: str
    capability_id: str


@dataclass(slots=True, frozen=True)
class OutputDeltaEvent:
    """
    模型输出增量事件。

    这解决的问题是：聊天界面不想等完整回答生成完才显示，
    可以通过 delta 一段一段渲染。
    """

    run_id: str
    delta: str


@dataclass(slots=True, frozen=True)
class ActionStartedEvent:
    """
    工具调用开始事件。

    这解决的问题是：审计和前端可以知道 Agent 准备调用哪个工具，以及传入了什么参数。
    """

    run_id: str
    action_id: str
    action_name: str
    action_payload: dict[str, Any]


@dataclass(slots=True, frozen=True)
class ActionCompletedEvent:
    """
    工具调用完成事件。

    这解决的问题是：系统可以记录工具成功/失败、耗时和结构化结果，
    后续排查 Agent 回答错误时有依据。
    """

    run_id: str
    action_id: str
    action_name: str
    action_payload: dict[str, Any]
    success: bool
    latency_ms: float
    result: Any = None
    error: dict[str, Any] | None = None


@dataclass(slots=True, frozen=True)
class ActionRequiredEvent:
    """
    等待人工动作事件。

    这解决的问题是：高风险工具不能直接执行时，runtime 可以用结构化事件告诉前端
    “现在需要人工审批”，而不是只返回一段自然语言。
    """

    run_id: str
    pending_action: AgentPendingAction


@dataclass(slots=True, frozen=True)
class RunCompletedEvent:
    """
    Agent run 完成事件。

    它携带最终 AgentRunResult，解决 stream 消费方需要知道最终状态的问题。
    """

    result: AgentRunResult


@dataclass(slots=True, frozen=True)
class RunFailedEvent:
    """
    Agent run 失败事件。

    这解决的问题是：失败也要有结构化输出，方便 API、SSE 和日志统一处理。
    """

    run_id: str
    error: AgentError


type RunEvent = (
    RunStartedEvent
    | OutputDeltaEvent
    | ActionStartedEvent
    | ActionCompletedEvent
    | ActionRequiredEvent
    | RunCompletedEvent
    | RunFailedEvent
)
```

`tests/test_agent_contracts.py`：

```python
"""
Agent contract 单元测试。

这个文件解决的问题是：在接入 LangChain runtime 之前，
先验证 registry、ToolSpec 和审批策略这些内部契约本身是可用的。
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from agent_1_after_sales.agent_service.contracts.actions import ApprovalRequirement, CallableApprovalPolicy, ToolContext, ToolSpec
from agent_1_after_sales.agent_service.contracts.capability import AgentDefinition
from agent_1_after_sales.agent_service.contracts.registry import AgentRegistry


class Args(BaseModel):
    order_id: str  # 工具需要的订单编号。


def handler(payload: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    # 测试 handler 只回显参数，用来证明 ToolSpec 能保存可调用对象。
    return {"capability_id": context.capability_id, "order_id": payload["order_id"]}


def test_agent_registry_lists_definitions_sorted_by_capability_id() -> None:
    # Arrange：故意按 b、a 顺序注册。
    registry = AgentRegistry()
    registry.register(AgentDefinition(capability_id="b_agent", system_prompt="b", tools=()))
    registry.register(AgentDefinition(capability_id="a_agent", system_prompt="a", tools=()))

    # Assert：list_definitions 应按 capability_id 稳定排序。
    assert [item.capability_id for item in registry.list_definitions()] == ["a_agent", "b_agent"]


def test_tool_spec_can_hold_approval_policy() -> None:
    # policy 命中后返回 ApprovalRequirement，表示工具执行前需要人工处理。
    policy = CallableApprovalPolicy(
        lambda payload: ApprovalRequirement(reason="需要审批", risk_level="medium")
    )
    tool = ToolSpec(
        name="get_order_detail",
        description="查订单",
        args_schema=Args,
        handler=handler,
        approval_policy=policy,
    )

    assert tool.approval_policy is not None
    assert tool.approval_policy.evaluate({"order_id": "ORD123"}).risk_level == "medium"
```

### 如何运行或验证

```bash
uv run pytest tests/test_agent_contracts.py -q
uv run python - <<'PY'
from pydantic import BaseModel
from agent_1_after_sales.agent_service.contracts.actions import ToolSpec, ToolContext

class Args(BaseModel):
    # args_schema 会被暴露给模型和 /api/agents/{id}/tools。
    order_id: str  # 工具调用时必须提供的订单编号。

def handler(payload: dict, context: ToolContext) -> dict:
    # handler 是工具真正执行的函数。
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
src/agent_1_after_sales/app_api/services/after_sales_agent_definition.py
src/agent_1_after_sales/app_api/routers/agents.py
src/agent_1_after_sales/app_api/schemas/agents.py
tests/test_after_sales_agent_definition.py
```

### 推荐目录结构

```text
src/agent_1_after_sales/app_api/
  services/
    after_sales_agent_definition.py
  routers/
    agents.py
  schemas/
    agents.py
tests/
  test_after_sales_agent_definition.py
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
7. 写工具目录测试，确认退款工具需要审批。

### 示例代码

`after_sales_agent_definition.py`：

```python
"""
售后 Agent Definition 适配器。

这个文件解决的问题是：把售后业务 service 包装成 Agent 可调用的 ToolSpec，
同时保持 business_service 不依赖 agent_service 或 LangChain。
"""

from __future__ import annotations

from typing import Any

from agent_1_after_sales.agent_service.contracts.actions import ApprovalRequirement, CallableApprovalPolicy, ToolContext, ToolSpec
from agent_1_after_sales.agent_service.contracts.capability import AgentDefinition
from agent_1_after_sales.business_service.after_sales.application.services.after_sales_service import AfterSalesService
from agent_1_after_sales.business_service.after_sales.domain.entities import OrderLookupInput, RefundRequestCreate


def build_after_sales_agent_definition(
    *,
    after_sales_service: AfterSalesService,
) -> AgentDefinition:
    """
    把售后业务服务包装成一个可注册的 AgentDefinition。

    这里是 app_api 层的 adapter：它知道业务 service，也知道 Agent ToolSpec，
    但 business_service 本身不需要 import agent_service。

    这解决的问题是：业务层只提供结构化售后能力，Agent 层负责把这些能力
    描述成模型可选择的工具。两层通过 adapter 相遇，避免业务代码被 LangChain 污染。
    """

    async def get_order_detail(
        payload: dict[str, Any],
        context: ToolContext,
    ) -> dict[str, Any]:
        """
        订单查询工具 handler。

        payload 来自 LLM 生成的工具参数，不能直接信任。
        先用 OrderLookupInput 校验，再调用业务 service，最后把领域模型转成 JSON 友好字典。

        这解决的问题是：LLM 生成的参数可能缺字段、错类型或带多余内容。
        工具 handler 是最后一道入参校验边界，不能把原始 dict 直接丢给业务层。
        """

        # context 里有 actor 信息，本工具暂时不需要，所以显式丢弃。
        del context
        # LLM 传来的 payload 先通过 Pydantic 校验，再进入业务 service。
        order = await after_sales_service.get_order_detail(
            OrderLookupInput.model_validate(payload)
        )
        # mode="json" 会把 Decimal、datetime 等类型转成 JSON 友好格式。
        return order.model_dump(mode="json")

    async def submit_refund_request(
        payload: dict[str, Any],
        context: ToolContext,
    ) -> dict[str, Any]:
        """
        退款申请工具 handler。

        这个函数只负责参数校验、调用业务 service、序列化返回值。
        是否需要审批由 approval_policy 决定，不应该混在 handler 主流程里。

        这解决的问题是：工具执行逻辑和风险审批逻辑分离。
        handler 只描述“批准后怎么执行”，approval_policy 描述“执行前要不要暂停”。
        """

        # 退款工具同样不直接信任 LLM 参数，先做 schema 校验。
        del context
        refund = await after_sales_service.submit_refund_request(
            RefundRequestCreate.model_validate(payload)
        )
        return refund.model_dump(mode="json")

    def evaluate_refund_approval(payload: dict[str, Any]) -> ApprovalRequirement | None:
        """
        把业务层退款审批规则适配成 Agent 层审批规则。

        返回 None 表示可以直接执行退款工具；返回 ApprovalRequirement 表示
        runtime 应该暂停当前 run，等待人工批准或拒绝。

        这解决的问题是：审批规则仍然来自业务 service，Agent adapter 只做格式转换。
        如果把审批阈值写死在 runtime，业务规则就会散落到框架层。
        """

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
            # 用 tuple + join 避免一行 prompt 太长，也避免多余换行影响模型行为。
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
        name="After-Sales Assistant",  # 展示名。解决前端工具目录不能只显示技术 id 的问题。
        description="售后客服 agent，支持查单、物流、工单、退款审批和政策查询。",  # 能力简介，供 /api/agents 和前端展示。
        system_prompt=system_prompt,
        tools=(
            ToolSpec(
                name="get_order_detail",  # 工具名。解决模型需要稳定名称发起 tool call 的问题。
                description="获取订单详情，适用于查询订单状态、商品概要和下单信息。",  # 工具说明。解决模型不知道何时选它的问题。
                args_schema=OrderLookupInput,  # 参数 schema。解决模型生成参数没有结构约束的问题。
                handler=get_order_detail,  # 执行函数。解决 ToolSpec 只描述工具但不能执行的问题。
            ),
            ToolSpec(
                name="submit_refund_request",  # 退款申请工具名。解决退款动作需要独立审计和审批的问题。
                description="提交退款申请。命中审批策略时会先等待人工动作。",  # 明确告诉模型可能触发审批，减少错误预期。
                args_schema=RefundRequestCreate,  # 退款参数 schema。解决金额、原因、订单号缺失时无法提前拦截的问题。
                handler=submit_refund_request,  # 退款提交处理函数。只有审批通过或无需审批时才真正执行。
                approval_policy=CallableApprovalPolicy(evaluate_refund_approval),  # 审批策略。解决高风险退款不能自动落库的问题。
            ),
        ),
    )
```

第 10 章还要把 Agent Definition 注册进应用容器。否则后面的
`routers/agents.py` 虽然会写 `Depends(get_agent_registry)`，但 `deps.py`
里没有这个 dependency，`AppContainer` 里也没有 `agent_registry`，接口启动后会直接断。

扩展 `container.py`：

```python
"""
带 Agent registry 的应用容器。

这个文件解决的问题是：把 Agent catalog 和业务 service 放进同一个运行时容器，
让 /api/agents 读取的是 bootstrap 注册好的真实能力定义。
"""

from __future__ import annotations

from dataclasses import dataclass

from agent_1_after_sales.agent_service.contracts.registry import AgentRegistry
from agent_1_after_sales.app_api.settings import AppSettings
from agent_1_after_sales.business_service.after_sales.application.services.after_sales_service import AfterSalesService
from agent_1_after_sales.business_service.after_sales.infrastructure.persistence.sqlalchemy.session import BusinessDatabase


@dataclass(slots=True)
class AppContainer:
    """
    应用运行时依赖容器。

    第 10 章在第 7 章基础上新增 `agent_registry`。
    这解决的问题是：`/api/agents` 和 `/api/agents/{capability_id}/tools`
    需要从统一 catalog 读取能力定义，不能在 route 里临时 new 一个 registry。
    """

    settings: AppSettings  # 当前应用配置。
    business_database: BusinessDatabase  # 售后业务数据库入口。
    after_sales_service: AfterSalesService  # 售后业务用例服务。
    agent_registry: AgentRegistry  # Agent 能力目录，供 catalog API 和后续 runtime 使用。

    async def close(self) -> None:
        """
        关闭容器持有的资源。

        当前新增的 agent_registry 没有外部连接，所以 close 仍然只释放数据库。
        后面加入 runtime/checkpoint 后，再在这里补对应资源释放。
        """

        await self.business_database.dispose()
```

扩展 `bootstrap.py`：

```python
"""
注册售后 Agent Definition 的应用装配入口。

这个文件解决的问题是：在应用启动时把售后 service 包装成 AgentDefinition，
并注册到 AgentRegistry，供 catalog API 和后续 runtime 使用。
"""

from __future__ import annotations

from contextlib import AbstractAsyncContextManager

from agent_1_after_sales.agent_service.contracts.registry import AgentRegistry
from agent_1_after_sales.app_api.container import AppContainer
from agent_1_after_sales.app_api.services.after_sales_agent_definition import build_after_sales_agent_definition
from agent_1_after_sales.app_api.settings import AppSettings
from agent_1_after_sales.business_service.after_sales.application.ports import AfterSalesUnitOfWork
from agent_1_after_sales.business_service.after_sales.application.services.after_sales_service import AfterSalesService
from agent_1_after_sales.business_service.after_sales.infrastructure.persistence.sqlalchemy.session import BusinessDatabase
from agent_1_after_sales.business_service.after_sales.infrastructure.persistence.sqlalchemy.unit_of_work import SqlAlchemyAfterSalesUnitOfWork


async def build_container(settings: AppSettings) -> AppContainer:
    """
    创建应用容器，并注册售后 Agent Definition。

    这解决的问题是：Agent catalog 和业务 service 使用同一个容器装配出来的
    service 实例，避免工具目录展示的是一套 service，真正执行时又是另一套依赖。
    """

    business_database = BusinessDatabase(settings.business_database_url)

    def unit_of_work_factory() -> AbstractAsyncContextManager[AfterSalesUnitOfWork]:
        # 每次业务调用创建独立 UoW，解决不同请求共享事务的问题。
        return SqlAlchemyAfterSalesUnitOfWork(business_database.managed_session)

    after_sales_service = AfterSalesService(unit_of_work_factory=unit_of_work_factory)

    agent_registry = AgentRegistry()
    agent_registry.register(
        build_after_sales_agent_definition(after_sales_service=after_sales_service)
    )

    return AppContainer(
        settings=settings,
        business_database=business_database,
        after_sales_service=after_sales_service,
        agent_registry=agent_registry,
    )
```

扩展 `deps.py`：

```python
"""
带 Agent registry 的 FastAPI dependency。

这个文件解决的问题是：让 agents router 通过 Depends 获取统一的 AgentRegistry，
而不是在路由里临时创建或硬编码 agent 定义。
"""

from __future__ import annotations

from typing import Annotated, cast

from fastapi import Depends, Header, HTTPException, Request

from agent_1_after_sales.agent_service.contracts.registry import AgentRegistry
from agent_1_after_sales.app_api.container import AppContainer
from agent_1_after_sales.business_service.after_sales.application.services.after_sales_service import AfterSalesService


async def get_container(request: Request) -> AppContainer:
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


async def get_agent_registry(
    container: Annotated[AppContainer, Depends(get_container)],
) -> AgentRegistry:
    """
    从容器取出 AgentRegistry。

    这解决的问题是：`routers/agents.py` 不自己创建 registry，
    而是读取 bootstrap 时注册好的真实 Agent Definition。
    """

    return container.agent_registry
```

扩展 `main.py` 注册 Agent catalog router：

```python
from agent_1_after_sales.app_api.routers.agents import router as agents_router

# create_app() 里已有 health_router 和 after_sales_router，这里新增 agents_router。
app.include_router(agents_router)
```

`schemas/agents.py` 第 4 章已经创建过。这里贴出最终版用于对照；如果内容一致，不需要重复创建：

```python
"""
Agent catalog 的 HTTP schema。

这个文件解决的问题是：前端和外部调用方通过稳定响应读取 agent 和工具摘要，
而不是直接依赖 Python 内部 ToolSpec 对象。
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class AgentSummary(BaseModel):
    """
    Agent catalog 的摘要响应。

    这解决的问题是：前端或调用方需要先知道系统有哪些 agent，
    但不需要一次性拿到完整 prompt 和工具 schema。
    """

    capability_id: str  # Agent 能力 id，例如 after_sales_assistant。
    name: str | None = None  # 展示名。
    description: str | None = None  # 能力说明。


class ToolSummary(BaseModel):
    """
    Agent 工具摘要响应。

    这解决的问题是：前端需要展示工具名、说明、参数 schema 和是否需要审批，
    但不应该直接暴露 Python ToolSpec 对象。
    """

    name: str  # 工具名。
    description: str  # 工具说明。
    args_schema: dict[str, Any] = Field(default_factory=dict)  # JSON Schema，用于前端展示参数。
    requires_approval: bool = False  # 该工具是否可能触发人工审批。
```

`routers/agents.py`：

```python
"""
Agent catalog API。

这个文件解决的问题是：通过 HTTP 暴露当前系统有哪些 agent，
以及某个 agent 具备哪些工具和参数 schema。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from agent_1_after_sales.agent_service.contracts.registry import AgentRegistry
from agent_1_after_sales.app_api.deps import get_agent_registry
from agent_1_after_sales.app_api.schemas.agents import AgentSummary, ToolSummary

router = APIRouter(prefix="/api/agents", tags=["agents"])


@router.get("", response_model=list[AgentSummary])
async def list_agents(
    registry: AgentRegistry = Depends(get_agent_registry),
) -> list[AgentSummary]:
    """
    返回当前注册的 Agent 能力列表。

    这解决的问题是：前端或外部系统不需要硬编码 capability_id，
    可以从后端 catalog 动态发现当前有哪些 agent。
    """

    return [
        AgentSummary(
            capability_id=definition.capability_id,
            name=definition.name,
            description=definition.description,
        )
        for definition in registry.list_definitions()
    ]


@router.get("/{capability_id}/tools", response_model=list[ToolSummary])
async def list_agent_tools(
    capability_id: str,
    registry: AgentRegistry = Depends(get_agent_registry),
) -> list[ToolSummary]:
    """
    返回某个 Agent 的工具目录。

    这解决的问题是：调用方可以知道某个 agent 支持哪些工具、参数长什么样、
    哪些工具可能需要审批，而不是只能从 prompt 里猜。
    """

    definition = registry.get(capability_id)
    if definition is None:
        raise HTTPException(status_code=404, detail=f"agent not found: {capability_id}")

    return [
        ToolSummary(
            name=tool.name,
            description=tool.description,
            args_schema=tool.args_schema.model_json_schema(),
            requires_approval=tool.approval_policy is not None,
        )
        for tool in definition.tools
    ]
```

`tests/test_after_sales_agent_definition.py`：

```python
"""
售后 Agent Definition 单元测试。

这个文件解决的问题是：不连接真实数据库和 LLM，也能验证售后工具目录
以及退款工具的审批策略是否被正确注册。
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from agent_1_after_sales.app_api.services.after_sales_agent_definition import build_after_sales_agent_definition
from agent_1_after_sales.business_service.after_sales.domain.entities import RefundApprovalRequirement, RefundRequestCreate


class FakeAfterSalesService:
    """
    测试用售后 service。

    它只实现当前测试需要的审批规则，不连接真实数据库。
    这解决的问题是：Agent definition 的单元测试只关心工具目录和审批策略，
    不应该因为数据库、repository、seed 数据没准备好而失败。
    """

    def evaluate_refund_approval(
        self,
        payload: RefundRequestCreate,
    ) -> RefundApprovalRequirement | None:
        if Decimal(payload.amount) <= Decimal("100"):
            return None
        return RefundApprovalRequirement(
            reason="退款金额超过 100 元，需要人工审批。",
            risk_level="medium",
            display_payload={"order_id": payload.order_id, "amount": float(payload.amount)},
        )


def test_after_sales_definition_exposes_refund_tool_with_approval() -> None:
    # Arrange：用 fake service 构造 agent definition。
    definition = build_after_sales_agent_definition(
        after_sales_service=FakeAfterSalesService(),  # type: ignore[arg-type]
    )
    tools = {tool.name: tool for tool in definition.tools}

    # Assert：定义中应该注册退款工具，并且退款工具带审批策略。
    assert definition.capability_id == "after_sales_assistant"
    assert "submit_refund_request" in tools
    assert tools["submit_refund_request"].approval_policy is not None

    # Act：模拟一笔超过 100 元的退款，应该命中审批规则。
    requirement = tools["submit_refund_request"].approval_policy.evaluate(
        {"order_id": "ORD123", "amount": "200", "reason": "商品破损"}
    )

    assert requirement is not None
    assert requirement.risk_level == "medium"
```

### 如何运行或验证

先跑工具目录单元测试，不需要启动服务：

```bash
uv run pytest tests/test_after_sales_agent_definition.py -q
```

启动后调用：

```bash
make seed
make start
```

另开一个 WSL 终端调用：

```bash
curl http://127.0.0.1:8000/api/agents
curl http://127.0.0.1:8000/api/agents/after_sales_assistant/tools
```

如果只想看工具名字，可以用 Python 解析 JSON，避免额外安装 `jq`：

```bash
curl -s http://127.0.0.1:8000/api/agents/after_sales_assistant/tools \
  | uv run python -c "import sys,json; print([t['name'] for t in json.load(sys.stdin)])"
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
src/agent_1_after_sales/agent_service/infrastructure/runtime/langchain_runtime.py
src/agent_1_after_sales/agent_service/infrastructure/state_store/in_memory_store.py
src/agent_1_after_sales/agent_service/infrastructure/state_store/langgraph_postgres_store.py
src/agent_1_after_sales/agent_service/infrastructure/state_store/session_transcript_store.py
src/agent_1_after_sales/app_api/services/after_sales_assistant.py
src/agent_1_after_sales/app_api/services/after_sales_run_projector.py
tests/test_langchain_runtime.py
```

### 推荐目录结构

```text
src/agent_1_after_sales/agent_service/infrastructure/
  runtime/
    langchain_runtime.py
  state_store/
    in_memory_store.py
    langgraph_postgres_store.py
    session_transcript_store.py
src/agent_1_after_sales/app_api/services/
  after_sales_assistant.py
  after_sales_run_projector.py
tests/
  test_langchain_runtime.py
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
10. 写 runtime 单元测试，先覆盖直接回复，再覆盖工具调用和审批暂停。

先安装本章新增依赖。第 8 章只安装了 chat model 相关依赖，本章开始使用 LangGraph 的中断和 checkpoint 概念：

```bash
uv add langchain langgraph langgraph-checkpoint-postgres
```

`langchain` 提供 agent/runtime 相关封装，`langgraph` 提供中断和恢复执行能力，
`langgraph-checkpoint-postgres` 用于后续把 checkpoint 持久化到 PostgreSQL。
起步测试可以先用内存状态存储，但依赖要在这一章讲清楚，否则写到
`from langgraph.types import interrupt` 时会直接 `ModuleNotFoundError`。

### 示例代码

先把测试会 import 的两个文件创建出来。下面是起步版，只覆盖“没有工具调用的直接回复”。
工具调用、审批暂停和持久化 checkpoint 会在这个基础上继续扩展。

`in_memory_store.py`：

```python
"""
内存版 Agent 状态存储。

这个文件解决的问题是：本地和单元测试可以先不依赖 PostgreSQL checkpoint，
同时让 runtime 先拥有一个可替换的 state store 接口。
"""

from __future__ import annotations

from typing import Any


class InMemoryStateStore:
    """
    本地和测试用的内存状态存储。

    它不适合生产，因为进程重启后状态会丢失。
    但它能解决起步阶段的两个问题：

    1. runtime 测试不需要启动 PostgreSQL。
    2. `LangChainAgentRuntime` 可以先依赖一个稳定的 state store 接口。
    """

    def __init__(self) -> None:
        self._runs: dict[str, dict[str, Any]] = {}  # run_id 到运行状态的内存映射。

    async def save_run(self, run_id: str, state: dict[str, Any]) -> None:
        # 保存一份浅拷贝，避免调用方后续修改 state 时影响 store 内部状态。
        self._runs[run_id] = dict(state)

    async def get_run(self, run_id: str) -> dict[str, Any] | None:
        # 返回浅拷贝，解决测试或调用方误改内部状态的问题。
        state = self._runs.get(run_id)
        return dict(state) if state is not None else None

    async def close(self) -> None:
        """
        和后续 Postgres store 保持同名关闭方法。

        内存 store 没有外部连接，这里清空数据即可。
        """

        self._runs.clear()
```

`langchain_runtime.py` 的起步版：

```python
"""
LangChain Agent runtime 起步实现。

这个文件解决的问题是：把 AgentDefinition、chat model 和 RunEvent 串起来，
先跑通直接回复，再逐步扩展工具调用、审批中断和恢复执行。
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from uuid import uuid4

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage

from agent_1_after_sales.agent_service.contracts.capability import AgentDefinition
from agent_1_after_sales.agent_service.contracts.events import OutputDeltaEvent, RunCompletedEvent, RunEvent, RunStartedEvent
from agent_1_after_sales.agent_service.contracts.models import ActorContext, AgentRunResult


class LangChainAgentRuntime:
    """
    LangChain runtime 的起步实现。

    这一版先只做直接回复，不处理工具调用和审批中断。
    这样做解决的问题是：先让 `tests/test_langchain_runtime.py` 能跑通，
    再逐步把工具、事件映射、interrupt、resume 加进去，避免一上来堆太多概念。
    """

    def __init__(
        self,
        *,
        model: BaseChatModel,
        state_store: object,
        max_steps: int,
    ) -> None:
        self._model = model  # LangChain chat model，测试时可以传 fake model。
        self._state_store = state_store  # 状态存储，起步版暂时只保存 run 基本信息。
        self._max_steps = max_steps  # 最大执行步数，后续工具循环会用它防止无限调用。

    async def stream_run(
        self,
        *,
        definition: AgentDefinition,
        message: str,
        session_id: str | None,
        actor: ActorContext,
    ) -> AsyncIterator[RunEvent]:
        """
        执行一次 Agent run，并以项目自己的 RunEvent 输出。

        这里不把 LangChain 原始事件直接抛给 API。
        这解决的问题是：API、前端和测试只依赖项目稳定的事件契约，
        后续底层 runtime 从 LangChain 换成别的实现时，外部契约不用跟着变。
        """

        del actor
        run_id = f"run-{uuid4().hex[:8]}"
        resolved_session_id = session_id or f"session-{uuid4().hex[:8]}"

        if hasattr(self._state_store, "save_run"):
            await self._state_store.save_run(
                run_id,
                {
                    "session_id": resolved_session_id,
                    "capability_id": definition.capability_id,
                    "status": "running",
                    "max_steps": self._max_steps,
                },
            )

        yield RunStartedEvent(
            run_id=run_id,
            session_id=resolved_session_id,
            capability_id=definition.capability_id,
        )

        response = await self._model.ainvoke(
            [
                SystemMessage(content=definition.system_prompt),
                HumanMessage(content=message),
            ]
        )
        output = str(response.content)

        yield OutputDeltaEvent(run_id=run_id, delta=output)

        result = AgentRunResult(
            run_id=run_id,
            session_id=resolved_session_id,
            capability_id=definition.capability_id,
            status="completed",
            output=output,
        )
        yield RunCompletedEvent(result=result)
```

简化版 `_to_langchain_tool()`：

```python
"""
ToolSpec 到 LangChain tool 的适配片段。

这个片段通常放在 langchain_runtime.py 中，解决项目内部工具契约
和 LangChain StructuredTool 之间的转换问题。
"""

from __future__ import annotations

from typing import Any

from langchain_core.tools import StructuredTool
from langchain_core.tools.base import BaseTool

from agent_1_after_sales.agent_service.contracts.actions import ToolContext, ToolSpec


def to_langchain_tool(tool_spec: ToolSpec) -> BaseTool:
    """
    把项目内部 ToolSpec 转成 LangChain 可执行工具。

    这样 LangChain runtime 只依赖 adapter，业务工具仍然保持项目自己的 contract。

    这解决的问题是：项目内部可以用自己的 ToolSpec 表达工具，
    不被 LangChain 的工具类型绑死。未来换 runtime 时，只需要重写 adapter。
    """

    async def runner(**kwargs: Any) -> tuple[str, dict[str, Any]]:
        """
        LangChain 实际调用的工具函数。

        kwargs 来自模型生成的工具参数。这里把 kwargs 重新交给 ToolSpec.handler，
        并补上 ToolContext，解决“模型参数”和“系统上下文”混在一起的问题。
        """

        # LangChain tool 的 kwargs 来自模型生成的工具参数。
        result = await tool_spec.handler(
            kwargs,
            ToolContext(capability_id="after_sales_assistant"),
        )
        # content 给模型继续推理，artifact 给 runtime 或投影层保留结构化结果。
        envelope = {"success": True, "action": tool_spec.name, "result": result}
        return str(envelope), envelope

    return StructuredTool.from_function(
        coroutine=runner,  # 异步工具执行函数，LangChain 调用工具时会执行它。
        name=tool_spec.name,  # 暴露给模型的工具名，必须和 ToolSpec 保持一致。
        description=tool_spec.description,  # 暴露给模型的工具说明，影响模型是否选择该工具。
        args_schema=tool_spec.args_schema,  # 工具参数 schema，LangChain 会把它转成 provider tool schema。
        response_format="content_and_artifact",  # 同时返回文本 content 和结构化 artifact，方便模型和系统各取所需。
    )
```

简化版审批中断逻辑：

```python
"""
工具审批中断片段。

这个片段通常放在 langchain_runtime.py 中，解决高风险工具调用
在真正执行前需要暂停并等待人工审批的问题。
"""

from __future__ import annotations

from langgraph.types import interrupt

from agent_1_after_sales.agent_service.contracts.models import AgentPendingAction


def maybe_interrupt_for_approval(
    *,
    tool_name: str,
    tool_arguments: dict,
    action_id: str,
    requirement,
) -> object | None:
    """
    如果工具调用命中审批策略，就触发 LangGraph interrupt。

    返回 None 表示不需要暂停；返回 interrupt 结果表示当前 run 等待外部 resume。

    这解决的问题是：高风险工具调用不能直接执行，但也不能丢失当前 run 状态。
    interrupt 会把当前执行挂起，审批通过后可以从同一个状态继续。
    """

    # requirement 来自 ToolSpec.approval_policy.evaluate。
    if requirement is None:
        return None

    pending_action = AgentPendingAction(
        action_id=action_id,  # 待审批动作 id。
        action_name=tool_name,  # 原本准备执行的工具名。
        action_payload=tool_arguments,  # 工具参数，审批通过后继续使用。
        reason=requirement.reason,  # 展示给审批人的原因。
        risk_level=requirement.risk_level,  # 风险等级。
        display_payload=requirement.display_payload or {},  # 前端展示用精简 payload。
    )

    # interrupt 会把当前 run 暂停，后续通过 Command(resume=...) 恢复。
    return interrupt({"pending_action": pending_action.model_dump(mode="json")})
```

`AfterSalesAssistantService` 的作用：

```python
"""
售后 Agent 应用服务。

这个文件解决的问题是：把 runtime、AgentDefinition 和事件投影器封装起来，
让 HTTP route 只调用 run/stream，不直接操作底层 runtime。
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from agent_1_after_sales.agent_service.contracts.events import RunCompletedEvent, RunEvent
from agent_1_after_sales.agent_service.contracts.models import ActorContext, AgentRunResult


class AfterSalesAssistantService:
    """
    售后 Agent 的应用服务。

    它把 runtime、definition 和 projector 串起来，对 route 暴露 run/stream 两种入口。

    这解决的问题是：HTTP route 不直接操作 runtime，也不负责记录审计日志。
    route 只调用 assistant service，assistant service 统一处理执行和投影。
    """

    def __init__(self, *, runtime, definition, projector) -> None:
        self._runtime = runtime  # 真正执行 Agent 的 runtime。
        self._definition = definition  # 售后 Agent 的 prompt 和工具定义。
        self._projector = projector  # 把事件记录到日志/审批表/审计表。

    async def run(
        self,
        *,
        message: str,
        session_id: str | None,
        actor: ActorContext,
    ) -> AgentRunResult:
        """
        执行一次同步 Agent run。

        这里的“同步”不是阻塞线程，而是指 HTTP 调用方等待最终 RunCompletedEvent。
        内部仍然消费同一套 stream，避免同步接口和 SSE 接口出现两套执行逻辑。
        """

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
        """
        执行一次流式 Agent run。

        runtime 负责产出事件；projector 负责把事件落到日志、审批记录和审计表；
        API 层负责把事件转换成 JSON 或 SSE。
        """

        async for event in self._runtime.stream_run(
            definition=self._definition,
            message=message,
            session_id=session_id,
            actor=actor,
        ):
            # 所有事件先投影，再交给 API 层返回，保证审计记录不丢。
            await self._projector.record_event(event)
            yield event
```

`after_sales_run_projector.py` 的起步版：

```python
"""
Agent run 事件投影器。

这个文件解决的问题是：给事件落库和审计预留统一入口，
后续扩展 tool log、approval record 和 audit log 时不改 route/runtime。
"""

from __future__ import annotations

from agent_1_after_sales.agent_service.contracts.events import RunEvent


class AfterSalesRunProjector:
    """
    Agent 事件投影器。

    起步版先不写数据库，只保留统一入口。
    这解决的问题是：`AfterSalesAssistantService` 可以从第一版开始就调用
    `record_event()`，后续把 tool log、approval record、audit log 落库时，
    不需要改 route 和 runtime 的调用方式。
    """

    async def record_event(self, event: RunEvent) -> None:
        # 起步版只消费事件，不落库。完整实现会按事件类型写审计日志和审批记录。
        del event
```

`tests/test_langchain_runtime.py` 的起步测试：

```python
"""
LangChain runtime 单元测试。

这个文件解决的问题是：用 fake chat model 和内存状态存储验证 runtime
能产出 completed 结果，不依赖真实 LLM 或外部数据库。
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest

from agent_1_after_sales.agent_service.contracts.capability import AgentDefinition
from agent_1_after_sales.agent_service.contracts.events import RunCompletedEvent, RunEvent
from agent_1_after_sales.agent_service.contracts.models import ActorContext, AgentRunResult
from agent_1_after_sales.agent_service.infrastructure.runtime.langchain_runtime import LangChainAgentRuntime
from agent_1_after_sales.agent_service.infrastructure.state_store.in_memory_store import InMemoryStateStore
from tests.fake_chat_models import DeterministicToolCallingChatModel


async def collect_result(stream: AsyncIterator[RunEvent]) -> AgentRunResult:
    """
    从事件流里取出最终 RunCompletedEvent，方便测试断言。

    这解决的问题是：runtime 对外暴露的是事件流，测试最终状态时不能只看第一条事件。
    helper 会消费完整 stream，直到拿到最终结果。
    """

    async for event in stream:
        if isinstance(event, RunCompletedEvent):
            return event.result
    raise AssertionError("stream finished without RunCompletedEvent")


@pytest.mark.asyncio
async def test_runtime_completes_direct_reply() -> None:
    # Arrange：使用 fake model 和内存状态存储，不依赖外部服务。
    runtime = LangChainAgentRuntime(
        model=DeterministicToolCallingChatModel(),
        state_store=InMemoryStateStore(),
        max_steps=4,
    )
    definition = AgentDefinition(
        capability_id="test_assistant",
        system_prompt="你是测试助手。",
        tools=(),
    )

    # Act：执行一次没有工具的普通对话。
    result = await collect_result(
        runtime.stream_run(
            definition=definition,
            message="hello",
            session_id="session-1",
            actor=ActorContext(),
        )
    )

    # Assert：runtime 应该返回 completed，并沿用传入的 session_id。
    assert result.status == "completed"
    assert result.session_id == "session-1"
```

### 如何运行或验证

单元测试优先：

```bash
uv run pytest tests/test_langchain_runtime.py -q
uv run pytest tests/test_langchain_runtime.py -q -k pauses
uv run pytest tests/test_langchain_runtime.py -q -k rejected
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

如果要从 HTTP 入口观察同类流程，先启动服务，再用第 12 章的 SSE curl。SSE 要用 `curl -N`，因为 `-N` 会关闭 curl 的输出缓冲，让你看到服务端一条一条推送出来的事件；没有 `-N` 时，终端可能等缓冲区满了才显示。

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
src/agent_1_after_sales/app_api/bootstrap.py
src/agent_1_after_sales/app_api/container.py
src/agent_1_after_sales/app_api/deps.py
src/agent_1_after_sales/app_api/routers/after_sales_runs.py
src/agent_1_after_sales/app_api/routers/after_sales_approvals.py
src/agent_1_after_sales/app_api/routers/agents.py
src/agent_1_after_sales/app_api/routers/health.py
src/agent_1_after_sales/app_api/migrations.py
src/agent_1_after_sales/app_api/cli/doctor.py
src/agent_1_after_sales/app_api/cli/migrate.py
scripts/seed.py
migrations/
compose.yaml
Makefile
tests/
  integration/
    helpers.py
    test_app_api.py
  test_langchain_runtime.py
  test_model_factory.py
  test_settings.py
```

### 推荐目录结构

```text
src/agent_1_after_sales/app_api/
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
  integration/
    helpers.py
    test_app_api.py
  test_langchain_runtime.py
  test_model_factory.py
  test_settings.py
```

### 关键概念讲解

同步 run API：后端消费完整 Agent stream，只把最终 `RunResponse` 返回给调用方。

SSE stream API：把每个 `RunEvent` 转成 `event:` 和 `data:` 返回给前端。

Approval action API：提交 `approved` 或 `rejected`，恢复某个 paused run。

Projection：把运行事件投影成业务数据库里的 tool log、approval record 和 audit log。

Alembic：版本化管理数据库 schema。

Migration：不是手写一个随便执行的 SQL 文件，也不是依赖 `create_all()` 自动建表。当前项目的迁移文件应该通过 Alembic 命令生成 revision，再由开发者检查生成内容是否符合预期。

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
11. 用 Alembic 命令生成 migration revision，人工检查后再执行迁移，并补 seed 数据。
12. 创建集成测试 helper，集中构造临时数据库、测试 app 和 fake model。
13. 写 API 集成测试，覆盖 health、业务 API、同步 run、SSE run、审批恢复。
14. 写 pytest、ruff、mypy 质量门槛。

先安装第 12 章新增依赖。前面章节已经有 FastAPI、SQLAlchemy 和 LangChain 基础依赖，
这一章开始需要 SSE、迁移和 PostgreSQL 驱动：

```bash
uv add sse-starlette alembic "psycopg[binary]"
```

`sse-starlette` 解决 FastAPI 直接返回 SSE 事件流的问题。
`alembic` 解决数据库 schema 版本化迁移的问题。
`psycopg[binary]` 解决后续本地 PostgreSQL 和 LangGraph checkpoint 连接驱动问题。

### 示例代码

第 12 章要先扩展第 10 章的容器和装配入口。否则下面的
`after_sales_runs.py` 会 import `get_after_sales_assistant_service`，测试 helper
也会调用 `create_app(..., chat_model_override=...)`，但前面的代码还没有这些入口。

扩展 `container.py`：

```python
"""
最终应用运行时容器。

这个文件解决的问题是：把普通业务 API、Agent catalog 和 Agent run 服务
统一放进容器，并允许 LLM 不可用时只关闭 Agent run 能力。
"""

from __future__ import annotations

from dataclasses import dataclass

from agent_1_after_sales.agent_service.contracts.registry import AgentRegistry
from agent_1_after_sales.app_api.services.after_sales_assistant import AfterSalesAssistantService
from agent_1_after_sales.app_api.settings import AppSettings
from agent_1_after_sales.business_service.after_sales.application.services.after_sales_service import AfterSalesService
from agent_1_after_sales.business_service.after_sales.infrastructure.persistence.sqlalchemy.session import BusinessDatabase


@dataclass(slots=True)
class AppContainer:
    """
    应用运行时依赖容器。

    第 12 章在第 10 章基础上新增 `after_sales_assistant_service`。
    它允许为空，是因为本地没有 LLM key 时应用仍然应该能启动普通业务 API，
    只是 Agent run 接口返回 503。
    """

    settings: AppSettings  # 当前应用配置。
    business_database: BusinessDatabase  # 售后业务数据库入口。
    after_sales_service: AfterSalesService  # 普通业务 API 使用的售后 service。
    agent_registry: AgentRegistry  # Agent catalog 使用的能力注册表。
    after_sales_assistant_service: AfterSalesAssistantService | None = None  # Agent run API 使用的应用服务。

    async def close(self) -> None:
        """
        释放容器持有的外部资源。

        这解决的问题是：测试和开发服务器反复启动时不能留下数据库连接池。
        后续如果 runtime/state store 持有外部连接，也应该在这里统一释放。
        """

        await self.business_database.dispose()
```

扩展 `deps.py`：

```python
"""
最终版 FastAPI dependency。

这个文件解决的问题是：统一提供普通业务 service、Agent registry、
Agent assistant service 和 API key 鉴权，route 不直接操作 app.state。
"""

from __future__ import annotations

from typing import Annotated, cast

from fastapi import Depends, Header, HTTPException, Request

from agent_1_after_sales.agent_service.contracts.registry import AgentRegistry
from agent_1_after_sales.app_api.container import AppContainer
from agent_1_after_sales.app_api.services.after_sales_assistant import AfterSalesAssistantService
from agent_1_after_sales.business_service.after_sales.application.services.after_sales_service import AfterSalesService


async def get_container(request: Request) -> AppContainer:
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


async def get_agent_registry(
    container: Annotated[AppContainer, Depends(get_container)],
) -> AgentRegistry:
    return container.agent_registry


async def get_after_sales_assistant_service(
    container: Annotated[AppContainer, Depends(get_container)],
) -> AfterSalesAssistantService:
    """
    从容器中取出售后 Agent 应用服务。

    这解决的问题是：LLM key 缺失或 runtime 初始化失败时，应用仍可启动，
    但 run 接口会明确返回 503，而不是在 route 内部出现 NoneType 错误。
    """

    service = container.after_sales_assistant_service
    if service is None:
        raise HTTPException(status_code=503, detail="assistant service unavailable")
    return service
```

扩展 `bootstrap.py`：

```python
"""
最终版应用装配入口。

这个文件解决的问题是：把数据库、UoW、业务 service、AgentDefinition、
LLM、runtime 和 assistant service 装配成一个可运行的容器。
"""

from __future__ import annotations

from contextlib import AbstractAsyncContextManager

from langchain_core.language_models.chat_models import BaseChatModel

from agent_1_after_sales.agent_service.contracts.registry import AgentRegistry
from agent_1_after_sales.agent_service.infrastructure.runtime.langchain_runtime import LangChainAgentRuntime
from agent_1_after_sales.agent_service.infrastructure.state_store.in_memory_store import InMemoryStateStore
from agent_1_after_sales.agent_service.llm.factory import build_chat_model
from agent_1_after_sales.app_api.container import AppContainer
from agent_1_after_sales.app_api.services.after_sales_agent_definition import build_after_sales_agent_definition
from agent_1_after_sales.app_api.services.after_sales_assistant import AfterSalesAssistantService
from agent_1_after_sales.app_api.services.after_sales_run_projector import AfterSalesRunProjector
from agent_1_after_sales.app_api.settings import AppSettings
from agent_1_after_sales.business_service.after_sales.application.ports import AfterSalesUnitOfWork
from agent_1_after_sales.business_service.after_sales.application.services.after_sales_service import AfterSalesService
from agent_1_after_sales.business_service.after_sales.infrastructure.persistence.sqlalchemy.session import BusinessDatabase
from agent_1_after_sales.business_service.after_sales.infrastructure.persistence.sqlalchemy.unit_of_work import SqlAlchemyAfterSalesUnitOfWork


async def build_container(
    settings: AppSettings,
    *,
    chat_model_override: BaseChatModel | None = None,
) -> AppContainer:
    """
    创建最终应用容器。

    `chat_model_override` 只给测试使用。它解决的问题是：API 集成测试可以走完整
    FastAPI lifespan 和 route，但不请求真实 LLM。
    """

    business_database = BusinessDatabase(settings.business_database_url)
    if settings.auto_create_schema:
        # 测试和本地教学可以自动建表；生产环境应使用 Alembic migration。
        await business_database.create_schema()

    def unit_of_work_factory() -> AbstractAsyncContextManager[AfterSalesUnitOfWork]:
        return SqlAlchemyAfterSalesUnitOfWork(business_database.managed_session)

    after_sales_service = AfterSalesService(unit_of_work_factory=unit_of_work_factory)
    definition = build_after_sales_agent_definition(after_sales_service=after_sales_service)

    agent_registry = AgentRegistry()
    agent_registry.register(definition)

    assistant_service: AfterSalesAssistantService | None = None
    try:
        chat_model = chat_model_override or build_chat_model(
            llm_provider=settings.llm_provider,
            llm_model=settings.llm_model,
            llm_timeout_seconds=settings.llm_timeout_seconds,
            llm_max_retries=settings.llm_max_retries,
            deepseek_api_key=settings.deepseek_api_key.get_secret_value() if settings.deepseek_api_key else None,
            openai_api_key=settings.openai_api_key.get_secret_value() if settings.openai_api_key else None,
        )
        runtime = LangChainAgentRuntime(
            model=chat_model,
            state_store=InMemoryStateStore(),
            max_steps=settings.max_steps,
        )
        assistant_service = AfterSalesAssistantService(
            runtime=runtime,
            definition=definition,
            projector=AfterSalesRunProjector(),
        )
    except ValueError:
        # 没有 LLM key 时不阻止普通业务 API 启动，Agent run 接口由 dependency 返回 503。
        assistant_service = None

    return AppContainer(
        settings=settings,
        business_database=business_database,
        after_sales_service=after_sales_service,
        agent_registry=agent_registry,
        after_sales_assistant_service=assistant_service,
    )
```

扩展 `main.py`：

```python
"""
最终版 FastAPI 应用工厂。

这个文件解决的问题是：支持测试注入 fake chat model，
同时注册 health、普通售后 API、Agent catalog 和 Agent run 路由。
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from langchain_core.language_models.chat_models import BaseChatModel
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from agent_1_after_sales.app_api.bootstrap import build_container
from agent_1_after_sales.app_api.routers.after_sales_resources import router as after_sales_router
from agent_1_after_sales.app_api.routers.after_sales_runs import router as after_sales_runs_router
from agent_1_after_sales.app_api.routers.agents import router as agents_router
from agent_1_after_sales.app_api.routers.health import router as health_router
from agent_1_after_sales.app_api.settings import AppSettings


def create_lifespan(
    settings: AppSettings,
    *,
    chat_model_override: BaseChatModel | None = None,
):
    """
    创建 FastAPI lifespan，并把测试用 override 传给 bootstrap。

    这解决的问题是：测试需要替换 LLM，但不应该在 route 层写测试分支。
    """

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
        container = await build_container(
            settings,
            chat_model_override=chat_model_override,
        )
        app.state.settings = settings
        app.state.container = container
        try:
            yield
        finally:
            await container.close()

    return lifespan


def create_app(
    settings: AppSettings | None = None,
    *,
    chat_model_override: BaseChatModel | None = None,
) -> FastAPI:
    """
    创建 FastAPI app。

    `chat_model_override` 解决测试不能请求真实 LLM 的问题；
    生产代码不传这个参数，就会按配置创建真实 provider model。
    """

    resolved_settings = settings or AppSettings()
    app = FastAPI(
        title="After-Sales Agent API",
        version="1.0.0",
        lifespan=create_lifespan(
            resolved_settings,
            chat_model_override=chat_model_override,
        ),
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=resolved_settings.parsed_cors_allowed_origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(health_router)
    app.include_router(after_sales_router)
    app.include_router(agents_router)
    app.include_router(after_sales_runs_router)
    return app
```

`after_sales_runs.py` 核心接口：

```python
"""
售后 Agent run HTTP API。

这个文件解决的问题是：提供同步 run 和 SSE stream 两种入口，
并把内部 RunEvent 转换成 HTTP response 或浏览器可消费的 SSE 事件。
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import APIRouter, Depends
from sse_starlette.sse import EventSourceResponse

from agent_1_after_sales.agent_service.contracts.events import OutputDeltaEvent, RunCompletedEvent, RunStartedEvent
from agent_1_after_sales.agent_service.contracts.models import ActorContext
from agent_1_after_sales.app_api.deps import get_after_sales_assistant_service, require_api_key
from agent_1_after_sales.app_api.schemas.runs import CreateRunRequest, RunResponse

router = APIRouter(prefix="/api/after-sales", tags=["after-sales-runs"])


def encode_sse(event: str, payload: dict[str, object]) -> dict[str, str]:
    """
    把内部事件转成 sse-starlette 需要的字典格式。

    SSE 的 `data` 必须是字符串，所以这里统一用 JSON 编码。

    这解决的问题是：内部事件是 Python/Pydantic 对象，浏览器 EventSource
    只能接收文本协议。统一编码可以避免每个事件分支各自处理 JSON。
    """

    return {"event": event, "data": json.dumps(payload, ensure_ascii=False)}


async def sse_stream(stream: AsyncIterator[object]) -> AsyncIterator[dict[str, str]]:
    """
    把 Agent runtime 的事件流转换为浏览器可消费的 SSE 事件流。

    这里只展示核心事件；完整项目还可以继续映射 tool.started、approval.required 等事件。

    这解决的问题是：API 层不把 LangChain/LangGraph 原始事件直接暴露给前端。
    前端只依赖项目自己的事件名，例如 `run.started`、`output.delta`。
    """

    async for event in stream:
        if isinstance(event, RunStartedEvent):
            # run.started 告诉前端一次执行已经创建。
            yield encode_sse("run.started", {"run_id": event.run_id, "session_id": event.session_id})
        elif isinstance(event, OutputDeltaEvent):
            # output.delta 是模型输出的增量文本。
            yield encode_sse("output.delta", {"run_id": event.run_id, "delta": event.delta})
        elif isinstance(event, RunCompletedEvent):
            # run.completed 携带最终结构化结果。
            yield encode_sse("run.completed", event.result.model_dump(mode="json"))


@router.post("/runs", response_model=RunResponse)
async def create_run(
    payload: CreateRunRequest,
    assistant_service: Annotated[object, Depends(get_after_sales_assistant_service)],
    _: None = Depends(require_api_key),
) -> RunResponse:
    """
    创建一次同步 Agent run。

    这里的同步表示 HTTP 请求会等待最终结果或等待审批状态。
    它解决的是普通后端调用方不想处理 SSE，只想拿一个 JSON 结果的场景。
    """

    result = await assistant_service.run(
        message=payload.message,
        session_id=payload.session_id,
        actor=ActorContext(actor_id=payload.actor_id, metadata=payload.actor_metadata),
    )
    # result 是内部 contract，RunResponse 是 HTTP response schema，这里做一次边界转换。
    return RunResponse.model_validate(result.model_dump(mode="json"))


@router.post("/runs/stream")
async def stream_run(
    payload: CreateRunRequest,
    assistant_service: Annotated[object, Depends(get_after_sales_assistant_service)],
    _: None = Depends(require_api_key),
) -> EventSourceResponse:
    """
    创建一次流式 Agent run。

    它立即返回 SSE 连接，后续把 token、工具调用、完成事件逐条推送给前端。
    这解决的是聊天界面需要边生成边展示的问题。
    """

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
    image: postgres:16  # 固定主版本，解决不同机器拉到不同数据库大版本导致行为不一致的问题。
    container_name: agent-postgres  # 固定容器名，方便 docker exec / 日志排查。
    environment:
      POSTGRES_USER: agent  # 本地数据库用户名。
      POSTGRES_PASSWORD: agent  # 本地数据库密码，只用于开发环境。
      POSTGRES_DB: agent_platform  # 默认创建的数据库名。
    ports:
      - "5432:5432"  # 把容器端口映射到宿主机，解决本地后端无法连接容器数据库的问题。
    volumes:
      - pgdata:/var/lib/postgresql/data  # 持久化数据，解决容器重启后数据库内容丢失的问题。

  redis:
    image: redis:7  # 后续如果接缓存/队列，可以复用这个服务。
    container_name: agent-redis  # 固定容器名，方便本地排查。
    ports:
      - "6379:6379"  # 暴露 Redis 本地端口。

volumes:
  pgdata:  # 命名 volume，由 Docker 管理生命周期。
```

教学版可选新增 `Dockerfile`：

```dockerfile
FROM python:3.12-slim

# 固定容器内工作目录，解决后续 COPY/RUN 路径不一致的问题。
WORKDIR /app

# 先复制依赖文件，利用 Docker layer cache 加速重复构建。
COPY pyproject.toml uv.lock ./
# 使用 uv.lock 安装固定版本依赖，解决构建不可复现的问题。
RUN pip install uv && uv sync --frozen --no-dev

# 复制应用源码。
COPY src ./src
# 复制迁移文件，解决容器内无法执行数据库迁移的问题。
COPY migrations ./migrations
# 复制 Alembic 配置。
COPY alembic.ini ./alembic.ini

CMD [".venv/bin/python", "-m", "uvicorn", "agent_1_after_sales.app_api.main:create_app", "--factory", "--app-dir", "src", "--host", "0.0.0.0", "--port", "8000"]
```

### 测试文件怎么组织

第 12 章不要把所有测试都塞进一个文件。建议这样创建：

```bash
mkdir -p tests/integration
touch tests/integration/helpers.py
touch tests/integration/test_app_api.py
```

`tests/integration/helpers.py` 负责复用测试装配：

```python
"""
API 集成测试 helper。

这个文件解决的问题是：集中创建带临时数据库和 fake chat model 的测试 app，
避免每个集成测试都重复写同一套装配代码。
"""

from __future__ import annotations

from pathlib import Path

from agent_1_after_sales.app_api.main import create_app
from agent_1_after_sales.app_api.settings import AppSettings
from tests.fake_chat_models import DeterministicToolCallingChatModel


def build_test_app(database_path: Path):
    """
    构造集成测试专用 app。

    每个测试传入独立数据库文件，并注入 deterministic fake model，
    这样 API 集成测试既走完整应用装配，又不依赖真实 LLM。

    这解决的问题是：集成测试需要走真实 FastAPI lifespan、router、service 装配，
    但不能共享数据库文件，也不能请求真实模型服务。
    """

    database_url = f"sqlite+pysqlite:///{database_path}"  # 每个测试独立数据库，解决测试数据互相污染的问题。
    return create_app(
        AppSettings(
            app_env="test",  # test 环境放宽真实密钥和生产配置要求。
            business_database_url=database_url,  # 指向临时 SQLite 文件。
            auto_create_schema=True,  # 测试启动时自动建表，解决测试前手动迁移的负担。
        ),
        chat_model_override=DeterministicToolCallingChatModel(),  # 注入 fake model，解决测试依赖真实 LLM 的问题。
    )
```

`tests/integration/test_app_api.py` 先从最小闭环开始：

```python
"""
最终 API 集成测试。

这个文件解决的问题是：从 HTTP 入口验证 health、lifespan、assistant service
和 runtime 的最小闭环，不依赖真实端口或真实 LLM。
"""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from tests.integration.helpers import build_test_app


@pytest.mark.asyncio
async def test_health_endpoint_reports_status(tmp_path: Path) -> None:
    # Arrange：创建带临时数据库的测试 app。
    # tmp_path 保证每次测试都有独立文件目录，解决本地残留数据库影响断言的问题。
    app = build_test_app(tmp_path / "health.db")
    async with app.router.lifespan_context(app):
        # Act：通过 ASGITransport 调用 /health。
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            response = await client.get("/health")

    # Assert：health 可以根据依赖状态返回 ok 或 degraded。
    assert response.status_code == 200
    assert response.json()["status"] in {"ok", "degraded"}


@pytest.mark.asyncio
async def test_agent_run_endpoint_returns_run_response(tmp_path: Path) -> None:
    # Arrange：创建测试 app，fake model 会返回稳定结果。
    # 这里测试的是 HTTP -> assistant service -> runtime 的最小闭环，而不是模型质量。
    app = build_test_app(tmp_path / "run.db")
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            # Act：调用同步 run 接口。
            response = await client.post(
                "/api/after-sales/runs",
                json={"message": "你好", "session_id": "test-session"},
            )

    # Assert：响应符合 RunResponse 的基本契约。
    assert response.status_code == 200
    body = response.json()
    assert body["run_id"].startswith("run-")
    assert body["session_id"] == "test-session"
    assert body["status"] in {"completed", "awaiting_action", "failed"}
```

然后再逐步加场景：

```text
test_after_sales_resources_routes_and_sync_run
  验证业务 API 和同步 Agent run。

test_refund_stream_action_and_audit_projection
  验证 SSE 先返回 action.required，再通过 /actions 恢复。

test_invalid_action_id_does_not_resolve_approval
  验证错误 action_id 返回 409，approval record 仍是 pending。

test_same_session_allows_new_run_while_previous_run_waits_for_approval
  验证 run_id 和 session_id 分离，不会互相阻塞。
```

### 如何运行或验证

本地 SQLite 快速验证：

```bash
uv sync --extra dev
cp .env.example .env
make seed
make start
curl http://127.0.0.1:8000/health
```

另开一个 WSL 终端查看服务和端口：

```bash
ss -ltnp | grep 8000 || true
ps -ef | grep uvicorn
make doctor
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
uv run pytest tests/test_settings.py -q
uv run pytest tests/test_model_factory.py -q
uv run pytest tests/test_langchain_runtime.py -q
uv run pytest tests/integration/test_app_api.py -q
uv run pytest -q
uv run ruff check src tests scripts
uv run mypy src
```

数据库迁移和种子数据：

```bash
make migrate
make seed
make doctor
```

当你修改了 SQLAlchemy ORM model，例如新增表、字段或索引，正确流程是先生成 migration revision：

```bash
DATABASE_URL=sqlite+pysqlite:///./after_sales_mvp.db \
  uv run alembic revision --autogenerate -m "add after sales mvp tables"
```

然后打开 `migrations/versions/` 下新生成的文件，检查 `upgrade()` 和 `downgrade()` 是否符合预期。确认无误后再执行：

```bash
DATABASE_URL=sqlite+pysqlite:///./after_sales_mvp.db uv run alembic upgrade head
```

项目里的 `make migrate` 是对应用迁移入口的封装，读取的是 `BUSINESS_DATABASE_URL` / `.env`：

```bash
BUSINESS_DATABASE_URL=sqlite+pysqlite:///./after_sales_mvp.db make migrate
```

两种方式的区别：

```text
uv run alembic revision --autogenerate ...
  生成新的 migration 文件，通常在开发表结构变更时使用

uv run alembic upgrade head
  执行已有 migration 到最新版本

make migrate
  调用项目封装的迁移入口，适合本地启动前把数据库升级到 head
```

不要手动凭感觉写完整 migration 文件。可以人工微调 Alembic 生成的 revision，但第一步应该让 Alembic 基于 `Base.metadata` 和当前数据库差异生成骨架。

使用 Docker Compose 启动 PostgreSQL 和 Redis：

```bash
docker compose up -d postgres redis
docker compose ps
```

如果要让 runtime checkpoint 使用 PostgreSQL，可以在 `.env` 中设置：

```bash
AGENT_RUNTIME_DATABASE_URL=postgresql://agent:agent@127.0.0.1:5432/agent_platform
```

然后重新启动后端：

```bash
make start
```

本教程默认先用 SQLite，是为了让业务主链路不依赖 Docker。PostgreSQL 更适合生产环境或需要 durable checkpoint 的场景。

### 常见错误

- LLM key 缺失：`/health` 会显示 degraded，`/api/after-sales/runs` 返回 503。
- 数据库缺表：运行 `make migrate` 或本地设置 `AUTO_CREATE_SCHEMA=true`。
- 修改 ORM 后忘记生成 Alembic revision：本地可能靠 `create_all()` 暂时跑通，但别人或生产数据库不会得到这次 schema 变更。
- Alembic autogenerate 后不检查文件：自动生成不是绝对正确，尤其是重命名字段、复杂默认值、JSON 类型和数据迁移要人工确认。
- SSE 没有事件：确认客户端使用 `curl -N`，不要被缓冲。
- 审批 action_id 错误：接口应返回 409，approval record 仍保持 pending。
- PostgreSQL runtime URL 写成同步驱动：项目会把 `postgresql://` 转成 `postgresql+psycopg://` 给 SQLAlchemy async 使用。
- MCP server 连接失败：应用可以继续启动，`/health` 的 `mcp.ok` 为 `false`。
- `Address already in use`：8000 端口已经被占用，先用 `ps -ef | grep uvicorn` 找进程，或用 `PORT=8001 make start` 换端口。
- `ModuleNotFoundError: agent_1_after_sales.app_api`：通常是没有通过 `uv run` 运行，或者 uvicorn 少了 `--app-dir src`。
- curl JSON 报错：WSL bash 里 JSON 外层建议用单引号，内部字段用双引号，例如 `-d '{"message":"hello"}'`。

### 面试时怎么讲

可以这样说：

> 这个项目的最终请求链路是 FastAPI route 进入 assistant service，assistant service 调用 LangChain runtime，runtime 根据 AgentDefinition 调用 ToolSpec，ToolSpec handler 再调用售后业务 service，业务 service 通过 Unit of Work 操作数据库。运行过程会投影成 tool log、approval record 和 audit log。高风险退款通过 LangGraph interrupt 暂停，审批后 resume 同一个 run。

---

## 完整项目扩展篇

前 12 章的目标是带你按主线完成一个可运行的售后 Agent 后端。接下来这一篇用于对齐当前仓库的完整项目能力。它们不应该一开始就压给新手，但如果你想说“我基本会这个项目了”，这些内容都要看懂。

完整项目能力地图：

| 扩展能力                      | 学完后要会什么                                             | 当前项目位置                                               |
| ----------------------------- | ---------------------------------------------------------- | ---------------------------------------------------------- |
| 最终版依赖和质量工具          | 看懂完整 `pyproject.toml`、`uv.lock`、`pyrightconfig.json` | `pyproject.toml`、`pyrightconfig.json`                     |
| MCP 外部工具接入              | 配置 MCP server，把外部工具变成 `ToolSpec`                 | `src/agent_1_after_sales/agent_service/infrastructure/mcp` |
| PostgreSQL durable checkpoint | 用 Postgres 保存 LangGraph checkpoint 和 transcript        | `langgraph_postgres_store.py`                              |
| 前端工作台                    | 看懂 React 前端如何调用 REST、SSE、审批接口                | `frontend/`                                                |
| Docker/部署口径               | 区分当前 compose 和教学建议 Dockerfile                     | `compose.yaml`                                             |

---

## 扩展 A：最终版依赖和质量工具

### 本章目标

把第 1 章的轻量 `pyproject.toml` 升级成当前项目完整版，理解每类依赖为什么存在，以及 `ruff`、`mypy`、Pyright 分别解决什么问题。

### 为什么要做这一步

第 1 章只安装了 FastAPI 起步依赖。当前项目真正跑起来还需要数据库、迁移、SSE、LangChain、LangGraph、MCP、LLM provider、token 统计和测试工具。如果不补这一章，学习者会懂骨架，但复刻不了当前项目。

### 本章要创建或修改哪些文件

```text
pyproject.toml
uv.lock
pyrightconfig.json
```

### 关键概念讲解

`pyproject.toml` 是项目依赖、打包和工具配置的入口。

`uv.lock` 锁定精确版本，保证不同机器安装到同一组依赖。

`ruff` 负责 lint 和导入排序，速度快，适合日常检查。

`mypy` 是当前仓库的命令行类型质量门槛。

`pyrightconfig.json` 主要服务 IDE/Pylance/Pyright，让编辑器知道 `src` 是 import 路径，质量门槛仍以 `mypy` 为主。

### 开发步骤

1. 保留第 1 章已有的 `build-system`、`project`、`setuptools`、`pytest` 配置。
2. 在 dependencies 中补数据库、迁移、SSE、LangChain/LangGraph、MCP、provider 和 tokenizer。
3. 在 dev optional dependencies 中保留 pytest、pytest-asyncio、httpx、ruff、mypy。
4. 添加 `ruff` 规则、FastAPI router 的 B008 豁免、mypy strict 配置。
5. 添加 `pyrightconfig.json`，让 IDE 从 `src` 解析项目包。
6. 执行 `uv sync --extra dev` 更新虚拟环境。

### 示例配置

最终依赖按类别理解，不要死记：

```text
基础后端:
  pydantic, pydantic-settings, fastapi, uvicorn

数据库:
  sqlalchemy, alembic, psycopg[binary], aiosqlite

Agent runtime:
  langchain, langgraph, langgraph-checkpoint-postgres

工具生态:
  langchain-mcp-adapters

LLM provider:
  langchain-deepseek, langchain-openai

流式和统计:
  sse-starlette, tiktoken

开发质量:
  pytest, pytest-asyncio, httpx, ruff, mypy
```

如果从轻量版升级，可以用这些命令逐步加依赖：

```bash
uv add sqlalchemy alembic "psycopg[binary]" aiosqlite
uv add sse-starlette
uv add langchain langgraph langgraph-checkpoint-postgres
uv add langchain-mcp-adapters langchain-deepseek langchain-openai
uv add tiktoken
uv add --optional dev pytest pytest-asyncio httpx ruff mypy
uv sync --extra dev
```

`pyrightconfig.json` 可以这样写：

```json
{
  "include": ["src", "tests"],
  "exclude": [".venv", "**/__pycache__"],
  "venvPath": ".",
  "venv": ".venv",
  "executionEnvironments": [
    {
      "root": ".",
      "extraPaths": ["src"]
    }
  ]
}
```

### 如何运行或验证

```bash
uv sync --extra dev
uv run pytest -q
uv run ruff check src tests scripts
uv run mypy src
```

如果 IDE 还提示找不到 `agent_1_after_sales.app_api`，重启 VS Code/Cursor 的 Python/Pylance server，并确认解释器选中 `.venv`。

### 常见错误

- 只复制第 1 章轻量依赖：后面 LangChain、SQLAlchemy、SSE 会 import 失败。
- 忘记 `asyncio_default_fixture_loop_scope = "session"`：pytest-asyncio 可能出现事件循环 fixture 警告。
- FastAPI router 里 `Depends(...)` 触发 `B008`：当前项目通过 `per-file-ignores` 对 router 层显式豁免。
- 以为 Pyright 和 mypy 二选一：当前仓库里 Pyright 更偏 IDE 体验，命令行门槛是 `mypy src`。

### 面试时怎么讲

可以这样说：

> 我用 `pyproject.toml` 管理运行依赖、开发依赖和质量工具。`uv.lock` 保证依赖可复现，`ruff` 做快速静态规则检查，`mypy strict` 保证后端核心代码类型质量，`pyrightconfig.json` 主要改善 IDE 对 `src` layout 的识别。

---

## 扩展 B：MCP 外部工具接入

### 本章目标

理解当前项目如何通过 `MCP_SERVERS` 配置外部 MCP server，并把 MCP tool 适配成项目内部统一的 `ToolSpec`。

### 为什么要做这一步

本项目主线工具来自售后业务 service，但真实 Agent 项目常常需要接外部工具。MCP 是一种标准化工具协议。当前项目把 MCP 工具放在扩展层，不让 MCP 协议进入业务层。

### 本章要创建或修改哪些文件

```text
src/agent_1_after_sales/app_api/settings.py
src/agent_1_after_sales/app_api/bootstrap.py
src/agent_1_after_sales/agent_service/infrastructure/mcp/tool_provider.py
tests/test_mcp_registry.py
```

### 关键概念讲解

`MCPServerConfig` 描述外部 server 怎么连，支持 `http`、`streamable_http` 和 `stdio`。

`MCPToolProvider` 用 `MultiServerMCPClient` 加载外部工具。

加载到的 MCP tool 会被转换成 `ToolSpec`，并统一命名为 `mcp_{server}_{tool}`。

MCP 加载失败不会让应用启动失败，而是让 `/health` 返回 degraded，同时本地售后 agent 仍可运行。

### 开发步骤

1. 在 settings 中增加 `mcp_servers: dict[str, MCPServerConfig]`。
2. 在 settings validator 中校验 http 必须有 `url`，stdio 必须有 `command`。
3. 在 `MCPToolProvider.load_tools()` 中加载外部工具。
4. 用 `_tool_spec_from_mcp_tool()` 把外部 tool 转成项目 `ToolSpec`。
5. 在 `bootstrap.load_mcp_tools()` 中捕获异常并生成 `DependencyStatus`。
6. 把 MCP tools 合并进售后 agent definition。
7. 用 `/api/agents/{capability_id}/tools` 验证 MCP tool 是否出现在工具目录。

### 示例配置

`.env`：

```env
MCP_SERVERS={"weather":{"transport":"http","url":"http://localhost:8000/mcp"}}
```

或 stdio：

```env
MCP_SERVERS={"math":{"transport":"stdio","command":"python","args":["./examples/math_server.py"]}}
```

验证配置解析：

```bash
uv run python - <<'PY'
from agent_1_after_sales.app_api.settings import AppSettings

# 这里读取 .env 中的 MCP_SERVERS。
settings = AppSettings()
print(settings.mcp_servers)
PY
```

### 如何运行或验证

```bash
uv run pytest tests/test_mcp_registry.py -q
uv run pytest tests/integration/test_app_api.py -q -k mcp
```

启动后看 health：

```bash
make start
curl http://127.0.0.1:8000/health
curl http://127.0.0.1:8000/api/agents/after_sales_assistant/tools
```

### 常见错误

- `MCP_SERVERS` 不是合法 JSON：应用启动时 settings 解析失败。
- HTTP server 没填 `url`：validator 会报错。
- stdio server 没填 `command`：validator 会报错。
- MCP server 不可用：应用仍启动，但 `/health` 的 `mcp.ok` 为 `false`。
- MCP tool 名字和本地 tool 混淆：当前项目通过 `mcp_{server}_{tool}` 命名空间避免冲突。

### 面试时怎么讲

可以这样说：

> MCP 是外部工具协议，但我不会让 MCP 泄漏到业务层。项目在 composition 阶段加载 MCP tools，并把它们适配成内部 `ToolSpec`，这样 runtime 只处理一种工具模型。

---

## 扩展 C：PostgreSQL durable checkpoint

### 本章目标

理解当前项目如何从本地内存 checkpoint 切换到 PostgreSQL durable checkpoint，并区分业务数据库、LangGraph checkpoint 和 session transcript。

### 为什么要做这一步

本地开发用内存 state store 很方便，但服务重启后 run 状态会丢。生产环境需要持久化 Agent 执行状态，尤其是审批暂停后必须能恢复。

### 本章要创建或修改哪些文件

```text
compose.yaml
src/agent_1_after_sales/app_api/bootstrap.py
src/agent_1_after_sales/agent_service/infrastructure/state_store/in_memory_store.py
src/agent_1_after_sales/agent_service/infrastructure/state_store/langgraph_postgres_store.py
src/agent_1_after_sales/agent_service/infrastructure/state_store/session_transcript_store.py
```

### 关键概念讲解

业务数据库保存订单、物流、工单、退款、审批记录、审计日志。

LangGraph checkpoint 保存 run 级执行状态，用于中断和恢复。

Session transcript 保存 session 级对话历史，用于下一轮对话上下文。

`run_id` 是 LangGraph thread id，负责一次执行；`session_id` 是对话上下文 id，可以包含多个 run。

### 开发步骤

1. 本地默认使用 `InMemoryStateStore`。
2. 如果配置 `AGENT_RUNTIME_DATABASE_URL`，`bootstrap` 选择 `LangGraphPostgresStateStore`。
3. `LangGraphPostgresStateStore.ensure_initialized()` 调用 `AsyncPostgresSaver.setup()`。
4. 同时创建 `agent_session_transcripts` 表保存 session transcript。
5. `runtime._persist_session_transcript()` 在 run 完成后追加 Human/AI message。
6. `/health` 调用 state store healthcheck，判断 runtime store 是否可用。

### 如何运行或验证

先启动 Postgres：

```bash
docker compose up -d postgres
docker compose ps
```

设置 `.env`：

```env
AGENT_RUNTIME_DATABASE_URL=postgresql://agent:agent@127.0.0.1:5432/agent_platform
```

启动并检查：

```bash
make start
curl http://127.0.0.1:8000/health
```

确认 session transcript 表存在：

```bash
docker exec -it agent-postgres psql -U agent -d agent_platform -c "\\dt"
```

### 常见错误

- Docker Desktop 没开：`docker compose up` 失败。
- `AGENT_RUNTIME_DATABASE_URL` 留空：本地会使用内存 state store，这是开发默认行为。
- 把业务库和 runtime store 混为一谈：它们可以使用同一个 Postgres 服务，但状态语义不同。
- 把 `session_id` 当 checkpoint thread id：当前项目用 `run_id` 做 thread id，避免同一 session 下多个待审批 run 互相阻塞。

### 面试时怎么讲

可以这样说：

> 本地开发使用内存 checkpointer，生产或需要恢复时切到 LangGraph Postgres saver。业务数据库、checkpoint 和 transcript 是三类状态：业务事实、run 执行状态、session 对话上下文，不能混成一套。

---

## 扩展 D：前端工作台

### 本章目标

看懂当前 Vite/React 前端如何调用后端 REST API、SSE run 接口和审批接口。

### 为什么要做这一步

这个项目主线是后端和 Agent，但仓库里也有一个前端工作台。学习者不一定要先写前端，但应该知道后端 API 是如何被真实 UI 使用的。

### 本章要创建或修改哪些文件

```text
frontend/package.json
frontend/src/api/chat.ts
frontend/src/App.tsx
frontend/src/types.ts
frontend/src/styles.css
```

### 关键概念讲解

`VITE_API_BASE_URL` 控制前端请求哪个后端地址。

`fetchEventSource` 用来消费 `/api/after-sales/runs/stream` 的 SSE 事件。

前端把 `action.required` 放进审批队列，用户点击批准或拒绝后调用 `/api/after-sales/actions`。

前端还会调用订单、物流、客户、政策和审计日志 API 来刷新右侧工作台数据。

### 开发步骤

1. 后端先启动在 `127.0.0.1:8000`。
2. 前端进入 `frontend/` 安装 npm 依赖。
3. 配置 `VITE_API_BASE_URL` 指向后端。
4. 启动 Vite dev server。
5. 在前端输入查单、查物流、退款请求，观察 SSE 事件和审批队列。

### 如何运行或验证

后端：

```bash
make seed
make start
```

前端另开一个 WSL 终端：

```bash
cd frontend
npm install
VITE_API_BASE_URL=http://127.0.0.1:8000 npm run dev -- --host 127.0.0.1 --port 5173
```

浏览器打开：

```text
http://127.0.0.1:5173
```

### 常见错误

- 前端报 CORS：确认 `.env` 里的 `CORS_ALLOWED_ORIGINS` 包含 `http://127.0.0.1:5173`。
- 前端 401：如果后端设置了 `API_KEY`，前端也要配置 `VITE_API_KEY`。
- SSE 不显示：确认后端 `/api/after-sales/runs/stream` 正常，先用 curl 验证。
- 在 `/mnt/c/...` 里安装前端依赖：`node_modules` 会很慢，建议放 WSL Linux 文件系统。

### 面试时怎么讲

可以这样说：

> 前端只是后端能力的使用者。它通过普通 REST API 获取业务资源，通过 SSE 消费 Agent 运行事件，通过 actions API 处理审批。后端 API 契约稳定，前端只需要按事件类型更新 UI。

---

## 扩展 E：Dockerfile、Docker Compose 和部署口径

### 本章目标

区分当前仓库已有的 Docker Compose 和教学建议新增的后端 Dockerfile，理解本地依赖服务、后端容器化和生产部署之间的关系。

### 为什么要做这一步

当前仓库的 `compose.yaml` 只提供 Postgres 和 Redis，没有后端 Dockerfile。学习时不能误以为 `docker compose up` 会启动完整后端。完整部署时可以新增后端镜像，但那是扩展工作。

### 本章要创建或修改哪些文件

```text
compose.yaml
Dockerfile
.dockerignore
.env.example
```

### 关键概念讲解

Compose 当前负责启动依赖服务，不负责启动 FastAPI 后端。

后端 Dockerfile 负责把 Python 运行时、依赖、源代码和启动命令打成镜像。

`.dockerignore` 用来避免把 `.venv`、缓存、数据库文件和前端构建垃圾复制进镜像。

生产环境需要明确 `APP_ENV=production`、`API_KEY`、CORS、业务数据库和 runtime 数据库。

### 教学建议 Dockerfile

当前仓库没有这个文件。如果你要做部署扩展，可以新增：

```dockerfile
FROM python:3.12-slim

# 固定容器内工作目录，解决 COPY/RUN 路径不一致的问题。
WORKDIR /app

# 先复制依赖文件，利用 Docker layer cache，避免源码小改动就重新解析依赖。
COPY pyproject.toml uv.lock ./
# 使用 uv.lock 安装固定版本依赖，解决镜像构建不可复现的问题。
RUN pip install uv && uv sync --frozen --no-dev

# 复制应用源码。
COPY src ./src
# 复制迁移文件，解决容器内无法执行 Alembic migration 的问题。
COPY migrations ./migrations
# 复制 Alembic 配置。
COPY alembic.ini ./alembic.ini

CMD [".venv/bin/python", "-m", "uvicorn", "agent_1_after_sales.app_api.main:create_app", "--factory", "--app-dir", "src", "--host", "0.0.0.0", "--port", "8000"]
```

`.dockerignore`：

```text
.venv
.mypy_cache
.ruff_cache
__pycache__
*.db
frontend/node_modules
frontend/dist
.env
```

### 如何运行或验证

只启动依赖服务：

```bash
docker compose up -d postgres redis
docker compose ps
```

构建教学后端镜像：

```bash
docker build -t after-sales-agent-api .
```

运行后端容器：

```bash
docker run --rm -p 8000:8000 \
  --env-file .env \
  after-sales-agent-api
```

### 常见错误

- 以为 `compose.yaml` 会启动后端：当前文件只定义了 Postgres 和 Redis。
- 把 `.env` COPY 进镜像：真实密钥不应该进入镜像层。
- 容器内连接 `127.0.0.1` 的 Postgres：容器网络里应该使用服务名或宿主机地址，不能机械照搬本地 WSL 的地址。
- 忘记迁移：生产启动前应执行 `make migrate` 或等价迁移命令。

### 面试时怎么讲

可以这样说：

> 当前仓库的 Compose 先服务本地依赖，后端仍通过 `make start` 开发运行。真正部署时可以新增 Dockerfile 构建后端镜像，并通过环境变量注入数据库、LLM key、API key 和 CORS 配置。

---

## WSL 常见问题排查

### `uv: command not found`

先确认 `uv` 是否安装到默认目录：

```bash
ls -la "$HOME/.local/bin/uv"
source "$HOME/.local/bin/env"
uv --version
```

如果新开终端后又找不到，把下面这行加到 `~/.bashrc`：

```bash
echo 'source "$HOME/.local/bin/env"' >> ~/.bashrc
source ~/.bashrc
```

### `python: command not found`

本教程建议通过 `uv run python` 执行项目 Python：

```bash
uv python pin 3.12
uv run python --version
```

不要依赖系统自带 `python` 命令。Ubuntu 上系统命令可能叫 `python3`，而项目虚拟环境由 `uv` 管理。

### `docker: Cannot connect to the Docker daemon`

先在 Windows 启动 Docker Desktop，再检查 WSL integration。回到 WSL 后执行：

```bash
docker ps
docker compose ps
```

如果还是失败，重启 WSL：

```powershell
wsl --shutdown
```

然后重新打开 Ubuntu 终端。

### `Address already in use`

说明端口被占用。先看 8000 端口：

```bash
ss -ltnp | grep 8000 || true
ps -ef | grep uvicorn
```

不想杀进程时，直接换端口：

```bash
PORT=8001 make start
curl http://127.0.0.1:8001/health
```

### `.env` 没生效

确认你在项目根目录：

```bash
pwd
ls -la .env pyproject.toml
```

确认配置内容：

```bash
grep -n "APP_ENV\\|BUSINESS_DATABASE_URL\\|LLM_PROVIDER" .env
```

如果同名变量已经在 shell 里设置，它可能覆盖 `.env`：

```bash
env | grep -E "APP_ENV|BUSINESS_DATABASE_URL|LLM_PROVIDER" || true
```

### `ModuleNotFoundError: agent_1_after_sales.app_api`

优先用项目命令：

```bash
uv run uvicorn agent_1_after_sales.app_api.main:create_app --factory --app-dir src --reload
```

如果运行 Python 脚本，也用 `uv run`：

```bash
uv run python -c "import agent_1_after_sales; print(agent_1_after_sales.__file__)"
```

### curl JSON 引号问题

在 WSL bash 里推荐这样写：

```bash
curl -X POST http://127.0.0.1:8000/api/after-sales/runs \
  -H "Content-Type: application/json" \
  -d '{"message":"查一下订单 ORD123","session_id":"demo-1"}'
```

如果你在 Windows PowerShell 里执行 curl，引用规则不同，容易把 JSON 搞坏。建议本教程里的 curl 都在 WSL Ubuntu 终端执行。

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
