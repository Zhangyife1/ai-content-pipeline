"""自动生成 sitemap.xml，供搜索引擎抓取与提交。"""

from __future__ import annotations

from datetime import datetime
from xml.sax.saxutils import escape


class SitemapEntry:
    def __init__(self, loc: str, lastmod: datetime | None = None, priority: float = 0.7) -> None:
        self.loc = loc
        self.lastmod = lastmod
        self.priority = priority


def build_sitemap(entries: list[SitemapEntry], base_url: str = "https://www.somaagent.com.cn") -> str:
    parts = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
    ]
    for entry in entries:
        loc = entry.loc if entry.loc.startswith("http") else f"{base_url.rstrip('/')}/{entry.loc.lstrip('/')}"
        parts.append("  <url>")
        parts.append(f"    <loc>{escape(loc)}</loc>")
        if entry.lastmod:
            parts.append(f"    <lastmod>{entry.lastmod.strftime('%Y-%m-%d')}</lastmod>")
        parts.append(f"    <priority>{entry.priority:.1f}</priority>")
        parts.append("  </url>")
    parts.append("</urlset>")
    return "\n".join(parts)

