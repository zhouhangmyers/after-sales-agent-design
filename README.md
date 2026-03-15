# Agent Orchestrator Platform

Minimal Python agent engineering scaffold for a 12-stage AI agent roadmap.

This repository currently covers two stages:

- Stage 1: a small but real `agent_runtime` core
- Stage 2: a backend shell built with `FastAPI`, `SQLAlchemy`, persistence tables, and `SSE`

It is not a full agent platform yet. What it already gives you is a runnable, testable skeleton that shows how a small runtime grows into a real backend service.

## What This Repo Covers

- `agent_runtime` core execution flow
- Tool registry and Pydantic argument validation
- Normalized runtime errors
- Logging middleware
- FastAPI app bootstrap with lifespan and `app.state`
- SQLAlchemy models and repository layer
- SQLite-first local development, with PostgreSQL-ready settings
- SSE streaming with memory or Redis-backed event cache
- Unit tests, integration tests, linting, and type checking

## Quick Start

Use a project-local virtual environment first.

Prerequisites:

- Python `3.12+`
- A shell that can run local scripts
- Optional: `uv`

Recommended setup:

```bash
cd /home/zhouhangmyers/python/agent-orchestrator-platform
python3.12 -m venv .venv
./.venv/bin/python -m pip install -e '.[dev]'
```

Optional `uv` setup:

```bash
cd /home/zhouhangmyers/python/agent-orchestrator-platform
uv sync --extra dev
```

Quick verification:

```bash
./.venv/bin/python -V
./.venv/bin/pytest --version
./.venv/bin/ruff --version
./.venv/bin/mypy --version
```

## Stage 2 Backend Shell

The Stage 2 shell can run locally with SQLite immediately, and it can later be pointed at PostgreSQL and Redis through environment variables.

Run the verification loop:

```bash
./.venv/bin/pytest -q
./.venv/bin/ruff check .
./.venv/bin/mypy src tests examples
```

Run the API server:

```bash
AUTO_CREATE_SCHEMA=true ./.venv/bin/uvicorn agent_service.main:app --reload
```

Try the endpoints:

```bash
curl http://127.0.0.1:8000/healthz

curl -X POST http://127.0.0.1:8000/api/v1/chat \
  -H "Content-Type: application/json" \
  -d '{"session_id":"sess-001","message":"add a=3 b=7"}'

curl -N "http://127.0.0.1:8000/api/v1/chat/stream?session_id=sess-002&message=add%20a=1%20b=2"
```

If you want PostgreSQL and Redis instead of SQLite, start the containers in [compose.yaml](./compose.yaml) and copy settings from [.env.example](./.env.example).

## Current Scope

The current codebase is intentionally small, but it already has real structure:

- Runtime layer
- API layer
- Service layer
- Repository layer
- Database infrastructure layer
- Streaming and cache layer

The goal is not to learn all Python syntax. The goal is to understand how a small agent backend is assembled:

- how input enters the system
- where dependencies come from
- where business orchestration lives
- where persistence happens
- where validation and normalized errors happen
- how startup bootstrap differs from request handling

## Architecture Mental Model

For Stage 2, the shortest useful map is:

```text
client
  -> api/chat.py
  -> Depends(...) from api/deps.py
  -> ChatService
  -> RuntimeService / StreamService
  -> repositories
  -> db models + db session
```

Application startup is a separate path:

```text
create_app()
  -> lifespan
  -> bootstrap_app_state(...)
  -> settings
  -> db_manager
  -> runtime_service
  -> event_cache
  -> app.state
```

This repo also includes a Stage 2 architecture diagram and exported tutorial:

- [agent_service architecture drawio](./agent_service架构.drawio)
- [architecture tutorial](./docs/agent_service_architecture_tutorial.md)
- [architecture report PDF](./docs/agent_service_architecture_tutorial.pdf)

## Project Layout

```text
agent-orchestrator-platform/
├── README.md
├── .env.example
├── alembic.ini
├── compose.yaml
├── pyproject.toml
├── agent_service架构.drawio
├── docs/
│   ├── agent_service_architecture_tutorial.md
│   ├── agent_service_architecture_tutorial.html
│   └── agent_service_diagram_*.svg
├── examples/
│   ├── 01_runtime_demo.py
│   ├── 02_pydantic_validation_demo.py
│   └── 03_asyncio_primer.py
├── migrations/
│   ├── env.py
│   └── versions/
├── scripts/
│   └── generate_agent_service_architecture_report.py
├── src/
│   ├── agent_runtime/
│   │   ├── __init__.py
│   │   ├── errors.py
│   │   ├── logging_middleware.py
│   │   ├── models.py
│   │   ├── registry.py
│   │   └── runtime.py
│   └── agent_service/
│       ├── api/
│       ├── db/
│       ├── repositories/
│       ├── schemas/
│       ├── services/
│       ├── config.py
│       └── main.py
└── tests/
    ├── integration/
    ├── conftest.py
    └── test_runtime.py
```

