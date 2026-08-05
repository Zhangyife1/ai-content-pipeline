"""仓储层：屏蔽 ORM 细节，向业务层提供明确的读写接口。"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Iterable, Sequence

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from ai_content_pipeline.models import (
    DocumentChunk,
    GeneratedArticle,
    PromptTemplate,
    PublishTask,
    SourceDocument,
)
from ai_content_pipeline.storage.database import (
    ChunkRecord,
    ContentRecord,
    DocumentRecord,
    PromptTemplateRecord,
    PublishLogRecord,
    get_session_factory,
)


class ContentRepository:
    """聚合文档、chunk、生成内容、发布日志与 Prompt 模板的读写。"""

    def __init__(self, database_url: str | None = None) -> None:
        self._session_factory = get_session_factory(database_url)

    def _session(self) -> Session:
        return self._session_factory()

    # ---- 文档与 chunk ----
    def upsert_document(self, doc: SourceDocument) -> None:
        with self._session() as session:
            record = session.get(DocumentRecord, doc.doc_id)
            if record is None:
                record = DocumentRecord(
                    doc_id=doc.doc_id,
                    title=doc.title,
                    source_type=doc.source_type.value,
                    url=doc.url,
                    metadata_json=doc.metadata,
                    updated_at=doc.updated_at,
                )
                session.add(record)
            else:
                record.title = doc.title
                record.source_type = doc.source_type.value
                record.url = doc.url
                record.metadata_json = doc.metadata
                record.updated_at = doc.updated_at
            session.commit()

    def get_chunks_by_doc(self, doc_id: str) -> list[ChunkRecord]:
        with self._session() as session:
            rows = session.scalars(
                select(ChunkRecord)
                .where(ChunkRecord.doc_id == doc_id)
                .order_by(ChunkRecord.chunk_index)
            ).all()
            return list(rows)

    def upsert_chunks(self, chunks: Iterable[DocumentChunk]) -> None:
        now = datetime.now(timezone.utc)
        with self._session() as session:
            for chunk in chunks:
                record = session.get(ChunkRecord, chunk.chunk_id)
                if record is None:
                    session.add(
                        ChunkRecord(
                            chunk_id=chunk.chunk_id,
                            doc_id=chunk.doc_id,
                            chunk_index=chunk.chunk_index,
                            content=chunk.content,
                            content_hash=chunk.content_hash,
                            is_active=True,
                            valid_from=now,
                            metadata_json=chunk.metadata,
                        )
                    )
                else:
                    record.content = chunk.content
                    record.content_hash = chunk.content_hash
                    record.is_active = True
                    record.valid_to = None
                    record.metadata_json = chunk.metadata
            session.commit()

    def deactivate_chunks(self, chunk_ids: Sequence[str]) -> None:
        if not chunk_ids:
            return
        now = datetime.now(timezone.utc)
        with self._session() as session:
            session.execute(
                update(ChunkRecord)
                .where(ChunkRecord.chunk_id.in_(list(chunk_ids)))
                .values(is_active=False, valid_to=now)
            )
            session.commit()

    def search_active_chunks(self, limit: int = 200) -> list[ChunkRecord]:
        with self._session() as session:
            rows = session.scalars(select(ChunkRecord).where(ChunkRecord.is_active).limit(limit)).all()
            return list(rows)

    def get_document(self, doc_id: str) -> DocumentRecord | None:
        with self._session() as session:
            return session.get(DocumentRecord, doc_id)

    # ---- 生成内容 ----
    def save_content(self, article: GeneratedArticle) -> None:
        with self._session() as session:
            record = session.get(ContentRecord, article.content_id)
            if record is None:
                session.add(
                    ContentRecord(
                        content_id=article.content_id,
                        content_type=article.content_type.value,
                        title=article.title,
                        body=article.body,
                        summary=article.summary,
                        status=article.status,
                        prompt_version=article.prompt_version,
                    )
                )
            else:
                record.title = article.title
                record.body = article.body
                record.summary = article.summary
                record.status = article.status
                record.prompt_version = article.prompt_version
            session.commit()

    def get_content(self, content_id: str) -> ContentRecord | None:
        with self._session() as session:
            return session.get(ContentRecord, content_id)

    # ---- 发布日志 ----
    def save_publish_log(self, task: PublishTask) -> None:
        with self._session() as session:
            session.add(
                PublishLogRecord(
                    log_id=uuid.uuid4().hex[:16],
                    task_id=task.task_id,
                    content_id=task.content_id,
                    platform=task.platform,
                    status=task.status.value,
                    retries=task.retries,
                    last_error=task.last_error,
                    result_json=task.result,
                )
            )
            session.commit()

    # ---- Prompt 模板 ----
    def list_prompt_templates(self) -> list[PromptTemplateRecord]:
        with self._session() as session:
            return list(session.scalars(select(PromptTemplateRecord).order_by(PromptTemplateRecord.prompt_id)).all())

    def save_prompt_templates(self, templates: Iterable[PromptTemplate]) -> None:
        with self._session() as session:
            for tpl in templates:
                session.add(
                    PromptTemplateRecord(
                        prompt_id=tpl.prompt_id,
                        version=tpl.version,
                        template=tpl.template,
                        variables_json=tpl.variables,
                        output_schema_json=tpl.output_schema,
                        is_active=tpl.is_active,
                        weight=tpl.weight,
                    )
                )
            session.commit()

