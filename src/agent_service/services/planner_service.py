from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from dataclasses import dataclass
from time import perf_counter, sleep
from typing import Any, TYPE_CHECKING

from agent_service.services.planners import (
    DeepSeekPlannerClient,
    DemoPlannerClient,
    PlannerCallTrace,
    PlannerDecision,
    PlannerModelClient,
    PlannerRequest,
    PromptRender,
    TokenUsage,
    ToolObservation,
    ToolSchema,
    dump_payload,
)

if TYPE_CHECKING:
    from agent_service.config import Settings


# 这个类专门用来保存一套 prompt 模板。
# 你可以把它理解成：
# “我规定好 prompt 长什么样，以后每次都按这个格式去拼内容”。
# frozen=True 表示这个模板对象创建好以后，不希望再被随手改掉。
@dataclass(frozen=True)
class PromptTemplate:
    # 模板名字。
    name: str
    # 模板版本。
    version: str
    # system prompt 内容。
    # 也就是最上面那段“你是谁，你该怎么做”的说明。
    system_instructions: str

    # render 的作用只有一个：
    # 把当前已知的信息，拼成一整段 prompt 文本，交给 planner 模型看。
    #
    # 这段 prompt 里会包含：
    # 1. 你是谁、要做什么（system_instructions）
    # 2. 现在有哪些工具能用（tool_schemas）
    # 3. 用户刚刚说了什么（user_message）
    # 4. 前面工具执行后发生了什么（observations）
    def render(
        self,
        # * 后面的参数必须写参数名传入。
        # 好处是调用时更清楚，不容易把顺序写错。
        *,
        # 当前这轮能用到的工具列表。
        tool_schemas: list[ToolSchema],
        # 用户原始消息。
        user_message: str,
        # 前面执行工具后留下来的结果列表。
        observations: list[ToolObservation],
    ) -> PromptRender:
        # 这个列表最后会变成：
        # [
        #   "- add: Add two numbers | args=a:integer, b:integer | required=a, b",
        #   "- divide: Divide two numbers | args=a:integer, b:integer | required=a, b",
        # ]
        tool_lines: list[str] = []

        # 现在开始，一个工具一个工具地整理。
        for tool in tool_schemas:
            # required 的意思是：
            # 这个工具有哪些参数“必须传”。
            # 例如 ["a", "b"] 就表示 a 和 b 都不能漏。
            required = tool.arguments_json_schema.get("required", [])

            # properties 的意思是：
            # 这个工具一共有哪几个参数，以及每个参数各自的类型。
            # 例如：
            # {
            #   "a": {"type": "integer"},
            #   "b": {"type": "integer"}
            # }
            properties = tool.arguments_json_schema.get("properties", {})

            # 下面这段是在把参数清单整理成一行更好读的文字。
            # 例如最后会变成：
            # "a:integer, b:integer"
            arg_parts: list[str] = []
            for arg_name in properties:
                arg_schema = properties.get(arg_name, {})
                arg_type = arg_schema.get("type", "any")
                arg_parts.append(f"{arg_name}:{arg_type}")
            arg_names = ", ".join(arg_parts)

            # 把必填参数名单变成字符串。
            # 如果 required = ["a", "b"]，这里就会变成 "a, b"。
            # 如果一个必填参数都没有，就写 "none"。
            if required:
                required_text = ", ".join(required)
            else:
                required_text = "none"

            # 把“这个工具的信息”拼成 prompt 里的一行介绍。
            # 例如：
            # - add: Add two numbers | args=a:integer, b:integer | required=a, b
            tool_line = (
                f"- {tool.name}: {tool.description} | args={arg_names or 'none'} | required={required_text}"
            )

            # 把这一行放进 tool_lines 列表里。
            # 后面会统一显示在 prompt 的 "Available tools:" 下面。
            tool_lines.append(tool_line)

        # 这个列表最后会变成：
        # [
        #   "1. tool=add success=True arguments={\"a\":1,\"b\":2} result=3 error=None",
        #   "2. tool=divide success=False arguments={\"a\":1,\"b\":0} result=null error='division by zero'",
        # ]
        observation_lines: list[str] = []

        # observations 里装的是“前面工具跑完之后的结果”。
        # 这里一条一条取出来，并顺手编号。
        # start=1 表示编号从 1 开始，不从 0 开始。
        for index, observation in enumerate(observations, start=1):
            # 这一行是在记录：
            # 第几条 observation、调用了哪个工具、成功没成功、传了什么参数、结果是什么。
            # !r 可以先简单理解成：
            # “把 error_message 按更适合调试的样子打印出来”。
            observation_line = (
                f"{index}. tool={observation.tool_name} success={observation.success} "
                f"arguments={dump_payload(observation.arguments)} result={dump_payload(observation.result)} "
                f"error={observation.error_message!r}"
            )
            observation_lines.append(observation_line)

        # 下面开始把前面准备好的内容，按顺序拼成最终 prompt。
        # 顺序是：
        # system 指令 -> 可用工具 -> 用户消息 -> 历史 observation -> 输出要求
        #
        # 这里用的是 "\n".join(...)：
        # 你可以把它理解成“拿换行符当胶水，把很多字符串粘成一整段文本”。
        #
        # 两个容易搞混的点：
        # 1. join 里面不一定必须是 [] 列表，只要里面是一串字符串就行；
        #    这里写成 []，只是因为这样最直观。
        # 2. 代码里的逗号只是用来分隔列表元素，不负责换行；
        #    真正让最终字符串换行的是前面的 "\n"。
        # 3. 列表里的 "" 是空字符串，被 "\n" 连起来以后，就会表现成一个空白行。
        content = "\n".join(
            [
                # 最上面先放 system 指令。
                self.system_instructions.strip(),
                # 空行只是为了排版更清楚。
                "",
                # 告诉模型：下面是工具列表。
                "Available tools:",
                # 如果当前有工具，就把所有工具说明放进去。
                # 如果一个工具都没有，就写 "- none"。
                *(tool_lines or ["- none"]),
                "",
                # 把用户原话放进去。
                f"User message: {user_message}",
                "",
                # 告诉模型：下面是历史 observation。
                "Observations:",
                # 如果有历史结果，就全部放进去；没有就写 "- none"。
                *(observation_lines or ["- none"]),
                "",
                # 最后再明确要求模型只能返回哪两种决策。
                "Return a structured planner decision with kind=respond or kind=tool_call.",
            ]
        )
        # 最后把结果包成 PromptRender 返回出去。
        # 你可以把它理解成：
        # “prompt 已经拼好了，现在拿着它去给 planner client 用。”
        return PromptRender(name=self.name, version=self.version, content=content)


