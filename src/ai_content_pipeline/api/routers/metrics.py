from __future__ import annotations

from fastapi import APIRouter

from ai_content_pipeline.observability.metrics import get_metrics

router = APIRouter(prefix="/api/v1/metrics", tags=["运维指标"])


@router.get("", summary="进程内运行指标")
def metrics() -> dict:
    return get_metrics().snapshot()

