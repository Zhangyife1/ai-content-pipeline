"""FastAPI 入口。"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from ai_content_pipeline import __version__
from ai_content_pipeline.api.deps import get_services
from ai_content_pipeline.api.routers import generation, ingestion, publish, quality, retrieval

logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(app: FastAPI):
    get_services()  # 预热：初始化存储、向量索引、Prompt 模板
    yield


app = FastAPI(
    title="AI Content Pipeline API",
    version=__version__,
    description="知识库投喂 / 多步生成 / 三层质检 / 多渠道分发",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(ingestion.router)
app.include_router(retrieval.router)
app.include_router(generation.router)
app.include_router(quality.router)
app.include_router(publish.router)


@app.get("/healthz", tags=["运维"])
def healthz() -> dict:
    return {"status": "ok", "version": __version__}

