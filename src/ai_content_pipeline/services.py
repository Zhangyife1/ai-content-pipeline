"""依赖装配：把 ingestion / generation / quality / distribution 串成可运行的管线。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ai_content_pipeline.config import Settings, ensure_data_dir, get_settings
from ai_content_pipeline.distribution.adapters import default_registry as default_adapter_registry
from ai_content_pipeline.distribution.publisher import Publisher
from ai_content_pipeline.distribution.scheduler import InMemoryScheduler, RedisZSetScheduler
from ai_content_pipeline.generation.chain import ContentChain
from ai_content_pipeline.generation.hyde import HydeRetriever
from ai_content_pipeline.generation.llm import create_llm
from ai_content_pipeline.ingestion.embeddings import create_embedder
from ai_content_pipeline.ingestion.pipeline import IngestionPipeline
from ai_content_pipeline.ingestion.vector_store import HybridRetriever, NumpyVectorStore
from ai_content_pipeline.prompts.registry import PromptRegistry
from ai_content_pipeline.quality.duplicate_check import DuplicateChecker
from ai_content_pipeline.quality.fact_check import FactChecker
from ai_content_pipeline.quality.format_check import FormatChecker
from ai_content_pipeline.quality.orchestrator import QualityChecker
from ai_content_pipeline.storage.database import init_db
from ai_content_pipeline.storage.repositories import ContentRepository


@dataclass
class Services:
    settings: Settings
    repository: ContentRepository
    embedder: Any
    vector_store: NumpyVectorStore
    hybrid_retriever: HybridRetriever
    ingestion_pipeline: IngestionPipeline
    llm: Any
    prompts: PromptRegistry
    hyde_retriever: HydeRetriever
    content_chain: ContentChain
    quality_checker: QualityChecker
    publisher: Publisher

    def sync_retrieval_corpus(self) -> None:
        """把关系库中的 active chunks 同步到检索器（demo 单机场景）。"""
        chunks = self.repository.search_active_chunks(limit=100_000)
        self.hybrid_retriever.set_corpus(chunks)


def build_services(settings: Settings | None = None) -> Services:
    settings = settings or get_settings()
    ensure_data_dir()
    init_db(settings.database_url)

    repository = ContentRepository(settings.database_url)
    embedder = create_embedder(settings)
    vector_store = NumpyVectorStore(threshold=settings.retrieval_threshold)
    hybrid = HybridRetriever(
        vector_store=vector_store,
        embedder=embedder,
        weight_vector=settings.hybrid_weight_vector,
        weight_keyword=settings.hybrid_weight_keyword,
    )
    pipeline = IngestionPipeline(
        embedder=embedder,
        vector_store=vector_store,
        repository=repository,
        chunk_size=settings.chunk_size,
        chunk_overlap=settings.chunk_overlap,
    )

    llm = create_llm(settings)
    prompts = PromptRegistry(repository)
    hyde = HydeRetriever(hybrid, llm, prompts)
    chain = ContentChain(llm=llm, retriever=hyde, prompts=prompts)

    duplicate_checker = DuplicateChecker(threshold=settings.simhash_duplicate_threshold)
    fact_checker = FactChecker(retriever=hybrid, require_evidence=settings.fact_check_require_evidence)
    format_checker = FormatChecker()
    quality = QualityChecker(
        duplicate_checker=duplicate_checker,
        fact_checker=fact_checker,
        format_checker=format_checker,
    )

    adapters = default_adapter_registry(settings.publish_mode)
    scheduler = InMemoryScheduler() if settings.publish_mode == "mock" else RedisZSetScheduler(settings.redis_url)
    publisher = Publisher(
        adapters=adapters,
        scheduler=scheduler,
        repository=repository,
        max_retries=settings.publish_max_retries,
    )

    services = Services(
        settings=settings,
        repository=repository,
        embedder=embedder,
        vector_store=vector_store,
        hybrid_retriever=hybrid,
        ingestion_pipeline=pipeline,
        llm=llm,
        prompts=prompts,
        hyde_retriever=hyde,
        content_chain=chain,
        quality_checker=quality,
        publisher=publisher,
    )
    services.sync_retrieval_corpus()
    return services
