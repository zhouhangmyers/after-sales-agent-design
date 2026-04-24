from __future__ import annotations

from decimal import Decimal
from typing import Protocol

from business_service.after_sales.domain.entities import (
    AuditLogRead,
    CustomerRead,
    OrderRead,
    PolicyArticleRead,
    RefundRequestCreate,
    RefundRequestRead,
    ShipmentRead,
    TicketCreate,
    TicketRead,
)


class AfterSalesRepository(Protocol):
    async def get_customer(self, customer_id: str) -> CustomerRead | None: ...

    async def get_order(self, order_id: str) -> OrderRead | None: ...

    async def get_shipment(self, order_id: str) -> ShipmentRead | None: ...

    async def search_policies(self, query: str) -> list[PolicyArticleRead]: ...

    async def create_ticket(self, payload: TicketCreate) -> TicketRead: ...

    async def get_ticket(self, ticket_id: str) -> TicketRead | None: ...

    async def create_refund_request(
        self,
        payload: RefundRequestCreate,
        *,
        status: str = "submitted",
    ) -> RefundRequestRead: ...

    async def list_audit_logs(self, run_id: str) -> list[AuditLogRead]: ...

    async def start_tool_call(
        self,
        *,
        conversation_id: str | None,
        tool_call_id: str | None,
        tool_name: str,
        tool_arguments: dict[str, object],
    ) -> int: ...

    async def finish_tool_call(
        self,
        *,
        log_id: int,
        success: bool,
        latency_ms: float,
        result: dict[str, object] | None,
        error_message: str | None,
    ) -> None: ...

    async def request_approval(
        self,
        *,
        conversation_id: str,
        tool_call_id: str | None,
        tool_name: str,
        order_id: str | None,
        amount: Decimal | None,
        reason: str | None,
        risk_level: str,
        display_payload: dict[str, object],
    ) -> None: ...

    async def resolve_approval(
        self,
        *,
        conversation_id: str,
        tool_call_id: str | None,
        status: str,
    ) -> None: ...

    async def record_audit_log(
        self,
        *,
        conversation_id: str | None,
        event_type: str,
        payload: dict[str, object],
    ) -> AuditLogRead: ...


class AfterSalesUnitOfWork(Protocol):
    @property
    def repository(self) -> AfterSalesRepository: ...

    async def commit(self) -> None: ...

    async def rollback(self) -> None: ...
