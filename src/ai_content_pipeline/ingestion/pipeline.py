"""投喂管线：拉取 -> 清洗 -> 分块 -> 向量化 -> 双轨写入，支持增量更新。"""

from __future__ import annotations

import logging

from ai_content_pipeline.ingestion.chunker import split_document
from ai_content_pipeline.ingestion.connectors import ConnectorRegistry, default_registry
from ai_content_pipeline.ingestion.vector_store import VectorStore
from ai_content_pipeline.models import DocumentChunk, IngestionStats, SourceDocument
from ai_content_pipeline.storage.repositories import ContentRepository

logger = logging.getLogger(__name__)


class IngestionPipeline:
    def __init__(
        self,
        embedder,
        vector_store: VectorStore,
        repository: ContentRepository,
        connectors: ConnectorRegistry | None = None,
        chunk_size: int = 512,
        chunk_overlap: int = 128,
        heading_aware: bool = True,
    ) -> None:
        self.embedder = embedder
        self.vector_store = vector_store
        self.repository = repository
        self.connectors = connectors or default_registry()
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.heading_aware = heading_aware

    def ingest(self, source: SourceDocument) -> IngestionStats:
        """增量投喂：按 content_hash 计算新增/变更/删除。"""
        doc = self.connectors.get(source.source_type).fetch(source)
        self.repository.upsert_document(doc)

        existing = self.repository.get_chunks_by_doc(doc.doc_id)
        existing_by_index = {row.chunk_index: row for row in existing}
        new_chunks = split_document(
            doc,
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap,
            heading_aware=self.heading_aware,
        )

        to_add: list[DocumentChunk] = []
        added = updated = unchanged = 0
        for chunk in new_chunks:
            old = existing_by_index.get(chunk.chunk_index)
            if old is None:
                added += 1
                to_add.append(chunk)
            elif old.content_hash != chunk.content_hash:
                updated += 1
                to_add.append(chunk)
            else:
                unchanged += 1

        new_ids = {chunk.chunk_index for chunk in new_chunks}
        removed_ids = [
            row.chunk_id for idx, row in existing_by_index.items() if idx not in new_ids and row.is_active
        ]
        removed = len(removed_ids)

        # 增量策略：无变化直接跳过；有增删改时，删除该 doc 的旧向量后整体重建，
        # 保证索引与关系库一致（生产可优化为按 chunk 精确更新）。
        has_change = added > 0 or updated > 0 or removed > 0
        if has_change:
            self.vector_store.delete_by_doc_ids([doc.doc_id])
            embeddings = self.embedder.embed_texts([chunk.content for chunk in new_chunks])
            self.vector_store.add(new_chunks, embeddings)
        if removed_ids:
            self.repository.deactivate_chunks(removed_ids)

        self.repository.upsert_chunks(to_add)
        logger.info(
            "投喂完成 doc=%s added=%d updated=%d unchanged=%d removed=%d",
            doc.doc_id,
            added,
            updated,
            unchanged,
            removed,
        )
        return IngestionStats(
            doc_id=doc.doc_id,
            added_chunks=added,
            updated_chunks=updated,
            unchanged_chunks=unchanged,
            removed_chunks=removed,
            total_chunks=len(new_chunks),
        )

    def reindex_all(self) -> int:
        """低峰期物理重建索引：从关系库全量重灌向量库。"""
        chunks = self.repository.search_active_chunks(limit=100_000)
        if not chunks:
            return 0
        docs = [
            DocumentChunk(
                chunk_id=row.chunk_id,
                doc_id=row.doc_id,
                chunk_index=row.chunk_index,
                content=row.content,
                content_hash=row.content_hash,
                metadata=row.metadata_json,
            )
            for row in chunks
        ]
        embeddings = self.embedder.embed_texts([c.content for c in docs])
        self.vector_store.add(docs, embeddings)
        return len(docs)
