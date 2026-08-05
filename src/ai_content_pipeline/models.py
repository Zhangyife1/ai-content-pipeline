"""核心领域模型（Pydantic v2）。API 契约与内部结构共用这一套 Schema。"""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


def content_hash(text: str) -> str:
    """BLAKE2b 内容指纹，用于增量更新比对。"""
    return hashlib.blake2b(text.encode("utf-8"), digest_size=16).hexdigest()


class SourceType(str, Enum):
    DOC = "doc"
    WEB = "web"
    PDF = "pdf"
    FAQ = "faq"
    REPORT = "report"
    OTHER = "other"


class SourceDocument(BaseModel):
    """统一的标准文档对象：所有数据源 Connector 都输出该格式。"""

    doc_id: str = Field(default_factory=lambda: _new_id("doc"))
    title: str
    content: str = ""
    source_type: SourceType = SourceType.DOC
    url: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    updated_at: datetime = Field(default_factory=_now)


class DocumentChunk(BaseModel):
    chunk_id: str = Field(default_factory=lambda: _new_id("chunk"))
    doc_id: str
    chunk_index: int
    content: str
    content_hash: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class RetrievalResult(BaseModel):
    doc_id: str
    chunk_id: str
    chunk_index: int
    content: str
    score: float
    source_url: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class OutlineSection(BaseModel):
    title: str = Field(..., min_length=5, max_length=60)
    key_points: list[str] = Field(..., min_length=1)
    word_count: int = Field(..., ge=100, le=2000)
    source_refs: list[str] = Field(default_factory=list)


class ArticleOutline(BaseModel):
    """大纲输出 Schema：LLM 输出必须符合该结构，否则触发重试。"""

    title: str = Field(..., min_length=10, max_length=80)
    sections: list[OutlineSection] = Field(..., min_length=3, max_length=12)
    total_word_count: int = Field(..., ge=500, le=10000)


class SeoMeta(BaseModel):
    title_tag: str
    meta_description: str
    keywords: list[str] = Field(default_factory=list)
    url_slug: str


class ContentType(str, Enum):
    ARTICLE = "article"
    SUMMARY = "summary"
    FAQ = "faq"
    SEO = "seo"


class GeneratedArticle(BaseModel):
    content_id: str = Field(default_factory=lambda: _new_id("content"))
    content_type: ContentType = ContentType.ARTICLE
    title: str
    body: str
    summary: str = ""
    faq_pairs: list[dict[str, str]] = Field(default_factory=list)
    seo: SeoMeta | None = None
    prompt_version: str = ""
    status: str = "draft"
    created_at: datetime = Field(default_factory=_now)


class QualityLevel(str, Enum):
    PASS = "pass"
    WARN = "warn"
    FAIL = "fail"


class QualityIssue(BaseModel):
    level: QualityLevel
    code: str
    message: str
    detail: dict[str, Any] = Field(default_factory=dict)


class QualityReport(BaseModel):
    content_id: str
    passed: bool
    scores: dict[str, float] = Field(default_factory=dict)
    issues: list[QualityIssue] = Field(default_factory=list)
    checked_at: datetime = Field(default_factory=_now)


class PublishStatus(str, Enum):
    PENDING = "pending"
    QUEUED = "queued"
    PUBLISHING = "publishing"
    PUBLISHED = "published"
    FAILED = "failed"
    FAILED_PERMANENT = "failed_permanent"


class PublishTask(BaseModel):
    task_id: str = Field(default_factory=lambda: _new_id("pub"))
    content_id: str
    platform: str
    publish_at: datetime = Field(default_factory=_now)
    status: PublishStatus = PublishStatus.PENDING
    retries: int = 0
    last_error: str | None = None
    result: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=_now)


class PromptTemplate(BaseModel):
    prompt_id: str
    version: str = "1.0.0"
    template: str
    variables: list[str] = Field(default_factory=list)
    output_schema: dict[str, Any] = Field(default_factory=dict)
    is_active: bool = True
    weight: float = 1.0


class IngestionStats(BaseModel):
    doc_id: str
    added_chunks: int = 0
    updated_chunks: int = 0
    unchanged_chunks: int = 0
    removed_chunks: int = 0
    total_chunks: int = 0
