# A-01 Guard Runs Contract

## 目标

引用审计结论：

- `API contract for runs / actions / events` -> `A 保留自研`
- `真正该保留的` 包含 `run lifecycle` 与 `workflow definitions`

本任务只做契约守护，不改实现。

## 涉及文件/模块

- `tests/integration/test_runs_api.py`
- `tests/integration/test_stream_api.py`
- `tests/test_runs_failures.py`
- `tests/test_definitions.py`
- `src/agent_service/runs/schemas.py`
- `src/agent_service/api/routers/runs.py`
- `src/agent_service/api/routers/definitions.py`

## 具体执行步骤

1. 在独立 worktree 中创建 `guardian-agent-runs-contract` 分支，记录当前 `git status` 与目标测试列表。
2. 盘点 `/api/v2/definitions`、`/api/v2/runs`、`/api/v2/runs/{id}`、`/api/v2/runs/{id}/events`、`/api/v2/runs/{id}/events/stream`、`/api/v2/runs/{id}/actions` 的字段、状态码、事件名。
3. 在测试中把现有“只测能跑通”的断言补成“锁定字段与语义”的断言，尤其补 `waiting_action`、`last_error`、`next_after_seq`、SSE `event` 名称与 `data` payload 形状。
4. 只允许在 schema/route 上补注释或 example；如果需要改行为才能让测试通过，停止并申请审批。
5. 运行目标测试并输出 diff、失败/通过清单。

## 预期简化效果

- 不追求删代码。
- 把外部契约从“隐式靠人工记忆”简化为“显式靠 4 个测试文件守护”。
- 把后续 SSE、HITL、event bus 重构的回归验证，收敛成固定接口测试入口。

## 核心约束

- 禁止修改 response 字段名、字段类型、SSE 事件名。
- 禁止修改 `/runs` 与 `/definitions` 的业务语义。