class PromptTemplateRegistry:
    def __init__(self, templates: list[PromptTemplate] | None = None) -> None:
        template_list = templates or [
            PromptTemplate(
                name="tool-planner",
                version="v1",
                system_instructions=(
                    "You are a structured planning model. Decide the next step for the agent loop. "
                    "Either respond directly, or call exactly one tool with validated arguments."
                ),
            )
        ]
        self._templates = {(template.name, template.version): template for template in template_list}

    def get(self, *, name: str, version: str) -> PromptTemplate:
        template = self._templates.get((name, version))
        if template is None:
            raise KeyError(f"unknown prompt template: {name}@{version}")
        return template

    def render(
        self,
        *,
        name: str,
        version: str,
        tool_schemas: list[ToolSchema],
        user_message: str,
        observations: list[ToolObservation],
    ) -> PromptRender:
        template = self.get(name=name, version=version)
        return template.render(
            tool_schemas=tool_schemas,
            user_message=user_message,
            observations=observations,
        )


class PlannerService:
    def __init__(
        self,
        *,
        client: PlannerModelClient,
        prompt_name: str,
        prompt_version: str,
        prompt_registry: PromptTemplateRegistry | None = None,
        timeout_seconds: float = 5.0,
        max_retries: int = 1,
    ) -> None:
        self._client = client
        self._prompt_name = prompt_name
        self._prompt_version = prompt_version
        self._prompt_registry = prompt_registry or PromptTemplateRegistry()
        self._timeout_seconds = timeout_seconds
        self._max_retries = max_retries

    def plan(
        self,
        *,
        session_id: str,
        user_message: str,
        tool_schemas: list[ToolSchema],
        observations: list[ToolObservation],
    ) -> PlannerCallTrace:
        prompt = self._prompt_registry.render(
            name=self._prompt_name,
            version=self._prompt_version,
            tool_schemas=tool_schemas,
            user_message=user_message,
            observations=observations,
        )
        request = PlannerRequest(
            session_id=session_id,
            user_message=user_message,
            tool_schemas=tool_schemas,
            observations=observations,
            prompt=prompt,
        )
        request_payload = request.model_dump(mode="json")

        start = perf_counter()
        # 总尝试次数 = 第一次正常调用 1 次 + 最多重试次数。
        # 例如 max_retries = 1，那么 attempts = 2，表示总共最多试两次。
        attempts = self._max_retries + 1
        last_error: str | None = None
        # range(1, attempts + 1) 的意思是：
        # 从 1 开始编号，一直到 attempts 为止。
        # Python 的 range 结尾是不包含的，所以这里要写 attempts + 1。
        # 例如 attempts = 2，这里实际会循环 attempt = 1、2。
        for attempt in range(1, attempts + 1):
            try:
                # 真正去调用 planner client。
                # 右边这个函数会返回 3 个值：
                # 1. decision：planner 做出的结构化决策
                # 2. raw_response：planner 的原始响应内容
                # 3. usage：这次调用消耗的 token 信息
                # 左边这样写，表示把这 3 个返回值分别接到 3 个变量里。
                decision, raw_response, usage = self._run_with_timeout(self._client, request)
                return PlannerCallTrace(
                    provider=self._client.provider,
                    model=self._client.model,
                    prompt_name=prompt.name,
                    prompt_version=prompt.version,
                    request_payload=request_payload,
                    raw_response=raw_response,
                    decision=decision,
                    usage=usage,
                    latency_ms=(perf_counter() - start) * 1000,
                    attempts=attempt,
                    success=True,
                )
            except FutureTimeoutError:
                last_error = f"planner timed out after {self._timeout_seconds:.2f}s"
            except Exception as exc:
                # 这里捕获到的不是 Exception 这个类本身，
                # 而是这次真正抛出来的异常对象，并把它放进变量 exc。
                # 先尝试拿这个异常对象自带的文字说明，例如 "division by zero"。
                # 如果这个异常对象没有可读的文字说明，就退回用异常类名，
                # 例如 ValueError、TimeoutError，这样至少能知道报错类型。
                last_error = str(exc) or exc.__class__.__name__

            # 如果失败后异常已经被 except 接住，代码会继续往下走到这里。
            # 只有“后面还剩重试次数”时，才先暂停一小会儿，再进入下一轮重试。
            if attempt < attempts:
                # 等待时间会随着 attempt 稍微变长一点，但最多只等 0.1 秒。
                sleep(min(0.05 * attempt, 0.1))

        error_payload = {"error": last_error}
        return PlannerCallTrace(
            provider=self._client.provider,
            model=self._client.model,
            prompt_name=prompt.name,
            prompt_version=prompt.version,
            request_payload=request_payload,
            raw_response=error_payload,
            decision=None,
            usage=TokenUsage.from_texts(prompt.content, dump_payload(error_payload)),
            latency_ms=(perf_counter() - start) * 1000,
            attempts=attempts,
            success=False,
            error_message=last_error,
        )

    def _run_with_timeout(
        self,
        client: PlannerModelClient,
        request: PlannerRequest,
    ) -> tuple[PlannerDecision, dict[str, Any], TokenUsage]:
        # 如果 timeout_seconds <= 0，就表示这里不做超时控制，
        # 直接同步调用 client.plan(request)。
        if self._timeout_seconds <= 0:
            return client.plan(request)

        # 这里会开一个子线程，让子线程去执行 client.plan(request)。
        # 主线程则调用 future.result(timeout=...) 去等这个子线程的结果。
        #
        # 正常情况：
        # 如果子线程在 timeout_seconds 内返回了，主线程就拿到结果并直接返回。
        #
        # 超时情况：
        # 如果子线程在 timeout_seconds 内还没返回，
        # future.result(timeout=...) 会先抛出 TimeoutError，
        # 表示“主线程不再继续等这个结果了”。
        #
        # 但这里有个很关键的实现细节：
        # 这个超时并不会立刻杀掉子线程，子线程里的 client.plan(request) 可能还在继续跑。
        #
        # 而且这里用了 with ThreadPoolExecutor(...)：
        # 离开 with 时，线程池默认还会等线程收尾。
        # 所以这段代码的真实行为并不是“5 秒一到立刻开始下一轮重试”，
        # 而更像是“5 秒后判定这次等待超时，但函数真正返回可能还要再晚一点”。
        #
        # 也就是说：
        # 这里超时的是“等待结果”这件事，不是“立刻终止底层线程”这件事。
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(client.plan, request)
            return future.result(timeout=self._timeout_seconds)


def build_planner_service(settings: Settings) -> PlannerService:
    if settings.planner_provider == "demo":
        client: PlannerModelClient = DemoPlannerClient(model=settings.planner_model)
    elif settings.planner_provider == "deepseek":
        if not settings.deepseek_api_key:
            raise ValueError("DEEPSEEK_API_KEY is required when planner_provider=deepseek")
        client = DeepSeekPlannerClient(
            api_key=settings.deepseek_api_key,
            model=settings.planner_model,
        )
    else:
        raise ValueError(f"unsupported planner provider: {settings.planner_provider}")

    return PlannerService(
        client=client,
        prompt_name=settings.planner_prompt_name,
        prompt_version=settings.planner_prompt_version,
        timeout_seconds=settings.planner_timeout_seconds,
        max_retries=settings.planner_max_retries,
    )
