from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from decimal import Decimal

from after_sales.application.ports import AfterSalesUnitOfWork
from after_sales.domain.entities import (
    ApprovalRiskLevel,
    AuditLogRead,
    CustomerRead,
    OrderRead,
    PolicyArticleRead,
    RefundApprovalRequirement,
    RefundRequestCreate,
    RefundRequestRead,
    ShipmentRead,
    TicketCreate,
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

    # ============================================================
    # 查询类业务方法：客户、订单、物流、工单、政策、审计日志
    # ============================================================

    async def get_customer_detail(self, customer_id: str) -> CustomerRead:
        async with self._unit_of_work_factory() as uow:
            customer = await uow.repository.get_customer_detail(customer_id)
        if customer is None:
            raise ValueError(f"customer not found: {customer_id}")
        return customer

    async def get_order_detail(self, order_id: str) -> OrderRead:
        async with self._unit_of_work_factory() as uow:
            order = await uow.repository.get_order_detail(order_id)
        if order is None:
            raise ValueError(f"order not found: {order_id}")
        return order

    async def get_shipment_detail(self, order_id: str) -> ShipmentRead:
        async with self._unit_of_work_factory() as uow:
            shipment = await uow.repository.get_shipment_detail(order_id)
        if shipment is None:
            raise ValueError(f"shipment not found for order: {order_id}")
        return shipment

    async def get_ticket_detail(self, ticket_id: str) -> TicketRead:
        async with self._unit_of_work_factory() as uow:
            ticket = await uow.repository.get_ticket_detail(ticket_id)
        if ticket is None:
            raise ValueError(f"ticket not found: {ticket_id}")
        return ticket

    async def search_after_sales_policy(self, query: str) -> list[PolicyArticleRead]:
        async with self._unit_of_work_factory() as uow:
            return await uow.repository.search_after_sales_policy(query)

    async def list_audit_logs(self, run_id: str) -> list[AuditLogRead]:
        async with self._unit_of_work_factory() as uow:
            return await uow.repository.list_audit_logs(run_id)

    # ============================================================
    # 工单类业务方法：创建售后工单
    # ============================================================

    async def create_ticket(self, payload: TicketCreate) -> TicketRead:
        async with self._unit_of_work_factory() as uow:
            ticket = await uow.repository.create_ticket(payload)
            await uow.commit()
            return ticket

    # ============================================================
    # 退款类业务方法：提交退款申请、审批规则判断
    # ============================================================

    async def submit_refund_request(
        self,
        payload: RefundRequestCreate,
        *,
        approval_granted: bool = False,
    ) -> RefundRequestRead:
        # Service 必须重新执行审批规则，不能直接信任前端或 Agent 传来的 requires_approval。
        approval_required = self.evaluate_refund_approval(payload) is not None
        requires_approval = payload.requires_approval or approval_required
        if approval_granted:
            status = "approved"
        elif requires_approval:
            status = "pending_approval"
        else:
            status = "submitted"
        async with self._unit_of_work_factory() as uow:
            refund_request = await uow.repository.submit_refund_request(
                RefundRequestCreate.model_validate(
                    {
                        **payload.model_dump(),
                        # 风险标记只能升级，不能降级：任一来源认为需要审批，最终就记录为需要审批。
                        "requires_approval": requires_approval,
                    }
                ),
                status=status,
            )
            await uow.commit()
            return refund_request

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
            # 这里的 reason 是“为什么需要人工审批”，不是用户提交退款时填写的退款原因。
            reason=reason_text,
            risk_level=risk_level,
            display_payload={
                "order_id": payload.order_id,
                "amount": float(payload.amount),
                # display_payload["reason"] 展示给审批客服看，表示用户提交退款时填写的原因。
                "reason": payload.reason,
                "risk_level": risk_level,
            },
        )
