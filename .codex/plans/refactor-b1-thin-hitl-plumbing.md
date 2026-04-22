# B-01 Thin HITL Plumbing

## 目标

引用审计结论：

- `approval / interrupt / resume 的大量自定义编排胶水` -> `B 保留但减薄`
- `图结构和业务节点可以保留；HITL 的底层机制不应继续自己包装得更厚`

目标是压薄 LangGraph `interrupt` / `Command(resume=...)` 周边 plumbing，不改变 run 状态机和事件语义。

## 涉及文件/模块

- `src/agent_service/agent/graph.py`
- `src/agent_service/agent/nodes.py`
- `src/agent_service/agent/service.py`
- `src/agent_service/agent/state.py`
- `tests/test_workflow.py`
- `tests/test_runs_failures.py`
- `tests/integration/test_runs_api.py`

## 具体执行步骤

1. 在独立 worktree 中创建 `thinning-agent-hitl` 分支，先读取 `A-01/A-02/A-03` 的守护测试和边界说明。
2. 盘点 `run/stream/resume/resume_stream` 中重复的 context 组装、resume 校验、错误包装路径。
3. 抽薄重复 plumbing，优先把公共组装逻辑收敛到更小的 helper；保留 `plan/approval/tool_execute/finalize` 的业务分流。
4. 如果发现需要改变 `waiting_action` 结构、事件名、状态值，立即停止并申请审批。
5. 运行 workflow/run 相关测试并输出 diff、删除行数、调用路径变化。

## 预期简化效果

- 预计删除约 `60-120` 行重复的 run/stream/resume plumbing。
- 保持 `interrupt` 与 `resume` 入口不变，把重复上下文装配从多处收敛到单处。
- 调用路径仍是 LangGraph 原生能力，但本地包装层更薄。

## 核心约束

- 不允许修改 `approval.requested`、`run.completed`、`run.failed` 的事件语义。
- 不允许修改 `waiting_action`、`status`、`current_node` 的外部含义。
