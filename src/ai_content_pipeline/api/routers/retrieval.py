from __future__ import annotations

from pydantic import BaseModel, Field
from fastapi import APIRouter, Depends

from ai_content_pipeline.api.deps import get_services
from ai_content_pipeline.models import RetrievalResult
from ai_content_pipeline.services import Services

router = APIRouter(prefix="/api/v1/kb", tags=["知识库检索"])


class RetrievalRequest(BaseModel):
    query: str = Field(..., min_length=1)
    top_k: int = Field(5, ge=1, le=50)
    threshold: float | None = Field(None, ge=0.0, le=1.0)


@router.post("/retrieval", response_model=list[RetrievalResult], summary="混合检索（向量 + BM25）")
def retrieve(req: RetrievalRequest, services: Services = Depends(get_services)) -> list[RetrievalResult]:
    return services.hybrid_retriever.search(req.query, top_k=req.top_k, threshold=req.threshold)

