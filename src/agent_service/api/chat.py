from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sse_starlette.sse import EventSourceResponse

from agent_service.api.deps import get_db_session, get_event_cache, get_runtime_service
from agent_service.schemas.chat import ChatRequest, ChatResponse
from agent_service.services.cache_service import EventCache
from agent_service.services.chat_service import ChatService
from agent_service.services.runtime_service import RuntimeService
from agent_service.services.stream_service import StreamService

# 创建一个聊天路由分组。
# 注意：tags=["chat"] 不是接口路径，而是文档分组标签。
# 真正的路径写在下面的 @router.post("/chat")、@router.get("/chat/stream") 里。
# 后面定义的 /chat 和 /chat/stream 都会挂在这个 router 下，
# 并且在 FastAPI 文档中归类到 chat 这一组。
router = APIRouter(tags=["chat"])


@router.post("/chat", response_model=ChatResponse)
def create_chat_response(
    # payload 是请求体，请求体结构必须符合 ChatRequest。
    # FastAPI 会自动把前端传来的 JSON 解析成 ChatRequest 对象。
    payload: ChatRequest,
    # db_session 不是前端传的，而是通过 Depends(get_db_session) 自动注入的。
    # 它表示当前这次请求可用的数据库操作会话。
    db_session: Session = Depends(get_db_session),
    # runtime_service 也是通过 Depends(...) 自动注入的应用级共享服务。
    # 它承接第一周 AgentRuntime 的能力，负责解析消息并执行工具。
    runtime_service: RuntimeService = Depends(get_runtime_service),
) -> ChatResponse:
    # 创建聊天业务服务，把数据库会话和 runtime 服务交给它。
    service = ChatService(db_session, runtime_service)
    # 真正的聊天处理逻辑不写在 API 层，而是交给 ChatService。
    # API 层只负责接请求、拿依赖、调服务、回结果。
    return service.handle_chat(payload)


@router.get("/chat/stream")
async def stream_chat_response(
    # 这里不是从 JSON 请求体里取值，而是从 URL 查询参数里取 session_id。
    # 因为当前这个 SSE 接口被设计成 GET + Query 参数的最小演示版本。
    # min_length=1 表示这个字符串至少要有 1 个字符，也就是不能为空字符串。
    session_id: str = Query(min_length=1),
    # message 同样来自 URL 查询参数，例如 ?message=add%20a=1%20b=2
    # min_length=1 同样表示 message 不能为空字符串。
    message: str = Query(min_length=1),
    # 为当前这次请求自动注入数据库 session。
    db_session: Session = Depends(get_db_session),
    # 自动注入 RuntimeService，用来解析消息并执行工具。
    runtime_service: RuntimeService = Depends(get_runtime_service),
    # 自动注入事件缓存对象，给 SSE 流式服务使用。
    event_cache: EventCache = Depends(get_event_cache),
) -> EventSourceResponse:
    # 先把查询参数手动组装成和普通聊天接口一致的 ChatRequest，
    # 这样后面的聊天业务逻辑可以复用同一套处理流程。
    payload = ChatRequest(session_id=session_id, message=message)
    # 先像普通聊天一样生成完整的聊天结果。
    # 当前 Week 2 的流式接口不是“边推理边输出”，而是“先得到完整结果，再拆成事件流”。
    response = ChatService(db_session, runtime_service).handle_chat(payload)
    # 创建流式服务，用它把 ChatResponse 拆成 start / message / tool_result / done 这些 SSE 事件。
    stream_service = StreamService(event_cache)
    # 返回 EventSourceResponse，告诉 FastAPI 这是一个 SSE 流式响应。
    # 客户端收到的不是一次性 JSON，而是一段一段推送出来的事件流。
    # 后面如果接入真实 LLM streaming，这层 EventSourceResponse 大概率还会保留，
    # 真正变化更大的会是括号里传入的事件流生成逻辑。
    return EventSourceResponse(stream_service.iter_events(response))
