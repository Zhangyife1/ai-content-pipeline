"""Prompt Registry：模板可存数据库、可版本回滚、支持 A/B 按权重分配。"""

from __future__ import annotations

import re
import string

from ai_content_pipeline.models import PromptTemplate
from ai_content_pipeline.storage.repositories import ContentRepository


DEFAULT_PROMPTS: list[PromptTemplate] = [
    PromptTemplate(
        prompt_id="outline",
        version="1.0.0",
        template=(
            "基于以下参考资料，为一篇面向{audience}的{content_type}生成大纲。\n"
            "选题：{topic}\n目标平台：{platform}\n风格：{style}\n字数要求：{word_count}\n"
            "参考资料：\n{context}\n"
            "要求：\n1. 标题需包含核心关键词，具备传播性；\n"
            "2. 每个 H2 小节需标注写作要点和参考来源编号；\n"
            "3. 避免与已有内容重复的结构；\n4. 输出 JSON，字段为 title/sections/total_word_count。"
        ),
        variables=["audience", "content_type", "topic", "platform", "style", "word_count", "context"],
        output_schema={
            "type": "object",
            "required": ["title", "sections", "total_word_count"],
        },
    ),
    PromptTemplate(
        prompt_id="section_writer",
        version="1.0.0",
        template=(
            "请撰写以下小节，要求事实准确、语言自然、与前文连贯。\n"
            "当前小节：{section_title}\n写作要点：{key_points}\n参考资料：{context}\n"
            "前文摘要：{previous_summary}\n字数要求：{word_count}\n风格：{style}"
        ),
        variables=["section_title", "key_points", "context", "previous_summary", "word_count", "style"],
        output_schema={"type": "string"},
    ),
    PromptTemplate(
        prompt_id="summary",
        version="1.0.0",
        template=(
            "文章标题：{title}\n\n"
            "为下面的文章生成 200 字以内的摘要（{mode}模式），保留核心结论与行动建议：\n{content}"
        ),
        variables=["title", "mode", "content"],
        output_schema={"type": "string"},
    ),
    PromptTemplate(
        prompt_id="faq",
        version="1.0.0",
        template=(
            "基于知识库 chunk 生成问答对：模拟用户可能提出的问题，再基于以下资料给出准确答案。\n"
            "要求输出 JSON 数组，每项含 question 与 answer。\n{context}"
        ),
        variables=["context"],
        output_schema={"type": "array"},
    ),
    PromptTemplate(
        prompt_id="seo",
        version="1.0.0",
        template=(
            "为文章生成 SEO 元数据：title_tag（<=60字）、meta_description（<=120字）、"
            "keywords（5-8个）、url_slug。输出 JSON。\n标题：{title}\n正文摘要：{summary}"
        ),
        variables=["title", "summary"],
        output_schema={"type": "object"},
    ),
    PromptTemplate(
        prompt_id="hyde",
        version="1.0.0",
        template=(
            "根据查询生成一段假设文档（Hypothetical Document）：想象一篇能够回答该问题的内容，"
            "写出其中可能出现的核心概念与表述，用于提升召回率。\n查询：{query}"
        ),
        variables=["query"],
        output_schema={"type": "string"},
    ),
    PromptTemplate(
        prompt_id="chat_answer",
        version="1.0.0",
        template=(
            "你是官网智能客服。请基于以下知识库上下文回答用户问题：\n"
            "用户问题：{question}\n知识库上下文：\n{context}\n"
            "要求：1. 只依据上下文回答，不要编造；2. 上下文不足时明确说明并引导联系人工；"
            "3. 回答简洁（200 字以内）。"
        ),
        variables=["question", "context"],
        output_schema={"type": "string"},
    ),
    PromptTemplate(
        prompt_id="query_rewrite",
        version="1.0.0",
        template=(
            "对话历史：\n{history}\n当前问题：{message}\n"
            "请把当前问题改写为可独立检索的查询，只输出改写后的查询文本。"
        ),
        variables=["history", "message"],
        output_schema={"type": "string"},
    ),
]


class PromptRegistry:
    def __init__(self, repository: ContentRepository | None = None) -> None:
        self._templates: dict[str, list[PromptTemplate]] = {}
        for tpl in DEFAULT_PROMPTS:
            self._templates.setdefault(tpl.prompt_id, []).append(tpl)
        if repository is not None:
            self._load_from_db(repository)

    def _load_from_db(self, repository: ContentRepository) -> None:
        records = repository.list_prompt_templates()
        if not records:
            repository.save_prompt_templates(DEFAULT_PROMPTS)
            return
        for record in records:
            self._templates.setdefault(record.prompt_id, []).append(
                PromptTemplate(
                    prompt_id=record.prompt_id,
                    version=record.version,
                    template=record.template,
                    variables=record.variables_json,
                    output_schema=record.output_schema_json,
                    is_active=record.is_active,
                    weight=record.weight,
                )
            )

    def get_active(self, prompt_id: str, seed: float | None = None) -> PromptTemplate:
        """按权重返回 active 模板；同 id 多版本 active 即 A/B 测试。"""
        candidates = [t for t in self._templates.get(prompt_id, []) if t.is_active]
        if not candidates:
            raise KeyError(f"prompt_id 不存在或未启用: {prompt_id}")
        if len(candidates) == 1 or seed is None:
            return candidates[0]
        total = sum(t.weight for t in candidates)
        pos = seed * total
        for tpl in candidates:
            pos -= tpl.weight
            if pos <= 0:
                return tpl
        return candidates[-1]

    def render(self, prompt_id: str, variables: dict, seed: float | None = None) -> str:
        tpl = self.get_active(prompt_id, seed)
        return _safe_format(tpl.template, variables)


def _safe_format(template: str, variables: dict) -> str:
    """容错渲染：缺失变量保留占位符，避免 KeyError。"""
    formatter = string.Formatter()

    def replace(match: re.Match) -> str:
        key = match.group(1)
        return str(variables.get(key, match.group(0)))

    return re.sub(r"\{(\w+)\}", replace, template)
