# Agent Orchestrator Platform

Minimal Python agent runtime scaffold with validation, middleware, and tests.

This repository is not a full agent platform yet. It is the smallest engineering skeleton you should understand before moving on to `FastAPI`, database persistence, streaming, workflow, and eval.

If you want the long-form foundations tutorial, start with [WEEK1_TUTORIAL.md](./WEEK1_TUTORIAL.md).

## Environment Setup

Use a project-local virtual environment first. This keeps the repository isolated.

Prerequisites:

- Python `3.12+`
- A shell that can run local scripts
- Optional: `uv` if you already use it

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

## Current Scope

This project currently covers:

- Minimal `agent_runtime` package
- Tool registry
- Pydantic argument validation
- Unified error shape
- Logging middleware
- Runnable examples
- Tests, lint, and type-check commands

The goal of this repository is not "learn all Python syntax". The goal is to understand a small but real runtime skeleton:

- how input enters the system
- how tools are registered and executed
- where validation happens
- how errors are normalized
- where middleware fits
- how tests describe behavior

## Project Layout

```text
agent-orchestrator-platform/
├── README.md
├── WEEK1_TUTORIAL.md
├── pyproject.toml
├── examples/
│   ├── 01_runtime_demo.py
│   ├── 02_pydantic_validation_demo.py
│   └── 03_asyncio_primer.py
├── src/
│   └── agent_runtime/
│       ├── __init__.py
│       ├── errors.py
│       ├── logging_middleware.py
│       ├── models.py
│       ├── registry.py
│       └── runtime.py
└── tests/
    └── test_runtime.py
```

## Recommended Learning Order

Do not start by reading every file line by line. This repository is much easier to absorb if you move from running -> observing -> reading -> testing -> modifying.

### 1. Run the examples first

Start here:

```bash
./.venv/bin/python examples/01_runtime_demo.py
./.venv/bin/python examples/02_pydantic_validation_demo.py
./.venv/bin/python examples/03_asyncio_primer.py
```

Read them in this order:

1. `examples/01_runtime_demo.py`
   This is the best high-level entry point. It shows tool registration, successful execution, validation failure, unknown tool failure, and logging.
2. `examples/02_pydantic_validation_demo.py`
   This isolates one idea: what `model_validate(...)` actually does.
3. `examples/03_asyncio_primer.py`
   This is not yet the runtime implementation. It exists to build async intuition before Week 2 and later workflow work.

### 2. Read `agent_runtime` in this order

Recommended file order:

1. `src/agent_runtime/models.py`
   Start here because this file defines the input and output shapes: `ToolCall`, `ToolResult`, and `ErrorResponse`.
2. `src/agent_runtime/errors.py`
   Read this next so you know the three runtime error categories before reading the main flow.
3. `src/agent_runtime/registry.py`
   This shows how tools are stored, looked up, and listed.
4. `src/agent_runtime/logging_middleware.py`
   Read this before `runtime.py` so middleware stops feeling magical.
5. `src/agent_runtime/runtime.py`
   This is the core control flow: `execute -> _dispatch -> _invoke`.
6. `src/agent_runtime/__init__.py`
   Read this last. It just shows the public export surface.

### 3. Use the tests as the behavior guide

After you finish the first source pass, read:

```bash
./.venv/bin/pytest -q
```

Then open `tests/test_runtime.py`.

Do not think of this file as "extra verification only". It is also the clearest behavior spec in the repo.

Recommended test reading order:

1. Registry basics
   `test_registry_lists_registered_names`
   `test_duplicate_registration_raises_value_error`
2. Core runtime success and failure cases
   `test_execute_success_returns_result`
   `test_unknown_tool_returns_structured_error`
   `test_validation_failure_returns_structured_error`
   `test_execution_failure_returns_structured_error`
3. Middleware behavior
   `test_middleware_chain_runs_in_wrapped_order`
   `test_middleware_can_modify_arguments_before_execution`
4. Logging behavior
   `test_logging_middleware_logs_start_and_finish`
   `test_logging_middleware_logs_errors`
5. Dependency injection
   `test_runtime_accepts_custom_registry`

When reading each test, ask:

- what input is being created
- which path in `runtime.py` it is trying to hit
- what behavior the test is protecting

### 4. Run the full verification loop

```bash
./.venv/bin/pytest -q
./.venv/bin/ruff check .
./.venv/bin/mypy src tests examples
```

This matters because the point here is engineering discipline, not only "it seems to work on my machine".

### 5. Modify something small yourself

Before moving to Week 2, do at least one small change:

- add one new tool
- add one or two tests
- rerun the verification loop

That is the moment where the project shifts from "I read it" to "I own it".

## How To Think About Each Part

If you only want the shortest mental model, keep this map in mind:

- `models.py`
  Defines the protocol between caller and runtime.
- `errors.py`
  Defines normalized failure categories.
- `registry.py`
  Holds available tools.
- `logging_middleware.py`
  Observes the request before and after execution.
- `runtime.py`
  Coordinates everything.
- `examples/`
  Show the runtime in action.
- `tests/test_runtime.py`
  Proves the behavior and edge cases.

## The Main Control Flow

The core chain for this repo is:

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

Failure also follows a consistent pattern:

```text
runtime raises structured runtime error
  -> execute() catches AgentRuntimeError
  -> returns ToolResult(success=False, error=...)
```

This is the main thing you should be able to explain from memory after finishing this foundations pass.

## What "Foundations Complete" Looks Like

You are ready to move on when you can do these things without guessing:

- explain `ToolCall`, `ToolResult`, and `ErrorResponse`
- explain the difference between `UnknownToolError`, `ToolValidationError`, and `ToolExecutionError`
- explain why middleware wraps execution like an onion
- explain why `execute()` returns a structured failure instead of leaking raw exceptions
- run the examples and verification commands yourself
- add a new tool and a test without getting lost

## Suggested Daily Review Loop

If you want a light review before starting each study session, do this instead of rereading the whole repo:

1. say the main chain out loud:
   `execute -> _dispatch -> _invoke -> validate -> handler -> ToolResult`
2. open one example
3. open one test
4. open one source file
5. explain what problem that file solves

Ten to twenty minutes of this is usually more valuable than mechanically rewriting the same files every day.

## Next Step

Week 2 is:

- `FastAPI`
- `SQLAlchemy 2`
- `Alembic`
- `PostgreSQL`
- `Redis`
- `SSE / Streaming`

The goal is not to replace `agent_runtime`. The goal is to place this runtime inside a real backend skeleton.

## Optional `uv` Commands

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
