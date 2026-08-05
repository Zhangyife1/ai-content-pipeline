import unittest

from ai_content_pipeline.quality.duplicate_check import DuplicateChecker, SimHash, tokenize_chinese
from ai_content_pipeline.quality.fact_check import FactChecker, extract_claims
from ai_content_pipeline.quality.format_check import FormatChecker
from ai_content_pipeline.quality.orchestrator import QualityChecker


class SimHashTests(unittest.TestCase):
    def test_identical_text_zero_distance(self):
        text = "星尘 AI 内容平台支持知识库投喂与多平台发布。"
        self.assertEqual(SimHash.from_text(text).distance(SimHash.from_text(text)), 0)

    def test_duplicate_checker_threshold(self):
        checker = DuplicateChecker(threshold=3)
        base = "星尘 AI 内容平台支持知识库投喂与多平台发布。"
        checker.add(base)
        dup = checker.check(base)
        self.assertTrue(dup.duplicated)
        fresh = checker.check("今天天气很好，适合出门散步。")
        self.assertFalse(fresh.duplicated)

    def test_tokenize_chinese(self):
        tokens = tokenize_chinese("AI 内容生产管线")
        self.assertTrue(any("内容" in t or "生产" in t for t in tokens))


class FactCheckTests(unittest.TestCase):
    def test_extract_claims_finds_numbers(self):
        text = "专业版价格 299 元/月，支持每秒 50 次请求。"
        claims = extract_claims(text)
        self.assertTrue(any("299" in "".join(c.numeric_values) for c in claims))

    def test_fact_check_contradiction(self):
        class FakeRetriever:
            def search(self, query, top_k=3):
                from ai_content_pipeline.models import RetrievalResult

                return [
                    RetrievalResult(
                        doc_id="d1",
                        chunk_id="c1",
                        chunk_index=0,
                        content="专业版价格 299 元/月，支持每秒 50 次请求。",
                        score=0.9,
                    )
                ]

        checker = FactChecker(FakeRetriever())
        issues = checker.check("专业版价格 999 元/月。")
        self.assertTrue(any(i.verdict == "contradiction" for i in issues))

    def test_fact_check_require_evidence(self):
        class EmptyRetriever:
            def search(self, query, top_k=3):
                return []

        checker = FactChecker(EmptyRetriever())
        issues = checker.check("专业版价格 299 元/月。")
        self.assertTrue(any(i.verdict == "neutral" for i in issues))


class FormatCheckTests(unittest.TestCase):
    def test_title_too_short(self):
        checker = FormatChecker(title_min=10, title_max=80)
        issues = checker.check("太短", "正文内容" * 10, keywords=["内容"])
        self.assertTrue(any(i.code == "title_length" and i.level == "fail" for i in issues))

    def test_image_alt_missing(self):
        checker = FormatChecker()
        issues = checker.check("这是一篇合格的标题文章", "正文\n\n![](https://example.com/a.png)")
        self.assertTrue(any(i.code == "image_alt_missing" for i in issues))


class OrchestratorTests(unittest.TestCase):
    def test_passed_report(self):
        class EmptyRetriever:
            def search(self, query, top_k=3):
                return []

        from ai_content_pipeline.quality.duplicate_check import DuplicateChecker
        from ai_content_pipeline.quality.fact_check import FactChecker

        checker = QualityChecker(
            duplicate_checker=DuplicateChecker(),
            fact_checker=FactChecker(EmptyRetriever(), require_evidence=False),
        )
        body = "星尘 AI 内容平台" * 30
        report = checker.check("content_1", "这是一篇合格的标题文章，用于测试", body)
        self.assertTrue(report.passed)


if __name__ == "__main__":
    unittest.main()
