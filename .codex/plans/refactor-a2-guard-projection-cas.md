# A-02 Guard Projection And CAS

## 目标

引用审计结论：

- `run lifecycle + run_events + run_actions + projection` -> `A 保留自研`
- `持久化与 projection 层` -> `这是最像战略高地的部分`

本任务只把投影与事件不变量锁成测试。

## 涉及文件/模块

- `tests/test_runs_failures.py`
- `tests/test_migrations.py`
- 新增或扩展 `tests/test_projection.py`（如需要）
- `src/agent_service/runs/service.py`
- `src/agent_service/db/models.py`
- `src/agent_service/db/repos.py`

## 具体执行步骤

1. 在独立 worktree 中创建 `guardian-agent-projection` 分支，记录当前 `run.started -> ... -> terminal` 事件路径与表结构。
2. 为以下不变量补测试：`run_events` 追加式语义、`run_actions` 输入动作语义、`runs` 仅保存当前投影、`last_projected_seq` 与 `projection_version` 的更新规则。
3. 为 `compare_and_swap_projection` 增加冲突/重试测试，锁定 CAS 语义而不是实现细节。
4. 为 `approval.requested`、`action.accepted`、`tool.completed`、`run.failed`、`run.completed` 对投影字段的影响补测试。
5. 只允许在受保护模块补注释；若发现实现与现有契约不一致，停止并申请审批。

## 预期简化效果

- 不追求删代码。
- 把跨 `runs/service.py`、`db/models.py`、`db/repos.py` 的隐式投影规则，简化为可回归的测试矩阵。
- 把后续行为验证从“人工 replay 事件流”简化为“固定 projection/CAS 守护套件”。

## 核心约束

- 禁止修改事件类型、表职责、`projection_version` 语义。
- 禁止改变 `status/current_node/waiting_action/output/last_error` 的投影结果。
