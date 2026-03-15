#!/usr/bin/env python3
from __future__ import annotations

import html
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DOCS_DIR = PROJECT_ROOT / "docs"
MARKDOWN_PATH = DOCS_DIR / "agent_service_architecture_tutorial.md"
HTML_PATH = DOCS_DIR / "agent_service_architecture_tutorial.html"
PDF_PATH = DOCS_DIR / "agent_service_architecture_tutorial.pdf"
REPORT_DATE = "2026-03-13"


def mermaid_for(name: str) -> str:
    diagrams = {
        "macro_layers": """flowchart TB
    C[外部客户端\\nBrowser / CLI / Test]
    APP[FastAPI App\\ncreate_app + app.state]
    API[API 层\\napi.chat / api.health / api.deps]
    SERVICE[服务编排层\\nChatService / StreamService]
    RUNTIME[运行时适配层\\nRuntimeService]
    CORE[执行内核\\nagent_runtime]
    REPO[持久化层\\nRepositories]
    DB[(SQLite / PostgreSQL)]
    CACHE[(Memory / Redis EventCache)]
    C --> APP --> API --> SERVICE
    SERVICE --> RUNTIME --> CORE
    SERVICE --> REPO --> DB
    SERVICE --> CACHE
""",
        "chat_chain": """flowchart TD
    A[1. POST /api/v1/chat] --> B[2. api.chat.create_chat_response]
    B --> C[3. Depends 注入\\ndb_session / runtime_service]
    C --> D[4. ChatService.handle_chat]
    D --> E[5. 创建 session / user message / workflow_run(running)]
    E --> F[6. RuntimeService.parse_message]
    F --> G[7. AgentRuntime.execute]
    G --> H[8. 可选写入 tool_calls]
    H --> I[9. 写入 assistant message\\nworkflow_run -> completed]
    I --> J[10. commit 并返回 ChatResponse]
""",
        "stream_chain": """flowchart TD
    A[1. GET /api/v1/chat/stream] --> B[2. Query 参数组装为 ChatRequest]
    B --> C[3. 复用 ChatService.handle_chat]
    C --> D[4. StreamService.iter_events]
    D --> E[5. 依次产出 start / message / tool_result / done]
    E --> F[6. EventCache.set_json(last_event)]
    F --> G[7. EventSourceResponse 输出 SSE]
""",
        "data_model": """erDiagram
    sessions ||--o{ messages : contains
    sessions ||--o{ tool_calls : owns
    sessions ||--o{ workflow_runs : owns
    messages ||--o{ tool_calls : triggers
    workflow_runs ||--o{ evaluations : is_measured_by
""",
    }
    return diagrams[name]


DIAGRAM_NAMES = ("macro_layers", "chat_chain", "stream_chain", "data_model")


def diagram_filename(name: str) -> str:
    return f"agent_service_diagram_{name}.svg"


def diagram_path(name: str) -> Path:
    return DOCS_DIR / diagram_filename(name)


