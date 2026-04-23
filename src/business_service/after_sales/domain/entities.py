from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class DomainModel(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class CustomerRead(DomainModel):
    customer_id: str
    name: str
    email: str
    phone: str
    created_at: datetime


class OrderRead(DomainModel):
    order_id: str
    customer_id: str
    status: str
    total_amount: Decimal
    currency: str
    item_summary: str
    created_at: datetime


class ShipmentRead(DomainModel):
    shipment_id: str
    order_id: str
    carrier: str
    tracking_no: str
    status: str
    latest_location: str | None = None
    estimated_delivery_at: datetime | None = None
    events_json: list[dict[str, Any]] = Field(default_factory=list)
    updated_at: datetime


class TicketCreate(BaseModel):
    order_id: str
    issue_type: Literal["damaged", "return", "exchange", "other"]
    summary: str
    priority: Literal["low", "normal", "high"] = "normal"


class TicketRead(DomainModel):
    ticket_id: str
    order_id: str
    customer_id: str
    issue_type: str
    summary: str
    priority: str
    status: str
    created_at: datetime
    updated_at: datetime


class RefundRequestCreate(BaseModel):
    order_id: str
    amount: Decimal
    reason: str
    requires_approval: bool = False


class RefundRequestRead(DomainModel):
    refund_request_id: str
    order_id: str
    amount: Decimal
    reason: str
    status: str
    requires_approval: bool
    created_at: datetime
    updated_at: datetime


class PolicyArticleRead(DomainModel):
    article_id: str
    title: str
    category: str
    keywords: list[str] = Field(default_factory=list)
    content: str
    created_at: datetime


class AuditLogRead(DomainModel):
    id: int
    conversation_id: str | None = None
    event_type: str
    payload_json: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class OrderLookupInput(BaseModel):
    order_id: str


class PolicySearchInput(BaseModel):
    query: str


class TicketLookupInput(BaseModel):
    ticket_id: str
