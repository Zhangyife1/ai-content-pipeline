from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from ai_content_pipeline.api.deps import get_services
from ai_content_pipeline.models import ReviewStatus
from ai_content_pipeline.services import Services

router = APIRouter(prefix="/api/v1/review", tags=["人工审核"])


@router.get("/pending", summary="待审核内容列表")
def pending_review(services: Services = Depends(get_services)) -> list[dict]:
    records = services.repository.list_contents_by_status(ReviewStatus.PENDING_REVIEW.value)
    return [
        {
            "content_id": r.content_id,
            "title": r.title,
            "content_type": r.content_type,
            "created_at": r.created_at.isoformat(),
            "body_preview": r.body[:200],
        }
        for r in records
    ]


@router.post("/{content_id}/approve", summary="审核通过（进入发布流程）")
def approve(content_id: str, services: Services = Depends(get_services)) -> dict:
    if not services.repository.update_content_status(content_id, ReviewStatus.APPROVED.value):
        raise HTTPException(status_code=404, detail=f"内容不存在: {content_id}")
    return {"content_id": content_id, "status": ReviewStatus.APPROVED.value}


@router.post("/{content_id}/reject", summary="审核驳回")
def reject(content_id: str, services: Services = Depends(get_services)) -> dict:
    if not services.repository.update_content_status(content_id, ReviewStatus.REJECTED.value):
        raise HTTPException(status_code=404, detail=f"内容不存在: {content_id}")
    return {"content_id": content_id, "status": ReviewStatus.REJECTED.value}

