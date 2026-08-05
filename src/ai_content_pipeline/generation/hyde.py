"""HyDE（Hypothetical Document Embeddings）：先用 LLM 生成假设回答再检索，提升召回。"""

from __future__ import annotations

from ai_content_pipeline.generation.llm import LLMClient
from ai_content_pipeline.ingestion.vector_store import HybridRetriever
from ai_content_pipeline.models import RetrievalResult
from ai_content_pipeline.prompts.registry import PromptRegistry


class HydeRetriever:
    def __init__(
        self,
        retriever: HybridRetriever,
        llm: LLMClient,
        prompts: PromptRegistry,
    ) -> None:
        self.retriever = retriever
        self.llm = llm
        self.prompts = prompts

    def search(self, query: str, top_k: int = 5) -> list[RetrievalResult]:
        hypothetical = self.llm.complete(
            system="你是检索增强助手。",
            user=self.prompts.render("hyde", {"query": query}),
            prompt_id="hyde",
        )
        return self.retriever.search(query=hypothetical or query, top_k=top_k)

