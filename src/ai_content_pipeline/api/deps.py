"""FastAPI 依赖注入。"""

from __future__ import annotations

from functools import lru_cache

from ai_content_pipeline.services import Services, build_services


@lru_cache
def get_services() -> Services:
    return build_services()

