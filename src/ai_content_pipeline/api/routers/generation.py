from __future__ import annotations

from pydantic import BaseModel, Field
from fastapi import APIRouter, Depends

from ai_content_pipeline.api.deps import get_services
from ai_content_pipeline.models import GeneratedArticle
from ai_content_pipeline.services import Services

router = APIRouter(prefix="/api/v1/generation", tags=["内容生成"])


class GenerationRequest(BaseModel):
    topic: str = Field(..., min_length=2, max_length=100)
    platform: str = "公众号"
    style: str = "专业"
    word_count: int = Field(2000, ge=500, le=10000)
    audience: str = "目标用户"


@router.post("/articles", response_model=GeneratedArticle, summary="生成一篇完整文章（含摘要/FAQ/SEO）")
def generate_article(req: GenerationRequest, services: Services = Depends(get_services)) -> GeneratedArticle:
    article = services.content_chain.run_article(
        topic=req.topic,
        platform=req.platform,
        style=req.style,
        word_count=req.word_count,
        audience=req.audience,
    )
    services.repository.save_content(article)
    return article

