# Refactoring Master Plan

本文件只覆盖第一、二阶段：

1. 依据 `audit-report.md` 完成 A/B/C/D 到当前代码的落点映射。
2. 生成可并行分发给子代理的原子任务计划。
3. 不执行任何业务代码重构；第三阶段需等待人工审核后再启动。

## 审计结论到代码落点

| 分类 | 审计结论 | 当前模块落点 | 说明 |
|---|---|---|---|
| `C/D` 可直接移除/替代 | `DeepSeekChatModel` provider wrapper、手写 SSE、过厚工具链 | `src/agent_service/llm/deepseek.py`、`src/agent_service/api/routers/runs.py` 的 `_format_sse_message/_sse_response`、`src/agent_service/agent/executor.py` + `src/agent_service/tool_registry.py` + `src/agent_service/agent/service.py` | 这些层不是战略高地；优先用 `langchain-deepseek`、`sse-starlette`，并压缩对象层级。 |
| `B` 保留但减薄 | HITL 胶水、LLM provider plumbing、event bus 抽象、startup handle 模式、FastAPI 边界包装 | `src/agent_service/agent/graph.py`、`src/agent_service/agent/nodes.py`、`src/agent_service/agent/service.py`、`src/agent_service/llm/service.py`、`src/agent_service/llm/bound_client.py`、`src/agent_service/runs/event_bus.py`、`src/agent_service/main.py`、`src/agent_service/api/deps.py`、`src/agent_service/api/auth.py`、`src/agent_service/api/middleware.py`、`src/agent_service/observability/context.py` | 这些边界可以保留，但只能收薄，不能继续长成自定义框架。 |
| `A` 必须保留并保护 | `run lifecycle`、`run_events + run_actions + projection`、`workflow definitions`、`tool policy / allowed_tools`、`process-level tool isolation` | `src/agent_service/runs/service.py`、`src/agent_service/runs/errors.py`、`src/agent_service/runs/schemas.py`、`src/agent_service/runs/stream.py`、`src/agent_service/db/models.py`、`src/agent_service/db/repos.py`、`src/agent_service/definitions.py`、`src/agent_service/tool_registry.py` 的治理语义、`src/agent_service/agent/tool_runtime.py` | 这些模块只允许做守护性工作；任何改变运行语义的修改都必须单独审批。 |

## 保护边界

- 不允许改 `runs/service.py` 的核心状态机、事件类型、投影规则、动作处理语义。
- 不允许改 `/api/v2/runs*` 与 `/api/v2/definitions` 的外部契约。
- `tool policy / allowed_tools` 的治理语义必须先由 guardian 任务锁定，再允许工具链减薄。
- `ProcessToolRuntime` 的超时终止、崩溃识别、结构化错误语义必须原样保留。
- 任何 touching `agent/graph.py`、`agent/nodes.py`、`agent/executor.py`、`runs/event_bus.py`、`main.py` 的行为改动，都必须以 guardian 测试先落地为前置条件。

## 执行顺序

1. 先执行 A 类 guardian 任务，锁定契约与不变量。
2. 再执行 `C/D` 任务，优先处理最干净的直接替代项。
3. 最后执行 `B` 任务，对保留边界做减薄。

## 子任务总览

| ID | 类别 | 计划文件 | 预定子代理角色 | 依赖 | 目标摘要 |
|---|---|---|---|---|---|
| `A-01` | A | `.codex/plans/refactor-a1-guard-runs-contract.md` | `guardian-agent-runs-contract` | 无 | 锁定 `/runs` 与 `/definitions` 对外 JSON/SSE 契约。 |
| `A-02` | A | `.codex/plans/refactor-a2-guard-projection-cas.md` | `guardian-agent-projection` | 无 | 锁定 `run_events/run_actions/projection/CAS` 不变量。 |
| `A-03` | A | `.codex/plans/refactor-a3-guard-tool-policy-isolation.md` | `guardian-agent-tooling` | 无 | 锁定 `allowed_tools`、审批策略、进程隔离语义。 |
| `CD-01` | C | `.codex/plans/refactor-cd1-remove-deepseek-wrapper.md` | `removal-agent-provider` | `A-01` | 去掉 `llm/deepseek.py` provider wrapper，直接用 `langchain-deepseek`。 |
| `CD-02` | D | `.codex/plans/refactor-cd2-adopt-sse-starlette.md` | `removal-agent-sse` | `A-01` | 用 `sse-starlette` 替代手写 SSE 协议格式化。 |
| `CD-03` | D | `.codex/plans/refactor-cd3-collapse-tool-executor-chain.md` | `removal-agent-toolchain` | `A-03` | 收缩 `ToolRegistry -> ScopedToolExecutor -> ToolExecutor` 链条，但不动治理语义。 |
| `B-01` | B | `.codex/plans/refactor-b1-thin-hitl-plumbing.md` | `thinning-agent-hitl` | `A-01`, `A-02`, `A-03` | 压薄 LangGraph interrupt/resume 周边胶水，不改 run 语义。 |
| `B-02` | B | `.codex/plans/refactor-b2-thin-llm-service-plumbing.md` | `thinning-agent-llm` | `A-01`, `A-03`, `CD-01` | 保留 prompt/decision/trace，收掉 provider plumbing。 |
| `B-03` | B | `.codex/plans/refactor-b3-thin-event-bus-bootstrap.md` | `thinning-agent-runtime` | `A-01`, `A-02` | 保留薄接口，减掉 `event bus` 与 `main.py` 中不必要的 handle/plumbing。 |
| `B-04` | B | `.codex/plans/refactor-b4-thin-fastapi-boundary.md` | `thinning-agent-boundary` | `A-01`, `B-03` | 把 `Depends/lifespan/request_id/auth` 收回 FastAPI 原生薄边界。 |

## 任务说明

- `api/routers/runs.py` 属于跨边界文件：SSE helper 属于 `D`，但 response schema 与事件名属于 `A`。
- `tool_registry.py` 属于跨边界文件：治理语义属于 `A`，对象链厚度属于 `D`。
- `agent/service.py` 属于跨边界文件：装配 plumbing 属于 `B`，但如果影响 `allowed_tools` 注入边界，则要退回审批。
- `runs/stream.py` 的流语义受 `A` 保护；`event bus` 的实现细节是 `B`，但不能改变 replay/live 顺序。
- `main.py`、`api/deps.py`、`api/auth.py`、`api/middleware.py`、`observability/context.py` 只允许向 FastAPI 原生边界收薄，不允许长成自定义容器或 DI 范式。

## 交付物

- 主计划文件：本文件。
- 子任务计划文件：`A-01` 到 `B-04` 共 10 个。
- 当前状态：计划已生成，等待人工审核；尚未启动第三阶段的并行重构。
