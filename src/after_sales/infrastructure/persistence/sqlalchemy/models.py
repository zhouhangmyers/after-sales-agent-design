from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from after_sales.infrastructure.persistence.sqlalchemy.session import (
    Base,
)


def utcnow() -> datetime:
    return datetime.now(UTC)


# ============================================================
# 售后业务相关 ORM
# ============================================================
# 这些表直接支撑售后业务：客户、订单、物流、工单、退款申请和政策文章。


class Customer(Base):
    __tablename__ = "customers"

    customer_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    phone: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    orders: Mapped[list[Order]] = relationship(back_populates="customer")
    tickets: Mapped[list[Ticket]] = relationship(back_populates="customer")


class Order(Base):
    __tablename__ = "orders"

    order_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    customer_id: Mapped[str] = mapped_column(ForeignKey("customers.customer_id"), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    total_amount: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(8), nullable=False, default="CNY")
    item_summary: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    customer: Mapped[Customer] = relationship(back_populates="orders")
    shipment: Mapped[Shipment | None] = relationship(back_populates="order", uselist=False)
    tickets: Mapped[list[Ticket]] = relationship(back_populates="order")
    refund_requests: Mapped[list[RefundRequest]] = relationship(back_populates="order")


class Shipment(Base):
    __tablename__ = "shipments"

    shipment_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    order_id: Mapped[str] = mapped_column(ForeignKey("orders.order_id"), nullable=False, unique=True)
    carrier: Mapped[str] = mapped_column(String(64), nullable=False)
    tracking_no: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    latest_location: Mapped[str | None] = mapped_column(String(255))
    estimated_delivery_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    events_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    order: Mapped[Order] = relationship(back_populates="shipment")


class Ticket(Base):
    __tablename__ = "tickets"

    ticket_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    order_id: Mapped[str] = mapped_column(ForeignKey("orders.order_id"), nullable=False)
    customer_id: Mapped[str] = mapped_column(ForeignKey("customers.customer_id"), nullable=False)
    issue_type: Mapped[str] = mapped_column(String(32), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    priority: Mapped[str] = mapped_column(String(16), nullable=False, default="normal")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="open")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    order: Mapped[Order] = relationship(back_populates="tickets")
    customer: Mapped[Customer] = relationship(back_populates="tickets")


class RefundRequest(Base):
    __tablename__ = "refund_requests"

    refund_request_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    order_id: Mapped[str] = mapped_column(ForeignKey("orders.order_id"), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    requires_approval: Mapped[bool] = mapped_column(nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    order: Mapped[Order] = relationship(back_populates="refund_requests")


class PolicyArticle(Base):
    __tablename__ = "policy_articles"

    article_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    category: Mapped[str] = mapped_column(String(64), nullable=False)
    keywords: Mapped[list[str]] = mapped_column(JSON, default=list)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


# ============================================================
# 其它 ORM：Agent 运行态投影和审计
# ============================================================
# 这些表不是售后业务主实体，暂时归到“其它”：工具调用日志、人工审批记录和审计日志。


class ToolCallLog(Base):
    __tablename__ = "tool_call_logs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    conversation_id: Mapped[str | None] = mapped_column(String(64))
    tool_call_id: Mapped[str | None] = mapped_column(String(64))
    tool_name: Mapped[str] = mapped_column(String(128), nullable=False)
    tool_arguments_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    latency_ms: Mapped[float | None] = mapped_column(nullable=True)
    result_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text)


class ApprovalRecord(Base):
    __tablename__ = "approval_records"

    approval_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    conversation_id: Mapped[str] = mapped_column(String(64), nullable=False)
    tool_call_id: Mapped[str | None] = mapped_column(String(64))
    tool_name: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    order_id: Mapped[str | None] = mapped_column(String(32))
    amount: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    reason: Mapped[str | None] = mapped_column(Text)
    risk_level: Mapped[str] = mapped_column(String(16), nullable=False, default="low")
    display_payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    conversation_id: Mapped[str | None] = mapped_column(String(64))
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
