from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

type ApprovalRiskLevel = Literal["low", "medium", "high"]  # 退款审批风险等级取值。


class DomainModel(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class CustomerRead(DomainModel):
    customer_id: str  # 客户唯一标识。
    name: str  # 客户姓名。
    email: str  # 客户邮箱地址。
    phone: str  # 客户联系电话。
    created_at: datetime  # 客户资料创建时间。


class OrderRead(DomainModel):
    order_id: str  # 订单唯一标识。
    customer_id: str  # 下单客户 ID。
    status: str  # 当前订单状态。
    total_amount: Decimal  # 订单总金额。
    currency: str  # 订单金额币种。
    item_summary: str  # 订单商品摘要。
    created_at: datetime  # 订单创建时间。


class ShipmentRead(DomainModel):
    shipment_id: str  # 物流记录或发货单的唯一标识。
    order_id: str  # 关联的订单 ID。
    carrier: str  # 承运商或物流公司名称。
    tracking_no: str  # 物流运单号，用于查询运输轨迹。
    status: str  # 当前物流状态。
    latest_location: str | None = None  # 最近一次物流事件发生的位置；未知时为空。
    estimated_delivery_at: datetime | None = None  # 预计送达时间；无法预估时为空。
    events_json: list[dict[str, Any]] = Field(default_factory=list)  # 物流轨迹事件列表，保留事件的结构化明细。
    updated_at: datetime  # 物流记录最后更新时间。


class TicketCreate(DomainModel):
    order_id: str  # 需要创建售后工单的订单 ID。
    issue_type: Literal["damaged", "return", "exchange", "other"]  # 售后问题类型。
    summary: str  # 用户描述的问题摘要。
    priority: Literal["low", "normal", "high"] = "normal"  # 工单优先级，默认普通。


class TicketRead(DomainModel):
    ticket_id: str  # 售后工单唯一标识。
    order_id: str  # 关联的订单 ID。
    customer_id: str  # 关联的客户 ID。
    issue_type: str  # 售后问题类型。
    summary: str  # 工单问题摘要。
    priority: str  # 工单优先级。
    status: str  # 当前工单状态。
    created_at: datetime  # 工单创建时间。
    updated_at: datetime  # 工单最后更新时间。


class RefundRequestCreate(DomainModel):
    order_id: str  # 需要申请退款的订单 ID。
    amount: Decimal  # 申请退款金额。
    reason: str  # 用户填写的退款原因。
    requires_approval: bool = False  # 是否需要人工审批，默认不需要。


class RefundRequestRead(DomainModel):
    refund_request_id: str  # 退款申请唯一标识。
    order_id: str  # 关联的订单 ID。
    amount: Decimal  # 申请退款金额。
    reason: str  # 用户填写的退款原因。
    status: str  # 当前退款申请状态。
    requires_approval: bool  # 是否需要人工审批。
    created_at: datetime  # 退款申请创建时间。
    updated_at: datetime  # 退款申请最后更新时间。


class RefundApprovalRequirement(DomainModel):
    reason: str  # 为什么这笔退款申请需要人工审批，不是用户填写的退款原因。
    risk_level: ApprovalRiskLevel = "low"  # 审批风险等级，默认低风险。
    display_payload: dict[str, Any] = Field(default_factory=dict)  # 审批界面展示摘要；其中 reason 是用户退款原因。


class PolicyArticleRead(DomainModel):
    article_id: str  # 售后政策文章唯一标识。
    title: str  # 政策文章标题。
    category: str  # 政策文章分类。
    keywords: list[str] = Field(default_factory=list)  # 用于搜索和匹配的关键词列表。
    content: str  # 政策文章正文内容。
    created_at: datetime  # 政策文章创建时间。


class AuditLogRead(DomainModel):
    id: int  # 审计日志自增主键。
    conversation_id: str | None = None  # 关联的会话 ID；没有会话上下文时为空。
    event_type: str  # 审计事件类型。
    payload_json: dict[str, Any] = Field(default_factory=dict)  # 审计事件的结构化载荷。
    created_at: datetime  # 审计日志创建时间。
