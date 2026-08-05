"""三层质检编排：任一 fail 即不通过，按层级返回可解释报告。"""

from __future__ import annotations

from ai_content_pipeline.models import QualityIssue, QualityLevel, QualityReport
from ai_content_pipeline.quality.duplicate_check import DuplicateChecker
from ai_content_pipeline.quality.fact_check import FactChecker
from ai_content_pipeline.quality.format_check import FormatChecker, FormatIssue


class QualityChecker:
    def __init__(
        self,
        duplicate_checker: DuplicateChecker,
        fact_checker: FactChecker,
        format_checker: FormatChecker | None = None,
        keyword_extractor=None,
    ) -> None:
        self.duplicate_checker = duplicate_checker
        self.fact_checker = fact_checker
        self.format_checker = format_checker or FormatChecker()
        self.keyword_extractor = keyword_extractor or (lambda title, body: [title[:8]])

    def check(
        self,
        content_id: str,
        title: str,
        body: str,
        platform: str = "公众号",
    ) -> QualityReport:
        issues: list[QualityIssue] = []

        # 第一层：重复率
        dup = self.duplicate_checker.check(body)
        dup_score = 1.0 if not dup.duplicated else 0.0
        if dup.duplicated:
            issues.append(
                QualityIssue(
                    level=QualityLevel.FAIL,
                    code="duplicate_simhash",
                    message=f"与历史内容高度相似（Hamming distance={dup.distance}）",
                    detail={"distance": dup.distance, "threshold": dup.threshold},
                )
            )
        else:
            self.duplicate_checker.add(body)

        # 第二层：事实性
        fact_issues = self.fact_checker.check(body)
        contradictions = [f for f in fact_issues if f.verdict == "contradiction"]
        neutrals = [f for f in fact_issues if f.verdict == "neutral"]
        fact_score = 1.0 if not contradictions else 0.0
        for item in contradictions:
            issues.append(
                QualityIssue(
                    level=QualityLevel.FAIL,
                    code="fact_contradiction",
                    message=f"事实声明与知识库矛盾：{item.claim[:80]}",
                    detail={"claim": item.claim, "evidence": item.evidence, "reason": item.reason},
                )
            )
        for item in neutrals[:3]:
            issues.append(
                QualityIssue(
                    level=QualityLevel.WARN,
                    code="fact_neutral",
                    message=f"声明无法验证，需人工确认：{item.claim[:80]}",
                    detail={"claim": item.claim, "reason": item.reason},
                )
            )

        # 第三层：格式
        keywords = self.keyword_extractor(title, body)
        format_issues = self.format_checker.check(title, body, keywords=keywords, platform=platform)
        fail_formats = [f for f in format_issues if f.level == "fail"]
        format_score = 1.0 if not fail_formats else 0.0
        for item in format_issues:
            issues.append(
                QualityIssue(
                    level=QualityLevel.FAIL if item.level == "fail" else QualityLevel.WARN,
                    code=item.code,
                    message=item.message,
                    detail=item.detail,
                )
            )

        failed = any(issue.level == QualityLevel.FAIL for issue in issues)
        return QualityReport(
            content_id=content_id,
            passed=not failed,
            scores={
                "duplicate": dup_score,
                "fact": fact_score,
                "format": format_score,
                "overall": 1.0 if not failed else 0.0,
            },
            issues=issues,
        )

