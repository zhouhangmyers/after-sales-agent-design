from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from tests.helpers import build_test_app


@pytest.mark.asyncio
async def test_health_endpoint_returns_ok(tmp_path: Path) -> None:
    app = build_test_app(f"sqlite+pysqlite:///{tmp_path / 'health.db'}")
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            response = await client.get("/healthz")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["db"] == "ok"
