from __future__ import annotations

import json
import re
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import httpx
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import BaseTool
from sse_starlette.sse import AppStatus

from agent_service.llm import text_from_message
from app_api.main import create_app
from app_api.settings import AppSettings
from business_service.after_sales.infrastructure.persistence.sqlalchemy.models import (
    Customer,
    Order,
    PolicyArticle,
    Shipment,
)
from business_service.after_sales.infrastructure.persistence.sqlalchemy.session import (
    BusinessDatabase,
)


class AfterSalesRoutingChatClient:
    provider = "test"
    model = "test-after-sales-v2"

    async def ainvoke(
        self,
        messages: list[BaseMessage],
        tools: list[BaseTool],
        config: RunnableConfig | None = None,
    ) -> AIMessage:
        del config
        if messages and isinstance(messages[-1], ToolMessage):
            return self._respond_from_tool_message(messages[-1])

        human_message = self._latest_human_message(messages)
        if human_message is None:
            return AIMessage(content="当前测试模型没有拿到用户输入。")
        return self._plan_from_human_message(human_message, tools=tools)

    def _latest_human_message(self, messages: list[BaseMessage]) -> HumanMessage | None:
        for message in reversed(messages):
            if isinstance(message, HumanMessage):
                return message
        return None

    def _respond_from_tool_message(self, message: ToolMessage) -> AIMessage:
        artifact = getattr(message, "artifact", None) or {}
        tool_name = message.name or artifact.get("action") or "tool"
        if isinstance(artifact, dict) and artifact.get("success") is False:
            error = artifact.get("error") or {}
            error_message = error.get("message") or text_from_message(message) or "unknown error"
            return AIMessage(content=f"工具 `{tool_name}` 执行失败：{error_message}。")

        result = artifact.get("result") if isinstance(artifact, dict) else None
        if tool_name == "get_order_detail" and isinstance(result, dict):
            return AIMessage(
                content=(
                    f"订单 {result['order_id']} 当前状态是 {result['status']}，"
                    f"商品为 {result['item_summary']}。"
                )
            )
        if tool_name == "get_shipment_detail" and isinstance(result, dict):
            return AIMessage(
                content=(
                    f"订单 {result['order_id']} 的物流状态是 {result['status']}，"
                    f"最新位置在 {result['latest_location']}。"
                )
            )
        if tool_name == "create_ticket" and isinstance(result, dict):
            return AIMessage(
                content=(
                    f"已为订单 {result['order_id']} 创建工单 {result['ticket_id']}，"
                    f"当前状态为 {result['status']}。"
                )
            )
        if tool_name == "get_ticket_detail" and isinstance(result, dict):
            return AIMessage(
                content=(
                    f"工单 {result['ticket_id']} 当前状态是 {result['status']}，"
                    f"问题摘要为 {result['summary']}。"
                )
            )
        if tool_name == "submit_refund_request" and isinstance(result, dict):
            return AIMessage(
                content=(
                    f"订单 {result['order_id']} 的退款申请已通过，金额为 {result['amount']} 元，"
                    f"原因是 {result['reason']}。"
                )
            )
        if tool_name == "search_after_sales_policy" and isinstance(result, list):
            if not result:
                return AIMessage(content="没有找到匹配的售后政策。")
            return AIMessage(content=f"已找到相关售后政策：{result[0]['title']}。")

        return AIMessage(content=f"我已经调用 `{tool_name}` 完成处理。")

    def _plan_from_human_message(
        self,
        message: HumanMessage,
        *,
        tools: list[BaseTool],
    ) -> AIMessage:
        content = text_from_message(message)
        available_tools = {tool.name for tool in tools}
        order_id = self._extract_order_id(content)

        if order_id and ("物流" in content or "到哪" in content or "shipment" in content.lower()):
            if "get_shipment_detail" in available_tools:
                return self._tool_call_message("get_shipment_detail", {"order_id": order_id})

        if order_id and "退款" in content:
            amount = self._extract_refund_amount(content)
            if amount is not None and "submit_refund_request" in available_tools:
                return self._tool_call_message(
                    "submit_refund_request",
                    {
                        "order_id": order_id,
                        "amount": amount,
                        "reason": content,
                    },
                )

        if order_id and any(keyword in content for keyword in ["坏了", "破损", "退货", "换货"]):
            if "create_ticket" in available_tools:
                return self._tool_call_message(
                    "create_ticket",
                    {
                        "order_id": order_id,
                        "issue_type": self._issue_type_from_message(content),
                        "summary": content,
                        "priority": "normal",
                    },
                )

        ticket_id = self._extract_ticket_id(content)
        if ticket_id and ("工单" in content or "ticket" in content.lower()):
            if "get_ticket_detail" in available_tools:
                return self._tool_call_message("get_ticket_detail", {"ticket_id": ticket_id})

        if order_id and ("订单" in content or "查一下" in content or "order" in content.lower()):
            if "get_order_detail" in available_tools:
                return self._tool_call_message("get_order_detail", {"order_id": order_id})

        if any(keyword in content for keyword in ["退款", "政策", "规则", "破损"]):
            if "search_after_sales_policy" in available_tools:
                return self._tool_call_message("search_after_sales_policy", {"query": "破损"})

        return AIMessage(content="当前模型没找到需要调用工具的场景。")

    def _tool_call_message(self, tool_name: str, arguments: dict[str, str]) -> AIMessage:
        return AIMessage(
            content="",
            tool_calls=[
                {
                    "name": tool_name,
                    "args": arguments,
                    "id": f"call_{tool_name}",
                    "type": "tool_call",
                }
            ],
        )

    def _extract_order_id(self, message: str) -> str | None:
        match = re.search(r"(ORD\d+)", message.upper())
        return match.group(1) if match else None

    def _extract_ticket_id(self, message: str) -> str | None:
        match = re.search(r"(TCK-[A-Z0-9]+)", message.upper())
        return match.group(1) if match else None

    def _extract_refund_amount(self, message: str) -> str | None:
        refund_match = re.search(r"退款\s*([0-9]+(?:\.[0-9]+)?)", message)
        if refund_match:
            return refund_match.group(1)
        amount_match = re.search(r"([0-9]+(?:\.[0-9]+)?)\s*元", message)
        return amount_match.group(1) if amount_match else None

    def _issue_type_from_message(self, message: str) -> str:
        if "换货" in message:
            return "exchange"
        if "退货" in message:
            return "return"
        if "坏了" in message or "破损" in message:
            return "damaged"
        return "other"


