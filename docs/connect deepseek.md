# 接入真实 LLM —— 以 DeepSeek 为例

## 核心思路

框架用 `PlannerModelClient` Protocol 作为唯一插入口。
只要实现了这个 Protocol，任何模型都能被整套框架使用，上层代码完全不需要改动。

```python
class PlannerModelClient(Protocol):
    provider: str
    model: str
    def plan(self, request: PlannerRequest) -> tuple[PlannerDecision, dict[str, Any], TokenUsage]:
        ...
```

---

## 接入步骤

### 1. 选择调用方式

DeepSeek 提供 OpenAI 兼容 API，直接复用 `openai` 包，只需换 `base_url`：

```python
from openai import OpenAI

client = OpenAI(
    api_key="你的key",
    base_url="https://api.deepseek.com",
)
```

### 2. 构造 messages

框架的 `PromptRender` 已经把工具列表、用户消息、observations 全部渲染好了，
直接把渲染结果塞进 `user` 消息，`system` 消息只负责规定输出格式：

```python
messages = [
    {
        "role": "system",
        "content": "只输出 JSON，格式是 kind / response / tool_name / tool_arguments / rationale",
    },
    {
        "role": "user",
        "content": request.prompt.content,  # 直接复用已渲染的 prompt
    },
]
```

### 3. 处理 R1 的 `<think>` 推理块

R1（deepseek-reasoner）回复里会有推理过程，用正则剥掉，只留最终 JSON：

```python
import re

_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL)
content = _THINK_RE.sub("", raw_content).strip()
```

V3（deepseek-chat）没有 `<think>` 块，这段正则对它无害，直接跳过。

### 4. 解析 JSON → PlannerDecision

```python
data = json.loads(content)
return PlannerDecision(
    kind=data.get("kind"),
    response=data.get("response"),
    tool_name=data.get("tool_name"),
    tool_arguments=data.get("tool_arguments") or {},
    rationale=data.get("rationale", ""),
)
```

解析失败时降级返回 `kind=respond`，把原始内容透出来方便排查。

### 5. 接入配置和工厂函数

**config.py** — 加新字段：
```python
deepseek_api_key: str | None = None
# from_env 里加：
deepseek_api_key=os.getenv("DEEPSEEK_API_KEY"),
```

**planner_service.py** — `build_planner_service` 加分支：
```python
elif settings.planner_provider == "deepseek":
    if not settings.deepseek_api_key:
        raise ValueError("DEEPSEEK_API_KEY is required when planner_provider=deepseek")
    client = DeepSeekPlannerClient(
        api_key=settings.deepseek_api_key,
        model=settings.planner_model,
    )
```

**planners/__init__.py** — 导出新 class：
```python
from .deepseek_client import DeepSeekPlannerClient
```

---

## 启动配置（.env）

```env
PLANNER_PROVIDER=deepseek
PLANNER_MODEL=deepseek-chat        # 推荐 V3，速度快；R1 用 deepseek-reasoner
DEEPSEEK_API_KEY=你的key
PLANNER_TIMEOUT_SECONDS=15         # R1 推理慢，建议调大到 60
```

---

## 模型选择

| 模型 | 特点 | 适合场景 |
|------|------|----------|
| `deepseek-chat`（V3） | 速度快，首 token 延迟低 | 日常开发、调试、生产 |
| `deepseek-reasoner`（R1） | 推理能力强，但有 `<think>` 延迟 | 复杂规划、研究推理过程 |

---

## 改动范围

```
.env 改两行
  ↓
build_planner_service 走 elif deepseek 分支
  ↓
DeepSeekPlannerClient.plan() 被调用
  ↓
返回同样的 (PlannerDecision, raw_response, TokenUsage)
  ↓
PlannerService / Orchestrator 完全感知不到换了模型
```

上层的 orchestrator、chat_service、DB、stream **一行都不用动**，
这是 Protocol 抽象做得好的直接体现。

---

## 接入其他 LLM 的通用步骤

1. 在 `planners/` 下新建 `xxx_client.py`，实现 `plan()` 方法
2. `config.py` 加对应的 `api_key` 字段
3. `build_planner_service` 加 `elif` 分支
4. `planners/__init__.py` 导出新 class
5. `.env` 切换 `PLANNER_PROVIDER`
