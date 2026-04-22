# A-03 Guard Tool Policy And Isolation

## 目标

引用审计结论：

- `tool policy + allowed_tools + scoped executor` -> `A 保留自研`
- `process-level tool isolation` -> `A 保留自研`

本任务先锁定治理语义，再允许工具链减薄。

## 涉及文件/模块

- `tests/test_executor.py`
- `tests/test_workflow.py`
- `tests/test_definitions.py`
- `tests/sample_tools.py`
- `src/agent_service/tool_registry.py`
- `src/agent_service/agent/executor.py`
- `src/agent_service/agent/tool_runtime.py`
- `src/agent_service/definitions.py`

## 具体执行步骤

1. 在独立 worktree 中创建 `guardian-agent-tooling` 分支，记录 `allowed_tools`、`tool_policy_overrides`、unknown tool、timeout、worker crash 的现有语义。
2. 为 `allowed_tools` 白名单、审批策略覆盖、`may_require_actions`、拒绝未授权工具执行补齐测试。
3. 为 `ProcessToolRuntime` 的 timeout kill、worker crash、结构化错误码与“超时后无副作用”补齐测试。
4. 在必要位置补注释，明确“治理语义不可变”和“隔离能力不可变”。
5. 运行目标测试并输出 diff 与风险摘要。

## 预期简化效果

- 不追求删代码。
- 把“工具治理”和“工具执行实现”拆成明确可验证的两层边界。
- 为后续 `CD-03` 收缩对象链提供安全网，减少误伤 `A` 语义的概率。

## 核心约束

- 禁止改变 `allowed_tools`、`tool_policy_overrides`、`approval_required` 的业务含义。
- 禁止改变 timeout、crash、结构化错误码语义。
