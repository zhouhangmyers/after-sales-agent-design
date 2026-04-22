# B-02 Thin LLMService Plumbing

## 目标

引用审计结论：

- `LLMService` -> `B 保留但减薄`
- `保留领域语义输出；不要继续加厚成自有 LLM 适配框架`

目标是保留 `prompt / decision / trace`，把 provider plumbing 从 `LLMService` 里继续收边。

## 涉及文件/模块

- `src/agent_service/llm/service.py`
- `src/agent_service/llm/bound_client.py`
- `src/agent_service/domain/llm.py`
- `tests/test_llm_service.py`
- `tests/test_workflow.py`

## 具体执行步骤

1. 在独立 worktree 中创建 `thinning-agent-llm` 分支，先读取 `CD-01` 结果或基于其分支继续工作。
2. 拆分 `LLMService` 里的 provider plumbing、retry 分类、request assembly、trace assembly，保留一个明确的领域主入口。
3. 将 provider-specific 绑定逻辑继续压到 `ToolBindingChatModelClient` 或更薄的 helper，避免 `LLMService` 同时承担 provider factory 与 domain orchestration。
4. 保持 `generate_turn()` 的返回结构、`trace` 字段、fallback 行为不变。
5. 运行 llm/workflow 测试并输出 diff、删除行数、职责收缩情况。

## 预期简化效果

- 预计删除或搬移约 `40-80` 行 provider plumbing。
- `LLMService` 的职责从“prompt + provider plumbing + retry + trace”收敛到“prompt + domain turn + trace”。
- 后续接更多 provider 时，不再继续把 `LLMService` 扩成 model gateway。

## 核心约束

- 不允许改变 `LLMCallTrace`、`AssistantDecision`、fallback `AIMessage` 的语义。
- 不允许修改 `tool` 绑定结果对模型可见能力面的含义。
