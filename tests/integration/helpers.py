from __future__ import annotations

import json
import re
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI
from langchain_core.messages import AIMessage, ToolMessage
from sse_starlette.sse import AppStatus

from after_sales.infrastructure.persistence.sqlalchemy.models import (
    Customer,
    Order,
    PolicyArticle,
    Shipment,
)
from after_sales.infrastructure.persistence.sqlalchemy.session import (
    BusinessDatabase,
)
from agent_core.support import text_from_message
from app_api.main import create_app
from app_api.settings import AppSettings, MCPServerConfig
from tests.fake_chat_models import DeterministicToolCallingChatModel


class AfterSalesRoutingChatModel(DeterministicToolCallingChatModel):
    def respond_from_tool_message(self, message: ToolMessage) -> AIMessage:
        artifact = message.artifact if isinstance(message.artifact, dict) else {}
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

    def plan_from_human_message(
        self,
        message: Any,
        *,
        tools: list[Any],
    ) -> AIMessage:
        content = text_from_message(message)
        available_tools = {tool.name for tool in tools}
        order_id = self._extract_order_id(content)

        if order_id and ("物流" in content or "到哪" in content or "shipment" in content.lower()):
            if "get_shipment_detail" in available_tools:
                return self.tool_call_message(
                    "get_shipment_detail",
                    {"order_id": order_id},
                    tool_call_id="call_get_shipment_detail",
                )

        if order_id and "退款" in content:
            amount = self._extract_refund_amount(content)
            if amount is not None and "submit_refund_request" in available_tools:
                return self.tool_call_message(
                    "submit_refund_request",
                    {
                        "order_id": order_id,
                        "amount": amount,
                        "reason": content,
                    },
                    tool_call_id="call_submit_refund_request",
                )

        if order_id and any(keyword in content for keyword in ["坏了", "破损", "退货", "换货"]):
            if "create_ticket" in available_tools:
                return self.tool_call_message(
                    "create_ticket",
                    {
                        "order_id": order_id,
                        "issue_type": self._issue_type_from_message(content),
                        "summary": content,
                        "priority": "normal",
                    },
                    tool_call_id="call_create_ticket",
                )

        ticket_id = self._extract_ticket_id(content)
        if ticket_id and ("工单" in content or "ticket" in content.lower()):
            if "get_ticket_detail" in available_tools:
                return self.tool_call_message(
                    "get_ticket_detail",
                    {"ticket_id": ticket_id},
                    tool_call_id="call_get_ticket_detail",
                )

        if order_id and ("订单" in content or "查一下" in content or "order" in content.lower()):
            if "get_order_detail" in available_tools:
                return self.tool_call_message(
                    "get_order_detail",
                    {"order_id": order_id},
                    tool_call_id="call_get_order_detail",
                )

        if any(keyword in content for keyword in ["退款", "政策", "规则", "破损"]):
            if "search_after_sales_policy" in available_tools:
                return self.tool_call_message(
                    "search_after_sales_policy",
                    {"query": "破损"},
                    tool_call_id="call_search_after_sales_policy",
                )

        return AIMessage(content="当前模型没找到需要调用工具的场景。")

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


async def build_after_sales_app(
    database_path: Path,
    *,
    mcp_servers: dict[str, MCPServerConfig] | None = None,
) -> FastAPI:
    database_url = f"sqlite+pysqlite:///{database_path}"
    await _seed_business_database(database_url)
    settings = AppSettings(
        app_env="test",
        business_database_url=database_url,
        agent_runtime_database_url=None,
        auto_create_schema=False,
        api_key=None,
        mcp_servers=mcp_servers or {},
    )
    return create_app(
        settings,
        chat_model_override=AfterSalesRoutingChatModel(),
    )


async def build_health_only_app(database_path: Path) -> FastAPI:
    database_url = f"sqlite+pysqlite:///{database_path}"
    database = BusinessDatabase(database_url)
    await database.create_schema()
    await database.dispose()
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


async def _seed_business_database(database_url: str) -> None:
    database = BusinessDatabase(database_url)
    await database.create_schema()
    now = datetime.now(UTC)
    async with database.managed_session() as session:
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
        await session.commit()
    await database.dispose()
