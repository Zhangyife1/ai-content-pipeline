from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from ai_content_pipeline.api.deps import get_services
from ai_content_pipeline.models import GeneratedArticle, PublishTask
from ai_content_pipeline.services import Services

router = APIRouter(prefix="/api/v1/publish", tags=["内容分发"])


class PublishRequest(BaseModel):
    content_id: str = Field(..., min_length=1)
    platform: str = Field(..., min_length=1)
    publish_at: datetime | None = None


@router.post("/tasks", response_model=PublishTask, summary="创建发布任务（定时/立即）")
def create_task(req: PublishRequest, services: Services = Depends(get_services)) -> PublishTask:
    record = services.repository.get_content(req.content_id)
    if record is None:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail=f"内容不存在: {req.content_id}")
    content = GeneratedArticle(
        content_id=record.content_id,
        content_type=record.content_type,
        title=record.title,
        body=record.body,
        summary=record.summary,
        status=record.status,
    )
    return services.publisher.schedule(content, req.platform, req.publish_at)


@router.post("/process", response_model=list[PublishTask], summary="处理所有到期的发布任务")
async def process_due(services: Services = Depends(get_services)) -> list[PublishTask]:
    def load(content_id: str):
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

    return await services.publisher.process_due(load)

