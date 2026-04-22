# B-03 Thin Event Bus And Bootstrap

## 目标

引用审计结论：

- `event bus 层` -> `B 保留但减薄`
- `handle 模式用得偏满` -> `B 保留但减薄`

目标是保留薄的 `publish/open_subscription/close` 接口，同时减掉 `main.py` 中不必要的 handle/plumbing。

## 涉及文件/模块

- `src/agent_service/runs/event_bus.py`
- `src/agent_service/main.py`
- `src/agent_service/runs/stream.py`
- `tests/integration/test_stream_api.py`
- `tests/test_stream_service.py`
- `tests/support.py`

## 具体执行步骤

1. 在独立 worktree 中创建 `thinning-agent-runtime` 分支，先读取 `A-01/A-02` 的流契约与 replay 约束。
2. 盘点 `RunEventBusHandle`、`LangGraphCheckpointerHandle`、`bootstrap_app_state()` 里的重复资源包装和关闭路径。
3. 只压薄装配层：能直接存 `bus` 或 `checkpointer` 的地方不再套 dataclass handle；保持 lifespan shutdown 语义不变。
4. 保持 `RunStreamService` 的 replay/live 顺序和终止条件不变；如需改订阅时机，停止并申请审批。
5. 运行 stream 相关测试并输出 diff、删除行数、资源关闭路径变化。

## 预期简化效果

- 预计删除约 `40-70` 行 handle/plumbing 代码。
- 资源关闭路径从“`app.state.handle.close()` 间接调用”收敛到“lifespan 直接关闭资源”。
- `event bus` 仍保留薄接口，但不再继续长成消息系统框架。

## 核心约束

- 不允许改变 `open_subscription(run_id, after_seq)` 语义。
- 不允许改变 `stream_existing_run()` 的 replay/live merge 与终态停流行为。
