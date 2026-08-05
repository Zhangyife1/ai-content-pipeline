"""独立调度循环：轮询延时队列并执行到期发布任务。"""

from __future__ import annotations

import asyncio
import logging
import time

from ai_content_pipeline.models import GeneratedArticle
from ai_content_pipeline.services import build_services

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("publish-scheduler")


def load_content(services, content_id: str) -> GeneratedArticle | None:
    record = services.repository.get_content(content_id)
    if record is None:
        return None
    return GeneratedArticle(
        content_id=record.content_id,
        content_type=record.content_type,
        title=record.title,
        body=record.body,
        summary=record.summary,
        status=record.status,
    )


async def loop_once(services, interval: float = 1.0) -> int:
    tasks = await services.publisher.process_due(lambda cid: load_content(services, cid))
    for task in tasks:
        logger.info("task=%s status=%s result=%s", task.task_id, task.status.value, task.result)
    return len(tasks)


async def run_forever(interval: float = 1.0) -> None:
    services = build_services()
    logger.info("发布调度循环启动，轮询间隔 %.1fs", interval)
    while True:
        try:
            processed = await loop_once(services, interval)
            if processed:
                logger.info("本轮回处理 %d 个任务", processed)
        except Exception:
            logger.exception("调度循环异常，继续运行")
        await asyncio.sleep(interval)


def main() -> None:
    try:
        asyncio.run(run_forever())
    except KeyboardInterrupt:
        logger.info("调度循环已停止")


if __name__ == "__main__":
    main()

