from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any

from agent_service.schemas.chat import ChatResponse
from agent_service.services.cache_service import EventCache


def _encode(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


class StreamService:
    def __init__(self, event_cache: EventCache) -> None:
        self._event_cache = event_cache

    async def iter_events(self, response: ChatResponse) -> AsyncIterator[dict[str, str]]:
        events: list[dict[str, Any]] = [
            {
                "type": "start",
                "session_id": response.session_id,
                "message_id": response.message_id,
            },
            {
                "type": "message",
                "assistant_message_id": response.assistant_message_id,
                "content": response.reply,
            },
        ]
        if response.tool_result is not None:
            events.append(
                {
                    "type": "tool_result",
                    **response.tool_result.model_dump(),
                }
            )
        events.append({"type": "done"})

        for event in events:
            self._event_cache.set_json(f"stream:{response.session_id}:last_event", event)
            yield {"event": "message", "data": _encode(event)}
            await asyncio.sleep(0)
