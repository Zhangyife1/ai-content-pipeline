"""集中式配置管理：从环境变量读取，支持 demo / dev / prod 三种模式。"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


def _env_bool(name: str, default: bool = False) -> bool:
    return _env(name, "true" if default else "false").strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    try:
        return int(_env(name, str(default)))
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(_env(name, str(default)))
    except ValueError:
        return default


@dataclass(frozen=True)
class Settings:
    """全局配置。所有生产组件均通过可选依赖 + 环境变量切换。"""

    app_env: str = "dev"
    log_level: str = "INFO"
    api_host: str = "0.0.0.0"
    api_port: int = 8000

    # LLM（OpenAI 兼容协议：DeepSeek / Qwen）
    llm_provider: str = "deepseek"  # mock | qwen | deepseek
    qwen_api_key: str = ""
    qwen_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    qwen_model: str = "qwen-max"
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-chat"
    llm_temperature: float = 0.7
    llm_max_retries: int = 3
    llm_request_timeout: float = 30.0

    # Embedding / 向量检索
    embedding_model: str = "BAAI/bge-large-zh-v1.5"
    embedding_dim: int = 512
    use_deterministic_embeddings: bool = False
    chunk_size: int = 512
    chunk_overlap: int = 128
    retrieval_top_k: int = 5
    retrieval_threshold: float = 0.75
    hybrid_weight_vector: float = 0.6
    hybrid_weight_keyword: float = 0.4
    rerank_top_n: int = 3

    # 存储
    database_url: str = "sqlite:///./data/pipeline.db"
    redis_url: str = "redis://localhost:6379/0"

    # 分发
    publish_mode: str = "mock"
    publish_max_retries: int = 3

    # 质检
    simhash_duplicate_threshold: int = 3
    fact_check_require_evidence: bool = True

    @property
    def is_demo(self) -> bool:
        return self.app_env == "demo"

    @property
    def has_qwen_key(self) -> bool:
        return bool(self.qwen_api_key)

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            app_env=_env("APP_ENV", "dev"),
            log_level=_env("LOG_LEVEL", "INFO"),
            api_host=_env("API_HOST", "0.0.0.0"),
            api_port=_env_int("API_PORT", 8000),
            llm_provider=_env("LLM_PROVIDER", "deepseek"),
            qwen_api_key=_env("QWEN_API_KEY"),
            qwen_base_url=_env("QWEN_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
            qwen_model=_env("QWEN_MODEL", "qwen-max"),
            deepseek_api_key=_env("DEEPSEEK_API_KEY"),
            deepseek_base_url=_env("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
            deepseek_model=_env("DEEPSEEK_MODEL", "deepseek-chat"),
            llm_temperature=_env_float("LLM_TEMPERATURE", 0.7),
            llm_max_retries=_env_int("LLM_MAX_RETRIES", 3),
            llm_request_timeout=_env_float("LLM_REQUEST_TIMEOUT", 30.0),
            embedding_model=_env("EMBEDDING_MODEL", "BAAI/bge-large-zh-v1.5"),
            embedding_dim=_env_int("EMBEDDING_DIM", 512),
            use_deterministic_embeddings=_env_bool("USE_DETERMINISTIC_EMBEDDINGS"),
            chunk_size=_env_int("CHUNK_SIZE", 512),
            chunk_overlap=_env_int("CHUNK_OVERLAP", 128),
            retrieval_top_k=_env_int("RETRIEVAL_TOP_K", 5),
            retrieval_threshold=_env_float("RETRIEVAL_THRESHOLD", 0.75),
            hybrid_weight_vector=_env_float("HYBRID_WEIGHT_VECTOR", 0.6),
            hybrid_weight_keyword=_env_float("HYBRID_WEIGHT_KEYWORD", 0.4),
            rerank_top_n=_env_int("RERANK_TOP_N", 3),
            database_url=_env("DATABASE_URL", "sqlite:///./data/pipeline.db"),
            redis_url=_env("REDIS_URL", "redis://localhost:6379/0"),
            publish_mode=_env("PUBLISH_MODE", "mock"),
            publish_max_retries=_env_int("PUBLISH_MAX_RETRIES", 3),
            simhash_duplicate_threshold=_env_int("SIMHASH_DUPLICATE_THRESHOLD", 3),
            fact_check_require_evidence=_env_bool("FACT_CHECK_REQUIRE_EVIDENCE", True),
        )


@lru_cache
def get_settings() -> Settings:
    return Settings.from_env()


def ensure_data_dir() -> Path:
    data_dir = Path("data")
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir
