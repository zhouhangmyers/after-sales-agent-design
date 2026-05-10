from __future__ import annotations

import sys
from pathlib import Path
from types import ModuleType

import httpx
import pytest
from sqlalchemy import inspect, select

from after_sales.domain.entities import TicketCreate
from after_sales.infrastructure.persistence.sqlalchemy.models import (
    ApprovalRecord,
    RefundRequest,
    Ticket,
    ToolCallLog,
)
from after_sales.infrastructure.persistence.sqlalchemy.session import (
    BusinessDatabase,
)
from after_sales.infrastructure.persistence.sqlalchemy.unit_of_work import (
    SqlAlchemyAfterSalesUnitOfWork,
)
from app_api.cli.migrate import run_migrations
from app_api.migrations import upgrade_business_database
from app_api.settings import AppSettings, MCPServerConfig
from tests.integration.helpers import (
    build_after_sales_app,
    build_health_only_app,
    collect_sse_events,
)


@pytest.mark.asyncio
async def test_health_starts_without_business_modules(tmp_path: Path) -> None:
    app = await build_health_only_app(tmp_path / "health-only.db")

    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            response = await client.get("/health")
            run_response = await client.post(
                "/api/after-sales/runs",
                json={"message": "查一下订单 ORD123", "session_id": "health-only-run"},
            )

    assert response.status_code == 200
    assert response.json() == {
        "status": "degraded",
        "runtime_store": {
            "ok": True,
            "backend": "in-memory",
            "detail": None,
        },
        "business_database": {
            "ok": True,
            "schema_ready": True,
            "detail": None,
        },
        "llm": {
            "ok": False,
            "provider": "missing-provider",
            "model": "deepseek-chat",
            "detail": "unsupported llm provider: missing-provider",
        },
        "mcp": {
            "ok": True,
            "configured_servers": [],
            "detail": None,
        },
    }
    assert run_response.status_code == 503
    assert "assistant service unavailable" in run_response.json()["detail"]


@pytest.mark.asyncio
async def test_after_sales_resources_routes_and_sync_run(tmp_path: Path) -> None:
    app = await build_after_sales_app(tmp_path / "after-sales-domain.db")

    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            order_response = await client.get("/api/after-sales/orders/ORD123")
            shipment_response = await client.get("/api/after-sales/orders/ORD123/shipment")
            ticket_response = await client.post(
                "/api/after-sales/tickets",
                json={
                    "order_id": "ORD123",
                    "issue_type": "damaged",
                    "summary": "订单 ORD123 商品坏了，帮我登记一下",
                    "priority": "normal",
                },
            )
            run_response = await client.post(
                "/api/after-sales/runs",
                json={"message": "查一下订单 ORD123", "session_id": "run-order-1"},
            )
            agents_response = await client.get("/api/agents")
            tools_response = await client.get("/api/agents/after_sales_assistant/tools")

    assert order_response.status_code == 200
    assert order_response.json()["status"] == "shipped"
    assert shipment_response.status_code == 200
    assert shipment_response.json()["status"] == "in_transit"
    assert ticket_response.status_code == 200
    assert ticket_response.json()["ticket_id"].startswith("TCK-")
    assert run_response.status_code == 200
    payload = run_response.json()
    assert payload["session_id"] == "run-order-1"
    assert payload["run_id"].startswith("run-")
    assert payload["status"] == "completed"
    assert payload["output"] == "订单 ORD123 当前状态是 shipped，商品为 蓝牙耳机 x1。"
    assert payload["pending_action"] is None
    assert payload["error"] is None
    assert agents_response.status_code == 200
    assert agents_response.json() == [
        {
            "capability_id": "after_sales_assistant",
            "name": "After-Sales Assistant",
            "description": "售后客服 agent，支持查单、物流、工单、退款审批和政策查询。",
            "tool_count": 6,
        }
    ]
    assert tools_response.status_code == 200
    tool_names = [item["name"] for item in tools_response.json()["tools"]]
    assert "get_order_detail" in tool_names
    assert "submit_refund_request" in tool_names
    refund_tool = next(
        item for item in tools_response.json()["tools"] if item["name"] == "submit_refund_request"
    )
    assert refund_tool["source"] == "local"
    assert refund_tool["requires_approval"] is True