BLOCKS: list[dict[str, Any]] = [
    {
        "type": "cover",
        "title": "agent_service 架构与分工关系教程",
        "subtitle": "从宏观分层、职责边界、请求关系链到数据关系图的一份本地源码导读",
        "meta": [
            "范围：src/agent_service 与其依赖的 src/agent_runtime",
            "产出：Markdown 教程 + PDF 图解版",
            f"生成日期：{REPORT_DATE}",
        ],
    },
    {"type": "page_break"},
    {"type": "heading", "level": 1, "text": "一、宏观定位"},
    {
        "type": "paragraph",
        "text": "agent_service 不是一个完整的 Agent 平台，而是建立在 agent_runtime 之上的服务外壳。它负责把 HTTP 请求、数据库事务、事件流、会话消息和工具执行结果组织成一个可运行、可持久化、可继续扩展的后端骨架。",
    },
    {
        "type": "paragraph",
        "text": "如果从大图看，它做的是“应用壳层”的工作：对上接 FastAPI 与客户端协议，对下接数据库、缓存和 Week 1 的执行内核；中间通过 ChatService 把一次聊天请求拼成一条完整的业务链路。",
    },
    {
        "type": "bullet_list",
        "items": [
            "最外层是应用装配：`main.py` 负责启动、配置、数据库、运行时、缓存和路由挂载。",
            "入口层是 API：`api/chat.py` 只处理 HTTP 形态、依赖注入和响应协议，不直接写业务细节。",
            "中心层是服务编排：`ChatService` 统一掌控事务边界、会话落库、工具调用记录和回复组装。",
            "执行适配层是 `RuntimeService`：把自然语言消息解析成结构化工具调用，再委托 `agent_runtime` 执行。",
            "底层是 repository + db models：把持久化细节从业务服务里抽离出来。",
            "旁路是 `StreamService` + `EventCache`：负责把已经得到的完整响应拆成 SSE 事件流。",
        ],
    },
    {"type": "diagram", "name": "macro_layers", "title": "宏观分层图"},
    {"type": "page_break"},
    {"type": "heading", "level": 1, "text": "二、模块分工与职责边界"},
    {
        "type": "bullet_list",
        "items": [
            "`config.py`：统一读取环境变量，把运行参数收敛成不可变 Settings 对象。",
            "`main.py`：应用启动装配点，创建 DatabaseManager、RuntimeService、EventCache，并把它们挂到 `app.state`。",
            "`api/deps.py`：把 `app.state` 中的共享对象转换成 FastAPI 可注入依赖；数据库 session 在这里按请求创建和释放。",
            "`api/chat.py`：两个接口入口。`POST /chat` 走普通 JSON 响应，`GET /chat/stream` 走 SSE 响应。",
            "`schemas/`：请求和响应的外部契约层，避免 API 直接暴露 ORM 或内部对象。",
            "`services/chat_service.py`：业务编排核心。它不是单纯调用 runtime，而是把会话、消息、workflow、tool_call 和事务提交串在一起。",
            "`services/runtime_service.py`：Week 2 的运行时适配器。当前用正则把消息解析成 `add` 或 `get_city` 两种演示工具调用。",
            "`services/stream_service.py`：把一个完整的 `ChatResponse` 切分成 `start / message / tool_result / done` 事件。",
            "`services/cache_service.py`：定义 EventCache 协议，并提供内存版和 Redis 版实现。",
            "`repositories/`：薄仓储层，每个类只处理一张表的最小读写动作，提交权保留给上层 service。",
            "`db/models.py`：定义 session、message、tool_call、workflow_run、evaluation 五张核心表。",
            "`src/agent_runtime/`：真正的工具注册、参数校验、middleware 链和统一错误结果都在这里完成。",
        ],
    },
    {
        "type": "paragraph",
        "text": "最关键的边界有两个。第一，API 层不拥有业务事务，事务在 ChatService 里统一提交或回滚；第二，ChatService 不关心工具执行细节，它只依赖 RuntimeService 返回一个结构稳定的 RuntimeExecution。",
    },
    {
        "type": "paragraph",
        "text": "因此，这个架构不是“路由直接调数据库”，也不是“runtime 直接落库”。它通过服务层把应用协议、执行内核与持久化隔开，方便后续把演示工具替换成更复杂的 agent workflow。",
    },
    {"type": "page_break"},
    {"type": "heading", "level": 1, "text": "三、`/chat` 主链路关系分析"},
    {
        "type": "paragraph",
        "text": "`POST /api/v1/chat` 是当前 agent_service 的主干链路。它体现了这套骨架最重要的设计取向：先持久化上下文，再调用 runtime，再把结果回写到数据库，最后统一提交事务并返回结构化响应。",
    },
    {
        "type": "numbered_list",
        "items": [
            "请求先进入 `api.chat.create_chat_response`，FastAPI 负责把 JSON 解析成 `ChatRequest`。",
            "`Depends(get_db_session)` 为这次请求创建一个数据库 session；`Depends(get_runtime_service)` 取出应用级 RuntimeService。",
            "API 层只实例化 `ChatService` 并调用 `handle_chat(...)`，不处理持久化顺序和回滚。",
            "ChatService 先确保 session 存在，再写入一条 user message，并创建状态为 `running` 的 workflow_run。",
            "随后它调用 `RuntimeService.execute_from_message(...)`。如果消息无法解析成工具请求，就返回 `None`；如果能解析，就交给 `agent_runtime` 执行。",
            "`agent_runtime` 负责工具查找、Pydantic 参数校验、handler 调用、中间件日志和统一错误封装。",
            "ChatService 根据 runtime 执行结果生成自然语言 reply；若存在工具执行，则额外写入 `tool_calls`。",
            "最后它写入 assistant message，把 workflow_run 状态更新为 `completed`，统一 `commit()`；中间任一异常都会触发 `rollback()`。",
        ],
    },
    {"type": "diagram", "name": "chat_chain", "title": "`/chat` 请求关系链"},
    {
        "type": "bullet_list",
        "items": [
            "这里的事务边界非常清晰：一次聊天请求对应一次数据库事务。",
            "当前版本通常一条 user message 最多触发一个工具调用，因为 `parse_message()` 只返回一个 ParsedToolRequest。",
            "reply 是给前端直接展示的人话，`tool_result` 是机器可读结构，两者并存。",
        ],
    },
    {"type": "page_break"},
    {"type": "heading", "level": 1, "text": "四、`/chat/stream` 支链路关系分析"},
    {
        "type": "paragraph",
        "text": "`GET /api/v1/chat/stream` 不是一条完全独立的业务链，而是在主链路之上增加了一个“输出协议转换层”。它先复用 ChatService 得到完整结果，再由 StreamService 把结果拆成 SSE 事件。",
    },
    {
        "type": "numbered_list",
        "items": [
            "入口仍在 `api/chat.py`，但参数来自 Query，而不是 JSON body。",
            "接口先把 `session_id` 和 `message` 重新装配成 `ChatRequest`，这样可以完整复用普通聊天逻辑。",
            "ChatService 返回完整 `ChatResponse` 后，`StreamService.iter_events(...)` 才开始把响应拆成事件。",
            "事件顺序固定为：`start` -> `message` -> `tool_result`（可选）-> `done`。",
            "每发一条事件，都会把最后一条事件写入 EventCache；底层既可以是内存，也可以是 Redis。",
            "因此，当前 Week 2 的 streaming 本质上是“后置拆包流”，还不是真正的 token-by-token 实时推理流。",
        ],
    },
    {"type": "diagram", "name": "stream_chain", "title": "`/chat/stream` 输出链"},
    {"type": "page_break"},
    {"type": "heading", "level": 1, "text": "五、数据关系与对象依赖关系"},
    {
        "type": "paragraph",
        "text": "数据库层面，`sessions` 是顶层容器；`messages`、`tool_calls`、`workflow_runs` 都围绕 session 展开。这个设计把“对话容器”和“本次执行痕迹”区分开了，因此后续做回放、审计、评测和多步 workflow 都有落点。",
    },
    {"type": "diagram", "name": "data_model", "title": "核心数据关系图"},
    {
        "type": "bullet_list",
        "items": [
            "`sessions -> messages`：一条会话包含多条用户/助手消息。",
            "`sessions -> tool_calls`：同一会话里可能发生多次工具调用。",
            "`messages -> tool_calls`：一条消息可以触发零次或多次工具调用；当前实现通常是 0 或 1。",
            "`sessions -> workflow_runs`：每次业务执行都会留下一个工作流运行记录。",
            "`workflow_runs -> evaluations`：评测表还未进入主链路，但位置已预留给后续 Eval 体系。",
        ],
    },
    {
        "type": "paragraph",
        "text": "代码依赖方向也很规整：API 依赖 schemas 与 services；services 依赖 repositories、schemas 和 runtime adapter；repositories 只依赖 db models；RuntimeService 再向下依赖 agent_runtime。换句话说，越往下的层越稳定，越往上的层越贴近外部协议。",
    },
    {"type": "page_break"},
    {"type": "heading", "level": 1, "text": "六、这套骨架的设计判断"},
    {
        "type": "bullet_list",
        "items": [
            "优点一：职责切分清楚。HTTP、事务编排、执行内核、持久化、事件流各有单独位置。",
            "优点二：扩展面明确。后续把正则解析替换成 LLM planner 时，只需要替换 RuntimeService，而不必重写 API 或 repository。",
            "优点三：可观测性已经预埋。workflow_runs、tool_calls、evaluation 表都在为未来的追踪与评测留钩子。",
            "优点四：SSE、Redis、PostgreSQL 都有适配位，说明作者在搭一个可生长的后端壳，不是一次性 demo。",
            "限制一：`parse_message()` 仍是规则式解析，离真正的 agent planning 很远。",
            "限制二：streaming 目前不是实时流，而是完整结果生成后的事件拆分。",
            "限制三：`build_event_cache()` 初始化 Redis 失败时会静默降级到内存缓存，可用性更高，但可观测性偏弱。",
            "限制四：仓储层非常薄，适合当前阶段；如果业务规则继续增长，后续可能需要 query service 或 domain service 进一步分拆。",
        ],
    },
    {"type": "heading", "level": 2, "text": "推荐阅读顺序"},
    {
        "type": "numbered_list",
        "items": [
            "`src/agent_service/main.py`：先看应用是如何被装配起来的。",
            "`src/agent_service/api/chat.py` 与 `api/deps.py`：理解入口层怎样拿到数据库和 runtime。",
            "`src/agent_service/services/chat_service.py`：这是最重要的编排核心。",
            "`src/agent_service/services/runtime_service.py`：看消息如何转成工具调用。",
            "`src/agent_runtime/runtime.py`、`registry.py`、`errors.py`：理解真正的执行内核。",
            "`src/agent_service/repositories/` + `db/models.py`：最后再看持久化和数据结构。",
        ],
    },
    {
        "type": "paragraph",
        "text": "一句话总结：agent_service 的价值，不在于它已经实现了多强的 agent，而在于它已经把“以后怎么长成真正的平台”这件事，用一套分层清楚、关系明确的骨架提前铺好了。",
    },
]


