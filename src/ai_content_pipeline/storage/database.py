"""SQLAlchemy 2.0 数据模型。

设计要点：
- chunk 表采用 is_active + valid_from/valid_to 时序模式，不做物理删除；
- 向量库只存 doc_id + embedding + chunk_index，全文/元数据/版本历史放在关系库；
- 发布日志独立成表，用于效果归因与失败追踪。
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker


class Base(DeclarativeBase):
    pass


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class DocumentRecord(Base):
    __tablename__ = "documents"

    doc_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    title: Mapped[str] = mapped_column(String(512))
    source_type: Mapped[str] = mapped_column(String(32), index=True)
    url: Mapped[str | None] = mapped_column(String(1024))
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ChunkRecord(Base):
    __tablename__ = "chunks"
    __table_args__ = (
        Index("ix_chunks_doc_index", "doc_id", "chunk_index"),
        Index("ix_chunks_hash", "content_hash"),
    )

    chunk_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    doc_id: Mapped[str] = mapped_column(String(64), ForeignKey("documents.doc_id"))
    chunk_index: Mapped[int] = mapped_column(Integer)
    content: Mapped[str] = mapped_column(Text)
    content_hash: Mapped[str] = mapped_column(String(64))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)


class ContentRecord(Base):
    __tablename__ = "contents"

    content_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    content_type: Mapped[str] = mapped_column(String(32))
    title: Mapped[str] = mapped_column(String(512))
    body: Mapped[str] = mapped_column(Text)
    summary: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(32), default="draft", index=True)
    prompt_version: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class PublishLogRecord(Base):
    __tablename__ = "publish_log"

    log_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    task_id: Mapped[str] = mapped_column(String(64), index=True)
    content_id: Mapped[str] = mapped_column(String(64), index=True)
    platform: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(32), index=True)
    retries: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    result_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class PromptTemplateRecord(Base):
    __tablename__ = "prompt_templates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    prompt_id: Mapped[str] = mapped_column(String(64), index=True)
    version: Mapped[str] = mapped_column(String(32))
    template: Mapped[str] = mapped_column(Text)
    variables_json: Mapped[list] = mapped_column(JSON, default=list)
    output_schema_json: Mapped[dict] = mapped_column(JSON, default=dict)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    weight: Mapped[float] = mapped_column(Float, default=1.0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


_engines: dict[str, object] = {}
_SessionLocals: dict[str, object] = {}


def get_engine(database_url: str | None = None):
    url = database_url or "sqlite:///./data/pipeline.db"
    if url not in _engines:
        kwargs = {"connect_args": {"check_same_thread": False}} if url.startswith("sqlite") else {}
        _engines[url] = create_engine(url, future=True, **kwargs)
    return _engines[url]


def get_session_factory(database_url: str | None = None):
    url = database_url or "sqlite:///./data/pipeline.db"
    if url not in _SessionLocals:
        _SessionLocals[url] = sessionmaker(bind=get_engine(url), expire_on_commit=False, future=True)
    return _SessionLocals[url]


def init_db(database_url: str | None = None) -> None:
    """建表。生产环境建议用 Alembic 管理迁移，demo 阶段 create_all 足够。"""
    Base.metadata.create_all(bind=get_engine(database_url))
