"""LLM 客户端抽象：Qwen（OpenAI 兼容协议）与 MockLLM（本地 demo）。"""

from __future__ import annotations

import json
import re
from typing import Protocol

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from ai_content_pipeline.config import Settings


class LLMError(RuntimeError):
    pass


class LLMClient(Protocol):
    def complete(
        self,
        system: str,
        user: str,
        prompt_id: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 2048,
    ) -> str: ...


class QwenLLMClient:
    """阿里云百炼 Qwen（OpenAI 兼容模式）。"""

    def __init__(self, settings: Settings) -> None:
        if not settings.qwen_api_key:
            raise LLMError("缺少 QWEN_API_KEY")
        self.base_url = settings.qwen_base_url.rstrip("/")
        self.api_key = settings.qwen_api_key
        self.model = settings.qwen_model
        self.timeout = settings.llm_request_timeout
        self.max_retries = settings.llm_max_retries

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        reraise=True,
    )
    def complete(
        self,
        system: str,
        user: str,
        prompt_id: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 2048,
    ) -> str:
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        try:
            resp = httpx.post(
                f"{self.base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json=payload,
                timeout=self.timeout,
            )
            resp.raise_for_status()
            data = resp.json()
            return data["choices"][0]["message"]["content"]
        except (httpx.HTTPError, KeyError, ValueError) as exc:
            raise LLMError(f"Qwen 调用失败: {exc}") from exc


class MockLLM:
    """确定性 Mock：无 API Key 时跑通全链路 demo 与测试。"""

    def complete(
        self,
        system: str,
        user: str,
        prompt_id: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 2048,
    ) -> str:
        topic = self._extract_topic(user)
        if prompt_id == "outline":
            return self._mock_outline(topic)
        if prompt_id == "section_writer":
            section = self._extract_section(user)
            return self._mock_section(topic, section)
        if prompt_id == "summary":
            return f"本文围绕「{topic}」系统梳理了核心概念、实践路径与落地建议，帮助读者快速建立完整认知并直接用于业务实践。"
        if prompt_id == "faq":
            return json.dumps(
                [
                    {"question": f"{topic}是什么？", "answer": f"{topic} 是内容管线中的核心能力，用于统一生产与分发。"},
                    {"question": f"如何落地{topic}？", "answer": "建议先梳理知识库，再逐步接入生成与质检流程。"},
                    {"question": f"{topic}的效果如何衡量？", "answer": "关注生成质量、发布成功率与内容转化率三类指标。"},
                ],
                ensure_ascii=False,
            )
        if prompt_id == "seo":
            return json.dumps(
                {
                    "title_tag": f"{topic} - 完整指南",
                    "meta_description": f"一文读懂{topic}：架构、流程、质检与发布。",
                    "keywords": [topic, "内容管线", "RAG", "AI 增长"],
                    "url_slug": f"ai-{self._slug(topic)}-guide",
                },
                ensure_ascii=False,
            )
        if prompt_id == "hyde":
            return f"假设文档：{topic} 的核心内容包括定义、工作原理、实施步骤、常见问题与效果指标。"
        return f"（Mock 输出）关于{topic}：需要配置真实 LLM 后生成高质量内容。"

    @staticmethod
    def _extract_topic(user: str) -> str:
        match = re.search(r"选题[:：]\s*([^\n]+)", user)
        if match:
            return match.group(1).strip()
        match = re.search(r"文章标题[:：]\s*([^\n]+)", user)
        if match:
            return match.group(1).strip()
        match = re.search(r"标题[:：]\s*([^\n]+)", user)
        if match:
            return match.group(1).strip()
        first_line = user.strip().splitlines()[0] if user.strip() else "AI 内容生产管线"
        return first_line.strip()[:40]

    @staticmethod
    def _extract_section(user: str) -> str:
        match = re.search(r"当前小节[:：]\s*([^\n]+)", user)
        return match.group(1).strip() if match else "核心方案"

    @staticmethod
    def _slug(text: str) -> str:
        return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:40]

    def _mock_outline(self, topic: str) -> str:
        sections = [
            {
                "title": f"{topic}：背景与核心挑战",
                "key_points": [f"{topic}的行业背景", "当前内容生产的主要瓶颈"],
                "word_count": 500,
                "source_refs": [],
            },
            {
                "title": f"{topic}：整体架构设计",
                "key_points": ["知识库投喂与 RAG", "多步生成 Chain", "质量与发布闭环"],
                "word_count": 600,
                "source_refs": [],
            },
            {
                "title": f"{topic}：落地实践与效果评估",
                "key_points": ["工程化实施路径", "核心指标与持续优化"],
                "word_count": 500,
                "source_refs": [],
            },
        ]
        return json.dumps(
            {
                "title": f"从 0 到 1 搭建{topic}体系",
                "sections": sections,
                "total_word_count": 1600,
            },
            ensure_ascii=False,
        )

    def _mock_section(self, topic: str, section: str) -> str:
        return (
            f"## {section}\n\n"
            f"在「{topic}」的实践中，我们采用分层设计：先统一数据接入与清洗，再通过语义分块与向量检索建立知识底座；"
            f"生成侧以多步 Chain 控制质量，分发侧以适配器模式对接多平台，最终通过数据回流驱动持续优化。"
            f"这套体系能够将单篇内容的生产成本降低 60% 以上，同时保持风格与事实的一致性。"
        )


def create_llm(settings: Settings) -> LLMClient:
    if settings.has_qwen_key:
        return QwenLLMClient(settings)
    return MockLLM()


def extract_json(text: str):
    """从 LLM 输出中提取第一个 JSON 对象/数组。"""
    text = text.strip()
    start_chars = ("{", "[")
    end_chars = ("}", "]")
    start = min([text.find(c) for c in start_chars if text.find(c) >= 0] or [-1])
    if start < 0:
        raise LLMError("LLM 输出中未找到 JSON")
    end = max([text.rfind(c) for c in end_chars if text.rfind(c) >= 0] or [-1])
    if end < start:
        raise LLMError("LLM 输出 JSON 结构不完整")
    return json.loads(text[start : end + 1])
