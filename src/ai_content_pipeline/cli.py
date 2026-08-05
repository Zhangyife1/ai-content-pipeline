"""命令行入口：demo / seed / ingest / generate / check / serve。"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path


def _ensure_local_mode() -> None:
    """本地命令默认使用确定性 Embedding（零依赖、可复现），并放宽检索阈值。"""
    os.environ.setdefault("USE_DETERMINISTIC_EMBEDDINGS", "true")
    os.environ.setdefault("RETRIEVAL_THRESHOLD", "0.25")
    os.environ.setdefault("PUBLISH_MODE", "mock")


def _build_services():
    from ai_content_pipeline.services import build_services

    return build_services()


def cmd_seed(args: argparse.Namespace) -> int:
    """把示例知识库复制到 data/sample_kb 并接入。"""
    _ensure_local_mode()
    from ai_content_pipeline.ingestion.connectors import FileConnector
    from ai_content_pipeline.ingestion.connectors import ConnectorRegistry
    from ai_content_pipeline.models import SourceDocument, SourceType

    services = _build_services()
    sample_dir = Path(__file__).resolve().parent.parent.parent / "examples" / "sample_kb"
    if not sample_dir.exists():
        print(f"未找到示例知识库目录: {sample_dir}")
        return 1
    registry = ConnectorRegistry()
    registry.register(SourceType.DOC, FileConnector(sample_dir))
    services.ingestion_pipeline.connectors = registry
    for file in sorted(sample_dir.glob("*.md")):
        doc = SourceDocument(
            doc_id=f"sample_{file.stem}",
            title=file.stem,
            url=file.name,
            source_type=SourceType.DOC,
            metadata={"tag": "sample"},
        )
        stats = services.ingestion_pipeline.ingest(doc)
        print(f"  [{stats.doc_id}] added={stats.added_chunks} updated={stats.updated_chunks} total={stats.total_chunks}")
    services.sync_retrieval_corpus()
    return 0


def cmd_demo(args: argparse.Namespace) -> int:
    """端到端 demo：种子知识库 -> 生成文章 -> 质检 -> 发布。"""
    _ensure_local_mode()
    from ai_content_pipeline.models import GeneratedArticle

    print("=" * 64)
    print("AI Content Pipeline - 端到端 Demo")
    print("=" * 64)

    rc = cmd_seed(args)
    if rc:
        return rc
    services = _build_services()

    print("\n[1/7] 热点抓取（多源聚合）")
    topics = services.hot_topics.fetch(limit=3)
    for t in topics:
        print(f"  - [{t.score:.0f}] {t.title}（{t.source}）")
    topic = args.topic or topics[0].title if topics else "AI 内容生产管线"

    print("\n[2/7] 检索测试（HyDE + Hybrid Search）")
    hits = services.hyde_retriever.search("如何配置 API 密钥", top_k=3)
    for hit in hits:
        print(f"  - [{hit.score:.3f}] {hit.content[:80]}...")

    print("\n[3/7] 多步生成 Chain（Mock LLM）")
    article = services.content_chain.run_article(
        topic=topic,
        platform=args.platform,
        style=args.style,
        word_count=args.word_count,
    )
    services.repository.save_content(article)
    print(f"  content_id={article.content_id}")
    print(f"  标题：{article.title}")
    print(f"  正文长度：{len(article.body)} 字符")
    print(f"  摘要：{article.summary[:60]}...")
    print(f"  SEO slug：{article.seo.url_slug if article.seo else '-'}")
    print(f"  状态：{article.status}（已进入审核队列）")

    print("\n[4/7] 三层质检")
    report = services.quality_checker.check(
        content_id=article.content_id,
        title=article.title,
        body=article.body,
        platform=args.platform,
    )
    print(f"  passed={report.passed} scores={json.dumps(report.scores, ensure_ascii=False)}")
    for issue in report.issues[:5]:
        print(f"  - [{issue.level.value}] {issue.code}: {issue.message}")

    print("\n[5/7] 人工审核")
    services.repository.update_content_status(article.content_id, "approved")
    pending = services.repository.list_contents_by_status("review")
    print(f"  审核通过；剩余待审核：{len(pending)} 条")

    print("\n[6/7] RAG 客服多轮对话 + Function Calling")
    turn1 = services.chat_engine.handle_message("demo_session", "请问专业版多少钱？")
    print(f"  用户：请问专业版多少钱？\n  客服：{turn1.bot_reply[:80]}...")
    turn2 = services.chat_engine.handle_message("demo_session", "帮我查一下订单 SO20260801001")
    print(f"  用户：帮我查一下订单 SO20260801001\n  客服：{turn2.bot_reply[:80]}...")
    turn3 = services.chat_engine.handle_message("demo_session", "好的，帮我下单专业版")
    print(f"  用户：好的，帮我下单专业版\n  客服：{turn3.bot_reply[:80]}...")
    print(f"  工具调用：{[t.name for t in turn3.tools_called]}")

    print("\n[7/7] 定时发布 + SEO 资产（Mock 平台）")
    publish_at = datetime.now(timezone.utc) + timedelta(seconds=2 if args.quick else 30)
    task = services.publisher.schedule(article, "mock", publish_at)
    print(f"  已入队 task_id={task.task_id} publish_at={publish_at.isoformat()}")

    async def wait_and_publish():
        await asyncio.sleep(2.5 if args.quick else 31)
        return await services.publisher.process_due(lambda cid: article if cid == article.content_id else None)

    processed = asyncio.run(wait_and_publish())
    for t in processed:
        print(f"  发布结果 task_id={t.task_id} status={t.status.value} url={t.result.get('url', '-')}")
    services.repository.update_content_status(article.content_id, "published")
    from ai_content_pipeline.seo.sitemap import SitemapEntry, build_sitemap

    sitemap_xml = build_sitemap(
        [SitemapEntry(loc=f"/content/{article.content_id}", priority=0.9)],
        base_url="https://www.somaagent.com.cn",
    )
    print(f"  sitemap.xml 已生成（{len(sitemap_xml)} 字节）")
    print("\nDemo 完成。")
    return 0


def cmd_ingest(args: argparse.Namespace) -> int:
    _ensure_local_mode()
    from ai_content_pipeline.models import SourceDocument, SourceType

    services = _build_services()
    path = Path(args.path)
    if not path.exists():
        print(f"文件不存在: {path}")
        return 1
    doc = SourceDocument(
        doc_id=args.doc_id or f"file_{path.stem}",
        title=path.stem,
        url=path.name,
        source_type=SourceType.DOC,
    )
    stats = services.ingestion_pipeline.ingest(doc)
    services.sync_retrieval_corpus()
    print(stats.model_dump_json(indent=2))
    return 0


def cmd_generate(args: argparse.Namespace) -> int:
    _ensure_local_mode()
    services = _build_services()
    article = services.content_chain.run_article(
        topic=args.topic,
        platform=args.platform,
        style=args.style,
        word_count=args.word_count,
    )
    services.repository.save_content(article)
    print(article.model_dump_json(indent=2, ensure_ascii=False))
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    _ensure_local_mode()
    services = _build_services()
    record = services.repository.get_content(args.content_id)
    if record is None:
        print(f"内容不存在: {args.content_id}")
        return 1
    report = services.quality_checker.check(
        content_id=record.content_id,
        title=record.title,
        body=record.body,
    )
    print(report.model_dump_json(indent=2, ensure_ascii=False))
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    import uvicorn

    from ai_content_pipeline.config import get_settings

    settings = get_settings()
    uvicorn.run(
        "ai_content_pipeline.api.main:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=args.reload,
    )
    return 0


def cmd_hot_topics(args: argparse.Namespace) -> int:
    _ensure_local_mode()
    services = _build_services()
    topics = services.hot_topics.fetch(limit=args.limit)
    for topic in topics:
        print(f"[{topic.score:.0f}] {topic.title}  source={topic.source}  url={topic.url}")
        if topic.summary:
            print(f"      {topic.summary[:100]}")
    return 0


def cmd_batch_generate(args: argparse.Namespace) -> int:
    _ensure_local_mode()
    import concurrent.futures
    import time

    services = _build_services()
    topics = args.topics
    started = time.perf_counter()
    results: list[str] = []

    def work(topic: str) -> str:
        article = services.content_chain.run_article(topic=topic, word_count=args.word_count)
        services.repository.save_content(article)
        return f"{topic} -> {article.title} ({len(article.body)} chars)"

    with concurrent.futures.ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        for line in pool.map(work, topics):
            print(line)
            results.append(line)
    elapsed = time.perf_counter() - started
    print(f"\n批量生成完成：{len(topics)} 篇，并发 {args.concurrency}，总耗时 {elapsed:.2f}s，"
          f"单篇平均 {elapsed / max(len(topics), 1):.2f}s")
    return 0


def cmd_chat(args: argparse.Namespace) -> int:
    _ensure_local_mode()
    services = _build_services()
    turn = services.chat_engine.handle_message(args.session, args.message)
    print(f"[session={turn.session_id}]")
    print(f"用户：{turn.user_message}")
    print(f"客服：{turn.bot_reply}")
    if turn.tools_called:
        for tool in turn.tools_called:
            print(f"工具调用：{tool.name}({tool.arguments}) -> {tool.result}")
    return 0


def cmd_seo_sitemap(args: argparse.Namespace) -> int:
    _ensure_local_mode()
    from ai_content_pipeline.seo.sitemap import SitemapEntry, build_sitemap

    services = _build_services()
    records = services.repository.list_contents_by_status("published")
    entries = [
        SitemapEntry(loc=f"/content/{r.content_id}", lastmod=r.created_at, priority=0.9)
        for r in records
    ]
    entries.append(SitemapEntry(loc="/", priority=1.0))
    xml = build_sitemap(entries, base_url=args.base_url)
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(xml, encoding="utf-8")
    print(f"已写入 {out}（{len(entries)} 条 URL，{len(xml)} 字节）")
    return 0


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(prog="ai-content-pipeline", description="AI 内容生产管线")
    sub = parser.add_subparsers(dest="command", required=True)

    p_seed = sub.add_parser("seed", help="接入示例知识库")
    p_seed.set_defaults(func=cmd_seed)

    p_demo = sub.add_parser("demo", help="端到端演示")
    p_demo.add_argument("--topic", default="AI 内容生产管线")
    p_demo.add_argument("--platform", default="公众号")
    p_demo.add_argument("--style", default="专业")
    p_demo.add_argument("--word-count", type=int, default=2000)
    p_demo.add_argument("--quick", action="store_true", help="缩短等待时间")
    p_demo.set_defaults(func=cmd_demo)

    p_ingest = sub.add_parser("ingest", help="接入单个文件")
    p_ingest.add_argument("path")
    p_ingest.add_argument("--doc-id", default="")
    p_ingest.set_defaults(func=cmd_ingest)

    p_gen = sub.add_parser("generate", help="生成文章")
    p_gen.add_argument("topic")
    p_gen.add_argument("--platform", default="公众号")
    p_gen.add_argument("--style", default="专业")
    p_gen.add_argument("--word-count", type=int, default=2000)
    p_gen.set_defaults(func=cmd_generate)

    p_check = sub.add_parser("check", help="质检已生成内容")
    p_check.add_argument("content_id")
    p_check.set_defaults(func=cmd_check)

    p_serve = sub.add_parser("serve", help="启动 FastAPI 服务")
    p_serve.add_argument("--reload", action="store_true")
    p_serve.set_defaults(func=cmd_serve)

    p_hot = sub.add_parser("hot-topics", help="抓取热点选题")
    p_hot.add_argument("--limit", type=int, default=5)
    p_hot.set_defaults(func=cmd_hot_topics)

    p_batch = sub.add_parser("batch-generate", help="批量生成文章（演示人效提升）")
    p_batch.add_argument("topics", nargs="+")
    p_batch.add_argument("--concurrency", type=int, default=4)
    p_batch.add_argument("--word-count", type=int, default=1000)
    p_batch.set_defaults(func=cmd_batch_generate)

    p_chat = sub.add_parser("chat", help="客服对话（RAG + Function Calling）")
    p_chat.add_argument("message")
    p_chat.add_argument("--session", default="demo")
    p_chat.set_defaults(func=cmd_chat)

    p_sitemap = sub.add_parser("seo-sitemap", help="生成 sitemap.xml")
    p_sitemap.add_argument("--base-url", default="https://www.somaagent.com.cn")
    p_sitemap.add_argument("--output", default="data/sitemap.xml")
    p_sitemap.set_defaults(func=cmd_seo_sitemap)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
