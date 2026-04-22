from __future__ import annotations

import logging

from fastapi import APIRouter, Request
from pydantic import BaseModel
from sqlalchemy import text

logger = logging.getLogger(__name__)

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    status: str
    # 各依赖项的独立状态，方便 Kubernetes liveness / readiness probe 区分原因。
    db: str


@router.get("/healthz", response_model=HealthResponse)
async def healthz(request: Request) -> HealthResponse:
    """健康检查端点。

    - status=ok：所有依赖健康，可接受流量（readiness）。
    - status=degraded：至少一个依赖异常，返回仍是 200 但包含具体状态，
      方便告警系统解析而不是只看 HTTP 状态码。
    """
    db_status = _check_db(request)
    overall = "ok" if db_status == "ok" else "degraded"
    return HealthResponse(status=overall, db=db_status)


def _check_db(request: Request) -> str:
    try:
        with request.app.state.db_manager.managed_session() as session:
            session.execute(text("SELECT 1"))
        return "ok"
    except Exception:
        logger.exception("health check: database unreachable")
        return "error"
