from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from decimal import Decimal

from business_service.after_sales.application.ports import AfterSalesUnitOfWork
from business_service.after_sales.domain.entities import (
    ApprovalRiskLevel,
    AuditLogRead,
    CustomerRead,
    OrderLookupInput,
    OrderRead,
    PolicyArticleRead,
    PolicySearchInput,
    RefundApprovalRequirement,
    RefundRequestCreate,
    RefundRequestRead,
    ShipmentRead,
    TicketCreate,
    TicketLookupInput,
    TicketRead,
)

_RISK_KEYWORDS = ("破损", "质量问题")


class AfterSalesService:
    def __init__(
        self,
        *,
        unit_of_work_factory: Callable[
            [],
            AbstractAsyncContextManager[AfterSalesUnitOfWork],
        ],
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory

    async def get_customer_detail(self, customer_id: str) -> CustomerRead:
        async with self._unit_of_work_factory() as uow:
            customer = await uow.repository.get_customer(customer_id)
        if customer is None:
            raise ValueError(f"customer not found: {customer_id}")
        return customer

    async def get_order_detail(self, payload: OrderLookupInput) -> OrderRead:
        async with self._unit_of_work_factory() as uow:
            order = await uow.repository.get_order(payload.order_id)
        if order is None:
            raise ValueError(f"order not found: {payload.order_id}")
        return order

    async def get_shipment_detail(self, payload: OrderLookupInput) -> ShipmentRead:
        async with self._unit_of_work_factory() as uow:
            shipment = await uow.repository.get_shipment(payload.order_id)
        if shipment is None:
            raise ValueError(f"shipment not found for order: {payload.order_id}")
        return shipment

    async def create_ticket(self, payload: TicketCreate) -> TicketRead:
        async with self._unit_of_work_factory() as uow:
            ticket = await uow.repository.create_ticket(payload)
            await uow.commit()
            return ticket

    async def get_ticket_detail(self, payload: TicketLookupInput) -> TicketRead:
        async with self._unit_of_work_factory() as uow:
            ticket = await uow.repository.get_ticket(payload.ticket_id)
        if ticket is None:
            raise ValueError(f"ticket not found: {payload.ticket_id}")
        return ticket

    async def submit_refund_request(self, payload: RefundRequestCreate) -> RefundRequestRead:
        approval_required = self.evaluate_refund_approval(payload) is not None
        async with self._unit_of_work_factory() as uow:
            refund_request = await uow.repository.create_refund_request(
                RefundRequestCreate.model_validate(
                    {
                        **payload.model_dump(),
                        "requires_approval": payload.requires_approval or approval_required,
                    }
                ),
                status="approved",
            )
            await uow.commit()
            return refund_request

    async def create_refund_request(self, payload: RefundRequestCreate) -> RefundRequestRead:
        async with self._unit_of_work_factory() as uow:
            refund_request = await uow.repository.create_refund_request(payload)
            await uow.commit()
            return refund_request

    async def search_after_sales_policy(
        self,
        payload: PolicySearchInput,
    ) -> list[PolicyArticleRead]:
        async with self._unit_of_work_factory() as uow:
            return await uow.repository.search_policies(payload.query)

    async def list_audit_logs(self, run_id: str) -> list[AuditLogRead]:
        async with self._unit_of_work_factory() as uow:
            return await uow.repository.list_audit_logs(run_id)

    def evaluate_refund_approval(
        self,
        payload: RefundRequestCreate,
    ) -> RefundApprovalRequirement | None:
        keyword_hit = any(keyword in payload.reason for keyword in _RISK_KEYWORDS)
        amount_hit = Decimal(payload.amount) > Decimal("100")
        if not keyword_hit and not amount_hit:
            return None

        risk_level: ApprovalRiskLevel
        if keyword_hit and amount_hit:
            reason_text = "退款金额超过 100 元，且原因涉及破损或质量问题，需要人工审批。"
            risk_level = "high"
        elif keyword_hit:
            reason_text = "退款原因涉及破损或质量问题，需要人工审批。"
            risk_level = "high"
        else:
            reason_text = "退款金额超过 100 元，需要人工审批。"
            risk_level = "medium"

        return RefundApprovalRequirement(
            reason=reason_text,
            risk_level=risk_level,
            display_payload={
                "order_id": payload.order_id,
                "amount": float(payload.amount),
                "reason": payload.reason,
                "risk_level": risk_level,
            },
        )
