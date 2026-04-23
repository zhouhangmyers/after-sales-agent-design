from __future__ import annotations

from decimal import Decimal
from typing import Any

from agent_service.contracts.actions import AgentActionDefinition, AgentExecutionContext
from agent_service.contracts.capability import AgentCapability
from agent_service.tools.models import ApprovalRequirement
from business_service.after_sales.domain.entities import (
    OrderLookupInput,
    PolicySearchInput,
    RefundRequestCreate,
    TicketCreate,
    TicketLookupInput,
)
from business_service.after_sales.infrastructure.persistence.sqlalchemy.repositories import (
    SqlAlchemyAfterSalesRepository,
)

_RISK_KEYWORDS = ("破损", "质量问题")


def build_capability(
    *,
    repository: SqlAlchemyAfterSalesRepository,
) -> AgentCapability:
    def get_order_detail(
        payload: dict[str, Any],
        context: AgentExecutionContext,
    ) -> dict[str, Any]:
        del context
        order_id = str(payload["order_id"])
        order = repository.get_order(order_id)
        if order is None:
            raise ValueError(f"order not found: {order_id}")
        return order.model_dump(mode="json")

    def get_shipment_detail(
        payload: dict[str, Any],
        context: AgentExecutionContext,
    ) -> dict[str, Any]:
        del context
        order_id = str(payload["order_id"])
        shipment = repository.get_shipment(order_id)
        if shipment is None:
            raise ValueError(f"shipment not found for order: {order_id}")
        return shipment.model_dump(mode="json")

    def create_ticket(
        payload: dict[str, Any],
        context: AgentExecutionContext,
    ) -> dict[str, Any]:
        del context
        ticket = repository.create_ticket(TicketCreate.model_validate(payload))
        return ticket.model_dump(mode="json")

    def get_ticket_detail(
        payload: dict[str, Any],
        context: AgentExecutionContext,
    ) -> dict[str, Any]:
        del context
        ticket_id = str(payload["ticket_id"])
        ticket = repository.get_ticket(ticket_id)
        if ticket is None:
            raise ValueError(f"ticket not found: {ticket_id}")
        return ticket.model_dump(mode="json")

    def submit_refund_request(
        payload: dict[str, Any],
        context: AgentExecutionContext,
    ) -> dict[str, Any]:
        del context
        approval_required = evaluate_refund_approval(payload) is not None
        refund_request = repository.create_refund_request(
            RefundRequestCreate.model_validate(
                {
                    **payload,
                    "requires_approval": bool(payload.get("requires_approval"))
                    or approval_required,
                }
            ),
            status="approved",
        )
        return refund_request.model_dump(mode="json")

    def search_after_sales_policy(
        payload: dict[str, Any],
        context: AgentExecutionContext,
    ) -> list[dict[str, Any]]:
        del context
        return [
            item.model_dump(mode="json")
            for item in repository.search_policies(str(payload["query"]))
        ]

    return AgentCapability(
        capability_id="after_sales_assistant",
        role_title="售后客服专家",
        domain_objective="帮助用户完成查单、查物流、建工单、退款申请和售后政策解释。",
        action_selection_rules=(
            "当用户查询订单状态时，优先调用 get_order_detail。",
            "当用户追问物流状态、运输位置、到哪了时，优先调用 get_shipment_detail。",
            "当用户描述破损、退货、换货并要求登记处理时，优先调用 create_ticket。",
            "当用户追问工单状态时，调用 get_ticket_detail。",
            "当用户明确要求退款并提供订单号、金额和原因时，调用 submit_refund_request。",
        ),
        response_rules=(
            "回复必须简洁、专业、中文输出。",
            "如果动作已经返回结果，优先基于结果作答，不要编造业务数据。",
        ),
        actions=(
            AgentActionDefinition(
                name="get_order_detail",
                description="获取订单详情，适用于查询订单状态、商品概要和下单信息。",
                args_schema=OrderLookupInput,
                handler=get_order_detail,
            ),
            AgentActionDefinition(
                name="get_shipment_detail",
                description="获取物流详情，适用于查询运输节点和最新位置。",
                args_schema=OrderLookupInput,
                handler=get_shipment_detail,
            ),
            AgentActionDefinition(
                name="create_ticket",
                description="创建售后工单，适用于破损、退货、换货等问题登记。",
                args_schema=TicketCreate,
                handler=create_ticket,
            ),
            AgentActionDefinition(
                name="get_ticket_detail",
                description="查询工单详情，适用于确认工单状态与摘要。",
                args_schema=TicketLookupInput,
                handler=get_ticket_detail,
            ),
            AgentActionDefinition(
                name="submit_refund_request",
                description="提交退款申请。命中审批策略时会先等待人工动作。",
                args_schema=RefundRequestCreate,
                handler=submit_refund_request,
                approval_evaluator=evaluate_refund_approval,
            ),
            AgentActionDefinition(
                name="search_after_sales_policy",
                description="搜索售后政策、退款规则和售后 SOP。",
                args_schema=PolicySearchInput,
                handler=search_after_sales_policy,
            ),
        ),
    )


def evaluate_refund_approval(payload: dict[str, Any]) -> ApprovalRequirement | None:
    order_id = payload.get("order_id")
    amount = _to_decimal(payload.get("amount"))
    reason = payload.get("reason")
    if not isinstance(order_id, str) or amount is None or not isinstance(reason, str):
        return None

    keyword_hit = any(keyword in reason for keyword in _RISK_KEYWORDS)
    amount_hit = amount > Decimal("100")
    if not keyword_hit and not amount_hit:
        return None

    if keyword_hit and amount_hit:
        reason_text = "退款金额超过 100 元，且原因涉及破损或质量问题，需要人工审批。"
        risk_level = "high"
    elif keyword_hit:
        reason_text = "退款原因涉及破损或质量问题，需要人工审批。"
        risk_level = "high"
    else:
        reason_text = "退款金额超过 100 元，需要人工审批。"
        risk_level = "medium"

    return ApprovalRequirement(
        reason=reason_text,
        risk_level=risk_level,
        display_payload={
            "order_id": order_id,
            "amount": float(amount),
            "reason": reason,
            "risk_level": risk_level,
        },
    )


def _to_decimal(value: object) -> Decimal | None:
    if isinstance(value, Decimal):
        return value
    if isinstance(value, int | float | str):
        return Decimal(str(value))
    return None
