# Architecture

This document is the stable architecture companion for the README. It captures the project boundaries and the public surface that should stay aligned with docs and tests.

## System Shape

```text
Client / Frontend
  -> app_api
     -> HTTP routers / CLI
     -> dependency injection
     -> composition root
     -> use cases / projectors
  -> agent_core
     -> AgentDefinition
     -> ToolSpec
     -> RunEvent
     -> RunState
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

## Layer Responsibilities

- `after_sales` owns business rules, transaction boundaries, repositories, and business data.
- `agent_core` defines framework-independent contracts used between business tools, runtime, APIs, and integrations.
- `agent_runtime` owns Agent execution, checkpointing, approval interruption, resume, event mapping, and result normalization.
- `agent_integrations` adapts external providers such as LLM vendors and MCP servers.
- `app_api` is the composition and delivery layer: it wires dependencies, exposes HTTP/CLI entry points, and projects runtime events into business audit records.
- `frontend` consumes HTTP and SSE APIs to provide the after-sales operator console.

## Core Contracts

- `AgentDefinition` describes one Agent capability: capability id, prompt, metadata, and tools.
- `ToolSpec` is the internal tool protocol: name, description, Pydantic args schema, handler, optional approval policy, and source metadata.
- `RunEvent` is the stable event stream emitted by runtime and consumed by HTTP/SSE and projectors.
- `RunState` is the queryable state derived from checkpoint snapshots.

The business layer does not depend on LangChain, LangGraph, FastAPI, or MCP. The runtime does not know after-sales concepts such as orders, tickets, or refund requests.

## Runtime Flow

```text
POST /api/after-sales/runs
  -> after_sales_runs router
  -> AfterSalesAgentUseCase.run()
  -> LangChainAgentRuntime.stream_run()
  -> ToolSpec -> StructuredTool
  -> AfterSalesService
  -> UnitOfWork / Repository
  -> Business Database
  -> RunCompletedEvent
  -> RunResponse
```

For streaming:

```text
POST /api/after-sales/runs/stream
  -> AfterSalesAgentUseCase.stream()
  -> Runtime RunEvent stream
  -> AfterSalesRunProjector.record_event()
  -> SSE event mapping
  -> text/event-stream
```

For approval resume:

```text
POST /api/after-sales/actions
  -> AfterSalesAgentUseCase.act()
  -> runtime.stream_action()
  -> LangGraph checkpoint resume
  -> projector.resolve_approval()
  -> RunCompletedEvent
```

## Public API Surface

Agent run:

- `POST /api/after-sales/runs`
- `POST /api/after-sales/runs/stream`
- `POST /api/after-sales/actions`
- `GET /api/after-sales/runs/{run_id}`

Business resources:

- `GET /api/after-sales/orders/{order_id}`
- `GET /api/after-sales/orders/{order_id}/shipment`
- `GET /api/after-sales/customers/{customer_id}`
- `GET /api/after-sales/policies/search?q=...`
- `POST /api/after-sales/tickets`
- `GET /api/after-sales/tickets/{ticket_id}`
- `POST /api/after-sales/refund-requests`
- `GET /api/after-sales/audit-logs?run_id=...`

Platform:

- `GET /health`
- `GET /api/agents`
- `GET /api/agents/{capability_id}/tools`

## Configuration Surface

Required or commonly used environment keys:

- `LLM_PROVIDER`
- `LLM_MODEL`
- `DEEPSEEK_API_KEY`
- `OPENAI_API_KEY`
- `BUSINESS_DATABASE_URL`
- `AGENT_RUNTIME_DATABASE_URL`
- `MCP_SERVERS`
- `MAX_STEPS`
- `APPROVAL_TIMEOUT_SECONDS`

Production additionally requires:

- `API_KEY`
- `CORS_ALLOWED_ORIGINS`
- `AGENT_RUNTIME_DATABASE_URL`
- The API key for the selected LLM provider.

## Persistence Boundary

Business database:

- customers
- orders
- shipments
- tickets
- refund requests
- policy articles
- tool call logs
- approval records
- audit logs

Runtime state store:

- LangGraph checkpoint state
- session transcript

Checkpoint data is used for Agent resume and should not leak into business models. Business audit data is projected from runtime events and remains queryable independently of LangGraph internals.

## Extension Points

- Add a new domain by defining domain services and exposing them as `ToolSpec`.
- Add a new LLM provider in `agent_integrations.llm.chat_model_factory`.
- Add external tools through `MCPToolProvider`.
- Replace lightweight policy search with RAG in a future domain without changing runtime contracts.
- Add richer production capabilities such as multi-tenant auth, observability, evaluation, and tool-level permissions.
