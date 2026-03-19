from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class SessionRecord(Base):
    # 这张表存的是“一个会话本身”的顶层记录。
    # 你可以把它理解成一次聊天、一次任务对话、或一次 agent 交互的容器。
    # 后面的 messages / tool_calls / workflow_runs，都会围绕某个 session 展开。
    __tablename__ = "sessions"

    # 会话唯一 ID，例如 sess-001。
    # 它是主键，用来唯一标识一条会话记录。
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    # 会话标题，通常给前端列表或管理页面展示用。
    # 如果创建时没显式传入标题，就默认使用 "New Session"。
    title: Mapped[str] = mapped_column(String(255), default="New Session", nullable=False)
    # 会话状态，默认是 active。
    # 这个字段当前 Week 2 用得不深，但后面可以扩展成 archived / closed 等状态。
    status: Mapped[str] = mapped_column(String(32), default="active", nullable=False)
    # 记录这条会话是什么时候创建的。
    # server_default=func.now() 表示：如果插入数据时没有手动传值，
    # 就由数据库自动填入当前时间。
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    # 记录这条会话最近一次被更新的时间。
    # onupdate=func.now() 表示：当这条记录发生更新时，
    # 数据库会自动把 updated_at 刷新成当前时间。
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class MessageRecord(Base):
    # 这张表存的是“会话里的具体消息”。
    # 一条 session 可以有很多条 message，例如用户消息、助手回复消息。
    __tablename__ = "messages"

    # 消息唯一 ID，例如 msg-001。
    # 它是主键，用来唯一标识一条消息记录。
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    # session_id 是外键，指向 sessions 表里的 id。
    # 外键（ForeignKey）的意思是：这条数据必须关联到另一张表中已存在的一条记录。
    # 这里表示：一条 message 必须属于某个已存在的 session。
    # ondelete="CASCADE" 表示：如果上层 session 被删除，关联的消息也一起删除。
    session_id: Mapped[str] = mapped_column(
        ForeignKey("sessions.id", ondelete="CASCADE"),
        nullable=False,
    )
    # 消息角色，表示这条消息是谁发出的，例如 user / assistant。
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    # 消息正文内容。
    content: Mapped[str] = mapped_column(Text, nullable=False)
    # 消息状态，默认 completed。
    # 后面如果接流式输出、生成中状态等，也可以扩展成 streaming / failed 等值。
    status: Mapped[str] = mapped_column(String(32), default="completed", nullable=False)
    # 记录消息创建时间。
    # 如果插入时没有手动传值，就由数据库自动填入当前时间。
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )


class ToolCallRecord(Base):
    # 这张表存的是“一次工具调用”的执行记录。
    # 比如当前 Week 2 演示里的 add 工具，或者以后更真实的 slither / forge test / get_price 等工具，
    # 每执行一次，都可以在这里落一条结构化记录。
    __tablename__ = "tool_calls"

    # 工具调用唯一 ID。
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    # 这次工具调用属于哪个会话。
    # 如果对应的 session 被删除，这条工具调用记录也一起删除。
    session_id: Mapped[str] = mapped_column(
        ForeignKey("sessions.id", ondelete="CASCADE"),
        nullable=False,
    )
    # 这次工具调用是由哪条消息触发的。
    # 例如某条用户消息要求“执行 add 工具”，那这里就会关联到那条 message。
    # 如果对应的消息被删除，这条工具调用记录也一起删除。
    message_id: Mapped[str] = mapped_column(
        ForeignKey("messages.id", ondelete="CASCADE"),
        nullable=False,
    )
    # 工具名称，例如 add、slither、forge_test 等。
    tool_name: Mapped[str] = mapped_column(String(128), nullable=False)
    # 工具入参，当前以 JSON 字符串形式保存。
    # 这样可以把结构化参数完整落库，后面方便调试、审计和回放。
    arguments_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    # 工具执行结果，同样以 JSON 字符串形式保存。
    # 这样不只是给前端一段人话，而是把机器可读的结果也保留下来。
    result_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    # 这次工具调用是否成功。
    success: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # 工具调用耗时，单位毫秒。
    # 后面做性能分析、超时控制、可观测性时会很有用。
    latency_ms: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    # 记录这次工具调用是什么时候发生的。
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )


