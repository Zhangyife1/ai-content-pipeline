import tempfile
import unittest
from pathlib import Path

from ai_content_pipeline.ingestion.embeddings import DeterministicEmbedder
from ai_content_pipeline.ingestion.connectors import ConnectorRegistry, FileConnector
from ai_content_pipeline.ingestion.pipeline import IngestionPipeline
from ai_content_pipeline.ingestion.vector_store import NumpyVectorStore
from ai_content_pipeline.models import SourceDocument, SourceType
from ai_content_pipeline.storage.database import init_db
from ai_content_pipeline.storage.repositories import ContentRepository


class IngestionPipelineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_url = f"sqlite:///{Path(self.tmp.name) / 'test.db'}"
        init_db(self.db_url)
        self.repo = ContentRepository(self.db_url)
        self.store = NumpyVectorStore()
        self.embedder = DeterministicEmbedder(dim=128)
        self.pipeline = IngestionPipeline(
            embedder=self.embedder,
            vector_store=self.store,
            repository=self.repo,
            chunk_size=100,
            chunk_overlap=20,
        )
        registry = ConnectorRegistry()
        registry.register(SourceType.DOC, FileConnector(self.tmp.name))
        self.pipeline.connectors = registry

    def tearDown(self):
        from ai_content_pipeline.storage.database import get_engine

        get_engine(self.db_url).dispose()
        self.tmp.cleanup()

    def _write_doc(self, name: str, content: str) -> SourceDocument:
        path = Path(self.tmp.name) / name
        path.write_text(content, encoding="utf-8")
        return SourceDocument(
            doc_id=name.replace(".md", ""),
            title=name,
            url=name,
            content=content,
            source_type=SourceType.DOC,
        )

    def test_ingest_and_retrieve(self):
        doc = self._write_doc("manual.md", "# 星尘平台\n\n如何配置 API 密钥？登录开发者中心创建。\n\n" * 20)
        stats = self.pipeline.ingest(doc)
        self.assertGreater(stats.added_chunks, 0)
        hits = self.store.search(self.embedder.embed_query("配置 API 密钥"), top_k=3, threshold=0.1)
        self.assertGreater(len(hits), 0)

    def test_incremental_update_no_duplicate(self):
        doc = self._write_doc("doc.md", "第一段内容。\n\n第二段内容。\n\n" * 10)
        first = self.pipeline.ingest(doc)
        second = self.pipeline.ingest(doc)
        self.assertEqual(second.unchanged_chunks, first.total_chunks)
        self.assertEqual(second.added_chunks, 0)
        self.assertEqual(second.updated_chunks, 0)

    def test_incremental_update_content_change(self):
        doc = self._write_doc("doc.md", "原始内容。\n\n" * 10)
        self.pipeline.ingest(doc)
        changed = self._write_doc("doc.md", "变更后的新内容。\n\n" * 10)
        stats = self.pipeline.ingest(changed)
        self.assertGreater(stats.updated_chunks, 0)


if __name__ == "__main__":
    unittest.main()
