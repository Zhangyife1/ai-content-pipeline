"""把本地知识库文件夹跑通「投喂 -> 混合检索 -> 多步生成 -> 质检 -> 人工审核」全流程。

用法：
    python scripts/run_kb_pipeline.py ^
        --kb-dir "C:/Users/YIFEI/Desktop/官网ai bot项目/知识库" ^
        --out-dir "C:/Users/YIFEI/Desktop/官网ai bot项目/知识库/生成内容_待审核"

输出：
    - 生成内容_待审核/00_审核清单.md   全部待审核文章清单
    - 生成内容_待审核/01_*.md          每篇文章（正文/摘要/FAQ/SEO/质检报告）
    - 生成内容_待审核/检索示例.md      混合检索结果示例
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# 本地运行模式：确定性 Embedding + Mock LLM + 放宽检索阈值
os.environ.setdefault("USE_DETERMINISTIC_EMBEDDINGS", "true")
os.environ.setdefault("RETRIEVAL_THRESHOLD", "0.25")
os.environ.setdefault("PUBLISH_MODE", "mock")
os.environ.setdefault("DATABASE_URL", "sqlite:///./data/kb_soma.db")

from ai_content_pipeline.ingestion.cleaner import clean_text
from ai_content_pipeline.ingestion.connectors import DocumentConnector
from ai_content_pipeline.models import SourceDocument, SourceType
from ai_content_pipeline.services import build_services


class PassthroughConnector(DocumentConnector):
    """内容已在脚本中解析（如 PDF），直接使用，不再二次读取。"""

    def fetch(self, source: SourceDocument) -> SourceDocument:
        return source


def _slug(text: str, max_len: int = 40) -> str:
    text = re.sub(r"[\\/:*?\"<>|\s]+", "_", text).strip("_")
    return text[:max_len]


def extract_pdf_text(path: Path, max_pages: int = 120) -> str:
    """用 pypdf 提取 PDF 文本；失败时返回空串并记录原因。"""
    try:
        from pypdf import PdfReader
    except ImportError as exc:  # pragma: no cover
        print(f"  [跳过] {path.name}: 缺少 pypdf ({exc})")
        return ""
    try:
        reader = PdfReader(str(path))
        parts: list[str] = []
        total = min(len(reader.pages), max_pages)
        for idx, page in enumerate(reader.pages[:total], 1):
            try:
                text = page.extract_text() or ""
            except Exception:
                text = ""
            if text.strip():
                parts.append(f"--- 第 {idx} 页 ---\n{text}")
        raw = "\n".join(parts)
        if total < len(reader.pages):
            raw += f"\n\n（注意：本 PDF 共 {len(reader.pages)} 页，本次仅提取前 {max_pages} 页）"
        return clean_text(raw)
    except Exception as exc:
        print(f"  [跳过] {path.name}: PDF 解析失败 ({exc})")
        return ""


def load_documents(kb_dir: Path, out_dir: Path, pdf_max_pages: int) -> list[SourceDocument]:
    docs: list[SourceDocument] = []
    files = sorted(kb_dir.rglob("*"))
    for path in files:
        if not path.is_file():
            continue
        if out_dir in path.parents or path == out_dir:
            continue
        suffix = path.suffix.lower()
        stem = _slug(path.stem)
        if suffix in {".txt", ".md", ".html", ".htm"}:
            raw = path.read_text(encoding="utf-8", errors="ignore")
            content = clean_text(raw)
            source_type = SourceType.FAQ if path.stem.startswith("FAQ") else SourceType.DOC
        elif suffix == ".pdf":
            content = extract_pdf_text(path, max_pages=pdf_max_pages)
            source_type = SourceType.PDF
        else:
            print(f"  [跳过] {path.name}: 不支持的文件类型")
            continue
        if not content.strip():
            print(f"  [跳过] {path.name}: 未提取到文本")
            continue
        docs.append(
            SourceDocument(
                doc_id=f"kb_{stem}",
                title=path.stem,
                url=str(path),
                content=content,
                source_type=source_type,
                metadata={"source_dir": str(kb_dir), "file_name": path.name},
            )
        )
        print(f"  [载入] {path.name} ({len(content)} 字)")
    return docs


def build_retrieval_demo(services) -> list[dict]:
    queries = [
        "如何购买机器人",
        "机器人维修与返厂流程",
        "软件如何升级",
        "如何开具发票",
        "语音交互功能怎么用",
        "嗖马机器人是什么",
        "智慧中医门店解决方案",
        "实体商家如何用 AI 机器人引流",
    ]
    results = []
    for query in queries:
        # Mock 模式下 HyDE 假设文档会稀释相似度，直接使用混合检索（真实 LLM 时再启用 HyDE）
        hits = services.hybrid_retriever.search(query, top_k=3)
        results.append(
            {
                "query": query,
                "hits": [
                    {
                        "doc_id": h.doc_id,
                        "score": round(h.score, 4),
                        "content": h.content[:180].replace("\n", " "),
                    }
                    for h in hits
                ],
            }
        )
    return results


def derive_topics(docs: list[SourceDocument], limit: int = 6) -> list[str]:
    pdf_topic_map = {
        "somaRobot_Intro": "嗖马机器人产品介绍",
        "SOMA机器人介绍最新版5.23": "嗖马机器人最新产品介绍",
        "嗖马AI医生品牌书": "嗖马AI医生品牌定位与价值",
        "嗖马AI医生智慧中医门店20250705": "嗖马AI医生智慧中医门店解决方案",
        "嗖马机器人智能体验中心设计方案第一版第五稿": "嗖马机器人智能体验中心设计方案",
    }
    faq_topics = []
    article_topics = []
    for doc in docs:
        title = doc.title
        if title.startswith("FAQ"):
            topic = title[3:].strip()
            if topic and topic not in faq_topics:
                faq_topics.append(topic)
        elif doc.source_type == SourceType.DOC and title not in article_topics:
            article_topics.append(title)
        elif doc.source_type == SourceType.PDF and title not in article_topics:
            article_topics.append(pdf_topic_map.get(title, title))
    topics = faq_topics[: max(1, limit // 2)] + article_topics[: limit - max(1, limit // 2)]
    return topics[:limit]


def render_article_md(article, report) -> str:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = [
        f"# {article.title}",
        "",
        f"> 状态：待人工审核 ｜ content_id：`{article.content_id}` ｜ 生成时间：{now}",
        "> 目标平台：公众号 ｜ 风格：专业 ｜ Prompt 版本：" + (article.prompt_version or "-"),
        "",
        "## 摘要",
        "",
        article.summary or "（无）",
        "",
        "## 正文",
        "",
        article.body,
        "",
    ]
    if article.faq_pairs:
        lines += ["## 附：FAQ", ""]
        for pair in article.faq_pairs:
            lines += [f"**Q：{pair['question']}**", "", pair["answer"], ""]
    if article.seo:
        lines += [
            "## SEO 元数据",
            "",
            f"- 标题标签：{article.seo.title_tag}",
            f"- Meta 描述：{article.seo.meta_description}",
            f"- 关键词：{'、'.join(article.seo.keywords)}",
            f"- URL Slug：{article.seo.url_slug}",
            "",
        ]
    lines += ["## 质检报告", ""]
    lines += [f"- 是否通过：{'✅ 通过' if report.passed else '❌ 未通过'}"]
    lines += [f"- 得分：{report.scores}"]
    if report.issues:
        lines += ["- 问题清单：", ""]
        for issue in report.issues:
            lines += [f"  - [{issue.level.value}] `{issue.code}` {issue.message}"]
    else:
        lines += ["- 问题清单：无", ""]
    return "\n".join(lines)


def write_outputs(services, kb_dir: Path, out_dir: Path, topics: list[str]) -> list[dict]:
    out_dir.mkdir(parents=True, exist_ok=True)
    # 清空上一轮生成物，避免旧文件残留
    for old in out_dir.glob("*.md"):
        old.unlink()
    manifest: list[dict] = []

    # 1) 检索示例
    demo = build_retrieval_demo(services)
    lines = ["# 混合检索示例（向量 + BM25）", ""]
    for item in demo:
        lines += [f"## 查询：{item['query']}", ""]
        if not item["hits"]:
            lines += ["（无结果）", ""]
        for hit in item["hits"]:
            lines += [f"- [{hit['score']:.3f}] `{hit['doc_id']}` {hit['content']}", ""]
    (out_dir / "检索示例.md").write_text("\n".join(lines), encoding="utf-8")

    # 2) 逐篇生成 + 质检 + 导出
    for idx, topic in enumerate(topics, 1):
        print(f"\n[生成 {idx}/{len(topics)}] {topic}")
        try:
            article = services.content_chain.run_article(
                topic=topic,
                platform="公众号",
                style="专业",
                word_count=1800,
            )
        except Exception as exc:
            print(f"  [失败] {topic}: {exc}")
            manifest.append({"topic": topic, "error": str(exc)})
            continue
        services.repository.save_content(article)
        report = services.quality_checker.check(
            content_id=article.content_id,
            title=article.title,
            body=article.body,
            platform="公众号",
        )
        md = render_article_md(article, report)
        file_name = f"{idx:02d}_{_slug(article.title)}_{article.content_id[:8]}.md"
        (out_dir / file_name).write_text(md, encoding="utf-8")
        manifest.append(
            {
                "content_id": article.content_id,
                "topic": topic,
                "title": article.title,
                "chars": len(article.body),
                "passed": report.passed,
                "scores": report.scores,
                "issues": [f"{i.code}:{i.level.value}" for i in report.issues[:5]],
                "file": file_name,
            }
        )
        print(f"  [完成] {article.title}（{len(article.body)} 字）质检通过={report.passed}")

    # 3) 审核清单
    rows = [
        "| # | content_id | 标题 | 字数 | 质检 | 主要问题 | 文件 |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for idx, item in enumerate(manifest, 1):
        if "error" in item:
            rows.append(f"| {idx} | - | {item['topic']} | - | ❌ 生成失败 | {item['error']} | - |")
            continue
        rows.append(
            f"| {idx} | {item['content_id']} | {item['title']} | {item['chars']} | "
            f"{'✅' if item['passed'] else '❌'} | {'；'.join(item['issues']) or '无'} | {item['file']} |"
        )
    header = [
        "# 待审核内容清单",
        "",
        f"> 生成时间：{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
        f"> 知识库文档数：{len(services.repository.search_active_chunks(limit=1_000_000))} 个片段",
        "",
    ]
    (out_dir / "00_审核清单.md").write_text("\n".join(header + rows + [""]), encoding="utf-8")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description="知识库 -> 投喂 -> 检索 -> 生成 -> 质检 -> 审核")
    parser.add_argument("--kb-dir", default=r"C:\Users\YIFEI\Desktop\官网ai bot项目\知识库")
    parser.add_argument("--out-dir", default="")
    parser.add_argument("--pdf-max-pages", type=int, default=120)
    parser.add_argument("--topics", nargs="*", default=[])
    parser.add_argument("--article-count", type=int, default=6)
    args = parser.parse_args()

    kb_dir = Path(args.kb_dir)
    if not kb_dir.exists():
        print(f"知识库目录不存在: {kb_dir}", file=sys.stderr)
        return 1
    out_dir = Path(args.out_dir) if args.out_dir else kb_dir / "生成内容_待审核"

    print(f"[1/5] 扫描知识库: {kb_dir}")
    docs = load_documents(kb_dir, out_dir, args.pdf_max_pages)
    if not docs:
        print("未载入任何文档", file=sys.stderr)
        return 1

    print(f"\n[2/5] 初始化管线并投喂 {len(docs)} 个文档")
    services = build_services()
    services.ingestion_pipeline.connectors.register(SourceType.PDF, PassthroughConnector())
    # 向量索引为内存态：启动时先从关系库重建，保证未变更文档可被检索
    rebuilt = services.ingestion_pipeline.reindex_all()
    if rebuilt:
        print(f"  已从关系库重建向量索引：{rebuilt} 个片段")
    total_chunks = 0
    for doc in docs:
        try:
            stats = services.ingestion_pipeline.ingest(doc)
            total_chunks += stats.total_chunks
            print(f"  {doc.doc_id}: added={stats.added_chunks} unchanged={stats.unchanged_chunks} total={stats.total_chunks}")
        except Exception as exc:
            print(f"  [失败] {doc.doc_id}: {exc}")
    services.sync_retrieval_corpus()
    print(f"  投喂完成，知识库片段总数：{total_chunks}")

    print("\n[3/5] 混合检索示例（见输出文件）")
    topics = args.topics or derive_topics(docs, limit=args.article_count)
    print(f"  本次生成选题：{topics}")

    print("\n[4/5] 多步生成 + 三层质检")
    manifest = write_outputs(services, kb_dir, out_dir, topics)

    print(f"\n[5/5] 输出目录：{out_dir}")
    print(f"  待审核文章：{sum(1 for m in manifest if 'error' not in m)} 篇，失败：{sum(1 for m in manifest if 'error' in m)} 篇")
    return 0


if __name__ == "__main__":
    sys.exit(main())
