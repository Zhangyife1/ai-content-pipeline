from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse, Response

from ai_content_pipeline.api.deps import get_services
from ai_content_pipeline.models import GeneratedArticle
from ai_content_pipeline.seo.sitemap import SitemapEntry, build_sitemap
from ai_content_pipeline.seo.structured_data import article_json_ld, faq_json_ld
from ai_content_pipeline.services import Services

router = APIRouter(prefix="/api/v1/seo", tags=["SEO / GEO"])


@router.get("/sitemap.xml", summary="自动生成 sitemap.xml")
def sitemap(services: Services = Depends(get_services)) -> Response:
    records = services.repository.list_contents_by_status("published")
    entries = [
        SitemapEntry(
            loc=f"/content/{r.content_id}",
            lastmod=r.created_at,
            priority=0.9 if r.content_type == "article" else 0.7,
        )
        for r in records
    ]
    entries.append(SitemapEntry(loc="/", priority=1.0))
    return Response(content=build_sitemap(entries), media_type="application/xml")


@router.get("/structured/{content_id}", summary="Schema.org JSON-LD 结构化数据")
def structured(content_id: str, services: Services = Depends(get_services)) -> JSONResponse:
    record = services.repository.get_content(content_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"内容不存在: {content_id}")
    article = GeneratedArticle(
        content_id=record.content_id,
        content_type=record.content_type,
        title=record.title,
        body=record.body,
        summary=record.summary,
        status=record.status,
    )
    data = article_json_ld(article)
    if record.content_type == "faq":
        data = faq_json_ld([{"question": record.title, "answer": record.summary or record.body[:300]}])
    return JSONResponse(content=data, media_type="application/ld+json")

