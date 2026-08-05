"""数据源 Connector：把异构数据源统一为 SourceDocument（JSON Lines 标准格式）。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

import httpx

from ai_content_pipeline.ingestion.cleaner import clean_html, clean_text
from ai_content_pipeline.models import SourceDocument, SourceType


class ConnectorError(RuntimeError):
    pass


class DocumentConnector(ABC):
    """每种数据源实现一个 Connector，输出统一的 SourceDocument。"""

    @abstractmethod
    def fetch(self, source: SourceDocument) -> SourceDocument:
        """拉取并规范化一个数据源。"""


class FileConnector(DocumentConnector):
    """本地文件接入：markdown / txt / html。PDF 建议接 PyMuPDF 或 unstructured。"""

    SUPPORTED_SUFFIXES = {".md", ".markdown", ".txt", ".html", ".htm"}

    def __init__(self, base_dir: str | Path = ".") -> None:
        self.base_dir = Path(base_dir)

    def fetch(self, source: SourceDocument) -> SourceDocument:
        if source.url:
            raw_path = Path(source.url)
            path = raw_path if raw_path.is_absolute() else self.base_dir / raw_path
        else:
            raise ConnectorError("FileConnector 需要 source.url 指定文件相对路径")
        if not path.exists():
            raise ConnectorError(f"文件不存在: {path}")
        if path.suffix.lower() not in self.SUPPORTED_SUFFIXES:
            raise ConnectorError(f"不支持的文件类型: {path.suffix}")

        raw = path.read_text(encoding="utf-8", errors="ignore")
        content = clean_html(raw) if path.suffix.lower() in {".html", ".htm"} else clean_text(raw)
        return SourceDocument(
            doc_id=source.doc_id,
            title=source.title or path.stem,
            content=content,
            source_type=source.source_type,
            url=str(path),
            metadata={**source.metadata, "local_path": str(path)},
        )


class WebConnector(DocumentConnector):
    """网页接入：拉取 HTML 并抽取正文。"""

    def __init__(self, timeout: float = 15.0, headers: dict[str, str] | None = None) -> None:
        self.timeout = timeout
        self.headers = headers or {
            "User-Agent": "Mozilla/5.0 (compatible; AI-Content-Pipeline/0.1)",
            "Accept-Language": "zh-CN,zh;q=0.9",
        }

    def fetch(self, source: SourceDocument) -> SourceDocument:
        if not source.url or not source.url.startswith(("http://", "https://")):
            raise ConnectorError("WebConnector 需要完整的 http(s) URL")
        try:
            resp = httpx.get(source.url, timeout=self.timeout, headers=self.headers, follow_redirects=True)
            resp.raise_for_status()
        except httpx.HTTPError as exc:  # pragma: no cover - 依赖网络
            raise ConnectorError(f"网页抓取失败: {exc}") from exc
        content = clean_html(resp.text)
        return SourceDocument(
            doc_id=source.doc_id,
            title=source.title or source.url,
            content=content,
            source_type=SourceType.WEB,
            url=source.url,
            metadata=source.metadata,
        )


class ConnectorRegistry:
    """按 source_type 路由到对应 Connector，方便新增数据源而不改主流程。"""

    def __init__(self) -> None:
        self._connectors: dict[SourceType, DocumentConnector] = {}

    def register(self, source_type: SourceType, connector: DocumentConnector) -> None:
        self._connectors[source_type] = connector

    def get(self, source_type: SourceType) -> DocumentConnector:
        if source_type not in self._connectors:
            raise ConnectorError(f"未注册 {source_type} 对应的 Connector")
        return self._connectors[source_type]


def default_registry() -> ConnectorRegistry:
    registry = ConnectorRegistry()
    registry.register(SourceType.DOC, FileConnector())
    registry.register(SourceType.WEB, WebConnector())
    registry.register(SourceType.FAQ, FileConnector())
    registry.register(SourceType.REPORT, FileConnector())
    registry.register(SourceType.OTHER, FileConnector())
    return registry
