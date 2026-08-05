"""Function Calling：工具 Schema + 意图路由 + 订单业务闭环（问答→查询→下单）。"""

from __future__ import annotations

import re
import uuid
from abc import ABC, abstractmethod
from datetime import datetime, timedelta, timezone

import httpx

from ai_content_pipeline.models import OrderInfo


TOOL_SCHEMAS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "query_order",
            "description": "按订单号或手机号查询订单状态、金额与物流信息",
            "parameters": {
                "type": "object",
                "properties": {
                    "order_id": {"type": "string", "description": "订单号，例如 SO20260801001"},
                    "phone": {"type": "string", "description": "下单手机号后四位"}
                },
                "required": ["order_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_order",
            "description": "基于已确认的商品与数量创建订单",
            "parameters": {
                "type": "object",
                "properties": {
                    "product": {"type": "string", "description": "商品名称"},
                    "quantity": {"type": "integer", "description": "数量，默认 1"},
                    "customer_note": {"type": "string", "description": "备注"}
                },
                "required": ["product"],
            },
        },
    },
]


class OrderService(ABC):
    @abstractmethod
    def query_order(self, order_id: str, phone: str | None = None) -> OrderInfo: ...

    @abstractmethod
    def create_order(self, product: str, quantity: int, customer_note: str = "") -> OrderInfo: ...


class MockOrderService(OrderService):
    """演示订单服务：进程内内存，数据可复现。"""

    def __init__(self) -> None:
        self._orders: dict[str, OrderInfo] = {
            "SO20260801001": OrderInfo(
                order_id="SO20260801001",
                status="shipped",
                amount=299.0,
                items=[{"product": "星尘 AI 专业版（年付）", "quantity": 1, "price": 299.0}],
                eta="预计 2026-08-08 前送达",
            )
        }

    def query_order(self, order_id: str, phone: str | None = None) -> OrderInfo:
        order = self._orders.get(order_id)
        if order is None:
            raise KeyError(f"未找到订单 {order_id}")
        return order

    def create_order(self, product: str, quantity: int, customer_note: str = "") -> OrderInfo:
        order = OrderInfo(
            order_id=f"SO{datetime.now(timezone.utc):%Y%m%d}{uuid.uuid4().hex[:6].upper()}",
            status="paid",
            amount=round(299.0 * quantity, 2),
            items=[{"product": product, "quantity": quantity, "price": 299.0}],
            created_at=datetime.now(timezone.utc),
            eta="预计 24 小时内发货",
        )
        self._orders[order.order_id] = order
        return order


class HttpOrderService(OrderService):
    """对接真实订单 API（PHP 后端 / 电商系统）。"""

    def __init__(self, base_url: str, api_key: str = "") -> None:
        self.base_url = base_url.rstrip("/")
        self.headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}

    def query_order(self, order_id: str, phone: str | None = None) -> OrderInfo:
        resp = httpx.get(f"{self.base_url}/api/orders/{order_id}", headers=self.headers, timeout=10)
        resp.raise_for_status()
        return OrderInfo.model_validate(resp.json())

    def create_order(self, product: str, quantity: int, customer_note: str = "") -> OrderInfo:
        resp = httpx.post(
            f"{self.base_url}/api/orders",
            headers=self.headers,
            json={"product": product, "quantity": quantity, "customer_note": customer_note},
            timeout=10,
        )
        resp.raise_for_status()
        return OrderInfo.model_validate(resp.json())


class FunctionCallRouter:
    """意图识别 + 工具执行。关键词路由用于 demo；生产可交给 LLM 输出 tool_calls。"""

    ORDER_QUERY_PATTERN = re.compile(r"(订单|快递|物流|发货|查单|查询订单)", re.IGNORECASE)
    ORDER_CREATE_PATTERN = re.compile(r"(下单|购买|买一个|买一份|开通|订阅)", re.IGNORECASE)

    def __init__(self, order_service: OrderService | None = None) -> None:
        self.order_service = order_service or MockOrderService()
        self._tools = {
            "query_order": self.order_service.query_order,
            "create_order": self.order_service.create_order,
        }

    def detect_tool(self, text: str) -> str | None:
        """返回候选工具名；由 ChatEngine 结合上下文确认。"""
        if self.ORDER_CREATE_PATTERN.search(text) and not self.ORDER_QUERY_PATTERN.search(text):
            return "create_order"
        if self.ORDER_QUERY_PATTERN.search(text):
            return "query_order"
        return None

    def execute(self, name: str, arguments: dict) -> dict:
        if name not in self._tools:
            raise KeyError(f"未知工具: {name}")
        result = self._tools[name](**arguments)
        return result.model_dump(mode="json")

    @staticmethod
    def extract_order_id(text: str) -> str | None:
        match = re.search(r"(SO\d{6,}|\d{10,})", text, re.IGNORECASE)
        return match.group(1) if match else None
