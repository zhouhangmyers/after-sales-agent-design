from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from agent_service.contracts.models import ActorContext
from app_api.deps import get_after_sales_assistant_service, require_api_key
from app_api.schemas.actions import ActionRequest
from app_api.schemas.runs import RunResponse
from app_api.services.after_sales_assistant import AfterSalesAssistantService

router = APIRouter(prefix="/api/after-sales", tags=["after-sales-approvals"])


@router.post("/actions", response_model=RunResponse)
async def submit_action(
    payload: ActionRequest,
    assistant_service: Annotated[
        AfterSalesAssistantService, Depends(get_after_sales_assistant_service)
    ],
    _: None = Depends(require_api_key),
) -> RunResponse:
    try:
        result = await assistant_service.act(
            run_id=payload.run_id,
            action_id=payload.action_id,
            decision=payload.decision,
            actor=ActorContext(actor_id=payload.actor_id, metadata=payload.actor_metadata),
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return RunResponse.model_validate(result.model_dump(mode="json"))
