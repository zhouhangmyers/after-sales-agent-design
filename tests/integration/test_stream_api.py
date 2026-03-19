from __future__ import annotations

import asyncio

from agent_runtime.models import ToolResult
from agent_service.schemas.chat import ChatResponse, TokenUsageSummary
from agent_service.services.stream_service import StreamService


async def _collect_events(stream_service: StreamService, response: ChatResponse) -> list[dict[str, str]]:
    events: list[dict[str, str]] = []
    async for event in stream_service.iter_post_response_events(response):
        events.append(event)
    return events


def test_stream_service_returns_sse_events(app) -> None:
    stream_service = StreamService(app.state.event_cache)
    response = ChatResponse(
        session_id="sess-stream",
        workflow_run_id="wf-stream",
        message_id="msg-1",
        assistant_message_id="msg-2",
        reply="我已经调用 `add` 完成处理，结果是 3。",
        tool_result=None,
        tool_results=[
            ToolResult(
                success=True,
                action="add",
                request_id="msg-1",
                result=3,
            )
        ],
        usage=TokenUsageSummary(prompt_tokens=11, completion_tokens=7, total_tokens=18),
    )

    events = asyncio.run(_collect_events(stream_service, response))

    assert '"type":"start"' in events[0]["data"]
    assert '"stream_mode":"post_response_sse"' in events[0]["data"]
    assert '"workflow_run_id":"wf-stream"' in events[0]["data"]
    assert '"type":"tool_result"' in events[1]["data"]
    assert '"result":3' in events[1]["data"]
    assert '"type":"message"' in events[2]["data"]
    assert '"type":"usage"' in events[3]["data"]
    assert '"total_tokens":18' in events[3]["data"]
    assert events[-1]["data"] == '{"type":"done"}'
