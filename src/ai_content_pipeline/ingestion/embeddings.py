"""Embedding 抽象：demo 用确定性 hash 向量；生产切 sentence-transformers BGE。"""

from __future__ import annotations

import hashlib
import re
from typing import Protocol

import numpy as np

from ai_content_pipeline.config import Settings


class Embedder(Protocol):
    dim: int

    def embed_texts(self, texts: list[str]) -> np.ndarray:
        """返回 shape=(n, dim) 的归一化向量。"""

    def embed_query(self, text: str) -> np.ndarray:
        """返回 shape=(dim,) 的归一化向量。"""


class DeterministicEmbedder:
    """基于 hash 特征的确定性 Embedding。

    仅用于本地 demo 与单元测试：可复现、零依赖、无网络。
    生产环境请切换 BgeEmbedder。
    """

    def __init__(self, dim: int = 512, ngram: int = 2) -> None:
        self.dim = dim
        self.ngram = ngram

    def _features(self, text: str) -> list[str]:
        tokens = re.findall(r"[\w\u4e00-\u9fff]+", text.lower())
        features = list(tokens)
        for i in range(len(tokens) - self.ngram + 1):
            features.append("".join(tokens[i : i + self.ngram]))
        return features

    def _embed_one(self, text: str) -> np.ndarray:
        vec = np.zeros(self.dim, dtype=np.float32)
        for feature in self._features(text):
            digest = hashlib.blake2b(feature.encode("utf-8"), digest_size=8).digest()
            idx = int.from_bytes(digest[:4], "little") % self.dim
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            vec[idx] += sign
        norm = np.linalg.norm(vec)
        if norm > 0:
            vec /= norm
        return vec

    def embed_texts(self, texts: list[str]) -> np.ndarray:
        return np.stack([self._embed_one(t) for t in texts])

    def embed_query(self, text: str) -> np.ndarray:
        return self._embed_one(text)


class BgeEmbedder:
    """BGE 系列中文语义 Embedding（本地部署，数据不出内网）。"""

    def __init__(self, model_name: str = "BAAI/bge-large-zh-v1.5") -> None:
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("缺少 sentence-transformers，请安装可选依赖: pip install -e '.[ml]'") from exc
        self._model = SentenceTransformer(model_name)
        self.dim = int(self._model.get_sentence_embedding_dimension())

    def embed_texts(self, texts: list[str]) -> np.ndarray:
        return self._model.encode(texts, normalize_embeddings=True, show_progress_bar=False).astype(np.float32)

    def embed_query(self, text: str) -> np.ndarray:
        return self._model.encode(text, normalize_embeddings=True).astype(np.float32)


def create_embedder(settings: Settings) -> Embedder:
    if settings.use_deterministic_embeddings or settings.app_env == "demo":
        return DeterministicEmbedder(dim=settings.embedding_dim)
    return BgeEmbedder(model_name=settings.embedding_model)

