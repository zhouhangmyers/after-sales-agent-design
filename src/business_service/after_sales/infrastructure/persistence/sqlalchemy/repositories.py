from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import String, cast, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

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
from business_service.after_sales.infrastructure.persistence.sqlalchemy.models import (
    ApprovalRecord,
    AuditLog,
    Customer,
    Order,
    PolicyArticle,
    RefundRequest,
    Shipment,
    Ticket,
    ToolCallLog,
)


def utcnow() -> datetime:
    return datetime.now(UTC)


class SqlAlchemyAfterSalesRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_customer(self, customer_id: str) -> CustomerRead | None:
        customer = await self._session.get(Customer, customer_id)
        return CustomerRead.model_validate(customer) if customer is not None else None

    async def get_order(self, order_id: str) -> OrderRead | None:
        order = await self._session.get(Order, order_id)
        return OrderRead.model_validate(order) if order is not None else None

    async def get_shipment(self, order_id: str) -> ShipmentRead | None:
        shipment = await self._session.scalar(
            select(Shipment).where(Shipment.order_id == order_id)
        )
        return ShipmentRead.model_validate(shipment) if shipment is not None else None

    async def search_policies(self, query: str) -> list[PolicyArticleRead]:
        pattern = f"%{query}%"
        stmt = (
            select(PolicyArticle)
            .where(
                or_(
                    PolicyArticle.title.ilike(pattern),
                    PolicyArticle.category.ilike(pattern),
                    cast(PolicyArticle.keywords, String).ilike(pattern),
                    PolicyArticle.content.ilike(pattern),
                )
            )
            .order_by(PolicyArticle.created_at.desc())
        )
        policies = await self._session.scalars(stmt)
        return [PolicyArticleRead.model_validate(item) for item in policies]

    async def create_ticket(self, payload: TicketCreate) -> TicketRead:
        order = await self._session.get(Order, payload.order_id)
        if order is None:
            raise ValueError(f"order not found: {payload.order_id}")
        ticket = Ticket(
            ticket_id=f"TCK-{uuid4().hex[:8].upper()}",
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

    async def get_ticket(self, ticket_id: str) -> TicketRead | None:
        ticket = await self._session.get(Ticket, ticket_id)
        return TicketRead.model_validate(ticket) if ticket is not None else None

    async def create_refund_request(
        self,
        payload: RefundRequestCreate,
        *,
        status: str = "submitted",
    ) -> RefundRequestRead:
        order = await self._session.get(Order, payload.order_id)
        if order is None:
            raise ValueError(f"order not found: {payload.order_id}")
        refund_request = RefundRequest(
            refund_request_id=f"REF-{uuid4().hex[:8].upper()}",
            order_id=payload.order_id,
            amount=Decimal(payload.amount),
            reason=payload.reason,
            status=status,
            requires_approval=payload.requires_approval,
            created_at=utcnow(),
            updated_at=utcnow(),
        )
        self._session.add(refund_request)
        await self._session.flush()
        await self._session.refresh(refund_request)
        return RefundRequestRead.model_validate(refund_request)

    async def start_tool_call(
        self,
        *,
        conversation_id: str | None,
        tool_call_id: str | None,
        tool_name: str,
        tool_arguments: dict[str, object],
    ) -> int:
        tool_call_log = ToolCallLog(
            conversation_id=conversation_id,
            tool_call_id=tool_call_id,
            tool_name=tool_name,
            tool_arguments_json=tool_arguments,
            status="started",
            started_at=utcnow(),
        )
        self._session.add(tool_call_log)
        await self._session.flush()
        await self._session.refresh(tool_call_log)
        return tool_call_log.id

    async def finish_tool_call(
        self,
        *,
        log_id: int,
        success: bool,
        latency_ms: float,
        result: dict[str, object] | None,
        error_message: str | None,
    ) -> None:
        tool_call_log = await self._session.get(ToolCallLog, log_id)
        if tool_call_log is None:
            return
        tool_call_log.status = "succeeded" if success else "failed"
        tool_call_log.finished_at = utcnow()
        tool_call_log.latency_ms = latency_ms
        tool_call_log.result_json = result
        tool_call_log.error_message = error_message
        await self._session.flush()

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
    ) -> None:
        approval_record = ApprovalRecord(
            approval_id=f"APR-{uuid4().hex[:8].upper()}",
            conversation_id=conversation_id,
            tool_call_id=tool_call_id,
            tool_name=tool_name,
            status="pending",
            order_id=order_id,
            amount=amount,
            reason=reason,
            risk_level=risk_level,
            display_payload_json=display_payload,
            requested_at=utcnow(),
        )
        self._session.add(approval_record)
        await self._session.flush()

    async def resolve_approval(
        self,
        *,
        conversation_id: str,
        tool_call_id: str | None,
        status: str,
    ) -> None:
        filters = [
            ApprovalRecord.conversation_id == conversation_id,
            ApprovalRecord.status == "pending",
        ]
        if tool_call_id is not None:
            filters.append(ApprovalRecord.tool_call_id == tool_call_id)

        stmt = select(ApprovalRecord).where(*filters).order_by(
            ApprovalRecord.requested_at.desc()
        )
        approval_record = await self._session.scalar(stmt)
        if approval_record is None:
            return
        approval_record.status = status
        approval_record.resolved_at = utcnow()
        await self._session.flush()

    async def record_audit_log(
        self,
        *,
        conversation_id: str | None,
        event_type: str,
        payload: dict[str, object],
    ) -> AuditLogRead:
        audit_log = AuditLog(
            conversation_id=conversation_id,
            event_type=event_type,
            payload_json=payload,
            created_at=utcnow(),
        )
        self._session.add(audit_log)
        await self._session.flush()
        await self._session.refresh(audit_log)
        return AuditLogRead.model_validate(audit_log)

    async def list_audit_logs(self, run_id: str) -> list[AuditLogRead]:
        stmt = (
            select(AuditLog)
            .where(AuditLog.conversation_id == run_id)
            .order_by(AuditLog.created_at.asc(), AuditLog.id.asc())
        )
        logs = await self._session.scalars(stmt)
        return [AuditLogRead.model_validate(item) for item in logs]
