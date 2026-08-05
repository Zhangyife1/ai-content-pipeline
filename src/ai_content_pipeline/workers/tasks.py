"""可复用的任务函数：生成 / 质检 / 发布，供 Celery 或独立循环调用。"""

from __future__ import annotations

import logging

from ai_content_pipeline.models import GeneratedArticle
from ai_content_pipeline.services import build_services

logger = logging.getLogger(__name__)


def generate_article_task(payload: dict) -> dict:
    """同步执行文章生成链。生产环境建议放到线程池/异步 worker。"""
    services = build_services()
    article = services.content_chain.run_article(
        topic=payload["topic"],
        platform=payload.get("platform", "公众号"),
        style=payload.get("style", "专业"),
        word_count=payload.get("word_count", 2000),
    )
    services.repository.save_content(article)
    logger.info("生成任务完成 content_id=%s", article.content_id)
    return article.model_dump(mode="json")


def quality_check_task(content_id: str) -> dict:
    services = build_services()
    record = services.repository.get_content(content_id)
    if record is None:
        raise ValueError(f"内容不存在: {content_id}")
    report = services.quality_checker.check(
        content_id=content_id,
        title=record.title,
        body=record.body,
    )
    if report.passed:
        record.status = "review"
        services.repository.save_content(
            GeneratedArticle(
                content_id=record.content_id,
                content_type=record.content_type,
                title=record.title,
                body=record.body,
                summary=record.summary,
                status="review",
            )
        )
    return report.model_dump(mode="json")


def publish_task(content_id: str, platform: str, publish_at_iso: str | None = None) -> dict:
    services = build_services()
    record = services.repository.get_content(content_id)
    if record is None:
        raise ValueError(f"内容不存在: {content_id}")
    article = GeneratedArticle(
        content_id=record.content_id,
        content_type=record.content_type,
        title=record.title,
        body=record.body,
        summary=record.summary,
        status=record.status,
    )
    from datetime import datetime

    publish_at = datetime.fromisoformat(publish_at_iso) if publish_at_iso else None
    return services.publisher.schedule(article, platform, publish_at).model_dump(mode="json")

