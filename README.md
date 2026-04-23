# After-Sales Agent Platform

Greenfield backend for an after-sales support agent.  
The codebase is now split into three layers:

- `src/agent_service/`: agent runtime, workflow engine adapters, action dispatch, state-store abstraction.
- `src/business_service/after_sales/`: after-sales business module, domain rules, persistence, audit projection.
- `src/app_api/`: the only HTTP entrypoint and composition root.

## Current Architecture

```text
src/
  agent_service/
    contracts/
    application/
    infrastructure/
    conversation/
    llm/
  business_service/
    after_sales/
      domain/
      application/
      infrastructure/
  app_api/
    asgi.py
    main.py
    bootstrap.py
    routers/
    schemas/
```

## Official Entry Point

The only supported ASGI entrypoint is:

```bash
uvicorn app_api.main:create_app --factory --app-dir src --reload --host 127.0.0.1 --port 8000
```

The repository wraps that with:

```bash
make start
```

`make start` injects safe local-dev defaults so it still works even if your `.env` file contains production-oriented values.

## Local Setup

1. Ensure the virtualenv exists and dependencies are installed.
2. Copy `.env.example` to `.env` if you want explicit local config.
3. Seed demo data:

```bash
make seed
```

4. Start the API:

```bash
make start
```

The default local business database is `after_sales_mvp.db`.  
If `AGENT_RUNTIME_DATABASE_URL` is unset, the runtime uses the in-memory state store.

## Useful Commands

```bash
make start
make seed
make test
make doctor
make migrate
```

## Public API

### Agent endpoints

- `POST /api/after-sales/runs`
- `POST /api/after-sales/runs/stream`
- `POST /api/after-sales/actions`
- `GET /api/after-sales/runs/{run_id}`

### Business endpoints

- `GET /api/after-sales/orders/{order_id}`
- `GET /api/after-sales/orders/{order_id}/shipment`
- `GET /api/after-sales/customers/{customer_id}`
- `GET /api/after-sales/policies/search?q=...`
- `POST /api/after-sales/tickets`
- `GET /api/after-sales/tickets/{ticket_id}`
- `POST /api/after-sales/refund-requests`
- `GET /api/after-sales/audit-logs?conversation_id=...`

## Test Status

The active test suite is aligned to the new architecture and validates:

- agent runtime conversation flow
- inline tool execution
- LLM service behavior
- `app_api` health, domain APIs, run streaming, approval flow, and audit projection

Run all tests with:

```bash
make test
```
