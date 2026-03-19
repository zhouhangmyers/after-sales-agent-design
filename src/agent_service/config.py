from __future__ import annotations

import os
from dataclasses import dataclass
from dotenv import load_dotenv

# 启动时先加载项目根目录下的 .env。
# 这样本地开发时写在 .env 里的配置，就会先进入环境变量，
# 后面的 os.getenv(...) 才能像读取系统环境变量一样把它们取出来。
load_dotenv()


def _read_bool(value: str | None, *, default: bool) -> bool:
    """把环境变量里的字符串转换成布尔值。"""

    # 环境变量本质上都是字符串。
    # 比如 AUTO_CREATE_SCHEMA=true，读出来实际是 "true"，
    # 所以这里需要手动把它转换成真正的 True / False。
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _read_int(value: str | None, *, default: int) -> int:
    """把环境变量里的字符串转换成整数。"""

    if value is None:
        return default
    return int(value.strip())


def _read_float(value: str | None, *, default: float) -> float:
    """把环境变量里的字符串转换成浮点数。"""

    if value is None:
        return default
    return float(value.strip())


@dataclass(slots=True, frozen=True)
class Settings:
    """应用启动时使用的统一配置对象。"""

    # 当前运行环境，通常用 dev / test / prod 这类值区分。
    app_env: str = "dev"
    # Web 服务监听的主机地址。
    app_host: str = "127.0.0.1"
    # Web 服务监听的端口号。
    app_port: int = 8000
    # 数据库连接串。当前默认是本地 SQLite，方便 Week 2 直接跑通。
    database_url: str = "sqlite+pysqlite:///./agent_platform.db"
    # Redis 连接串。留空时表示当前不接 Redis，系统会退回内存缓存。
    redis_url: str | None = None
    # 日志级别，后面接日志系统时会用到。
    log_level: str = "INFO"
    # 启动应用时是否自动建表。
    # 本地学习阶段设为 True 比较省事，生产环境通常更建议走 Alembic 迁移。
    auto_create_schema: bool = True
    # Week 3 默认用 demo planner，先把 agent loop 骨架跑通。
    planner_provider: str = "demo"
    # 记录当前规划器模型名；即便是 demo provider，也保留统一字段方便后续切真实模型。
    planner_model: str = "demo-structured-planner-v1"
    # Prompt 名称，用来区分不同规划模板。
    planner_prompt_name: str = "tool-planner"
    # Prompt 版本，用来记录一次决策使用的是哪一版模板。
    planner_prompt_version: str = "v1"
    # 一次 agent loop 最多规划多少步，避免死循环。
    agent_max_steps: int = 4
    # 单次模型调用最大等待时间，超过后按 timeout 处理。
    planner_timeout_seconds: float = 5.0
    # 规划失败后的最大重试次数。
    planner_max_retries: int = 1
    # DeepSeek API Key，切换到 deepseek provider 时必填。
    deepseek_api_key: str | None = None

    @classmethod
    def from_env(cls) -> Settings:
        """从环境变量构造一个 Settings 对象。"""

        # 这里统一从环境变量读取配置。
        # 如果某个变量没有设置，就回退到代码里给定的默认值。
        #
        # 典型流程是：
        # 1. load_dotenv() 先把 .env 里的内容加载进环境变量
        # 2. os.getenv(...) 再逐项读取
        # 3. 没读到的配置，使用这里写好的默认值
        return cls(
            # 运行环境，没有配置时默认为 dev。
            app_env=os.getenv("APP_ENV", "dev"),
            # 服务绑定地址，没有配置时默认为本机回环地址。
            app_host=os.getenv("APP_HOST", "127.0.0.1"),
            # 端口从环境变量读出来是字符串，所以这里需要转成 int。
            app_port=int(os.getenv("APP_PORT", "8000")),
            # 数据库 URL 默认指向项目根目录下的 SQLite 文件。
            database_url=os.getenv("DATABASE_URL", "sqlite+pysqlite:///./agent_platform.db"),
            # Redis URL 可以为空；为空时后续会走内存缓存实现。
            redis_url=os.getenv("REDIS_URL"),
            # 日志级别默认 INFO。
            log_level=os.getenv("LOG_LEVEL", "INFO"),
            # 布尔值不能直接靠字符串使用，所以这里通过 _read_bool 做一次转换。
            auto_create_schema=_read_bool(
                os.getenv("AUTO_CREATE_SCHEMA"),
                default=True,
            ),
            planner_provider=os.getenv("PLANNER_PROVIDER", "demo"),
            planner_model=os.getenv("PLANNER_MODEL", "demo-structured-planner-v1"),
            planner_prompt_name=os.getenv("PLANNER_PROMPT_NAME", "tool-planner"),
            planner_prompt_version=os.getenv("PLANNER_PROMPT_VERSION", "v1"),
            agent_max_steps=_read_int(os.getenv("AGENT_MAX_STEPS"), default=4),
            planner_timeout_seconds=_read_float(
                os.getenv("PLANNER_TIMEOUT_SECONDS"),
                default=5.0,
            ),
            planner_max_retries=_read_int(os.getenv("PLANNER_MAX_RETRIES"), default=1),
            deepseek_api_key=os.getenv("DEEPSEEK_API_KEY"),
        )
