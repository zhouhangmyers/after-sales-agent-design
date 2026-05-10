from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from agent_core.contracts.run_state import ActorContext
from app_api.deps import get_after_sales_agent_use_case, require_api_key
from app_api.schemas.actions import ActionRequest
from app_api.schemas.runs import RunResponse
from app_api.use_cases.after_sales_agent_use_case import AfterSalesAgentUseCase

router = APIRouter(prefix="/api/after-sales", tags=["after-sales-approvals"])


@router.post("/actions", response_model=RunResponse)
async def submit_action(
    payload: ActionRequest,
    agent_use_case: Annotated[
        AfterSalesAgentUseCase, Depends(get_after_sales_agent_use_case)
    ],
    _: None = Depends(require_api_key),
) -> RunResponse:
    try:
        result = await agent_use_case.act(
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
