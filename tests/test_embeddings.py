import unittest

import numpy as np

from ai_content_pipeline.ingestion.embeddings import DeterministicEmbedder


class DeterministicEmbedderTests(unittest.TestCase):
    def setUp(self):
        self.embedder = DeterministicEmbedder(dim=128, ngram=2)

    def test_shape_and_normalization(self):
        vecs = self.embedder.embed_texts(["你好世界", "API 密钥配置"])
        self.assertEqual(vecs.shape, (2, 128))
        norms = np.linalg.norm(vecs, axis=1)
        np.testing.assert_allclose(norms, 1.0, atol=1e-6)

    def test_deterministic(self):
        a = self.embedder.embed_query("如何配置 API 密钥")
        b = self.embedder.embed_query("如何配置 API 密钥")
        np.testing.assert_array_equal(a, b)

    def test_similar_texts_higher_similarity(self):
        same = self.embedder.embed_query("如何配置 API 密钥")
        similar = self.embedder.embed_query("API 密钥如何配置")
        unrelated = self.embedder.embed_query("今天天气不错")
        self.assertGreater(float(same @ similar), float(same @ unrelated))


if __name__ == "__main__":
    unittest.main()

