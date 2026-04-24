from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from agent_service.contracts.actions import (
    ApprovalRequirement,
    CallableApprovalPolicy,
    ToolContext,
    ToolSpec,
)
from agent_service.contracts.capability import AgentDefinition
from business_service.after_sales.application.services.after_sales_service import (
    AfterSalesService,
)
from business_service.after_sales.domain.entities import (
    OrderLookupInput,
    PolicySearchInput,
    RefundRequestCreate,
    TicketCreate,
    TicketLookupInput,
)


def build_after_sales_agent_definition(
    *,
    after_sales_service: AfterSalesService,
) -> AgentDefinition:
    async def get_order_detail(
        payload: dict[str, Any],
        context: ToolContext,
    ) -> dict[str, Any]:
        del context
        order = await after_sales_service.get_order_detail(
            OrderLookupInput.model_validate(payload)
        )
        return order.model_dump(mode="json")

    async def get_shipment_detail(
        payload: dict[str, Any],
        context: ToolContext,
    ) -> dict[str, Any]:
        del context
        shipment = await after_sales_service.get_shipment_detail(
            OrderLookupInput.model_validate(payload)
        )
        return shipment.model_dump(mode="json")

    async def create_ticket(
        payload: dict[str, Any],
        context: ToolContext,
    ) -> dict[str, Any]:
        del context
        ticket = await after_sales_service.create_ticket(TicketCreate.model_validate(payload))
        return ticket.model_dump(mode="json")

    async def get_ticket_detail(
        payload: dict[str, Any],
        context: ToolContext,
    ) -> dict[str, Any]:
        del context
        ticket = await after_sales_service.get_ticket_detail(
            TicketLookupInput.model_validate(payload)
        )
        return ticket.model_dump(mode="json")

    async def submit_refund_request(
        payload: dict[str, Any],
        context: ToolContext,
    ) -> dict[str, Any]:
        del context
        refund_request = await after_sales_service.submit_refund_request(
            RefundRequestCreate.model_validate(payload)
        )
        return refund_request.model_dump(mode="json")

    async def search_after_sales_policy(
        payload: dict[str, Any],
        context: ToolContext,
    ) -> list[dict[str, Any]]:
        del context
        return [
            item.model_dump(mode="json")
            for item in await after_sales_service.search_after_sales_policy(
                PolicySearchInput.model_validate(payload)
            )
        ]

    def evaluate_refund_approval(payload: dict[str, Any]) -> ApprovalRequirement | None:
        try:
            requirement = after_sales_service.evaluate_refund_approval(
                RefundRequestCreate.model_validate(payload)
            )
        except ValidationError:
            return None
        if requirement is None:
            return None
        return ApprovalRequirement(
            reason=requirement.reason,
            risk_level=requirement.risk_level,
            display_payload=requirement.display_payload,
        )

    system_prompt = "".join(
        (
            "你是售后客服专家。",
            "你的目标是帮助用户完成查单、查物流、建工单、退款申请和售后政策解释。",
            "当用户查询订单状态时，优先调用 get_order_detail。",
            "当用户追问物流状态、运输位置、到哪了时，优先调用 get_shipment_detail。",
            "当用户描述破损、退货、换货并要求登记处理时，优先调用 create_ticket。",
            "当用户追问工单状态时，调用 get_ticket_detail。",
            "当用户明确要求退款并提供订单号、金额和原因时，调用 submit_refund_request。",
            "回复必须简洁、专业、中文输出。",
            "如果动作已经返回结果，优先基于结果作答，不要编造业务数据。",
            "每轮最多调用一个工具。",
        )
    )

    return AgentDefinition(
        capability_id="after_sales_assistant",
        name="After-Sales Assistant",
        description="售后客服 agent，支持查单、物流、工单、退款审批和政策查询。",
        system_prompt=system_prompt,
        tools=(
            ToolSpec(
                name="get_order_detail",
                description="获取订单详情，适用于查询订单状态、商品概要和下单信息。",
                args_schema=OrderLookupInput,
                handler=get_order_detail,
            ),
            ToolSpec(
                name="get_shipment_detail",
                description="获取物流详情，适用于查询运输节点和最新位置。",
                args_schema=OrderLookupInput,
                handler=get_shipment_detail,
            ),
            ToolSpec(
                name="create_ticket",
                description="创建售后工单，适用于破损、退货、换货等问题登记。",
                args_schema=TicketCreate,
                handler=create_ticket,
            ),
            ToolSpec(
                name="get_ticket_detail",
                description="查询工单详情，适用于确认工单状态与摘要。",
                args_schema=TicketLookupInput,
                handler=get_ticket_detail,
            ),
            ToolSpec(
                name="submit_refund_request",
                description="提交退款申请。命中审批策略时会先等待人工动作。",
                args_schema=RefundRequestCreate,
                handler=submit_refund_request,
                approval_policy=CallableApprovalPolicy(evaluate_refund_approval),
            ),
            ToolSpec(
                name="search_after_sales_policy",
                description="搜索售后政策、退款规则和售后 SOP。",
                args_schema=PolicySearchInput,
                handler=search_after_sales_policy,
            ),
        ),
    )
