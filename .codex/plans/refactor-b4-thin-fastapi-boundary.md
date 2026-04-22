# B-04 Thin FastAPI Boundary

## 目标

引用审计结论：

- `启动与配置层` -> `B`
- `API auth / deps` -> `B`
- `Web / DI / lifecycle 的基础设施层` 应让社区接手

目标是把入口层收回 `FastAPI lifespan + Depends + middleware + contextvars` 的最小必要边界，不再像轻量容器。

## 涉及文件/模块

- `src/agent_service/main.py`
- `src/agent_service/api/deps.py`
- `src/agent_service/api/auth.py`
- `src/agent_service/api/middleware.py`
- `src/agent_service/observability/context.py`
- `tests/conftest.py`
- `tests/support.py`
- `tests/integration/test_health_api.py`
- `tests/integration/test_runs_api.py`

## 具体执行步骤

1. 在独立 worktree 中创建 `thinning-agent-boundary` 分支，先读取 `A-01` 契约守护与 `B-03` 资源关闭边界。
2. 固定 `lifespan`、request-scoped session、API key、`request_id` 日志上下文的现有行为与测试入口。
3. 去掉不必要的“轻容器式”包装，把依赖注入压回 `Depends + app.state` 的最小形式；只保留确实有必要的 startup/shutdown 收口。
4. 如果需要改变 `create_app()` 的测试替换点，先更新测试夹具，再检查所有集成测试是否仍可复用。
5. 运行入口与集成测试并输出 diff、删除行数、装配链变化。

## 预期简化效果

- 预计删除约 `20-50` 行入口层包装与重复注释。
- 入口装配链从“自定义 handle/工厂组合”进一步收敛到“FastAPI 原生生命周期 + app.state”。
- 降低后续维护 `create_app()`、测试夹具和 request context 的认知成本。

## 核心约束

- 不允许改变 `lifespan` 顺序、request-scoped session、API key 校验与 `request_id` 注入语义。
- 不允许修改 `/runs`、`/definitions` 对外行为。