@pytest.mark.asyncio
async def test_mcp_load_failure_degrades_health_but_local_agent_still_runs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    package = ModuleType("langchain_mcp_adapters")
    package.__path__ = []
    client_module = ModuleType("langchain_mcp_adapters.client")

    class FailingMultiServerMCPClient:
        def __init__(self, server_configs: dict[str, dict[str, object]]) -> None:
            self.server_configs = server_configs

        async def get_tools(self) -> list[object]:
            raise RuntimeError("mcp server unavailable")

    client_module.__dict__["MultiServerMCPClient"] = FailingMultiServerMCPClient
    monkeypatch.setitem(sys.modules, "langchain_mcp_adapters", package)
    monkeypatch.setitem(sys.modules, "langchain_mcp_adapters.client", client_module)

    app = await build_after_sales_app(
        tmp_path / "after-sales-mcp-failure.db",
        mcp_servers={
            "weather": MCPServerConfig(
                transport="http",
                url="http://localhost:8000/mcp",
            )
        },
    )

    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            health_response = await client.get("/health")
            run_response = await client.post(
                "/api/after-sales/runs",
                json={"message": "查一下订单 ORD123", "session_id": "mcp-failure-run"},
            )

    assert health_response.status_code == 200
    assert health_response.json()["status"] == "degraded"
    assert health_response.json()["mcp"] == {
        "ok": False,
        "configured_servers": ["weather"],
        "detail": "mcp server unavailable",
    }
    assert run_response.status_code == 200
    assert run_response.json()["status"] == "completed"


