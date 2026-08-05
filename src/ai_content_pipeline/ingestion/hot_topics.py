"""热点抓取与多源内容聚合：RSS + Mock 源，统一为 HotTopic 后进入生成管线。"""

from __future__ import annotations

import hashlib
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Protocol

import httpx


@dataclass
class HotTopic:
    title: str
    source: str
    url: str
    summary: str = ""
    published_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    score: float = 1.0

    @property
    def topic_id(self) -> str:
        return hashlib.blake2b(f"{self.source}:{self.title}".encode("utf-8"), digest_size=8).hexdigest()


class HotTopicSource(Protocol):
    name: str

    def fetch(self, limit: int = 10) -> list[HotTopic]: ...


class MockHotTopicSource:
    """本地演示用热点源：可复现，无网络依赖。"""

    name = "mock"

    SEED = [
        HotTopic(
            title="AI 客服机器人如何提升官网转化率",
            source="mock",
            url="https://example.com/ai-support-conversion",
            summary="大模型驱动的智能客服将 FAQ 响应时间从分钟级降到秒级，并可直接承接订单查询。",
            score=98,
        ),
        HotTopic(
            title="RAG 知识库在企业内容生产中的落地实践",
            source="mock",
            url="https://example.com/rag-content-pipeline",
            summary="知识库投喂、增量更新与混合检索是内容自动化系统的地基。",
            score=95,
        ),
        HotTopic(
            title="企业官网 SEO：结构化数据与 Sitemap 的最佳实践",
            source="mock",
            url="https://example.com/geo-seo-best-practices",
            summary="Schema.org 标记帮助搜索引擎理解页面语义，配合自动 Sitemap 提升收录效率。",
            score=92,
        ),
        HotTopic(
            title="Function Calling 让聊天机器人真正能办事",
            source="mock",
            url="https://example.com/function-calling-agents",
            summary="从问答到查询再到下单，工具调用把对话系统从聊天升级为业务入口。",
            score=90,
        ),
    ]

    def fetch(self, limit: int = 10) -> list[HotTopic]:
        return self.SEED[:limit]


class RSSHotTopicSource:
    """RSS 热点源：标准库解析 XML，生产可替换为官方 API。"""

    name = "rss"

    def __init__(self, feed_url: str, timeout: float = 15.0) -> None:
        self.feed_url = feed_url
        self.timeout = timeout

    def fetch(self, limit: int = 10) -> list[HotTopic]:
        try:
            resp = httpx.get(self.feed_url, timeout=self.timeout, follow_redirects=True)
            resp.raise_for_status()
            root = ET.fromstring(resp.content)
        except Exception:  # 网络失败不阻塞主流程
            return []
        items = []
        for item in root.iter("item"):
            title = (item.findtext("title") or "").strip()
            link = (item.findtext("link") or "").strip()
            description = (item.findtext("description") or "").strip()
            if not title:
                continue
            items.append(
                HotTopic(
                    title=title[:120],
                    source=self.name,
                    url=link or f"https://example.com/rss/{hashlib.blake2b(title.encode(), digest_size=8).hexdigest()}",
                    summary=description[:300],
                )
            )
            if len(items) >= limit:
                break
        return items


class HotTopicAggregator:
    """多源聚合：拉取全部源 -> 按标题去重 -> 按热度分排序。"""

    def __init__(self, sources: list[HotTopicSource] | None = None) -> None:
        self.sources = sources or [MockHotTopicSource()]

    def fetch(self, limit: int = 10) -> list[HotTopic]:
        merged: dict[str, HotTopic] = {}
        for source in self.sources:
            for topic in source.fetch(limit=limit * 2):
                key = hashlib.blake2b(topic.title.encode("utf-8"), digest_size=8).hexdigest()
                if key in merged:
                    # 同题多源：保留分数更高者，并记录多源标识
                    existing = merged[key]
                    if topic.score > existing.score:
                        merged[key] = topic
                else:
                    merged[key] = topic
        ranked = sorted(merged.values(), key=lambda t: t.score, reverse=True)
        return ranked[:limit]

