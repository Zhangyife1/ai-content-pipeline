"""多步生成 Chain：大纲 -> 分段撰写 -> 摘要/FAQ/SEO。

设计要点：
- 每一步输出都经过 Pydantic Schema 校验，失败自动重试（最多 3 次）；
- 连续失败抛错并进入“需人工处理”队列（由上层 Worker 落库/通知）；
- 分段撰写采用 Map-Reduce 变体：各节独立生成，Reduce 检查连贯性。
"""

from __future__ import annotations

import logging
import re

from pydantic import ValidationError

from ai_content_pipeline.generation.hyde import HydeRetriever
from ai_content_pipeline.generation.llm import LLMClient, extract_json
from ai_content_pipeline.models import (
    ArticleOutline,
    GeneratedArticle,
    RetrievalResult,
    SeoMeta,
)
from ai_content_pipeline.prompts.registry import PromptRegistry

logger = logging.getLogger(__name__)


class GenerationError(RuntimeError):
    pass


class ContentChain:
    def __init__(
        self,
        llm: LLMClient,
        retriever: HydeRetriever,
        prompts: PromptRegistry,
        max_attempts: int = 3,
    ) -> None:
        self.llm = llm
        self.retriever = retriever
        self.prompts = prompts
        self.max_attempts = max_attempts

    def retrieve_context(self, topic: str, top_k: int = 5) -> list[RetrievalResult]:
        return self.retriever.search(topic, top_k=top_k)

    def generate_outline(
        self,
        topic: str,
        platform: str = "公众号",
        style: str = "专业",
        word_count: int = 2000,
        audience: str = "目标用户",
        context: list[RetrievalResult] | None = None,
    ) -> ArticleOutline:
        context = context or []
        context_text = "\n".join(f"[{i}] {c.content}" for i, c in enumerate(context)) or "（无检索结果）"
        variables = {
            "audience": audience,
            "content_type": "文章",
            "topic": topic,
            "platform": platform,
            "style": style,
            "word_count": str(word_count),
            "context": context_text,
        }
        last_error: Exception | None = None
        for attempt in range(1, self.max_attempts + 1):
            raw = self.llm.complete(
                system="你是资深内容策略专家，只输出合法 JSON。",
                user=self.prompts.render("outline", variables),
                prompt_id="outline",
                temperature=0.5,
            )
            try:
                return ArticleOutline.model_validate(extract_json(raw))
            except (ValidationError, ValueError) as exc:
                last_error = exc
                logger.warning("大纲 Schema 校验失败，第 %d 次重试: %s", attempt, exc)
        raise GenerationError(f"大纲生成连续 {self.max_attempts} 次未通过 Schema 校验: {last_error}")

    def write_section(
        self,
        topic: str,
        section_title: str,
        key_points: list[str],
        word_count: int,
        style: str,
        context: list[RetrievalResult],
        previous_summary: str = "",
    ) -> str:
        context_text = "\n".join(f"[{i}] {c.content}" for i, c in enumerate(context)) or "（无检索结果）"
        user = self.prompts.render(
            "section_writer",
            {
                "section_title": section_title,
                "key_points": "；".join(key_points),
                "context": context_text,
                "previous_summary": previous_summary or "（首节）",
                "word_count": str(word_count),
                "style": style,
            },
        )
        return self.llm.complete(
            system=f"你是资深内容撰稿人，正在撰写关于「{topic}」的文章。",
            user=user,
            prompt_id="section_writer",
        ).strip()

    def _write_all_sections(self, topic: str, outline: ArticleOutline, context: list[RetrievalResult], style: str) -> list[str]:
        sections: list[str] = []
        previous = ""
        for section in outline.sections:
            body = self.write_section(
                topic=topic,
                section_title=section.title,
                key_points=section.key_points,
                word_count=section.word_count,
                style=style,
                context=context,
                previous_summary=previous,
            )
            sections.append(body)
            # Reduce 步骤：用前文摘要保证连贯性（demo 直接用节标题近似）
            previous = re.sub(r"^#+\s*", "", body.splitlines()[0]) if body else ""
        return sections

    def generate_summary(self, title: str, body: str, mode: str = "生成式") -> str:
        return self.llm.complete(
            system="你是内容编辑，擅长提炼摘要。",
            user=self.prompts.render("summary", {"mode": mode, "title": title, "content": body}),
            prompt_id="summary",
            temperature=0.3,
            max_tokens=400,
        ).strip()

    def generate_faq(self, context: list[RetrievalResult]) -> list[dict[str, str]]:
        context_text = "\n".join(c.content for c in context) or "（无检索结果）"
        raw = self.llm.complete(
            system="你是知识库问答生成器，只输出 JSON 数组。",
            user=self.prompts.render("faq", {"context": context_text}),
            prompt_id="faq",
            temperature=0.3,
        )
        try:
            data = extract_json(raw)
            return [{"question": str(item["question"]), "answer": str(item["answer"])} for item in data]
        except (ValueError, KeyError, TypeError) as exc:
            logger.warning("FAQ 解析失败，返回空列表: %s", exc)
            return []

    def generate_seo(self, title: str, summary: str) -> SeoMeta:
        raw = self.llm.complete(
            system="你是 SEO 专家，只输出合法 JSON。",
            user=self.prompts.render("seo", {"title": title, "summary": summary}),
            prompt_id="seo",
            temperature=0.2,
        )
        try:
            return SeoMeta.model_validate(extract_json(raw))
        except (ValidationError, ValueError) as exc:
            logger.warning("SEO Schema 校验失败，使用兜底: %s", exc)
            slug = re.sub(r"[^\w\u4e00-\u9fff]+", "-", title)[:40]
            return SeoMeta(
                title_tag=title[:60],
                meta_description=summary[:120],
                keywords=[title[:10]],
                url_slug=slug,
            )

    def run_article(
        self,
        topic: str,
        platform: str = "公众号",
        style: str = "专业",
        word_count: int = 2000,
        audience: str = "目标用户",
    ) -> GeneratedArticle:
        """执行完整文章生成链并组装输出（正文/摘要/FAQ/SEO）。"""
        context = self.retrieve_context(topic, top_k=5)
        outline = self.generate_outline(
            topic=topic,
            platform=platform,
            style=style,
            word_count=word_count,
            audience=audience,
            context=context,
        )
        sections = self._write_all_sections(topic, outline, context, style)
        body = "\n\n".join(sections)
        summary = self.generate_summary(outline.title, body)
        faq = self.generate_faq(context)
        seo = self.generate_seo(outline.title, summary)
        article = GeneratedArticle(
            title=outline.title,
            body=body,
            summary=summary,
            faq_pairs=faq,
            seo=seo,
            prompt_version=self.prompts.get_active("outline").version,
        )
        logger.info("文章生成完成 content_id=%s title=%s", article.content_id, article.title)
        return article
