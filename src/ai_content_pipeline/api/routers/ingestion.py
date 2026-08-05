from __future__ import annotations

from fastapi import APIRouter, Depends

from ai_content_pipeline.api.deps import get_services
from ai_content_pipeline.models import IngestionStats, SourceDocument
from ai_content_pipeline.services import Services

router = APIRouter(prefix="/api/v1/kb", tags=["知识库投喂"])


@router.post("/ingest", response_model=IngestionStats, summary="接入一个数据源并增量投喂")
def ingest(source: SourceDocument, services: Services = Depends(get_services)) -> IngestionStats:
    stats = services.ingestion_pipeline.ingest(source)
    services.sync_retrieval_corpus()
    return stats

