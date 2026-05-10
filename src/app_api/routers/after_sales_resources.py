from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from after_sales.application.services.after_sales_service import (
    AfterSalesService,
)
from after_sales.domain.entities import (
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
from app_api.deps import get_after_sales_service, require_api_key

router = APIRouter(prefix="/api/after-sales", tags=["after-sales-resources"])


@router.get("/orders/{order_id}", response_model=OrderRead)
async def get_order(
    order_id: str,
    service: AfterSalesService = Depends(get_after_sales_service),
    _: None = Depends(require_api_key),
) -> OrderRead:
    try:
        return await service.get_order_detail(order_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/orders/{order_id}/shipment", response_model=ShipmentRead)
async def get_shipment(
    order_id: str,
    service: AfterSalesService = Depends(get_after_sales_service),
    _: None = Depends(require_api_key),
) -> ShipmentRead:
    try:
        return await service.get_shipment_detail(order_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/customers/{customer_id}", response_model=CustomerRead)
async def get_customer(
    customer_id: str,
    service: AfterSalesService = Depends(get_after_sales_service),
    _: None = Depends(require_api_key),
) -> CustomerRead:
    try:
        return await service.get_customer_detail(customer_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/policies/search", response_model=list[PolicyArticleRead])
async def search_policies(
    q: str = Query(..., min_length=1),
    service: AfterSalesService = Depends(get_after_sales_service),
    _: None = Depends(require_api_key),
) -> list[PolicyArticleRead]:
    return await service.search_after_sales_policy(q)


@router.post("/tickets", response_model=TicketRead)
async def create_ticket(
    payload: TicketCreate,
    service: AfterSalesService = Depends(get_after_sales_service),
    _: None = Depends(require_api_key),
) -> TicketRead:
    try:
        ticket = await service.create_ticket(payload)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return ticket


@router.get("/tickets/{ticket_id}", response_model=TicketRead)
async def get_ticket(
    ticket_id: str,
    service: AfterSalesService = Depends(get_after_sales_service),
    _: None = Depends(require_api_key),
) -> TicketRead:
    try:
        return await service.get_ticket_detail(ticket_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/refund-requests", response_model=RefundRequestRead)
async def submit_refund_request(
    payload: RefundRequestCreate,
    service: AfterSalesService = Depends(get_after_sales_service),
    _: None = Depends(require_api_key),
) -> RefundRequestRead:
    try:
        refund = await service.submit_refund_request(payload)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return refund


@router.get("/audit-logs", response_model=list[AuditLogRead])
async def get_audit_logs(
    run_id: str = Query(..., min_length=1),
    service: AfterSalesService = Depends(get_after_sales_service),
    _: None = Depends(require_api_key),
) -> list[AuditLogRead]:
    return await service.list_audit_logs(run_id)
