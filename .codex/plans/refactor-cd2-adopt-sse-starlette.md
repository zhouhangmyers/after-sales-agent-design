# CD-02 Adopt sse-starlette

## 目标

引用审计结论：

- `自己手写 SSE 格式化与推送细节` -> `D 设计冗余 / 没必要这样设计`
- 优先替代方案：`sse-starlette`

目标是在不改变 `/runs/stream` 与 `/runs/{id}/events/stream` 外部事件格式的前提下，用 `sse-starlette` 替换手写协议层。

## 涉及文件/模块

- `src/agent_service/api/routers/runs.py`
- `src/agent_service/runs/stream.py`
- `tests/integration/test_stream_api.py`
- 如有必要补充 `tests/integration/test_runs_api.py`

## 具体执行步骤

1. 在独立 worktree 中创建 `removal-agent-sse` 分支，先运行并记录现有 SSE 事件名、`data` payload、终止行为。
2. 先补合同测试，锁定 `event:` 名称、`data:` JSON 结构、`after_seq` replay 行为。
3. 用 `sse-starlette` 的 `EventSourceResponse` 替换 `_format_sse_message/_sse_stream/_sse_response`，只替换协议输出层。
4. 清理手写 helper 与无用导入，保持 `RunStreamService` 不变。
5. 运行流式集成测试并输出 diff、删除行数、协议兼容性结论。

## 预期简化效果

- 预计删除约 `25-45` 行手写 SSE 协议代码。
- 删除 `3` 个协议 helper，流式出口从“自拼字符串”收敛成“框架原生响应对象”。
- 调用链不变，但协议维护责任从本地代码移交给依赖库。

## 核心约束

- 不允许修改 SSE 事件名和 `data` 的 JSON 结构。
- 不允许改变 `after_seq` replay/live merge 语义。
