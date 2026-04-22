# CD-03 Collapse Tool Executor Chain

## 目标

引用审计结论：

- `ToolRegistry -> ToolExecutor -> ScopedToolExecutor -> ToolRuntime 这条链偏厚`
- `ToolExecutor / ScopedToolExecutor` -> `D 设计冗余 / 没必要这样设计`

目标是只压缩对象层级，不改变 `tool policy / allowed_tools` 与 `ProcessToolRuntime` 语义。

## 涉及文件/模块

- `src/agent_service/agent/executor.py`
- `src/agent_service/tool_registry.py`
- `src/agent_service/agent/service.py`
- `src/agent_service/domain/tool.py`
- `tests/test_executor.py`
- `tests/test_workflow.py`
- `tests/support.py`

## 具体执行步骤

1. 在独立 worktree 中创建 `removal-agent-toolchain` 分支，先读取 `A-03` 的治理与隔离守护约束。
2. 识别哪一层只是“透传 allowed_tools 与 policy”的包装，计划将其收敛为一个更薄的 execution view 或直接内联到 `ToolRegistry`。
3. 先保留 `ToolExecutor.execute()/to_tool_message()` 与 `ProcessToolRuntime`，只压缩 `ScopedToolExecutor` 和 `ToolRegistry.build_executor` 周边的重复包装。
4. 更新 `WorkflowService`、测试辅助代码与单元测试，确保 unknown tool、审批策略、artifact 语义不变。
5. 运行 executor/workflow 测试并输出 diff、删除行数、对象数缩减情况。

## 预期简化效果

- 预计删除约 `80-140` 行对象包装与透传代码。
- 调用链从 `ToolRegistry -> ScopedToolExecutor -> ToolExecutor -> ToolRuntime` 收敛到 `ToolRegistry(or thin view) -> ToolExecutor -> ToolRuntime`。
- 保留治理语义，减少一个中间对象层。

## 核心约束

- 不允许改变 `allowed_tools` 白名单、`tool_policy_overrides` 合并、`unknown_tool`/`tool_timeout`/`tool_execution_failed` 错误语义。
- 不允许修改 `ProcessToolRuntime`。