def build_after_sales_app(database_path: Path):
    database_url = f"sqlite+pysqlite:///{database_path}"
    _seed_business_database(database_url)
    settings = AppSettings(
        app_env="test",
        business_database_url=database_url,
        agent_runtime_database_url=None,
        auto_create_schema=False,
        api_key=None,
    )
    return create_app(
        settings,
        chat_client_override=AfterSalesRoutingChatClient(),
    )


def build_health_only_app(database_path: Path):
    database_url = f"sqlite+pysqlite:///{database_path}"
    database = BusinessDatabase(database_url)
    database.create_schema()
    database.dispose()
    settings = AppSettings(
        app_env="test",
        business_database_url=database_url,
        agent_runtime_database_url=None,
        auto_create_schema=False,
        api_key=None,
        llm_provider="missing-provider",
    )
    return create_app(settings)


async def collect_sse_events(
    client: httpx.AsyncClient,
    endpoint: str,
    payload: dict[str, object],
) -> list[tuple[str, dict[str, object]]]:
    AppStatus.should_exit = False
    AppStatus.should_exit_event = None
    events: list[tuple[str, dict[str, object]]] = []
    event_name: str | None = None
    async with client.stream("POST", endpoint, json=payload) as response:
        assert response.status_code == 200
        async for line in response.aiter_lines():
            if not line:
                continue
            if line.startswith("event: "):
                event_name = line.removeprefix("event: ").strip()
                continue
            if line.startswith("data: ") and event_name is not None:
                events.append((event_name, json.loads(line.removeprefix("data: "))))
                event_name = None
    return events


def _seed_business_database(database_url: str) -> None:
    database = BusinessDatabase(database_url)
    database.create_schema()
    now = datetime.now(UTC)
    with database.managed_session() as session:
        session.add_all(
            [
                Customer(
                    customer_id="CUS001",
                    name="Lin Qian",
                    email="lin.qian@example.com",
                    phone="+86-13800000001",
                    created_at=now - timedelta(days=90),
                ),
                Order(
                    order_id="ORD123",
                    customer_id="CUS001",
                    status="shipped",
                    total_amount=Decimal("199.00"),
                    currency="CNY",
                    item_summary="蓝牙耳机 x1",
                    created_at=now - timedelta(days=5),
                ),
                Order(
                    order_id="ORD456",
                    customer_id="CUS001",
                    status="processing",
                    total_amount=Decimal("89.00"),
                    currency="CNY",
                    item_summary="手机壳 x2",
                    created_at=now - timedelta(days=2),
                ),
                Shipment(
                    shipment_id="SHP123",
                    order_id="ORD123",
                    carrier="SF Express",
                    tracking_no="SF123456789CN",
                    status="in_transit",
                    latest_location="Shanghai Sorting Center",
                    estimated_delivery_at=now + timedelta(days=1),
                    events_json=[
                        {
                            "timestamp": (now - timedelta(days=1)).isoformat(),
                            "location": "Shanghai Sorting Center",
                            "detail": "已到达分拨中心",
                        }
                    ],
                    updated_at=now - timedelta(hours=6),
                ),
                PolicyArticle(
                    article_id="POL001",
                    title="商品破损退款处理规则",
                    category="refund",
                    keywords=["退款", "破损", "质量问题"],
                    content="如商品存在破损，可发起退款申请。",
                    created_at=now - timedelta(days=7),
                ),
            ]
        )
        session.commit()
    database.dispose()
