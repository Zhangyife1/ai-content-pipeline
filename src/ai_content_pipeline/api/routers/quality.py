from __future__ import annotations

from pydantic import BaseModel, Field
from fastapi import APIRouter, Depends

from ai_content_pipeline.api.deps import get_services
from ai_content_pipeline.models import QualityReport
from ai_content_pipeline.services import Services

router = APIRouter(prefix="/api/v1/quality", tags=["内容质检"])


class QualityRequest(BaseModel):
    content_id: str = Field(..., min_length=1)
    title: str = Field(..., min_length=1)
    body: str = Field(..., min_length=1)
    platform: str = "公众号"
    check_levels: list[str] = Field(default_factory=lambda: ["duplicate", "fact", "format"])


@router.post("/check", response_model=QualityReport, summary="三层质检")
def check(req: QualityRequest, services: Services = Depends(get_services)) -> QualityReport:
    return services.quality_checker.check(content_id=req.content_id, title=req.title, body=req.body, platform=req.platform)

