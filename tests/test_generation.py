import unittest

from ai_content_pipeline.generation.chain import ContentChain
from ai_content_pipeline.generation.chain import normalize_outline
from ai_content_pipeline.generation.llm import MockLLM, extract_json
from ai_content_pipeline.ingestion.embeddings import DeterministicEmbedder
from ai_content_pipeline.ingestion.vector_store import HybridRetriever, NumpyVectorStore
from ai_content_pipeline.prompts.registry import PromptRegistry


class MockLLMTests(unittest.TestCase):
    def test_outline_json(self):
        llm = MockLLM()
        raw = llm.complete("system", "选题：AI 增长工程实践", prompt_id="outline")
        data = extract_json(raw)
        self.assertIn("title", data)
        self.assertGreaterEqual(len(data["sections"]), 3)


class OutlineNormalizeTests(unittest.TestCase):
    def test_deepseek_style_heading_and_int_refs(self):
        raw = {
            "title": "如何购买二代机器人",
            "sections": [
                {
                    "heading": "引言：购买前需要了解什么",
                    "key_points": ["适用场景", "预算"],
                    "word_count": "500",
                    "reference": [0, 1],
                },
                {
                    "h2": "购买流程详解",
                    "points": "联系销售；签订合同；安排交付",
                    "words": 600,
                    "source_ids": [2],
                },
            ],
            "total_word_count": "1100",
        }
        normalized = normalize_outline(raw, "二代机器人")
        self.assertEqual(normalized["title"], "如何购买二代机器人")
        self.assertEqual(normalized["sections"][0]["title"], "引言：购买前需要了解什么")
        self.assertEqual(normalized["sections"][0]["source_refs"], ["0", "1"])
        self.assertEqual(normalized["sections"][1]["title"], "购买流程详解")
        self.assertEqual(normalized["sections"][1]["key_points"], ["联系销售", "签订合同", "安排交付"])
        self.assertEqual(normalized["total_word_count"], 1100)


class ContentChainTests(unittest.TestCase):
    def setUp(self):
        store = NumpyVectorStore()
        embedder = DeterministicEmbedder(dim=128)
        from ai_content_pipeline.models import DocumentChunk

        docs = [
            DocumentChunk(
                doc_id="d1",
                chunk_index=0,
                content="星尘 AI 内容平台支持知识库投喂、三层质检与多渠道发布。专业版 299 元/月。",
                content_hash="h1",
            ),
            DocumentChunk(
                doc_id="d1",
                chunk_index=1,
                content="API 密钥配置：登录控制台开发者中心创建，密钥以 sk-st- 开头。",
                content_hash="h2",
            ),
        ]
        store.add(docs, embedder.embed_texts([d.content for d in docs]))
        hybrid = HybridRetriever(store, embedder)
        hybrid.set_corpus(docs)
        self.hybrid = hybrid
        self.chain = ContentChain(llm=MockLLM(), retriever=hybrid, prompts=PromptRegistry())

    def test_run_article(self):
        article = self.chain.run_article("如何配置 API 密钥", word_count=1000)
        self.assertGreater(len(article.title), 10)
        self.assertGreater(len(article.body), 200)
        self.assertTrue(article.summary)
        self.assertIsNotNone(article.seo)
        self.assertGreaterEqual(len(article.faq_pairs), 3)


if __name__ == "__main__":
    unittest.main()