class LLMCallRecord(Base):
    # 这张表存的是“一次模型规划调用”的完整痕迹。
    # Week 3 起，agent loop 不再只是正则解析，而是先让规划器决定“回复”还是“调工具”，
    # 这张表就是用来记录每次规划调用的 prompt、structured output、token 使用和错误信息。
    __tablename__ = "llm_calls"

    # 模型调用记录唯一 ID。
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    # 这次模型调用属于哪条会话。
    session_id: Mapped[str] = mapped_column(
        ForeignKey("sessions.id", ondelete="CASCADE"),
        nullable=False,
    )
    # 这次模型调用是由哪条用户消息触发的。
    message_id: Mapped[str] = mapped_column(
        ForeignKey("messages.id", ondelete="CASCADE"),
        nullable=False,
    )
    # 对应哪一次 workflow run。
    workflow_run_id: Mapped[str] = mapped_column(
        ForeignKey("workflow_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    # 规划器提供方，例如 demo / openai / anthropic。
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    # 记录当前使用的模型名。
    model: Mapped[str] = mapped_column(String(128), nullable=False)
    # Prompt 名称与版本，方便后续比较不同模板表现。
    prompt_name: Mapped[str] = mapped_column(String(128), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(64), nullable=False)
    # 原始请求、原始响应，以及解析后的结构化输出都保留为 JSON 字符串。
    request_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    response_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    structured_output_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    # 记录 retry 后实际尝试了几次。
    attempts: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    # 记录本次调用的 token 使用。
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    # 调用耗时，单位毫秒。
    latency_ms: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    # 是否成功拿到可用的 structured output。
    success: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # 如果失败，这里记录统一的错误结构，仍然按 JSON 字符串存储。
    error_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )


class WorkflowRunRecord(Base):
    # 这张表存的是“一次工作流运行”的记录。
    # 当前 Week 2 还没有真正复杂的 workflow，但这张表已经先把位置预留出来了。
    # 后面如果接 LangGraph、审批流、多步骤任务、恢复执行等能力，这张表会很关键。
    __tablename__ = "workflow_runs"

    # 这次 workflow run 的唯一 ID。
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    # 这次工作流运行属于哪个会话。
    # 如果对应的 session 被删除，相关的 workflow run 记录也一起删除。
    session_id: Mapped[str] = mapped_column(
        ForeignKey("sessions.id", ondelete="CASCADE"),
        nullable=False,
    )
    # 工作流类型，例如 chat、audit、coding_agent、sql_agent 等。
    # 当前 Week 2 还比较简单，但这个字段是为后续不同类型 run 做区分的。
    run_type: Mapped[str] = mapped_column(String(64), nullable=False)
    # 当前这次运行的状态，默认是 running。
    # 后面可以扩展为 completed / failed / waiting_approval / cancelled 等状态。
    status: Mapped[str] = mapped_column(String(32), default="running", nullable=False)
    # 这次 workflow 的输入数据，当前以 JSON 字符串形式存储。
    # 这样后面可以回看“这次任务一开始收到了什么输入”。
    input_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    # 这次 workflow 的输出数据，同样以 JSON 字符串形式存储。
    # 这样后面可以追踪“这次任务最后产出了什么结果”。
    output_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    # 记录这次工作流运行是什么时候创建的。
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    # 记录这次工作流运行最近一次更新时间。
    # 如果状态、输出或其他字段被更新，这个时间也会自动刷新。
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class EvaluationRecord(Base):
    # 这张表存的是“评测记录”。
    # 它不是当前 Week 2 主流程里最核心的表，但它是为后面 Week 5 的 LLM Eval 体系预留的。
    # 以后可以用它记录某次 workflow run 在不同指标上的表现，比如成功率、准确率、耗时、人工评分等。
    __tablename__ = "evaluations"

    # 评测记录唯一 ID。
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    # 这条评测记录对应哪一次 workflow run。
    # 如果对应的 workflow run 被删除，相关评测记录也一起删除。
    workflow_run_id: Mapped[str] = mapped_column(
        ForeignKey("workflow_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    # 指标名称，例如 accuracy、latency、tool_success_rate、human_score 等。
    metric_name: Mapped[str] = mapped_column(String(128), nullable=False)
    # 指标值。
    # 这里允许为空，是因为有些评测可能只有定性备注，没有明确数值。
    metric_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    # 对这次评测结果的补充说明，例如失败原因、人工点评、场景备注等。
    note: Mapped[str] = mapped_column(Text, default="", nullable=False)
    # 记录这条评测记录是什么时候创建的。
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
