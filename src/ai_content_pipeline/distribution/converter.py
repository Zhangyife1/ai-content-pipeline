"""平台格式转换：内部 Markdown -> 各平台富文本/HTML/JSON。"""

from __future__ import annotations

import re


PLATFORM_SPECS: dict[str, dict] = {
    "wechat": {"cover": (900, 383), "format": "html", "note": "外链需白名单"},
    "zhihu": {"cover": (690, 400), "format": "markdown", "note": "需标注 AI 辅助创作"},
    "cms": {"cover": (1200, 630), "format": "json", "note": "SEO 元数据必填"},
    "toutiao": {"cover": (660, 370), "format": "html", "note": "标题限制 30 字"},
}


class MarkdownConverter:
    """轻量 Markdown -> HTML 转换（面向常用语法；生产可换 markdown-it）。"""

    @staticmethod
    def to_html(md: str) -> str:
        lines = md.splitlines()
        out: list[str] = []
        in_list = False
        in_code = False
        for line in lines:
            if line.strip().startswith("```"):
                out.append("<pre><code>" if not in_code else "</code></pre>")
                in_code = not in_code
                continue
            if in_code:
                out.append(line)
                continue
            if re.match(r"^#{1,4}\s", line):
                if in_list:
                    out.append("</ul>")
                    in_list = False
                level = len(re.match(r"^(#+)", line).group(1))
                text = re.sub(r"^#+\s*", "", line)
                out.append(f"<h{level}>{MarkdownConverter._inline(text)}</h{level}>")
            elif re.match(r"^[-*]\s", line):
                if not in_list:
                    out.append("<ul>")
                    in_list = True
                item_text = re.sub(r"^[-*]\s", "", line)
                out.append(f"<li>{MarkdownConverter._inline(item_text)}</li>")
            elif line.strip() == "":
                if in_list:
                    out.append("</ul>")
                    in_list = False
            else:
                if in_list:
                    out.append("</ul>")
                    in_list = False
                out.append(f"<p>{MarkdownConverter._inline(line)}</p>")
        if in_list:
            out.append("</ul>")
        return "\n".join(out)

    @staticmethod
    def _inline(text: str) -> str:
        text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
        text = re.sub(r"\*(.+?)\*", r"<em>\1</em>", text)
        text = re.sub(r"`(.+?)`", r"<code>\1</code>", text)
        text = re.sub(r"\[(.+?)\]\((https?://[^)]+)\)", r'<a href="\2">\1</a>', text)
        text = re.sub(r"!\[(.*?)\]\((https?://[^)]+)\)", r'<img alt="\1" src="\2" />', text)
        return text

    @staticmethod
    def to_plain(md: str) -> str:
        text = re.sub(r"!\[(.*?)\]\([^)]+\)", r"\1", md)
        text = re.sub(r"\[(.+?)\]\([^)]+\)", r"\1", text)
        text = re.sub(r"[#*>`_~]", "", text)
        return "\n".join(line.strip() for line in text.splitlines() if line.strip())

    @staticmethod
    def add_utm(md: str, platform: str) -> str:
        """为外部链接追加 UTM 参数，用于效果归因。"""
        source = {"wechat": "wechat", "zhihu": "zhihu", "cms": "cms", "toutiao": "toutiao"}.get(platform, platform)

        def replace(match: re.Match) -> str:
            label, url = match.group(1), match.group(2)
            sep = "&" if "?" in url else "?"
            return f"[{label}]({url}{sep}utm_source={source}&utm_medium=content&utm_campaign=ai_pipeline)"

        return re.sub(r"\[(.+?)\]\((https?://[^)]+)\)", replace, md)