def build_markdown(blocks: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for block in blocks:
        kind = block["type"]
        if kind == "cover":
            parts.append(f"# {block['title']}")
            parts.append("")
            parts.append(block["subtitle"])
            parts.append("")
            for item in block["meta"]:
                parts.append(f"- {item}")
            parts.append("")
        elif kind == "page_break":
            continue
        elif kind == "heading":
            prefix = "#" * (block["level"] + 1)
            parts.append(f"{prefix} {block['text']}")
            parts.append("")
        elif kind == "paragraph":
            parts.append(block["text"])
            parts.append("")
        elif kind == "bullet_list":
            for item in block["items"]:
                parts.append(f"- {item}")
            parts.append("")
        elif kind == "numbered_list":
            for index, item in enumerate(block["items"], start=1):
                parts.append(f"{index}. {item}")
            parts.append("")
        elif kind == "diagram":
            parts.append(f"### {block['title']}")
            parts.append("")
            parts.append(f"![{block['title']}](./{diagram_filename(block['name'])})")
            parts.append("")
    return "\n".join(parts).strip() + "\n"


def split_pages(blocks: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    pages: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    for block in blocks:
        if block["type"] == "cover":
            if current:
                pages.append(current)
                current = []
            pages.append([block])
            continue
        if block["type"] == "page_break":
            if current:
                pages.append(current)
                current = []
            continue
        current.append(block)
    if current:
        pages.append(current)
    return pages


def esc(text: str) -> str:
    return html.escape(text, quote=True)


def svg_text(x: int, y: int, text: str, *, size: int = 16, fill: str = "#162033", weight: int = 500, anchor: str = "start") -> str:
    return (
        f'<text x="{x}" y="{y}" font-size="{size}" fill="{fill}" '
        f'font-weight="{weight}" text-anchor="{anchor}">{esc(text)}</text>'
    )


def svg_multiline(x: int, y: int, lines: list[str], *, size: int = 13, fill: str = "#162033", line_gap: int = 18) -> str:
    parts = []
    for index, line in enumerate(lines):
        parts.append(svg_text(x, y + index * line_gap, line, size=size, fill=fill, weight=400))
    return "".join(parts)


def svg_box(
    x: int,
    y: int,
    w: int,
    h: int,
    title: str,
    lines: list[str],
    *,
    stroke: str = "#2b5b90",
    fill: str = "#edf4ff",
    title_fill: str | None = None,
) -> str:
    body = [
        f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="18" ry="18" fill="{fill}" stroke="{stroke}" stroke-width="2"/>',
        svg_text(x + 16, y + 28, title, size=15, fill=title_fill or stroke, weight=700),
        svg_multiline(x + 16, y + 52, lines, size=12),
    ]
    return "".join(body)


def svg_arrow(x1: int, y1: int, x2: int, y2: int, *, stroke: str = "#2b5b90", dashed: bool = False) -> str:
    dash = ' stroke-dasharray="7 7"' if dashed else ""
    return (
        f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{stroke}" '
        f'stroke-width="2.4" marker-end="url(#arrow)"{dash}/>'
    )


def svg_root(width: int, height: int, body: str) -> str:
    return f"""
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" role="img" aria-label="architecture diagram">
  <defs>
    <marker id="arrow" markerWidth="12" markerHeight="12" refX="10" refY="6" orient="auto">
      <path d="M 0 0 L 12 6 L 0 12 z" fill="#5e6678"></path>
    </marker>
  </defs>
  {body}
</svg>
""".strip()


def diagram_svg(name: str) -> str:
    if name == "macro_layers":
        parts = [
            svg_box(315, 36, 330, 78, "外部客户端", ["Browser / CLI / tests"], stroke="#0d7d89", fill="#eefcfb", title_fill="#0d7d89"),
            svg_box(285, 160, 390, 88, "FastAPI App", ["create_app()", "app.state 挂载共享资源"], stroke="#214b80", fill="#eef4ff"),
            svg_arrow(480, 114, 480, 160),
            svg_box(42, 320, 220, 118, "API 层", ["api.chat", "api.deps", "api.health"], stroke="#214b80", fill="#f6f9ff"),
            svg_box(325, 320, 220, 118, "服务编排层", ["ChatService", "StreamService"], stroke="#0d7d89", fill="#effbf8", title_fill="#0d7d89"),
            svg_box(608, 320, 220, 118, "运行时适配层", ["RuntimeService", "parse -> execute"], stroke="#d46d2b", fill="#fff5eb", title_fill="#d46d2b"),
            svg_arrow(480, 248, 150, 320),
            svg_arrow(480, 248, 435, 320),
            svg_arrow(480, 248, 718, 320),
            svg_box(42, 510, 220, 118, "持久化层", ["repositories", "thin write/read wrappers"], stroke="#214b80", fill="#f6f9ff"),
            svg_box(325, 510, 220, 118, "事件缓存", ["InMemoryEventCache", "RedisEventCache"], stroke="#2a8a58", fill="#eefaf0", title_fill="#2a8a58"),
            svg_box(608, 510, 220, 118, "执行内核", ["AgentRuntime", "registry + validation"], stroke="#d46d2b", fill="#fff5eb", title_fill="#d46d2b"),
            svg_arrow(435, 438, 150, 510),
            svg_arrow(435, 438, 435, 510),
            svg_arrow(718, 438, 718, 510, stroke="#d46d2b"),
            svg_box(42, 682, 220, 102, "数据库", ["sessions / messages", "tool_calls / workflow_runs"], stroke="#214b80", fill="#f6f9ff"),
            svg_arrow(150, 628, 150, 682),
            svg_text(320, 688, "关系重点", size=20, fill="#0d7d89", weight=700),
            svg_multiline(
                320,
                722,
                [
                    "1. API 只做协议接入，不直接承载事务。",
                    "2. ChatService 是真正的业务编排中心。",
                    "3. RuntimeService 只负责把消息桥接到 agent_runtime。",
                    "4. repository 与 db model 负责稳定持久化边界。",
                ],
                size=13,
                line_gap=22,
            ),
        ]
        return svg_root(880, 820, "".join(parts))

    if name == "chat_chain":
        parts = [svg_text(32, 34, "POST /chat 主链路", size=22, fill="#214b80", weight=700)]
        steps = [
            ("1", "POST /api/v1/chat", "FastAPI 解析请求体为 ChatRequest"),
            ("2", "Depends 注入", "拿到 db_session 与 runtime_service"),
            ("3", "ChatService.handle_chat", "统一生成 id、掌控事务边界"),
            ("4", "repositories -> DB", "写 session / user message / workflow_run(running)"),
            ("5", "RuntimeService", "parse_message() 识别 add / get_city"),
            ("6", "AgentRuntime.execute", "查工具、参数校验、handler 执行、错误归一"),
            ("7", "ChatService", "生成 reply，并按需写入 tool_calls"),
            ("8", "repositories -> DB", "写 assistant message 与 workflow_run(completed)"),
            ("9", "commit + ChatResponse", "提交事务后返回 reply + tool_result"),
        ]
        y = 72
        for index, title, desc in steps:
            tone = "#d46d2b" if index in {"5", "6"} else "#214b80"
            fill = "#fff5eb" if index in {"5", "6"} else "#f6f9ff"
            parts.append(f'<circle cx="44" cy="{y + 46}" r="18" fill="{tone}"></circle>')
            parts.append(svg_text(44, y + 52, index, size=12, fill="#ffffff", weight=700, anchor="middle"))
            parts.append(svg_box(80, y, 760, 92, title, [desc], stroke=tone, fill=fill, title_fill=tone))
            if index != "9":
                parts.append(svg_arrow(44, y + 64, 44, y + 120, stroke="#5e6678"))
            y += 112
        parts.append(svg_box(80, y + 10, 760, 88, "链路结论", ["这条链路的核心不是路由，而是 ChatService 对“先记上下文，再执行，再回写结果”的统一编排。"], stroke="#0d7d89", fill="#eefcfb", title_fill="#0d7d89"))
        return svg_root(880, 1220, "".join(parts))

    if name == "stream_chain":
        parts = [svg_text(30, 36, "GET /chat/stream 输出链", size=22, fill="#0d7d89", weight=700)]
        labels = [
            ("GET /chat/stream", ["Query 参数入口"], "#214b80", "#f6f9ff"),
            ("ChatRequest", ["装配成统一请求对象"], "#214b80", "#f6f9ff"),
            ("ChatService", ["先得到完整 ChatResponse"], "#0d7d89", "#effbf8"),
            ("StreamService", ["拆成 start / message", "tool_result / done"], "#0d7d89", "#effbf8"),
            ("EventCache", ["记录 last_event"], "#2a8a58", "#eefaf0"),
            ("SSE", ["EventSourceResponse 输出"], "#d46d2b", "#fff5eb"),
        ]
        x = 24
        for idx, (title, lines, stroke, fill) in enumerate(labels):
            parts.append(svg_box(x, 86, 130, 112, title, lines, stroke=stroke, fill=fill, title_fill=stroke))
            if idx < len(labels) - 1:
                parts.append(svg_arrow(x + 130, 142, x + 154, 142))
            x += 154
        parts.append(svg_box(24, 266, 820, 160, "为什么当前流式只是“后置拆包流”", [
            "1. 业务结果先由 ChatService 一次性算完。",
            "2. StreamService 再把完整结果切成 start / message / tool_result / done。",
            "3. 所以它解决的是输出协议形态，不是推理过程本身的实时流式化。",
        ], stroke="#0d7d89", fill="#eefcfb", title_fill="#0d7d89"))
        return svg_root(880, 460, "".join(parts))

    if name == "data_model":
        parts = [
            svg_text(36, 40, "核心数据关系图", size=22, fill="#214b80", weight=700),
            svg_box(340, 74, 200, 110, "sessions", ["id", "title", "status", "created_at"], stroke="#214b80", fill="#f6f9ff"),
            svg_box(36, 286, 200, 126, "messages", ["id", "session_id", "role", "content", "status"], stroke="#214b80", fill="#f6f9ff"),
            svg_box(340, 286, 200, 126, "tool_calls", ["id", "session_id", "message_id", "tool_name", "result_json"], stroke="#d46d2b", fill="#fff5eb", title_fill="#d46d2b"),
            svg_box(644, 286, 200, 126, "workflow_runs", ["id", "session_id", "run_type", "status", "input/output"], stroke="#0d7d89", fill="#effbf8", title_fill="#0d7d89"),
            svg_box(644, 500, 200, 110, "evaluations", ["id", "workflow_run_id", "metric_name", "metric_value"], stroke="#2a8a58", fill="#eefaf0", title_fill="#2a8a58"),
            svg_arrow(440, 184, 136, 286),
            svg_arrow(440, 184, 440, 286, stroke="#d46d2b"),
            svg_arrow(440, 184, 744, 286, stroke="#0d7d89"),
            svg_arrow(744, 412, 744, 500, stroke="#2a8a58"),
            svg_arrow(236, 348, 340, 348, stroke="#5e6678", dashed=True),
            svg_text(174, 250, "1:N", size=16, fill="#214b80", weight=700),
            svg_text(452, 248, "1:N", size=16, fill="#d46d2b", weight=700),
            svg_text(764, 248, "1:N", size=16, fill="#0d7d89", weight=700),
            svg_text(768, 468, "1:N", size=16, fill="#2a8a58", weight=700),
            svg_text(244, 336, "message -> tool_calls", size=13, fill="#5e6678", weight=500),
        ]
        return svg_root(900, 650, "".join(parts))

    raise ValueError(f"unknown diagram: {name}")


def render_block_html(block: dict[str, Any]) -> str:
    kind = block["type"]
    if kind == "heading":
        tag = "h2" if block["level"] == 1 else "h3"
        return f"<{tag}>{esc(block['text'])}</{tag}>"
    if kind == "paragraph":
        return f"<p>{esc(block['text'])}</p>"
    if kind == "bullet_list":
        items = "".join(f"<li>{esc(item)}</li>" for item in block["items"])
        return f'<ul class="flat-list">{items}</ul>'
    if kind == "numbered_list":
        items = "".join(f"<li>{esc(item)}</li>" for item in block["items"])
        return f'<ol class="flat-list">{items}</ol>'
    if kind == "diagram":
        return (
            f'<figure class="diagram"><figcaption>{esc(block["title"])}</figcaption>'
            f'{diagram_svg(block["name"])}</figure>'
        )
    raise ValueError(f"unsupported block type: {kind}")


def render_cover_html(block: dict[str, Any]) -> str:
    meta = "".join(f'<div class="cover-meta-item">{esc(item)}</div>' for item in block["meta"])
    return f"""
<section class="page cover-page">
  <div class="cover-shell">
    <div class="cover-band"></div>
    <div class="cover-band accent"></div>
    <div class="cover-content">
      <div class="eyebrow">Architecture Tutorial</div>
      <h1>{esc(block["title"])}</h1>
      <p class="cover-subtitle">{esc(block["subtitle"])}</p>
      <div class="cover-meta">{meta}</div>
      <div class="cover-note">
        <div class="cover-note-title">这份教程会回答三个问题</div>
        <ul>
          <li>agent_service 在整个平台中属于哪一层。</li>
          <li>每个模块分别负责什么，边界在哪里。</li>
          <li>一次聊天请求怎样走到 runtime、数据库和 SSE。</li>
        </ul>
      </div>
    </div>
  </div>
</section>
""".strip()


def render_page_html(blocks: list[dict[str, Any]], page_no: int, total_pages: int) -> str:
    if len(blocks) == 1 and blocks[0]["type"] == "cover":
        return render_cover_html(blocks[0])
    content = "".join(render_block_html(block) for block in blocks)
    return f"""
<section class="page content-page">
  <div class="page-topline"></div>
  <div class="page-body">{content}</div>
  <div class="page-footer">agent_service Architecture Tutorial <span>{page_no} / {total_pages}</span></div>
</section>
""".strip()


def build_html(blocks: list[dict[str, Any]]) -> str:
    pages = split_pages(blocks)
    rendered_pages = [render_page_html(page, index, len(pages)) for index, page in enumerate(pages, start=1)]
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <title>agent_service 架构与分工关系教程</title>
  <style>
    @page {{
      size: A4;
      margin: 14mm;
    }}
    :root {{
      --ink: #162033;
      --muted: #5e6678;
      --brand: #214b80;
      --teal: #0d7d89;
      --orange: #d46d2b;
      --green: #2a8a58;
      --panel: #ffffff;
      --panel-soft: #f7f9fc;
      --border: #d9e1ee;
    }}
    * {{
      box-sizing: border-box;
      -webkit-print-color-adjust: exact;
      print-color-adjust: exact;
    }}
    html, body {{
      margin: 0;
      padding: 0;
      color: var(--ink);
      background: #eef2f7;
      font-family: "Microsoft YaHei", "Noto Sans SC", "PingFang SC", "Segoe UI", sans-serif;
      line-height: 1.65;
    }}
    body {{
      padding: 0;
    }}
    code {{
      font-family: "Cascadia Code", "Consolas", monospace;
      background: #f1f4f8;
      padding: 0.1rem 0.35rem;
      border-radius: 6px;
      font-size: 0.95em;
    }}
    .page {{
      background: var(--panel);
      page-break-after: always;
      break-after: page;
      position: relative;
      overflow: hidden;
    }}
    .content-page {{
      padding: 18px 20px 28px;
      border: 1px solid var(--border);
    }}
    .cover-page {{
      min-height: 1120px;
      padding: 0;
      border: none;
    }}
    .cover-shell {{
      min-height: 1120px;
      position: relative;
      background:
        radial-gradient(circle at top right, #c7ddff 0, #f4f8ff 32%, transparent 33%),
        linear-gradient(180deg, #ffffff 0%, #f7f9fc 100%);
      border: 1px solid var(--border);
      overflow: hidden;
    }}
    .cover-band {{
      position: absolute;
      inset: 0 0 auto 0;
      height: 220px;
      background: linear-gradient(135deg, #16365d 0%, #214b80 62%, #2f6cab 100%);
    }}
    .cover-band.accent {{
      top: 220px;
      height: 20px;
      background: linear-gradient(90deg, #d46d2b 0%, #ef9440 100%);
    }}
    .cover-content {{
      position: relative;
      padding: 92px 56px 56px;
    }}
    .eyebrow {{
      color: #d8e8ff;
      letter-spacing: 0.18em;
      text-transform: uppercase;
      font-size: 12px;
      margin-bottom: 18px;
    }}
    h1 {{
      margin: 0;
      color: #ffffff;
      font-size: 34px;
      line-height: 1.25;
    }}
    .cover-subtitle {{
      color: #edf4ff;
      font-size: 16px;
      max-width: 760px;
      margin: 22px 0 0;
    }}
    .cover-meta {{
      margin-top: 82px;
      display: grid;
      gap: 14px;
    }}
    .cover-meta-item {{
      background: rgba(255, 255, 255, 0.92);
      border: 1px solid #d9e1ee;
      border-radius: 18px;
      padding: 16px 20px;
      font-size: 15px;
    }}
    .cover-note {{
      margin-top: 34px;
      border: 1px solid #d6ecee;
      border-radius: 22px;
      background: linear-gradient(180deg, #f4fdfd 0%, #eef9f8 100%);
      padding: 22px 24px;
    }}
    .cover-note-title {{
      color: var(--teal);
      font-weight: 700;
      font-size: 18px;
      margin-bottom: 10px;
    }}
    .cover-note ul {{
      margin: 0;
      padding-left: 20px;
    }}
    .page-topline {{
      height: 10px;
      background: linear-gradient(90deg, #214b80 0%, #3b77b9 55%, #d46d2b 100%);
      border-radius: 999px;
      margin-bottom: 18px;
    }}
    .page-body h2 {{
      color: var(--brand);
      font-size: 28px;
      margin: 12px 0 16px;
      line-height: 1.3;
    }}
    .page-body h3 {{
      color: var(--teal);
      font-size: 20px;
      margin: 18px 0 10px;
      line-height: 1.35;
    }}
    .page-body p {{
      margin: 0 0 14px;
      font-size: 15px;
    }}
    .flat-list {{
      margin: 8px 0 16px 22px;
      padding: 0;
      font-size: 15px;
    }}
    .flat-list li {{
      margin: 0 0 8px;
    }}
    .diagram {{
      margin: 18px 0 22px;
      padding: 16px 16px 12px;
      border: 1px solid #d8e0ec;
      border-radius: 22px;
      background: linear-gradient(180deg, #fcfdff 0%, #f6f9fc 100%);
    }}
    .diagram figcaption {{
      margin-bottom: 12px;
      font-size: 16px;
      font-weight: 700;
      color: var(--teal);
    }}
    .diagram svg {{
      width: 100%;
      height: auto;
      display: block;
      font-family: "Microsoft YaHei", "Noto Sans SC", "Segoe UI", sans-serif;
    }}
    .page-footer {{
      margin-top: 24px;
      padding-top: 12px;
      border-top: 1px solid #d9e1ee;
      display: flex;
      justify-content: space-between;
      color: var(--muted);
      font-size: 12px;
    }}
  </style>
</head>
<body>
  {''.join(rendered_pages)}
</body>
</html>
"""


def decode_output(data: bytes) -> str:
    for encoding in ("utf-8", "utf-16le", "gbk", "cp936"):
        try:
            return data.decode(encoding).strip()
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace").strip()


def run_stdout(args: list[str]) -> str:
    completed = subprocess.run(args, check=True, capture_output=True)
    return decode_output(completed.stdout)


def windows_temp_dir() -> Path:
    raw = run_stdout(["cmd.exe", "/c", "echo", "%TEMP%"])
    if not raw:
        raise RuntimeError("Unable to resolve Windows TEMP directory.")
    return Path(run_stdout(["wslpath", "-u", raw]))


def windows_path(path: Path) -> str:
    return run_stdout(["wslpath", "-w", str(path)])


def find_browser() -> Path | None:
    env_browser = None
    if "BROWSER_PATH" in os.environ:
        env_browser = Path(os.environ["BROWSER_PATH"])
    candidates = [
        env_browser,
        Path("/mnt/c/Program Files/Google/Chrome/Application/chrome.exe"),
        Path("/mnt/c/Program Files (x86)/Microsoft/Edge/Application/msedge.exe"),
    ]
    for candidate in candidates:
        if candidate and candidate.exists():
            return candidate
    return None


def render_pdf_via_browser(html_path: Path, pdf_path: Path) -> None:
    browser = find_browser()
    if browser is None:
        raise RuntimeError(
            "No supported browser found. Set BROWSER_PATH or install Chrome/Edge under Windows."
        )

    stage_dir = windows_temp_dir() / "agent_service_architecture_export"
    stage_dir.mkdir(parents=True, exist_ok=True)
    stage_html = stage_dir / html_path.name
    stage_pdf = stage_dir / pdf_path.name
    shutil.copyfile(html_path, stage_html)

    command = [
        str(browser),
        "--headless=new",
        "--disable-gpu",
        "--no-first-run",
        "--no-default-browser-check",
        "--allow-file-access-from-files",
        "--no-pdf-header-footer",
        f"--print-to-pdf={windows_path(stage_pdf)}",
        windows_path(stage_html),
    ]
    completed = subprocess.run(command, capture_output=True, timeout=180)
    if completed.returncode != 0:
        raise RuntimeError(
            "Browser PDF rendering failed.\n"
            f"stdout:\n{decode_output(completed.stdout)}\n"
            f"stderr:\n{decode_output(completed.stderr)}"
        )
    if not stage_pdf.exists():
        raise RuntimeError("Browser finished without producing the PDF file.")
    shutil.copyfile(stage_pdf, pdf_path)


def main() -> None:
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    for name in DIAGRAM_NAMES:
        diagram_path(name).write_text(diagram_svg(name), encoding="utf-8")
    MARKDOWN_PATH.write_text(build_markdown(BLOCKS), encoding="utf-8")
    HTML_PATH.write_text(build_html(BLOCKS), encoding="utf-8")
    render_pdf_via_browser(HTML_PATH, PDF_PATH)
    print(MARKDOWN_PATH)
    print(HTML_PATH)
    print(PDF_PATH)


if __name__ == "__main__":
    main()
