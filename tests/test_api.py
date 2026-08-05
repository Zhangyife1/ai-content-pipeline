import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

# 必须在导入应用前配置 demo 环境（避免依赖 ML 组件与外部服务）
os.environ["USE_DETERMINISTIC_EMBEDDINGS"] = "true"
os.environ["RETRIEVAL_THRESHOLD"] = "0.25"
os.environ["PUBLISH_MODE"] = "mock"
_tmp_dir = tempfile.mkdtemp(prefix="acp_api_")
os.environ["DATABASE_URL"] = f"sqlite:///{Path(_tmp_dir) / 'api_test.db'}"

from fastapi.testclient import TestClient

from ai_content_pipeline.api.main import app


class ApiSmokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)
        cls.client.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.client.__exit__(None, None, None)
        from ai_content_pipeline.storage.database import get_engine

        get_engine().dispose()

    def test_healthz(self):
        resp = self.client.get("/healthz")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "ok")

    def test_ingest_and_retrieve(self):
        doc_path = Path(_tmp_dir) / "kb.md"
        doc_path.write_text("# API 密钥\n\n如何配置 API 密钥？登录开发者中心创建。\n\n" * 30, encoding="utf-8")
        ingest_resp = self.client.post(
            "/api/v1/kb/ingest",
            json={
                "doc_id": "api_kb",
                "title": "API 密钥配置手册",
                "url": str(doc_path),
                "source_type": "doc",
            },
        )
        self.assertEqual(ingest_resp.status_code, 200)
        self.assertGreater(ingest_resp.json()["added_chunks"], 0)

        retrieve_resp = self.client.post(
            "/api/v1/kb/retrieval",
            json={"query": "配置 API 密钥", "top_k": 3},
        )
        self.assertEqual(retrieve_resp.status_code, 200)
        hits = retrieve_resp.json()
        self.assertGreater(len(hits), 0)
        self.assertTrue(any("API" in hit["content"] for hit in hits))

    def test_generation_quality_publish(self):
        gen_resp = self.client.post(
            "/api/v1/generation/articles",
            json={"topic": "如何配置 API 密钥", "platform": "公众号", "word_count": 1000},
        )
        self.assertEqual(gen_resp.status_code, 200)
        article = gen_resp.json()
        content_id = article["content_id"]
        self.assertIsNotNone(article["seo"])

        quality_resp = self.client.post(
            "/api/v1/quality/check",
            json={"content_id": content_id, "title": article["title"], "body": article["body"]},
        )
        self.assertEqual(quality_resp.status_code, 200)
        self.assertIn("passed", quality_resp.json())

        publish_resp = self.client.post(
            "/api/v1/publish/tasks",
            json={
                "content_id": content_id,
                "platform": "mock",
                "publish_at": (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(),
            },
        )
        self.assertEqual(publish_resp.status_code, 200)
        task_id = publish_resp.json()["task_id"]

        process_resp = self.client.post("/api/v1/publish/process")
        self.assertEqual(process_resp.status_code, 200)
        processed = process_resp.json()
        self.assertTrue(any(t["task_id"] == task_id and t["status"] == "published" for t in processed))


if __name__ == "__main__":
    unittest.main()

