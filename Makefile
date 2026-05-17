SHELL := /bin/bash

PYTHON ?= .venv/bin/python
NPM ?= npm
HOST ?= 127.0.0.1
PORT ?= 8000
FRONTEND_HOST ?= 127.0.0.1
FRONTEND_PORT ?= 5173

.PHONY: frontend backend start frontend-start backend-start seed test doctor migrate

frontend:
	cd frontend && $(NPM) run dev -- --host $(FRONTEND_HOST) --port $(FRONTEND_PORT) --strictPort

backend:
	$(PYTHON) -m uvicorn app_api.main:create_app --factory --app-dir src --reload --host $(HOST) --port $(PORT)

start:
	@$(MAKE) backend & backend_pid=$$!; \
	$(MAKE) frontend & frontend_pid=$$!; \
	trap 'kill $$backend_pid $$frontend_pid 2>/dev/null || true; wait $$backend_pid $$frontend_pid 2>/dev/null || true' INT TERM EXIT; \
	wait -n $$backend_pid $$frontend_pid; \
	status=$$?; \
	kill $$backend_pid $$frontend_pid 2>/dev/null || true; \
	wait $$backend_pid $$frontend_pid 2>/dev/null || true; \
	trap - INT TERM EXIT; \
	exit $$status

frontend-start:
	@$(MAKE) frontend

backend-start:
	@$(MAKE) backend

seed:
	$(PYTHON) scripts/seed.py

test:
	$(PYTHON) -m pytest tests -q

doctor:
	$(PYTHON) -c "import asyncio, json; from app_api.cli.doctor import doctor; print(json.dumps(asyncio.run(doctor()), ensure_ascii=False, indent=2))"

migrate:
	$(PYTHON) -c "import asyncio; from app_api.cli.migrate import run_migrations; asyncio.run(run_migrations())"
