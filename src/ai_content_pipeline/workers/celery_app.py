"""Celery 入口（可选依赖）。未安装 celery 时仅导出空占位，不影响核心功能。"""

from __future__ import annotations

try:
    from celery import Celery
except ImportError:  # pragma: no cover
    Celery = None  # type: ignore

from ai_content_pipeline.config import get_settings


def create_celery_app() -> "Celery | None":
    if Celery is None:
        return None
    settings = get_settings()
    app = Celery(
        "content_pipeline",
        broker=settings.redis_url,
        backend=settings.redis_url,
        include=["ai_content_pipeline.workers.tasks"],
    )
    app.conf.task_serializer = "json"
    app.conf.result_serializer = "json"
    app.conf.accept_content = ["json"]
    app.conf.task_default_queue = "content_pipeline"
    app.conf.task_acks_late = True
    app.conf.worker_prefetch_multiplier = 1
    return app


celery_app = create_celery_app()

