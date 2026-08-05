"""向量存储抽象：NumpyVectorStore（demo）/ FaissVectorStore（生产）。

设计：向量库只存 doc_id + embedding + chunk_index；
全文、元数据、版本历史由 PostgreSQL 承担（双轨存储）。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Protocol

import numpy as np

from ai_content_pipeline.models import DocumentChunk, RetrievalResult


class VectorStore(Protocol):
    def add(self, chunks: list[DocumentChunk], embeddings: np.ndarray) -> None: ...

    def delete_by_doc_ids(self, doc_ids: list[str]) -> None: ...

    def search(self, query_embedding: np.ndarray, top_k: int = 5, threshold: float = 0.75) -> list[RetrievalResult]: ...


class NumpyVectorStore:
    """纯 NumPy 余弦检索，百万级以下规模足够；支持持久化到 .npz。"""

    def __init__(self, threshold: float = 0.75) -> None:
        self._vectors = np.zeros((0, 0), dtype=np.float32)
        self._ids: list[str] = []
        self._doc_ids: list[str] = []
        self._chunk_indexes: list[int] = []
        self._metadata: list[dict] = []
        self.threshold = threshold

    def add(self, chunks: list[DocumentChunk], embeddings: np.ndarray) -> None:
        if not chunks:
            return
        if self._vectors.size == 0:
            self._vectors = np.zeros((0, embeddings.shape[1]), dtype=np.float32)
        self._vectors = np.vstack([self._vectors, embeddings])
        for chunk in chunks:
            self._ids.append(chunk.chunk_id)
            self._doc_ids.append(chunk.doc_id)
            self._chunk_indexes.append(chunk.chunk_index)
            self._metadata.append(chunk.metadata)

    def delete_by_doc_ids(self, doc_ids: list[str]) -> None:
        doc_set = set(doc_ids)
        keep = [i for i, doc_id in enumerate(self._doc_ids) if doc_id not in doc_set]
        self._vectors = self._vectors[keep] if keep else np.zeros((0, self._vectors.shape[1]), dtype=np.float32)
        self._ids = [self._ids[i] for i in keep]
        self._doc_ids = [self._doc_ids[i] for i in keep]
        self._chunk_indexes = [self._chunk_indexes[i] for i in keep]
        self._metadata = [self._metadata[i] for i in keep]

    def search(self, query_embedding: np.ndarray, top_k: int = 5, threshold: float | None = None) -> list[RetrievalResult]:
        threshold = self.threshold if threshold is None else threshold
        if self._vectors.shape[0] == 0:
            return []
        q = np.asarray(query_embedding, dtype=np.float32).reshape(1, -1)
        q = q / (np.linalg.norm(q) + 1e-12)
        scores = (self._vectors @ q.T).ravel()
        order = np.argsort(-scores)
        results: list[RetrievalResult] = []
        for idx in order:
            score = float(scores[idx])
            if score < threshold:
                break
            results.append(
                RetrievalResult(
                    doc_id=self._doc_ids[idx],
                    chunk_id=self._ids[idx],
                    chunk_index=self._chunk_indexes[idx],
                    content="",
                    score=score,
                    metadata=self._metadata[idx],
                )
            )
            if len(results) >= top_k:
                break
        return results

    def save(self, path: str | Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(
            path,
            vectors=self._vectors,
            ids=np.array(self._ids, dtype=object),
            doc_ids=np.array(self._doc_ids, dtype=object),
            chunk_indexes=np.array(self._chunk_indexes, dtype=np.int32),
            metadata=np.array([json.dumps(m, ensure_ascii=False) for m in self._metadata], dtype=object),
        )

    def load(self, path: str | Path) -> None:
        data = np.load(path, allow_pickle=True)
        self._vectors = data["vectors"].astype(np.float32)
        self._ids = list(data["ids"])
        self._doc_ids = list(data["doc_ids"])
        self._chunk_indexes = list(map(int, data["chunk_indexes"]))
        self._metadata = [json.loads(m) for m in data["metadata"]]


class FaissVectorStore:
    """FAISS IDMap 实现，支持逻辑删除黑名单 + 低峰期物理重建。"""

    def __init__(self, dim: int, threshold: float = 0.75) -> None:
        try:
            import faiss  # noqa: F401
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("缺少 faiss-cpu，请安装可选依赖: pip install -e '.[ml]'") from exc
        import faiss

        self._index = faiss.IndexIDMap2(faiss.IndexFlatIP(dim))
        self._ids: list[str] = []
        self._doc_ids: list[str] = []
        self._chunk_indexes: list[int] = []
        self._metadata: list[dict] = []
        self._blacklist: set[int] = set()
        self.threshold = threshold

    def add(self, chunks: list[DocumentChunk], embeddings: np.ndarray) -> None:
        import faiss

        start = len(self._ids)
        ids = np.arange(start, start + len(chunks), dtype=np.int64)
        self._index.add_with_ids(embeddings.astype(np.float32), ids)
        for chunk in chunks:
            self._ids.append(chunk.chunk_id)
            self._doc_ids.append(chunk.doc_id)
            self._chunk_indexes.append(chunk.chunk_index)
            self._metadata.append(chunk.metadata)

    def delete_by_doc_ids(self, doc_ids: list[str]) -> None:
        doc_set = set(doc_ids)
        for i, doc_id in enumerate(self._doc_ids):
            if doc_id in doc_set:
                self._blacklist.add(i)

    def search(self, query_embedding: np.ndarray, top_k: int = 5, threshold: float | None = None) -> list[RetrievalResult]:
        threshold = self.threshold if threshold is None else threshold
        import faiss

        if len(self._ids) == 0:
            return []
        scores, indices = self._index.search(query_embedding.reshape(1, -1).astype(np.float32), top_k * 3)
        results: list[RetrievalResult] = []
        for score, idx in zip(scores[0], indices[0]):
            if idx < 0 or idx in self._blacklist or float(score) < threshold:
                continue
            results.append(
                RetrievalResult(
                    doc_id=self._doc_ids[idx],
                    chunk_id=self._ids[idx],
                    chunk_index=self._chunk_indexes[idx],
                    content="",
                    score=float(score),
                    metadata=self._metadata[idx],
                )
            )
            if len(results) >= top_k:
                break
        return results


class HybridRetriever:
    """混合检索：向量召回 + BM25 关键词召回，加权融合。"""

    def __init__(
        self,
        vector_store: VectorStore,
        embedder,
        weight_vector: float = 0.6,
        weight_keyword: float = 0.4,
        bm25_k1: float = 1.5,
        bm25_b: float = 0.75,
    ) -> None:
        self.vector_store = vector_store
        self.embedder = embedder
        self.weight_vector = weight_vector
        self.weight_keyword = weight_keyword
        self.bm25_k1 = bm25_k1
        self.bm25_b = bm25_b
        self._docs: dict[str, str] = {}

    def set_corpus(self, chunks: list[DocumentChunk]) -> None:
        self._docs = {chunk.chunk_id: chunk.content for chunk in chunks}

    def _bm25_scores(self, query: str) -> dict[str, float]:
        if not self._docs:
            return {}
        import math

        tokens = _tokenize(query)
        avg_len = sum(len(doc) for doc in self._docs.values()) / len(self._docs)
        doc_count = len(self._docs)
        df: dict[str, int] = {}
        for doc in self._docs.values():
            for token in set(_tokenize(doc)):
                df[token] = df.get(token, 0) + 1
        scores: dict[str, float] = {}
        for chunk_id, doc in self._docs.items():
            doc_tokens = _tokenize(doc)
            tf = {token: doc_tokens.count(token) for token in tokens}
            score = 0.0
            for token, count in tf.items():
                if count == 0:
                    continue
                idf = math.log((doc_count - df.get(token, 0) + 0.5) / (df.get(token, 0) + 0.5) + 1)
                denom = count + self.bm25_k1 * (1 - self.bm25_b + self.bm25_b * len(doc) / avg_len)
                score += idf * (count * (self.bm25_k1 + 1) / denom)
            scores[chunk_id] = score
        return scores

    def search(self, query: str, top_k: int = 5, threshold: float | None = None) -> list[RetrievalResult]:
        query_emb = self.embedder.embed_query(query)
        vector_hits = self.vector_store.search(query_emb, top_k=top_k * 2, threshold=threshold)
        bm25_scores = self._bm25_scores(query)
        if not bm25_scores:
            return self._fill_content(vector_hits[:top_k])

        max_bm25 = max(bm25_scores.values()) or 1.0
        combined: dict[str, dict] = {}
        for hit in vector_hits:
            combined[hit.chunk_id] = {
                "result": hit,
                "vector": hit.score,
                "keyword": bm25_scores.get(hit.chunk_id, 0.0) / max_bm25,
            }
        for chunk_id, kw_score in bm25_scores.items():
            if chunk_id not in combined:
                combined[chunk_id] = {
                    "result": RetrievalResult(
                        doc_id="",
                        chunk_id=chunk_id,
                        chunk_index=-1,
                        content="",
                        score=0.0,
                    ),
                    "vector": 0.0,
                    "keyword": kw_score / max_bm25,
                }
        ranked = sorted(
            combined.values(),
            key=lambda item: self.weight_vector * item["vector"] + self.weight_keyword * item["keyword"],
            reverse=True,
        )
        top = ranked[:top_k]
        for item in top:
            item["result"].score = round(
                self.weight_vector * item["vector"] + self.weight_keyword * item["keyword"],
                4,
            )
        return self._fill_content([item["result"] for item in top])

    def _fill_content(self, hits: list[RetrievalResult]) -> list[RetrievalResult]:
        for hit in hits:
            if not hit.content and hit.chunk_id in self._docs:
                hit.content = self._docs[hit.chunk_id]
        return hits


def _tokenize(text: str) -> list[str]:
    import re

    tokens = re.findall(r"[\w\u4e00-\u9fff]+", text.lower())
    return tokens
