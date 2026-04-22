# CD-01 Remove DeepSeek Wrapper

## 目标

引用审计结论：

- `DeepSeekChatModel 这一层 provider wrapper` -> `C 可直接第三方替代`
- `没必要自己再包一层 provider adapter`

目标是在不改变 `build_llm_service` 外部行为的前提下，去掉 `llm/deepseek.py` 这层本地 wrapper。

## 涉及文件/模块

- `src/agent_service/llm/deepseek.py`
- `src/agent_service/llm/service.py`
- `tests/test_llm_service.py`

## 具体执行步骤

1. 在独立 worktree 中创建 `removal-agent-provider` 分支，记录当前 provider 构造路径：`Settings -> build_llm_service -> build_deepseek_chat_model -> ChatDeepSeek`。
2. 先补或调整测试，把期望锁定在“`build_llm_service` 正确构造 LangChain chat model”，而不是锁定本地 wrapper 的存在。
3. 将 `langchain_deepseek.ChatDeepSeek` 的构造收敛到 `build_llm_service` 或同级极薄 adapter，删除 `llm/deepseek.py`。
4. 清理导入、死代码和相关 monkeypatch 测试。
5. 运行 `tests/test_llm_service.py` 与相关 workflow 测试，输出 diff、删除行数、调用链变化。

## 预期简化效果

- 预计删除约 `20-40` 行冗余 wrapper 代码。
- provider 构造链从 `2` 个本地模块收敛到 `1` 个。
- 后续若更换 provider，不再维护一套自有 provider class 外壳。

## 核心约束

- 保持 `Settings -> LLMService` 的对外装配接口不变。
- 不改变 `LLMService` 产出的 `provider/model/trace` 语义。
