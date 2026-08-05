import unittest

from ai_content_pipeline.conversation.chat import ChatEngine
from ai_content_pipeline.conversation.function_calling import FunctionCallRouter, MockOrderService
from ai_content_pipeline.generation.llm import MockLLM
from ai_content_pipeline.prompts.registry import PromptRegistry


class FunctionCallRouterTests(unittest.TestCase):
    def setUp(self):
        self.router = FunctionCallRouter(order_service=MockOrderService())

    def test_detect_order_query(self):
        self.assertEqual(self.router.detect_tool("帮我查一下订单 SO20260801001"), "query_order")
        self.assertIsNone(self.router.detect_tool("专业版多少钱"))

    def test_query_order(self):
        result = self.router.execute("query_order", {"order_id": "SO20260801001"})
        self.assertEqual(result["status"], "shipped")
        self.assertEqual(result["amount"], 299.0)

    def test_create_order(self):
        result = self.router.execute("create_order", {"product": "专业版", "quantity": 1})
        self.assertEqual(result["status"], "paid")
        self.assertIn("SO", result["order_id"])

    def test_extract_order_id(self):
        self.assertEqual(self.router.extract_order_id("订单号是 SO20260801001 谢谢"), "SO20260801001")


class ChatEngineTests(unittest.TestCase):
    def setUp(self):
        self.engine = ChatEngine(
            retriever=type("R", (), {"search": lambda self, q, top_k=3: []})(),
            llm=MockLLM(),
            prompts=PromptRegistry(),
            tools=FunctionCallRouter(order_service=MockOrderService()),
        )

    def test_faq_grounded_answer(self):
        turn = self.engine.handle_message(None, "专业版多少钱？")
        self.assertIn("299 元", turn.bot_reply)
        self.assertEqual(turn.tools_called, [])
        self.assertTrue(turn.session_id)

    def test_multi_turn_order_loop(self):
        session_id = "chat_test"
        self.engine.handle_message(session_id, "请问专业版多少钱？")
        query_turn = self.engine.handle_message(session_id, "帮我查一下订单 SO20260801001")
        self.assertEqual(query_turn.tools_called[0].name, "query_order")
        create_turn = self.engine.handle_message(session_id, "好的，帮我下单专业版")
        self.assertEqual(create_turn.tools_called[0].name, "create_order")
        self.assertIn("订单已创建", create_turn.bot_reply)
        self.assertGreaterEqual(len(self.engine.sessions.get(session_id).history), 6)


if __name__ == "__main__":
    unittest.main()

