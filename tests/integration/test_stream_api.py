from __future__ import annotations

import asyncio

from agent_service.schemas.chat import ChatResponse
from agent_service.services.stream_service import StreamService


async def _collect_events(stream_service: StreamService, response: ChatResponse) -> list[dict[str, str]]:
    events: list[dict[str, str]] = []
    async for event in stream_service.iter_events(response):
        events.append(event)
    return events


def test_stream_service_returns_sse_events(app) -> None:
    stream_service = StreamService(app.state.event_cache)
    response = ChatResponse(
        session_id="sess-stream",
        message_id="msg-1",
        assistant_message_id="msg-2",
        reply="工具 `add` 执行成功，结果是 3。",
        tool_result=app.state.runtime_service.execute_from_message(
            "add a=1 b=2",
            request_id="msg-1",
        ).result,
    )

    events = asyncio.run(_collect_events(stream_service, response))

    assert events[0]["data"] == '{"type":"start","session_id":"sess-stream","message_id":"msg-1"}'
    assert '"type":"message"' in events[1]["data"]
    assert '"type":"tool_result"' in events[2]["data"]
    assert '"result":3' in events[2]["data"]
    assert events[-1]["data"] == '{"type":"done"}'
