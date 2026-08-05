import unittest

from ai_content_pipeline.ingestion.chunker import HeadingAwareChunker, RecursiveCharacterTextSplitter
from ai_content_pipeline.ingestion.cleaner import clean_html, clean_text
from ai_content_pipeline.models import SourceDocument, SourceType, content_hash


class CleanerTests(unittest.TestCase):
    def test_clean_text_removes_noise_lines(self):
        raw = "正文第一段\n广告：点击购买\n\n  版权声明  \n正文第二段"
        cleaned = clean_text(raw)
        self.assertIn("正文第一段", cleaned)
        self.assertIn("正文第二段", cleaned)
        self.assertNotIn("广告", cleaned)
        self.assertNotIn("版权", cleaned)

    def test_clean_html_extracts_body(self):
        raw = "<html><head><script>var x=1;</script></head><body><nav>导航</nav><p>你好<strong>世界</strong></p><footer>页脚</footer></body></html>"
        cleaned = clean_html(raw)
        self.assertIn("你好", cleaned)
        self.assertIn("世界", cleaned)
        self.assertNotIn("导航", cleaned)
        self.assertNotIn("var x", cleaned)


class ChunkerTests(unittest.TestCase):
    def test_chunk_size_and_overlap(self):
        splitter = RecursiveCharacterTextSplitter(chunk_size=50, chunk_overlap=10)
        text = "这是第一句话。这是第二句话。这是第三句话。这是第四句话。这是第五句话。" * 3
        chunks = splitter.split_text(text)
        self.assertGreater(len(chunks), 1)
        for chunk in chunks:
            self.assertLessEqual(len(chunk), 60)  # size + overlap

    def test_heading_aware_keeps_headings(self):
        text = "# 第一章\n\n内容内容内容\n\n# 第二章\n\n更多内容"
        chunks = HeadingAwareChunker().split_text(text)
        self.assertTrue(any("第一章" in c for c in chunks))
        self.assertTrue(any("第二章" in c for c in chunks))

    def test_content_hash_stable(self):
        self.assertEqual(content_hash("abc"), content_hash("abc"))
        self.assertNotEqual(content_hash("abc"), content_hash("abd"))

    def test_split_document_produces_chunks(self):
        from ai_content_pipeline.ingestion.chunker import split_document

        doc = SourceDocument(title="测试", content="内容" * 300, source_type=SourceType.DOC)
        chunks = split_document(doc, chunk_size=100, chunk_overlap=20)
        self.assertGreater(len(chunks), 1)
        self.assertEqual(chunks[0].doc_id, doc.doc_id)
        self.assertEqual(chunks[0].chunk_index, 0)


if __name__ == "__main__":
    unittest.main()

