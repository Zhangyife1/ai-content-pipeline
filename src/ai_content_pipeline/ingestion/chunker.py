"""语义分块：递归字符切分 + 标题感知切分，支持 chunk_size / overlap。"""

from __future__ import annotations

import re

from ai_content_pipeline.models import DocumentChunk, SourceDocument, content_hash


class RecursiveCharacterTextSplitter:
    """按 段落 -> 句子 -> 子句 -> 词 的优先级递归切分，尽量保持语义完整。"""

    DEFAULT_SEPARATORS = ["\n\n", "\n", "。", "；", "；", "，", "、", " ", ""]

    def __init__(
        self,
        chunk_size: int = 512,
        chunk_overlap: int = 128,
        separators: list[str] | None = None,
    ) -> None:
        if chunk_overlap >= chunk_size:
            raise ValueError("chunk_overlap 必须小于 chunk_size")
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.separators = separators or self.DEFAULT_SEPARATORS

    def split_text(self, text: str) -> list[str]:
        if not text:
            return []
        chunks = self._split_by_separators(text, self.separators)
        merged: list[str] = []
        buffer = ""
        for chunk in chunks:
            if len(buffer) + len(chunk) + 1 <= self.chunk_size:
                buffer = f"{buffer}\n{chunk}" if buffer else chunk
                continue
            if buffer:
                merged.append(buffer)
            if len(chunk) <= self.chunk_size:
                buffer = chunk
            else:
                # 超长块：硬切 + 保留 overlap
                start = 0
                while start < len(chunk):
                    end = start + self.chunk_size
                    merged.append(chunk[start:end])
                    if end >= len(chunk):
                        break
                    start = max(end - self.chunk_overlap, start + 1)
                buffer = ""
        if buffer:
            merged.append(buffer)
        return self._apply_overlap(merged)

    def _split_by_separators(self, text: str, separators: list[str]) -> list[str]:
        if not separators:
            return [text]
        separator = separators[0]
        parts = text.split(separator) if separator else list(text)
        out: list[str] = []
        for part in parts:
            if separator and len(part) > self.chunk_size:
                out.extend(self._split_by_separators(part, separators[1:]))
            else:
                out.append(part)
        return [p for p in out if p.strip()]

    def _apply_overlap(self, chunks: list[str]) -> list[str]:
        """相邻 chunk 之间携带 overlap，避免切分处信息断裂。"""
        if len(chunks) <= 1 or self.chunk_overlap == 0:
            return chunks
        result: list[str] = []
        for i, chunk in enumerate(chunks):
            prefix = ""
            if result and self.chunk_overlap > 0:
                prefix = result[-1][-self.chunk_overlap :]
            merged = f"{prefix}{chunk}" if prefix else chunk
            result.append(merged)
        return result


class HeadingAwareChunker:
    """结构化文档（API 文档、产品手册）优先按标题层级切分。"""

    HEADING_RE = re.compile(r"^(#{1,4})\s+(.+)$")

    def __init__(self, splitter: RecursiveCharacterTextSplitter | None = None) -> None:
        self.splitter = splitter or RecursiveCharacterTextSplitter()

    def split_text(self, text: str) -> list[str]:
        sections: list[str] = []
        current: list[str] = []
        for line in text.splitlines():
            if self.HEADING_RE.match(line):
                if current:
                    sections.append("\n".join(current))
                current = [line]
            else:
                current.append(line)
        if current:
            sections.append("\n".join(current))
        chunks: list[str] = []
        for section in sections:
            if len(section) <= self.splitter.chunk_size:
                chunks.append(section)
            else:
                chunks.extend(self.splitter.split_text(section))
        return chunks


def split_document(
    doc: SourceDocument,
    chunk_size: int = 512,
    chunk_overlap: int = 128,
    heading_aware: bool = False,
) -> list[DocumentChunk]:
    splitter = RecursiveCharacterTextSplitter(chunk_size=chunk_size, chunk_overlap=chunk_overlap)
    parts = HeadingAwareChunker(splitter).split_text(doc.content) if heading_aware else splitter.split_text(doc.content)
    return [
        DocumentChunk(
            doc_id=doc.doc_id,
            chunk_index=idx,
            content=part,
            content_hash=content_hash(part),
            metadata={
                "title": doc.title,
                "source_type": doc.source_type.value,
                "url": doc.url or "",
                **doc.metadata,
            },
        )
        for idx, part in enumerate(parts)
    ]

