from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ValidationError

from after_sales.application.services.after_sales_service import (
    AfterSalesService,
)
from after_sales.domain.entities import (
    RefundRequestCreate,
    TicketCreate,
)
from agent_core.contracts.agent_definition import AgentDefinition
from agent_core.contracts.tool_spec import (
    ApprovalRequirement,
    CallableApprovalPolicy,
    ToolContext,
    ToolSpec,
)


class OrderLookupArgs(BaseModel):
    order_id: str


class TicketLookupArgs(BaseModel):
    ticket_id: str


class PolicySearchArgs(BaseModel):
    query: str


def build_after_sales_agent_definition(
    *,
    after_sales_service: AfterSalesService,
) -> AgentDefinition:
    async def get_order_detail(
        payload: dict[str, Any],
        context: ToolContext,
    ) -> dict[str, Any]:
        del context
        args = OrderLookupArgs.model_validate(payload)
        order = await after_sales_service.get_order_detail(args.order_id)
        return order.model_dump(mode="json")

    async def get_shipment_detail(
        payload: dict[str, Any],
        context: ToolContext,
    ) -> dict[str, Any]:
        del context
        args = OrderLookupArgs.model_validate(payload)
        shipment = await after_sales_service.get_shipment_detail(args.order_id)
        return shipment.model_dump(mode="json")

    async def create_ticket(
        payload: dict[str, Any],
        context: ToolContext,
    ) -> dict[str, Any]:
        del context
        created_ticket = await after_sales_service.create_ticket(
            TicketCreate.model_validate(payload)
        )
        verified_ticket = await after_sales_service.get_ticket_detail(
            created_ticket.ticket_id
        )
        if verified_ticket.ticket_id != created_ticket.ticket_id:
            raise RuntimeError(
                f"ticket persistence verification mismatch: {created_ticket.ticket_id}"
            )
        return {
            **verified_ticket.model_dump(mode="json"),
            "persistence": {
                "verified": True,
                "checked_by": "get_ticket_detail",
                "checked_ticket_id": verified_ticket.ticket_id,
            },
        }

    async def get_ticket_detail(
        payload: dict[str, Any],
        context: ToolContext,
    ) -> dict[str, Any]:
        del context
        args = TicketLookupArgs.model_validate(payload)
        ticket = await after_sales_service.get_ticket_detail(args.ticket_id)
        return ticket.model_dump(mode="json")

    async def submit_refund_request(
        payload: dict[str, Any],
        context: ToolContext,
    ) -> dict[str, Any]:
        del context
        refund_payload = RefundRequestCreate.model_validate(payload)
        refund_request = await after_sales_service.submit_refund_request(
            refund_payload,
            approval_granted=after_sales_service.evaluate_refund_approval(refund_payload)
            is not None,
        )
        return refund_request.model_dump(mode="json")

    async def search_after_sales_policy(
        payload: dict[str, Any],
        context: ToolContext,
    ) -> list[dict[str, Any]]:
        del context
        args = PolicySearchArgs.model_validate(payload)
        return [
            item.model_dump(mode="json")
            for item in await after_sales_service.search_after_sales_policy(args.query)
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
            "当用户明确要求登记、创建、生成或提交售后工单，并且提供订单号和问题描述时，必须调用 create_ticket，不能只口头承诺已经创建。",
            "如果用户要建工单但缺少订单号或问题描述，先追问缺失信息，不要编造。",
            "调用 create_ticket 后，必须根据工具返回的 persistence.verified 字段回复；只有 verified 为 true 时，才告诉用户工单已写入数据库并返回工单号。",
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
                args_schema=OrderLookupArgs,
                handler=get_order_detail,
            ),
            ToolSpec(
                name="get_shipment_detail",
                description="获取物流详情，适用于查询运输节点和最新位置。",
                args_schema=OrderLookupArgs,
                handler=get_shipment_detail,
            ),
            ToolSpec(
                name="create_ticket",
                description="创建售后工单，适用于破损、退货、换货等问题登记。工具会先写入业务数据库，再按 ticket_id 查询数据库确认持久化，返回 persistence.verified。只有调用该工具且 verified=true 才表示工单真正写入数据库，不能用纯文本回复代替。",
                args_schema=TicketCreate,
                handler=create_ticket,
            ),
            ToolSpec(
                name="get_ticket_detail",
                description="查询工单详情，适用于确认工单状态与摘要。",
                args_schema=TicketLookupArgs,
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
                args_schema=PolicySearchArgs,
                handler=search_after_sales_policy,
            ),
        ),
    )