@pytest.mark.asyncio
async def test_unit_of_work_rolls_back_uncommitted_repository_writes(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "after-sales-uow-rollback.db"
    await build_after_sales_app(database_path)
    database = BusinessDatabase(f"sqlite+pysqlite:///{database_path}")

    with pytest.raises(RuntimeError, match="force rollback"):
        async with SqlAlchemyAfterSalesUnitOfWork(database.managed_session) as uow:
            await uow.repository.create_ticket(
                TicketCreate(
                    order_id="ORD123",
                    issue_type="damaged",
                    summary="rollback this ticket",
                )
            )
            raise RuntimeError("force rollback")

    async with database.managed_session() as session:
        tickets = list(
            await session.scalars(
                select(Ticket).where(Ticket.summary == "rollback this ticket")
            )
        )
    await database.dispose()

    assert tickets == []


@pytest.mark.asyncio
async def test_refund_stream_action_and_audit_projection(tmp_path: Path) -> None:
    database_path = tmp_path / "after-sales-refund.db"
    app = await build_after_sales_app(database_path)

    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            first_events = await collect_sse_events(
                client,
                "/api/after-sales/runs/stream",
                {
                    "message": "订单 ORD123 退款 200，商品破损",
                    "session_id": "refund-run-1",
                },
            )
            run_id = first_events[0][1]["run_id"]
            assert isinstance(run_id, str)

            state_response = await client.get(f"/api/after-sales/runs/{run_id}")
            action_response = await client.post(
                "/api/after-sales/actions",
                json={
                    "run_id": run_id,
                    "action_id": "call_submit_refund_request",
                    "decision": "approved",
                },
            )
            audit_response = await client.get(
                "/api/after-sales/audit-logs",
                params={"run_id": run_id},
            )
            legacy_audit_response = await client.get(
                "/api/after-sales/audit-logs",
                params={"conversation_id": run_id},
            )

    assert [name for name, _ in first_events] == [
        "run.started",
        "action.required",
        "run.completed",
    ]
    assert run_id.startswith("run-")
    assert first_events[0][1]["session_id"] == "refund-run-1"
    assert first_events[1][1]["pending_action"] == {
        "action_id": "call_submit_refund_request",
        "action_name": "submit_refund_request",
        "action_payload": {
            "order_id": "ORD123",
            "amount": "200",
            "reason": "订单 ORD123 退款 200，商品破损",
        },
        "reason": "退款金额超过 100 元，且原因涉及破损或质量问题，需要人工审批。",
        "risk_level": "high",
        "display_payload": {
            "order_id": "ORD123",
            "amount": 200.0,
            "reason": "订单 ORD123 退款 200，商品破损",
            "risk_level": "high",
        },
    }
    assert first_events[2][1] == {
        "run_id": run_id,
        "session_id": "refund-run-1",
        "status": "awaiting_action",
        "output": "工具 `submit_refund_request` 需要人工审批，当前对话已暂停，等待批准后继续。",
        "pending_action": first_events[1][1]["pending_action"],
        "error": None,
    }

    assert state_response.status_code == 200
    assert state_response.json()["status"] == "awaiting_action"
    assert state_response.json()["pending_action"]["display_payload"]["amount"] == 200.0

    assert action_response.status_code == 200
    assert action_response.json() == {
        "run_id": run_id,
        "session_id": "refund-run-1",
        "status": "completed",
        "output": "订单 ORD123 的退款申请已通过，金额为 200.00 元，原因是 订单 ORD123 退款 200，商品破损。",
        "pending_action": None,
        "error": None,
    }

    assert audit_response.status_code == 200
    assert [item["event_type"] for item in audit_response.json()] == [
        "approval_requested",
        "approval_resolved",
    ]
    assert legacy_audit_response.status_code == 422

    database = BusinessDatabase(f"sqlite+pysqlite:///{database_path}")
    async with database.managed_session() as session:
        tool_logs = list(
            await session.scalars(
                select(ToolCallLog).where(ToolCallLog.conversation_id == run_id)
            )
        )
        approval_records = list(
            await session.scalars(
                select(ApprovalRecord).where(ApprovalRecord.conversation_id == run_id)
            )
        )
        refund_requests = list(
            await session.scalars(
                select(RefundRequest).where(RefundRequest.order_id == "ORD123")
            )
        )
    await database.dispose()

    assert len(tool_logs) == 1
    assert tool_logs[0].tool_name == "submit_refund_request"
    assert tool_logs[0].status == "succeeded"
    assert tool_logs[0].latency_ms is not None
    assert len(approval_records) == 1
    assert approval_records[0].tool_call_id == "call_submit_refund_request"
    assert approval_records[0].status == "approved"
    assert approval_records[0].risk_level == "high"
    assert len(refund_requests) == 1
    assert refund_requests[0].status == "approved"
    assert refund_requests[0].requires_approval is True


@pytest.mark.asyncio
async def test_invalid_action_id_does_not_resolve_approval(tmp_path: Path) -> None:
    database_path = tmp_path / "after-sales-invalid-action.db"
    app = await build_after_sales_app(database_path)

    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            events = await collect_sse_events(
                client,
                "/api/after-sales/runs/stream",
                {
                    "message": "订单 ORD123 退款 200，商品破损",
                    "session_id": "refund-run-invalid",
                },
            )
            run_id = events[0][1]["run_id"]
            assert isinstance(run_id, str)
            action_response = await client.post(
                "/api/after-sales/actions",
                json={
                    "run_id": run_id,
                    "action_id": "wrong_action_id",
                    "decision": "approved",
                },
            )
            audit_response = await client.get(
                "/api/after-sales/audit-logs",
                params={"run_id": run_id},
            )

    assert action_response.status_code == 409
    assert action_response.json() == {
        "detail": "action_id does not match pending action: wrong_action_id"
    }
    assert [item["event_type"] for item in audit_response.json()] == [
        "approval_requested",
    ]

    database = BusinessDatabase(f"sqlite+pysqlite:///{database_path}")
    async with database.managed_session() as session:
        approval_records = list(
            await session.scalars(
                select(ApprovalRecord).where(
                    ApprovalRecord.conversation_id == run_id
                )
            )
        )
    await database.dispose()

    assert len(approval_records) == 1
    assert approval_records[0].status == "pending"
    assert approval_records[0].resolved_at is None


@pytest.mark.asyncio
async def test_same_session_allows_new_run_while_previous_run_waits_for_approval(
    tmp_path: Path,
) -> None:
    app = await build_after_sales_app(tmp_path / "after-sales-session-decouple.db")

    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            first_response = await client.post(
                "/api/after-sales/runs",
                json={
                    "message": "订单 ORD123 退款 200，商品破损",
                    "session_id": "session-decouple-1",
                },
            )
            second_response = await client.post(
                "/api/after-sales/runs",
                json={
                    "message": "查一下订单 ORD123",
                    "session_id": "session-decouple-1",
                },
            )

            first_run_id = first_response.json()["run_id"]
            first_state_response = await client.get(f"/api/after-sales/runs/{first_run_id}")

    assert first_response.status_code == 200
    assert first_response.json()["status"] == "awaiting_action"
    assert first_response.json()["session_id"] == "session-decouple-1"

    assert second_response.status_code == 200
    assert second_response.json()["status"] == "completed"
    assert second_response.json()["session_id"] == "session-decouple-1"
    assert second_response.json()["run_id"] != first_run_id

    assert first_state_response.status_code == 200
    assert first_state_response.json()["status"] == "awaiting_action"


@pytest.mark.asyncio
async def test_business_database_healthcheck_reports_missing_columns_for_legacy_schema(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "after-sales-legacy-health.db"
    database_url = f"sqlite+pysqlite:///{database_path}"

    upgrade_business_database(
        database_url=database_url,
        revision="20260422_000001",
    )

    database = BusinessDatabase(database_url)
    status = await database.healthcheck()
    await database.dispose()

    assert status.ok is False
    assert status.schema_ready is False
    assert status.detail is not None
    assert "approval_records.tool_call_id" in status.detail


@pytest.mark.asyncio
async def test_run_migrations_upgrades_legacy_business_database(tmp_path: Path) -> None:
    database_path = tmp_path / "after-sales-legacy-upgrade.db"
    database_url = f"sqlite+pysqlite:///{database_path}"

    upgrade_business_database(
        database_url=database_url,
        revision="20260422_000001",
    )

    await run_migrations(
        AppSettings(
            app_env="test",
            business_database_url=database_url,
            agent_runtime_database_url=None,
            auto_create_schema=False,
        )
    )

    database = BusinessDatabase(database_url)
    with database.sync_engine.connect() as connection:
        columns = {
            column["name"]
            for column in inspect(connection).get_columns("approval_records")
        }
    status = await database.healthcheck()
    await database.dispose()

    assert "tool_call_id" in columns
    assert status.ok is True
    assert status.schema_ready is True


@pytest.mark.asyncio
async def test_run_migrations_upgrades_unversioned_legacy_business_database(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "after-sales-unversioned-legacy-upgrade.db"
    database_url = f"sqlite+pysqlite:///{database_path}"

    upgrade_business_database(
        database_url=database_url,
        revision="20260422_000001",
    )

    database = BusinessDatabase(database_url)
    with database.sync_engine.begin() as connection:
        connection.exec_driver_sql("DROP TABLE alembic_version")
    await database.dispose()

    await run_migrations(
        AppSettings(
            app_env="test",
            business_database_url=database_url,
            agent_runtime_database_url=None,
            auto_create_schema=False,
        )
    )

    database = BusinessDatabase(database_url)
    with database.sync_engine.connect() as connection:
        columns = {
            column["name"]
            for column in inspect(connection).get_columns("approval_records")
        }
        tables = set(inspect(connection).get_table_names())
    status = await database.healthcheck()
    await database.dispose()

    assert "alembic_version" in tables
    assert "tool_call_id" in columns
    assert status.ok is True
    assert status.schema_ready is True


@pytest.mark.asyncio
async def test_run_migrations_upgrades_legacy_database_with_empty_alembic_version(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "after-sales-empty-version-upgrade.db"
    database_url = f"sqlite+pysqlite:///{database_path}"

    upgrade_business_database(
        database_url=database_url,
        revision="20260422_000001",
    )

    database = BusinessDatabase(database_url)
    with database.sync_engine.begin() as connection:
        connection.exec_driver_sql("DELETE FROM alembic_version")
    await database.dispose()

    await run_migrations(
        AppSettings(
            app_env="test",
            business_database_url=database_url,
            agent_runtime_database_url=None,
            auto_create_schema=False,
        )
    )

    database = BusinessDatabase(database_url)
    with database.sync_engine.connect() as connection:
        columns = {
            column["name"]
            for column in inspect(connection).get_columns("approval_records")
        }
        version_rows = list(connection.exec_driver_sql("SELECT version_num FROM alembic_version"))
    status = await database.healthcheck()
    await database.dispose()

    assert "tool_call_id" in columns
    assert version_rows == [("20260423_000002",)]
    assert status.ok is True
    assert status.schema_ready is True
