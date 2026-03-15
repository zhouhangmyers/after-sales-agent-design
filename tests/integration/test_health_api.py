from __future__ import annotations

from agent_service.api.health import healthz


def test_health_endpoint_returns_ok() -> None:
    response = healthz()

    assert response.model_dump() == {"status": "ok"}
