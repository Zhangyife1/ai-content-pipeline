import json
import unittest
from datetime import datetime, timezone

from ai_content_pipeline.seo.sitemap import SitemapEntry, build_sitemap
from ai_content_pipeline.seo.structured_data import article_json_ld, faq_json_ld


class SitemapTests(unittest.TestCase):
    def test_build_sitemap(self):
        xml = build_sitemap(
            [
                SitemapEntry(loc="/content/abc", lastmod=datetime(2026, 8, 5, tzinfo=timezone.utc), priority=0.9),
                SitemapEntry(loc="https://www.somaagent.com.cn/about", priority=0.5),
            ],
            base_url="https://www.somaagent.com.cn",
        )
        self.assertIn("<loc>https://www.somaagent.com.cn/content/abc</loc>", xml)
        self.assertIn("<lastmod>2026-08-05</lastmod>", xml)
        self.assertIn("<priority>0.9</priority>", xml)
        self.assertIn("</urlset>", xml)


class StructuredDataTests(unittest.TestCase):
    def test_faq_json_ld(self):
        data = faq_json_ld([{"question": "价格？", "answer": "299 元/月"}])
        self.assertEqual(data["@type"], "FAQPage")
        self.assertEqual(data["mainEntity"][0]["acceptedAnswer"]["text"], "299 元/月")
        json.dumps(data)  # 可序列化

    def test_article_json_ld(self):
        from ai_content_pipeline.models import GeneratedArticle

        article = GeneratedArticle(title="标题", body="正文")
        data = article_json_ld(article)
        self.assertEqual(data["@type"], "Article")
        self.assertIn("datePublished", data)


if __name__ == "__main__":
    unittest.main()

