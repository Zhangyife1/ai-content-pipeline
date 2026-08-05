"""发布引擎：状态机 + 重试策略 + 发布日志。

状态机：pending -> queued -> publishing -> published
                            -> failed -> retry(max 3) -> failed_permanent
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from ai_content_pipeline.distribution.adapters import AdapterRegistry, PublishError
from ai_content_pipeline.distribution.scheduler import PublishScheduler
from ai_content_pipeline.models import GeneratedArticle, PublishStatus, PublishTask
from ai_content_pipeline.storage.repositories import ContentRepository

logger = logging.getLogger(__name__)


class Publisher:
    def __init__(
        self,
        adapters: AdapterRegistry,
        scheduler: PublishScheduler,
        repository: ContentRepository,
        max_retries: int = 3,
    ) -> None:
        self.adapters = adapters
        self.scheduler = scheduler
        self.repository = repository
        self.max_retries = max_retries

    def schedule(self, content: GeneratedArticle, platform: str, publish_at: datetime | None = None) -> PublishTask:
        if platform not in self.adapters.platforms():
            raise KeyError(f"不支持的平台: {platform}")
        task = PublishTask(
            content_id=content.content_id,
            platform=platform,
            publish_at=publish_at or datetime.now(timezone.utc) + timedelta(minutes=1),
            status=PublishStatus.QUEUED,
        )
        self.scheduler.schedule(task)
        self.repository.save_publish_log(task)
        logger.info("发布任务已入队 task_id=%s platform=%s", task.task_id, platform)
        return task

    async def process_due(self, content_by_id) -> list[PublishTask]:
        """处理所有到期任务；返回处理后的任务列表。"""
        tasks = self.scheduler.poll_due()
        results: list[PublishTask] = []
        for task in tasks:
            content = content_by_id(task.content_id)
            if content is None:
                task.status = PublishStatus.FAILED_PERMANENT
                task.last_error = "内容不存在"
                self.repository.save_publish_log(task)
                self.scheduler.ack(task.task_id)
                results.append(task)
                continue
            results.append(await self._execute(task, content))
        return results

    async def _execute(self, task: PublishTask, content: GeneratedArticle) -> PublishTask:
        task.status = PublishStatus.PUBLISHING
        try:
            adapter = self.adapters.get(task.platform)
            result = await adapter.publish(
                {
                    "title": content.title,
                    "body": content.body,
                    "summary": content.summary,
                    "seo": content.seo.model_dump() if content.seo else None,
                    "content_id": content.content_id,
                }
            )
            task.status = PublishStatus.PUBLISHED
            task.result = result
        except PublishError as exc:
            await self._handle_failure(task, exc)
        except Exception as exc:  # 网络/平台异常统一走重试
            await self._handle_failure(task, PublishError(str(exc), "network"))
        self.repository.save_publish_log(task)
        self.scheduler.ack(task.task_id)
        if task.status == PublishStatus.FAILED:
            # 指数退避后重新入队
            self.scheduler.schedule(task)
        return task

    async def _handle_failure(self, task: PublishTask, exc: PublishError) -> None:
        task.retries += 1
        task.last_error = str(exc)
        if task.retries >= self.max_retries:
            task.status = PublishStatus.FAILED_PERMANENT
            logger.error("发布任务永久失败 task_id=%s error=%s", task.task_id, exc)
            return
        # 指数退避重试：1s, 2s, 4s（生产环境可继续留在延时队列）
        delay = 2 ** (task.retries - 1)
        task.status = PublishStatus.FAILED
        task.publish_at = datetime.now(timezone.utc) + timedelta(seconds=delay)
        logger.warning("发布失败，%.0fs 后重试 task_id=%s error=%s", delay, task.task_id, exc)


async def run_publisher_once(publisher: Publisher, content_by_id, max_tasks: int = 100) -> list[PublishTask]:
    return await publisher.process_due(content_by_id)
