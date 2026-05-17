from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import delete

from after_sales.infrastructure.persistence.sqlalchemy.models import (
    ApprovalRecord,
    AuditLog,
    Customer,
    Order,
    PolicyArticle,
    RefundRequest,
    Shipment,
    Ticket,
    ToolCallLog,
)
from after_sales.infrastructure.persistence.sqlalchemy.session import (
    BusinessDatabase,
)
from app_api.settings import AppSettings


def utcnow() -> datetime:
    return datetime.now(UTC)


async def seed() -> None:
    settings = AppSettings()
    business_database = BusinessDatabase(settings.business_database_url)
    await business_database.create_schema()

    now = utcnow()

    customers = [
        Customer(
            customer_id="CUS001",
            name="Lin Qian",
            email="lin.qian@example.com",
            phone="+86-13800000001",
            created_at=now - timedelta(days=90),
        ),
        Customer(
            customer_id="CUS002",
            name="Wang Rui",
            email="wang.rui@example.com",
            phone="+86-13800000002",
            created_at=now - timedelta(days=60),
        ),
        Customer(
            customer_id="CUS003",
            name="Chen Mo",
            email="chen.mo@example.com",
            phone="+86-13800000003",
            created_at=now - timedelta(days=30),
        ),
    ]

    orders = [
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
            customer_id="CUS002",
            status="delivered",
            total_amount=Decimal("459.00"),
            currency="CNY",
            item_summary="智能手环 x1",
            created_at=now - timedelta(days=8),
        ),
        Order(
            order_id="ORD789",
            customer_id="CUS003",
            status="processing",
            total_amount=Decimal("89.00"),
            currency="CNY",
            item_summary="手机壳 x2",
            created_at=now - timedelta(days=2),
        ),
    ]

    shipments = [
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
                    "timestamp": (now - timedelta(days=4)).isoformat(),
                    "location": "Shenzhen Warehouse",
                    "detail": "包裹已出库",
                },
                {
                    "timestamp": (now - timedelta(days=3)).isoformat(),
                    "location": "Guangzhou Transit Hub",
                    "detail": "运输中",
                },
                {
                    "timestamp": (now - timedelta(days=1)).isoformat(),
                    "location": "Shanghai Sorting Center",
                    "detail": "已到达分拨中心",
                },
            ],
            updated_at=now - timedelta(hours=6),
        ),
        Shipment(
            shipment_id="SHP456",
            order_id="ORD456",
            carrier="JD Logistics",
            tracking_no="JD987654321CN",
            status="delivered",
            latest_location="Hangzhou",
            estimated_delivery_at=now - timedelta(days=2),
            events_json=[
                {
                    "timestamp": (now - timedelta(days=7)).isoformat(),
                    "location": "Hangzhou Warehouse",
                    "detail": "包裹已出库",
                },
                {
                    "timestamp": (now - timedelta(days=6)).isoformat(),
                    "location": "Hangzhou Delivery Station",
                    "detail": "派送中",
                },
                {
                    "timestamp": (now - timedelta(days=5)).isoformat(),
                    "location": "Hangzhou",
                    "detail": "客户已签收",
                },
            ],
            updated_at=now - timedelta(days=5),
        ),
        Shipment(
            shipment_id="SHP789",
            order_id="ORD789",
            carrier="YTO Express",
            tracking_no="YT1122334455CN",
            status="label_created",
            latest_location="Suzhou Warehouse",
            estimated_delivery_at=now + timedelta(days=3),
            events_json=[
                {
                    "timestamp": (now - timedelta(days=1)).isoformat(),
                    "location": "Suzhou Warehouse",
                    "detail": "电子面单已生成",
                },
                {
                    "timestamp": (now - timedelta(hours=12)).isoformat(),
                    "location": "Suzhou Warehouse",
                    "detail": "等待揽收",
                },
            ],
            updated_at=now - timedelta(hours=12),
        ),
    ]

    policy_articles = [
        PolicyArticle(
            article_id="POL001",
            title="商品破损退款处理规则",
            category="refund",
            keywords=["退款", "破损", "质量问题"],
            content="如商品在签收后 48 小时内确认存在破损或质量问题，可发起退款申请；高金额申请需人工审批。",
            created_at=now - timedelta(days=20),
        ),
        PolicyArticle(
            article_id="POL002",
            title="退货工单创建 SOP",
            category="ticket",
            keywords=["退货", "工单", "售后"],
            content="用户提出退货诉求时，客服需先核对订单状态，再创建售后工单并记录问题摘要。",
            created_at=now - timedelta(days=15),
        ),
        PolicyArticle(
            article_id="POL003",
            title="物流异常跟进说明",
            category="shipment",
            keywords=["物流", "延迟", "查单"],
            content="对于物流长时间未更新的订单，客服应先查询最新物流节点，再根据节点决定是否升级处理。",
            created_at=now - timedelta(days=10),
        ),
    ]

    async with business_database.managed_session() as session:
        for model in [
            AuditLog,
            ApprovalRecord,
            ToolCallLog,
            RefundRequest,
            Ticket,
            Shipment,
            Order,
            PolicyArticle,
            Customer,
        ]:
            await session.execute(delete(model))

        session.add_all(customers)
        session.add_all(orders)
        session.add_all(shipments)
        session.add_all(policy_articles)
        await session.commit()

    await business_database.dispose()


if __name__ == "__main__":
    asyncio.run(seed())
    print("seed completed")