## Recommended Reading Order

Do not start by reading every file line by line. Move from running to observing to reading.

### 1. Run the runtime examples first

```bash
./.venv/bin/python examples/01_runtime_demo.py
./.venv/bin/python examples/02_pydantic_validation_demo.py
./.venv/bin/python examples/03_asyncio_primer.py
```

Suggested order:

1. `examples/01_runtime_demo.py`
   High-level runtime demo: success path, validation failure, unknown tool, logging.
2. `examples/02_pydantic_validation_demo.py`
   Focused view of `model_validate(...)`.
3. `examples/03_asyncio_primer.py`
   Async intuition before the backend shell grows more complex.

### 2. Read `agent_runtime` next

Suggested order:

1. `src/agent_runtime/models.py`
2. `src/agent_runtime/errors.py`
3. `src/agent_runtime/registry.py`
4. `src/agent_runtime/logging_middleware.py`
5. `src/agent_runtime/runtime.py`
6. `src/agent_runtime/__init__.py`

The main control flow is:

```text
execute()
  -> build ToolCall
  -> _dispatch()
  -> middleware(s)
  -> _invoke()
  -> registry lookup
  -> args_model.model_validate(...)
  -> handler(...)
  -> ToolResult
```

Failures are normalized the same way:

```text
runtime raises structured runtime error
  -> execute() catches AgentRuntimeError
  -> returns ToolResult(success=False, error=...)
```

### 3. Then read `agent_service`

Suggested order:

1. `src/agent_service/main.py`
   Understand application startup, lifespan, and `app.state`.
2. `src/agent_service/config.py`
   Understand how settings are loaded.
3. `src/agent_service/api/deps.py`
   Understand where `db_session`, `runtime_service`, and `event_cache` come from.
4. `src/agent_service/api/chat.py`
   Understand the request entrypoints.
5. `src/agent_service/schemas/`
   Understand request and response contracts.
6. `src/agent_service/services/chat_service.py`
   This is the Stage 2 business orchestration center.
7. `src/agent_service/services/runtime_service.py`
   Understand message parsing and runtime bridging.
8. `src/agent_service/services/stream_service.py`
   Understand SSE event splitting.
9. `src/agent_service/repositories/`
   Understand how the persistence layer is separated.
10. `src/agent_service/db/`
   Understand ORM models, session factory, and schema creation.

### 4. Use the tests as the behavior guide

Runtime tests:

```bash
./.venv/bin/pytest tests/test_runtime.py -q
```

Integration tests:

```bash
./.venv/bin/pytest tests/integration -q
```

Do not treat tests as extra verification only. They are also the clearest behavior spec in the repo.

### 5. Modify something small yourself

Before moving on, do at least one small change:

- add one new tool
- add one or two tests
- add one new persistence field or endpoint behavior
- rerun the verification loop

That is the point where the repo shifts from "I read it" to "I can work in it."

## Verification Commands

```bash
./.venv/bin/pytest -q
./.venv/bin/ruff check .
./.venv/bin/mypy src tests examples
```

If you prefer `uv`, these commands are equivalent:

```bash
uv sync --extra dev
uv run python examples/01_runtime_demo.py
uv run python examples/02_pydantic_validation_demo.py
uv run python examples/03_asyncio_primer.py
uv run pytest -q
uv run ruff check .
uv run mypy src tests examples
```

## What "Stage 2 Complete" Looks Like

You are ready to move on when you can explain these things without guessing:

- how `agent_runtime` executes a tool call
- how `AgentRuntimeError` becomes structured output
- how `main.py` bootstraps shared state with lifespan
- how `api/deps.py` injects dependencies into the route layer
- how `ChatService` coordinates persistence and runtime execution
- how repositories differ from ORM models
- how `StreamService` turns one response into SSE events

## Next Step

The next stage is to make the backend smarter rather than just bigger:

- Tool Calling
- Structured Output
- Workflow
- Retry / Timeout
- Prompt management
- Eval

The goal is not to replace `agent_runtime`. The goal is to place this runtime inside a real backend skeleton and then keep evolving the orchestration layer.
