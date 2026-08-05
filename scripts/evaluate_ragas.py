"""RAGAS 评测脚手架：导出评测数据集，可选直接运行 ragas 指标。

用法：
    python scripts/evaluate_ragas.py ^
        --kb-dir "C:/Users/YIFEI/Desktop/官网ai bot项目/知识库" ^
        --questions "如何购买机器人" "软件怎么升级" ^
        --output data/ragas_dataset.jsonl

    pip install ragas
    python scripts/evaluate_ragas.py --run-ragas --dataset data/ragas_dataset.jsonl
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

os.environ.setdefault("USE_DETERMINISTIC_EMBEDDINGS", "true")
os.environ.setdefault("RETRIEVAL_THRESHOLD", "0.25")
os.environ.setdefault("PUBLISH_MODE", "mock")
os.environ.setdefault("DATABASE_URL", "sqlite:///./data/kb_soma.db")

from ai_content_pipeline.generation.llm import create_llm
from ai_content_pipeline.models import GeneratedArticle
from ai_content_pipeline.prompts.registry import PromptRegistry
from ai_content_pipeline.services import build_services


def load_questions(args) -> list[str]:
    if args.questions:
        return args.questions
    # 从 FAQ 文档标题自动生成问题
    services = build_services()
    questions = []
    for record in services.repository.search_active_chunks(limit=100_000):
        meta = record.metadata_json or {}
        if str(meta.get("source_type", "")) == "faq":
            title = meta.get("title", "")
            if title.startswith("FAQ") and len(questions) < 20:
                questions.append(title[3:].strip() + "？")
    return questions


def build_sample(services, llm, prompts, question: str) -> dict:
    hits = services.hybrid_retriever.search(question, top_k=3)
    contexts = [h.content for h in hits]
    context_text = "\n".join(f"[{i}] {c}" for i, c in enumerate(contexts)) or "（知识库暂无相关内容）"
    answer = llm.complete(
        system="你是官网智能客服，只依据知识库上下文回答。",
        user=prompts.render("chat_answer", {"question": question, "context": context_text}),
        prompt_id="chat_answer",
        temperature=0.3,
    ).strip()
    reference = contexts[0] if contexts else ""
    return {
        "question": question,
        "contexts": contexts,
        "answer": answer,
        "ground_truth": reference,
        "retrieved_doc_ids": [h.doc_id for h in hits],
    }


def export_dataset(services, llm, prompts, questions: list[str], output: Path) -> int:
    records = [build_sample(services, llm, prompts, q) for q in questions]
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8") as fh:
        for record in records:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    print(f"已导出 {len(records)} 条评测样本 -> {output}")
    return 0


def run_ragas(dataset: Path) -> int:
    try:
        from ragas import SingleTurnSample, evaluate
    except ImportError:
        from ragas import evaluate
        from ragas.dataset_schema import SingleTurnSample
    try:
        from ragas.metrics import answer_relevancy, context_precision, context_recall, faithfulness
    except ImportError as exc:
        print(f"缺少 ragas 指标模块：pip install ragas（{exc}）", file=sys.stderr)
        return 2

    samples = []
    for line in dataset.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        data = json.loads(line)
        samples.append(
            SingleTurnSample(
                user_input=data["question"],
                retrieved_contexts=data["contexts"],
                response=data["answer"],
                reference=data.get("ground_truth") or None,
            )
        )
    metrics = [faithfulness, answer_relevancy, context_precision, context_recall]
    try:
        result = evaluate(dataset=samples, metrics=metrics)
    except TypeError:
        from ragas import EvaluationDataset

        result = evaluate(dataset=EvaluationDataset(samples=samples), metrics=metrics)
    print(result)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="RAGAS 评测脚手架")
    parser.add_argument("--kb-dir", default=r"C:\Users\YIFEI\Desktop\官网ai bot项目\知识库")
    parser.add_argument("--questions", nargs="*", default=[])
    parser.add_argument("--output", default="data/ragas_dataset.jsonl")
    parser.add_argument("--dataset", default="data/ragas_dataset.jsonl")
    parser.add_argument("--run-ragas", action="store_true", help="直接运行 ragas 指标")
    args = parser.parse_args()

    if args.run_ragas:
        return run_ragas(Path(args.dataset))

    services = build_services()
    llm = create_llm(services.settings)
    prompts = PromptRegistry(services.repository)
    questions = load_questions(args)
    if not questions:
        print("未提供问题且知识库中没有 FAQ 文档", file=sys.stderr)
        return 1
    return export_dataset(services, llm, prompts, questions, Path(args.output))


if __name__ == "__main__":
    sys.exit(main())
