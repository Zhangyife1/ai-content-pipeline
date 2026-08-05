"""RAG 客服引擎：检索增强问答 + 多轮记忆 + Function Calling 闭环。"""

from __future__ import annotations

import logging

from ai_content_pipeline.conversation.function_calling import FunctionCallRouter
from ai_content_pipeline.conversation.session import SessionStore
from ai_content_pipeline.generation.hyde import HydeRetriever
from ai_content_pipeline.generation.llm import LLMClient
from ai_content_pipeline.models import ChatTurn, ToolCall
from ai_content_pipeline.prompts.registry import PromptRegistry

logger = logging.getLogger(__name__)


class ChatEngine:
    def __init__(
        self,
        retriever: HydeRetriever,
        llm: LLMClient,
        prompts: PromptRegistry,
        sessions: SessionStore | None = None,
        tools: FunctionCallRouter | None = None,
        top_k: int = 3,
    ) -> None:
        self.retriever = retriever
        self.llm = llm
        self.prompts = prompts
        self.sessions = sessions or SessionStore()
        self.tools = tools or FunctionCallRouter()
        self.top_k = top_k

    def handle_message(self, session_id: str | None, message: str) -> ChatTurn:
        session = self.sessions.get_or_create(session_id)
        history = session.recent(6)
        tools_called: list[ToolCall] = []
        reply = ""

        tool_name = self.tools.detect_tool(message)
        if tool_name == "query_order":
            order_id = self.tools.extract_order_id(message)
            arguments = {"order_id": order_id} if order_id else {"order_id": "SO20260801001"}
            if order_id is None:
                # 没有订单号时先向用户索要，保持多轮
                reply = "请提供订单号（例如 SO20260801001），我帮您查询物流与状态。"
            else:
                try:
                    result = self.tools.execute("query_order", arguments)
                    reply = (
                        f"已为您查询到订单 {result['order_id']}：状态为「{result['status']}」，"
                        f"金额 ¥{result['amount']}，{result.get('eta', '')}"
                    )
                    tools_called.append(ToolCall(name="query_order", arguments=arguments, result=result))
                    session.remember_fact(f"order={result['order_id']}")
                except KeyError as exc:
                    reply = f"抱歉，{exc}。请核对订单号后重试。"
        elif tool_name == "create_order":
            product_match = None
            import re

            for keyword in ("专业版", "企业版", "免费版"):
                if keyword in message:
                    product_match = keyword
                    break
            product = product_match or "星尘 AI 专业版（年付）"
            result = self.tools.execute("create_order", {"product": product, "quantity": 1})
            tools_called.append(ToolCall(name="create_order", arguments={"product": product}, result=result))
            reply = (
                f"订单已创建：{result['order_id']}，金额 ¥{result['amount']}，"
                f"{result.get('eta', '')}。如需人工确认请回复「人工」。"
            )
        else:
            # RAG 检索增强问答（多轮：带历史重写查询）
            query = message
            if history:
                query = self.llm.complete(
                    system="你是查询改写器。结合对话历史把当前问题改写为独立的检索查询。",
                    user=self.prompts.render("query_rewrite", {"history": "\n".join(history), "message": message}),
                    prompt_id="query_rewrite",
                    temperature=0.0,
                ).strip() or message
            hits = self.retriever.search(query, top_k=self.top_k)
            context = "\n".join(f"[{i}] {h.content}" for i, h in enumerate(hits)) or "（知识库暂无相关内容）"
            reply = self.llm.complete(
                system="你是官网智能客服。只依据知识库上下文回答；知识库没有的信息要明确说明，并引导用户联系人工。",
                user=self.prompts.render("chat_answer", {"question": message, "context": context}),
                prompt_id="chat_answer",
                temperature=0.3,
            ).strip()

        session.add_message("user", message)
        session.add_message("assistant", reply)
        turn = ChatTurn(
            session_id=session.session_id,
            user_message=message,
            bot_reply=reply,
            tools_called=tools_called,
        )
        logger.info("chat turn session=%s tools=%s", session.session_id, [t.name for t in tools_called])
        return turn

