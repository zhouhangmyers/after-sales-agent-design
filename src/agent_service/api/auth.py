from __future__ import annotations

import hmac

from fastapi import HTTPException, Request, Security
from fastapi.security import APIKeyHeader

# OpenAPI 文档里会展示 X-API-Key 这个 Header。
# auto_error=False：Header 缺失时不自动 401，让下面的函数决定策略。
_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


async def require_api_key(
    request: Request,
    api_key: str | None = Security(_api_key_header),
) -> None:
    """FastAPI 依赖：验证请求携带的 API Key。

    比较密钥时使用 `hmac.compare_digest` 做**常数时间比较**，
    而不是直接用 `!=`。Python 的字符串不等比较会按字节短路，
    攻击者可以通过观察响应时间差（微秒级）逐字节猜出密钥。
    `hmac.compare_digest` 无论密钥是否匹配都会扫完整段字节，
    是对时序攻击的标准防御方式。
    """
    configured_key = request.app.state.settings.api_key
    if configured_key is None:
        return
    provided = api_key or ""
    expected = configured_key.get_secret_value()
    if not hmac.compare_digest(provided, expected):
        raise HTTPException(status_code=401, detail="Invalid or missing API key")
