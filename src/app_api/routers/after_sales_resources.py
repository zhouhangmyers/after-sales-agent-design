from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from app_api.deps import get_after_sales_repository, require_api_key
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
from business_service.after_sales.infrastructure.persistence.sqlalchemy.repositories import (
    SqlAlchemyAfterSalesRepository,
)

router = APIRouter(prefix="/api/after-sales", tags=["after-sales-resources"])


@router.get("/orders/{order_id}", response_model=OrderRead)
def get_order(
    order_id: str,
    repository: SqlAlchemyAfterSalesRepository = Depends(get_after_sales_repository),
    _: None = Depends(require_api_key),
) -> OrderRead:
    order = repository.get_order(order_id)
    if order is None:
        raise HTTPException(status_code=404, detail=f"order not found: {order_id}")
    return order


@router.get("/orders/{order_id}/shipment", response_model=ShipmentRead)
def get_shipment(
    order_id: str,
    repository: SqlAlchemyAfterSalesRepository = Depends(get_after_sales_repository),
    _: None = Depends(require_api_key),
) -> ShipmentRead:
    shipment = repository.get_shipment(order_id)
    if shipment is None:
        raise HTTPException(status_code=404, detail=f"shipment not found for order: {order_id}")
    return shipment


@router.get("/customers/{customer_id}", response_model=CustomerRead)
def get_customer(
    customer_id: str,
    repository: SqlAlchemyAfterSalesRepository = Depends(get_after_sales_repository),
    _: None = Depends(require_api_key),
) -> CustomerRead:
    customer = repository.get_customer(customer_id)
    if customer is None:
        raise HTTPException(status_code=404, detail=f"customer not found: {customer_id}")
    return customer


@router.get("/policies/search", response_model=list[PolicyArticleRead])
def search_policies(
    q: str = Query(..., min_length=1),
    repository: SqlAlchemyAfterSalesRepository = Depends(get_after_sales_repository),
    _: None = Depends(require_api_key),
) -> list[PolicyArticleRead]:
    return repository.search_policies(q)


@router.post("/tickets", response_model=TicketRead)
def create_ticket(
    payload: TicketCreate,
    repository: SqlAlchemyAfterSalesRepository = Depends(get_after_sales_repository),
    _: None = Depends(require_api_key),
) -> TicketRead:
    try:
        ticket = repository.create_ticket(payload)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return ticket


@router.get("/tickets/{ticket_id}", response_model=TicketRead)
def get_ticket(
    ticket_id: str,
    repository: SqlAlchemyAfterSalesRepository = Depends(get_after_sales_repository),
    _: None = Depends(require_api_key),
) -> TicketRead:
    ticket = repository.get_ticket(ticket_id)
    if ticket is None:
        raise HTTPException(status_code=404, detail=f"ticket not found: {ticket_id}")
    return ticket


@router.post("/refund-requests", response_model=RefundRequestRead)
def create_refund_request(
    payload: RefundRequestCreate,
    repository: SqlAlchemyAfterSalesRepository = Depends(get_after_sales_repository),
    _: None = Depends(require_api_key),
) -> RefundRequestRead:
    try:
        refund = repository.create_refund_request(payload)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return refund


@router.get("/audit-logs", response_model=list[AuditLogRead])
def get_audit_logs(
    run_id: str = Query(..., min_length=1),
    repository: SqlAlchemyAfterSalesRepository = Depends(get_after_sales_repository),
    _: None = Depends(require_api_key),
) -> list[AuditLogRead]:
    return repository.list_audit_logs(run_id)
