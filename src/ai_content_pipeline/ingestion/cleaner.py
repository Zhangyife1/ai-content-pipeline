"""内容清洗：去掉模板噪声、广告、导航页脚，统一空白与编码。"""

from __future__ import annotations

import html as html_lib
import re
from html.parser import HTMLParser


NOISE_PATTERNS = [
    re.compile(r"^(导航|目录|菜单|首页|上一页|下一页|返回顶部)\s*$"),
    re.compile(r"^(版权|Copyright|©|All rights reserved).*$", re.IGNORECASE),
    re.compile(r"^(广告|推广|赞助|Advertisement).*$", re.IGNORECASE),
    re.compile(r"^\s*(关注我们|扫码|长按识别二维码|点赞|在看|分享)\s*$"),
    re.compile(r"^(\d{4})[-/年]\d{1,2}[-/月]\d{1,2}日?\s*(编辑|发布|来源)?\s*$"),
]


class _HTMLTextExtractor(HTMLParser):
    """轻量 HTML -> 文本，无 BeautifulSoup 依赖。"""

    BLOCK_TAGS = {"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "section", "blockquote", "pre"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in {"script", "style", "noscript", "iframe", "svg", "canvas", "nav", "footer", "header"}:
            self._skip_depth += 1
        if self._skip_depth == 0 and tag in self.BLOCK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript", "iframe", "svg", "canvas", "nav", "footer", "header"}:
            self._skip_depth = max(0, self._skip_depth - 1)
        if self._skip_depth == 0 and tag in self.BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip_depth == 0:
            self.parts.append(data)


def clean_html(raw_html: str) -> str:
    """HTML -> 正文纯文本，剥离脚本/样式/导航/页脚等噪声。"""
    parser = _HTMLTextExtractor()
    try:
        parser.feed(raw_html)
    except Exception:
        # 极端畸形 HTML 退化为去标签
        text = re.sub(r"<[^>]+>", " ", raw_html)
    else:
        text = "".join(parser.parts)
    return clean_text(html_lib.unescape(text))


def clean_text(text: str) -> str:
    """统一空白、去除噪声行、压缩重复空行。"""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = []
    for raw_line in text.split("\n"):
        line = raw_line.strip()
        if not line:
            continue
        if any(pattern.match(line) for pattern in NOISE_PATTERNS):
            continue
        lines.append(re.sub(r"[ \t\u3000]+", " ", line))
    cleaned = "\n".join(lines)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()

