"""第三层质检：格式规范检查（正则为主，可叠加 LLM 语气/调性检查）。"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass
class FormatRule:
    code: str
    description: str
    level: str = "warn"  # warn | fail


@dataclass
class FormatIssue:
    code: str
    message: str
    level: str = "warn"
    detail: dict = field(default_factory=dict)


class FormatChecker:
    def __init__(
        self,
        title_min: int = 10,
        title_max: int = 80,
        paragraph_max: int = 2000,
        keyword_min: int = 2,
    ) -> None:
        self.title_min = title_min
        self.title_max = title_max
        self.paragraph_max = paragraph_max
        self.keyword_min = keyword_min

    def check(
        self,
        title: str,
        body: str,
        keywords: list[str] | None = None,
        platform: str = "公众号",
    ) -> list[FormatIssue]:
        issues: list[FormatIssue] = []
        title_len = len(title)
        if title_len < self.title_min or title_len > self.title_max:
            issues.append(
                FormatIssue(
                    "title_length",
                    f"标题长度 {title_len} 不在 [{self.title_min}, {self.title_max}] 范围内",
                    "fail",
                    {"length": title_len},
                )
            )
        if platform == "头条号" and title_len > 30:
            issues.append(FormatIssue("title_limit_platform", "头条号标题限制 30 字", "fail"))

        for i, paragraph in enumerate(re.split(r"\n\s*\n", body)):
            if len(paragraph) > self.paragraph_max:
                issues.append(
                    FormatIssue(
                        "paragraph_too_long",
                        f"第 {i + 1} 段长度 {len(paragraph)} 超过 {self.paragraph_max}",
                        "warn",
                        {"paragraph_index": i, "length": len(paragraph)},
                    )
                )

        for keyword in keywords or []:
            count = body.count(keyword)
            if count < self.keyword_min:
                issues.append(
                    FormatIssue(
                        "keyword_frequency",
                        f"关键词「{keyword}」出现 {count} 次，低于阈值 {self.keyword_min}",
                        "warn",
                        {"keyword": keyword, "count": count},
                    )
                )

        link_re = re.compile(r"\[[^\]]+\]\([^)]+\)")
        for link in link_re.findall(body):
            if "http" not in link:
                issues.append(FormatIssue("relative_link", f"发现非绝对链接: {link[:50]}", "warn"))

        img_re = re.compile(r"!\[[^\]]*\]\([^)]+\)")
        for img in img_re.findall(body):
            alt = img[2 : img.find("]")]
            if not alt.strip():
                issues.append(FormatIssue("image_alt_missing", "图片缺少 alt 文本", "warn", {"img": img[:50]}))
        return issues

