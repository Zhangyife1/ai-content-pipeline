"""第二层质检：RAG 交叉验证。

流程：声明抽取 -> 知识库检索证据 -> NLI/数值/包含度比对。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from ai_content_pipeline.ingestion.vector_store import HybridRetriever


NUMERIC_PATTERN = re.compile(
    r"(?<![.\d])\d+(?:[.,]\d+)?\s*(?:元|块|%|％|万|亿|个|天|小时|分钟|秒|人|次|篇|G|GB|MB|TB|ms|并发|篇/天|req/s)"
)


@dataclass
class FactClaim:
    text: str
    position: int = 0
    numeric_values: list[str] = field(default_factory=list)


def extract_claims(text: str, use_llm: bool = False, llm=None) -> list[FactClaim]:
    """声明抽取：数值型声明用正则（稳定、可解释）；生产可叠加 LLM 抽取。"""
    claims: list[FactClaim] = []
    for match in NUMERIC_PATTERN.finditer(text):
        start = max(0, match.start() - 40)
        end = min(len(text), match.end() + 40)
        claims.append(
            FactClaim(
                text=text[start:end].replace("\n", " ").strip(),
                position=match.start(),
                numeric_values=[match.group(0).replace(" ", "")],
            )
        )
    if use_llm and llm is not None:  # pragma: no cover - 依赖外部 LLM
        raw = llm.complete(
            system="提取文本中的所有事实性声明，输出 JSON 数组，每项含 text 字段。",
            user=text,
            prompt_id="claim_extract",
        )
        try:
            import json

            for item in json.loads(raw):
                claims.append(FactClaim(text=str(item.get("text", "")), position=-1))
        except (ValueError, TypeError):
            pass
    # 去重
    seen: set[str] = set()
    unique: list[FactClaim] = []
    for claim in claims:
        key = claim.text[:60]
        if key not in seen:
            seen.add(key)
            unique.append(claim)
    return unique


@dataclass
class FactCheckIssue:
    claim: str
    verdict: str  # entailment | contradiction | neutral
    evidence: str | None = None
    reason: str = ""


class FactChecker:
    """以知识库为唯一事实源；无证据一律标记 neutral（需人工确认），不默认放行。"""

    def __init__(
        self,
        retriever: HybridRetriever,
        require_evidence: bool = True,
        threshold: float = 0.7,
        use_llm: bool = False,
        llm=None,
    ) -> None:
        self.retriever = retriever
        self.require_evidence = require_evidence
        self.threshold = threshold
        self.use_llm = use_llm
        self.llm = llm

    def check(self, text: str, top_k: int = 3) -> list[FactCheckIssue]:
        claims = extract_claims(text, use_llm=self.use_llm, llm=self.llm)
        issues: list[FactCheckIssue] = []
        for claim in claims:
            evidence_list = self.retriever.search(claim.text, top_k=top_k)
            evidence = next((hit.content for hit in evidence_list if hit.score >= self.threshold), None)
            if not evidence:
                if self.require_evidence:
                    issues.append(FactCheckIssue(claim.text, "neutral", None, "知识库中未找到支持证据"))
                continue
            verdict, reason = self._verify(claim, evidence)
            issues.append(FactCheckIssue(claim.text, verdict, evidence[:200], reason))
        return issues

    @staticmethod
    def _verify(claim: FactClaim, evidence: str) -> tuple[str, str]:
        # 数值精确比对：声明中的数字必须在证据中出现（价格/日期/版本号等）
        for value in claim.numeric_values:
            number = re.sub(r"\D", "", value)
            if number and number not in re.sub(r"\D", "", evidence):
                return "contradiction", f"数值 {value} 未在证据中找到精确匹配"
        # 词汇包含度：声明核心词多数出现在证据中视为 entailment
        claim_tokens = set(re.findall(r"[\w\u4e00-\u9fff]+", claim.text.lower()))
        evidence_tokens = set(re.findall(r"[\w\u4e00-\u9fff]+", evidence.lower()))
        overlap = len(claim_tokens & evidence_tokens) / max(len(claim_tokens), 1)
        if overlap >= 0.6:
            return "entailment", f"声明核心词与证据重合度 {overlap:.0%}"
        return "neutral", f"证据相关但无法完全验证（重合度 {overlap:.0%}），需人工确认"

