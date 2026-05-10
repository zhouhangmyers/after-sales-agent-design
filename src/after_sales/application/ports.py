from __future__ import annotations

from decimal import Decimal
from typing import Protocol

from after_sales.domain.entities import (
    AuditLogRead,
    CustomerRead,
    OrderRead,
    PolicyArticleRead,
    RefundRequestCreate,
    RefundRequestRead,
    ShipmentRead,
    TicketCreate,
    TicketRead,
)


class AfterSalesRepository(Protocol):
    # ============================================================
    # 售后业务数据端口：查询类
    # ============================================================

    # 对齐业务方法：AfterSalesService.get_customer_detail。
    async def get_customer_detail(self, customer_id: str) -> CustomerRead | None: ...

    # 对齐业务方法：AfterSalesService.get_order_detail。
    async def get_order_detail(self, order_id: str) -> OrderRead | None: ...

    # 对齐业务方法：AfterSalesService.get_shipment_detail。
    async def get_shipment_detail(self, order_id: str) -> ShipmentRead | None: ...

    # 对齐业务方法：AfterSalesService.get_ticket_detail。
    async def get_ticket_detail(self, ticket_id: str) -> TicketRead | None: ...

    # 对齐业务方法：AfterSalesService.search_after_sales_policy。
    async def search_after_sales_policy(self, query: str) -> list[PolicyArticleRead]: ...

    # 对齐业务方法：AfterSalesService.list_audit_logs；读取 Agent 写入的审计日志。
    async def list_audit_logs(self, run_id: str) -> list[AuditLogRead]: ...

    # ============================================================
    # 售后业务数据端口：工单类
    # ============================================================

    # 对齐业务方法：AfterSalesService.create_ticket。
    async def create_ticket(self, payload: TicketCreate) -> TicketRead: ...

    # ============================================================
    # 售后业务数据端口：退款类
    # ============================================================

    # 对齐业务方法：AfterSalesService.submit_refund_request。
    # repository 只负责按 application service 计算出的状态落库。
    async def submit_refund_request(
        self,
        payload: RefundRequestCreate,
        *,
        status: str = "submitted",
    ) -> RefundRequestRead: ...

    # ============================================================
    # Agent 运行态端口：工具调用日志
    # ============================================================

    # 记录 Agent 工具调用开始，用于运行态观测和排障。
    # 调用方：AfterSalesRunProjector.record_event(ActionStartedEvent)。
    async def start_tool_call(
        self,
        *,
        conversation_id: str | None,  # Agent 本次运行或会话 ID；没有上下文时为空。
        tool_call_id: str | None,  # Agent 单次工具调用 ID；无法取得时为空。
        tool_name: str,  # 被 Agent 调用的工具名称。
        tool_arguments: dict[str, object],  # Agent 调用工具时传入的原始参数。
    ) -> int: ...

    # 记录 Agent 工具调用完成、结果、耗时或错误。
    # 调用方：AfterSalesRunProjector.record_event(ActionCompletedEvent)。
    async def finish_tool_call(
        self,
        *,
        log_id: int,  # start_tool_call 返回的工具调用日志 ID。
        success: bool,  # 工具调用是否成功。
        latency_ms: float,  # 工具调用耗时，单位毫秒。
        result: dict[str, object] | None,  # 工具调用成功时的结构化结果；没有结果时为空。
        error_message: str | None,  # 工具调用失败时的错误信息；成功时为空。
    ) -> None: ...

    # ============================================================
    # Agent 运行态端口：人工审批记录
    # ============================================================

    # 持久化 Agent 工具调用触发的待人工审批请求。
    # 调用方：AfterSalesRunProjector._request_approval。
    async def request_approval(
        self,
        *,
        conversation_id: str,  # 触发审批的 Agent 运行或会话 ID。
        tool_call_id: str | None,  # 触发审批的工具调用 ID；无法取得时为空。
        tool_name: str,  # 触发审批的工具名称。
        order_id: str | None,  # 审批关联的订单 ID；无法关联订单时为空。
        amount: Decimal | None,  # 审批关联的金额；没有金额时为空。
        reason: str | None,  # 展示给审批人的申请原因；没有原因时为空。
        risk_level: str,  # 审批风险等级。
        display_payload: dict[str, object],  # 审批界面展示用的结构化摘要。
    ) -> None: ...

    # 记录人工审批动作的最终处理结果。
    # 调用方：AfterSalesRunProjector.resolve_approval。
    async def resolve_approval(
        self,
        *,
        conversation_id: str,  # 待处理审批所属的 Agent 运行或会话 ID。
        tool_call_id: str | None,  # 待处理审批关联的工具调用 ID；无法取得时为空。
        status: str,  # 审批处理结果，例如 approved 或 rejected。
    ) -> None: ...

    # ============================================================
    # Agent 运行态端口：审计日志写入
    # ============================================================

    # 写入 Agent 运行审计事件，供 list_audit_logs 查询和追踪。
    # 调用方：AfterSalesRunProjector。
    async def record_audit_log(
        self,
        *,
        conversation_id: str | None,  # 审计事件所属的 Agent 运行或会话 ID；没有上下文时为空。
        event_type: str,  # 审计事件类型。
        payload: dict[str, object],  # 审计事件的结构化载荷。
    ) -> AuditLogRead: ...

    # 总结：
    # 1. 售后业务数据端口服务于 AfterSalesService，用来读写订单、物流、工单、退款、政策和审计查询。
    # 2. Agent 运行态端口服务于 AfterSalesRunProjector，用来记录工具调用、人工审批和运行审计。
    # 3. AfterSalesService.evaluate_refund_approval 是纯业务规则计算，不依赖数据库读写，所以不属于 repository。


class AfterSalesUnitOfWork(Protocol):
    @property
    def repository(self) -> AfterSalesRepository: ...

    async def commit(self) -> None: ...

    async def rollback(self) -> None: ...
