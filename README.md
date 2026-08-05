# AI 内容生产管线（AI Content Pipeline）

端到端内容生产系统：
热点抓取 → AI 生成 → 人工审核 → 多渠道发布 → 数据回流闭环，并内置 RAG 多轮客服（Function Calling 业务闭环）与 GEO 工程化资产。
项目基于真实生产架构抽象而来，核心代码零外部服务即可运行，生产组件通过可选依赖平滑切换。

[![CI](https://github.com/Zhangyife1/ai-content-pipeline/actions/workflows/ci.yml/badge.svg)](https://github.com/Zhangyife1/ai-content-pipeline/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

## 功能总览

| 模块 | 能力 | 代码位置 |
| --- | --- | --- |
| 热点抓取 | 多源内容聚合器（RSS/Mock）、热度去重排序、热点直通生成管线 | `src/ai_content_pipeline/ingestion/hot_topics.py` |
| 知识库投喂 | 多数据源 Connector、正文清洗、递归/标题感知分块、BGE 向量化、混合检索（向量 + BM25）、BLAKE3 指纹增量更新、双轨存储 | `src/ai_content_pipeline/ingestion/` |
| 多步生成 | HyDE 召回增强、大纲生成、分段撰写（Map-Reduce）、摘要、FAQ、SEO 元数据、Pydantic Schema 校验 + 自动重试 | `src/ai_content_pipeline/generation/` |
| 审核流 | 生成后自动进入审核队列，API 支持通过/驳回，通过后才可发布 | `src/ai_content_pipeline/api/routers/review.py` |
| 三层质检 | SimHash 重复率检测、RAG 事实交叉验证（数值精确比对 + NLI 扩展位）、格式规范检查 | `src/ai_content_pipeline/quality/` |
| RAG 智能客服 | 多轮对话 + 上下文记忆、基于知识库的检索增强问答、Function Calling 订单「问答→查询→下单」闭环 | `src/ai_content_pipeline/conversation/` |
| 多渠道分发 | 平台适配器、Markdown 格式转换 + UTM 归因、Redis ZSET/内存延时队列、发布状态机 + 指数退避重试 | `src/ai_content_pipeline/distribution/` |
| GEO / SEO | 自动 Sitemap、Schema.org JSON-LD（Article/FAQ/Organization/Product） | `src/ai_content_pipeline/seo/` |
| 可观测性 | 生成耗时、发布成功率、错误数等进程内指标 + API | `src/ai_content_pipeline/observability/` |
| Prompt 管理 | 模板版本化、DB 持久化、按权重 A/B 分配、容错渲染 | `src/ai_content_pipeline/prompts/` |
| API / 任务 | FastAPI 全链路 REST API、Celery Worker、独立发布调度循环、批量生成 CLI | `src/ai_content_pipeline/api/`、`workers/`、`cli.py` |

## 架构图

```mermaid
flowchart TB
    subgraph 数据源层
        A[产品文档/历史文章/FAQ/网页]
    end
    subgraph 投喂层
        B[Connector 标准化]
        C[清洗/去噪]
        D[语义分块]
        E[Embedding + 向量库]
    end
    subgraph 存储层
        F[(向量库 FAISS/Numpy)]
        G[(PostgreSQL/SQLite 全文+元数据+版本)]
    end
    subgraph 生成层
        H[HyDE 混合检索]
        I[大纲生成]
        J[分段撰写]
        K[摘要/FAQ/SEO]
    end
    subgraph 质量层
        L[SimHash 去重]
        M[RAG 事实校验]
        N[格式规范]
    end
    subgraph 分发层
        O[平台适配器]
        P[延时调度队列]
        Q[发布状态机/重试]
    end
    subgraph 回流层
        R[效果数据采集]
        S[Prompt A/B / 知识库补全]
    end

    A --> B --> C --> D --> E --> F
    D --> G
    H --> I --> J --> K
    F --> H
    G --> H
    K --> L --> M --> N
    N --> O --> P --> Q
    Q --> R --> S
    S --> H
```

## 快速开始（3 分钟跑通全链路）

无需 API Key、无需 Redis/PostgreSQL/FAISS，demo 模式使用确定性 Embedding + Mock LLM + 内存队列：

```bash
git clone https://github.com/Zhangyife1/ai-content-pipeline.git
cd ai-content-pipeline

python -m venv .venv
# Windows: .venv\Scripts\activate
source .venv/bin/activate

pip install -e .
python -m ai_content_pipeline.cli demo --quick
```

你会看到 7 步全链路：热点抓取 → 示例知识库增量投喂 → HyDE 混合检索 → 文章生成（大纲/正文/摘要/FAQ/SEO）→ 三层质检 → 人工审核 → RAG 客服多轮对话（订单查询/下单）→ 定时发布 → Sitemap 生成。

## 启动 REST API

```bash
python -m ai_content_pipeline.cli serve
# 或
uvicorn ai_content_pipeline.api.main:app --reload
```

打开 http://localhost:8000/docs 查看交互式 API 文档。

### API 示例

```bash
# 1. 接入知识文档（本机绝对路径）
curl -X POST http://localhost:8000/api/v1/kb/ingest \
  -H "Content-Type: application/json" \
  -d '{"doc_id":"kb_001","title":"产品手册","url":"C:/docs/product.md","source_type":"doc"}'

# 2. 混合检索
curl -X POST http://localhost:8000/api/v1/kb/retrieval \
  -H "Content-Type: application/json" \
  -d '{"query":"如何配置 API 密钥","top_k":5}'

# 3. 生成文章（含摘要/FAQ/SEO）
curl -X POST http://localhost:8000/api/v1/generation/articles \
  -H "Content-Type: application/json" \
  -d '{"topic":"如何配置 API 密钥","platform":"公众号","style":"专业","word_count":2000}'

# 4. 三层质检
curl -X POST http://localhost:8000/api/v1/quality/check \
  -H "Content-Type: application/json" \
  -d '{"content_id":"content_xxx","title":"标题","body":"正文"}'

# 5. 创建发布任务并执行
curl -X POST http://localhost:8000/api/v1/publish/tasks \
  -H "Content-Type: application/json" \
  -d '{"content_id":"content_xxx","platform":"mock"}'
curl -X POST http://localhost:8000/api/v1/publish/process

# 6. RAG 客服（多轮 + Function Calling）
curl -X POST http://localhost:8000/api/v1/chat \
  -H "Content-Type: application/json" \
  -d '{"message":"帮我查一下订单 SO20260801001","session_id":"demo"}'

# 7. 人工审核
curl http://localhost:8000/api/v1/review/pending
curl -X POST http://localhost:8000/api/v1/review/{content_id}/approve

# 8. SEO / GEO 资产
curl http://localhost:8000/api/v1/seo/sitemap.xml
curl http://localhost:8000/api/v1/seo/structured/{content_id}

# 9. 运行指标
curl http://localhost:8000/api/v1/metrics
```

## 运行测试与 Lint

```bash
pip install -e ".[dev]"
python -m unittest discover -s tests -v   # 42 个测试：分块/向量/质检/生成/调度/投喂/热点/客服/SEO/指标/API
ruff check src tests
```

GitHub Actions 已配置 CI：lint + 测试 + demo 冒烟。

## 生产环境配置

复制 `.env.example` 为 `.env` 并填写：

```bash
# LLM（默认 DeepSeek，OpenAI 兼容协议）
LLM_PROVIDER=deepseek
DEEPSEEK_API_KEY=sk-xxx
DEEPSEEK_MODEL=deepseek-chat

# 阿里云百炼 Qwen（备用）
QWEN_API_KEY=sk-xxx
QWEN_MODEL=qwen-max

# 语义 Embedding（需安装 ml 可选依赖）
EMBEDDING_MODEL=BAAI/bge-large-zh-v1.5
USE_DETERMINISTIC_EMBEDDINGS=false

# 存储
DATABASE_URL=postgresql+psycopg://pipeline:pipeline@localhost:5432/content_pipeline
REDIS_URL=redis://localhost:6379/0

# 分发
PUBLISH_MODE=mock   # 接入真实平台时改为 real
```

生产组件安装：

```bash
pip install -e ".[ml,worker]"
```

Docker Compose 一键启动（API + Worker + 调度器 + Redis + PostgreSQL）：

```bash
docker compose up --build
```

## 密钥与安全

- **API Key 绝不进入仓库**：`DEEPSEEK_API_KEY` / `QWEN_API_KEY` 只放在本地 `.env`、环境变量或云密钥管理服务中。
- `.env` 已被 `.gitignore` 忽略，程序启动时会自动读取（`python-dotenv`）。使用方法：复制 `.env.example` 为 `.env`，填入真实密钥，无需改代码。
- CI 需要密钥时，在 GitHub 仓库 `Settings → Secrets and variables → Actions` 中配置，工作流里用 `${{ secrets.DEEPSEEK_API_KEY }}` 引用，禁止硬编码。
- 生产环境：使用云厂商 Secret Manager（阿里云 KMS/凭据管家）或 ECS/Docker 环境变量注入，`docker-compose.yml` 已通过 `env_file: .env` 支持本地编排。
- 仓库已内置 CI 密钥扫描（`ci.yml`），一旦检测到真实密钥格式会直接让流水线失败。
- 若怀疑密钥泄露：立即在 DeepSeek / 百炼控制台吊销并重新生成，然后轮换 `.env`。

## 项目结构

```text
ai-content-pipeline/
├── src/ai_content_pipeline/
│   ├── api/              # FastAPI 路由（投喂/检索/生成/质检/审核/客服/发布/SEO/指标）
│   ├── ingestion/        # Connector、清洗、分块、Embedding、向量库、热点聚合、投喂管线
│   ├── generation/       # LLM 客户端、HyDE、多步生成 Chain
│   ├── conversation/     # RAG 客服：多轮记忆、Function Calling 订单闭环
│   ├── quality/          # SimHash、事实校验、格式检查、质检编排
│   ├── distribution/     # 平台适配器、格式转换、调度器、发布引擎
│   ├── seo/              # Sitemap、Schema.org 结构化数据（GEO）
│   ├── observability/    # 进程内指标
│   ├── prompts/          # Prompt 版本注册表（A/B）
│   ├── storage/          # SQLAlchemy 模型与仓储（双轨存储关系侧）
│   ├── workers/          # Celery 任务、发布调度循环
│   └── cli.py            # demo / seed / ingest / generate / hot-topics / batch-generate / chat / seo-sitemap / serve
├── tests/                # 42 个单元 + API 测试
├── examples/sample_kb/   # 示例知识库
├── docs/                 # 架构设计、Dify 集成、面试指南
└── docker-compose.yml
```

## 文档

- [架构设计文档](docs/architecture.md)：每个模块的设计决策与取舍（ADR 风格）
- [Dify 集成指南](docs/dify-integration.md)：Dify 工作流与自研管线的边界与协作
- [真实生产迁移指南](docs/real-world-migration.md)：Mock/Demo 逐项替换为真实数据源、DeepSeek LLM、BGE、PostgreSQL、RAGAS 评测

## 设计亮点

1. **双轨存储**：向量库只做近似检索，PostgreSQL 做全文、元数据与版本历史，避免“索引卡当档案柜”。
2. **增量更新**：BLAKE3 内容指纹比对 + `is_active/valid_from/valid_to` 时序模式，支持事实追溯。
3. **可解释质检**：三层质检全部返回结构化 issue（代码/级别/证据），不通过即人工复核。
4. **生成即工程**：每步输出过 Pydantic Schema，失败自动重试 3 次，连续失败进人工队列。
5. **客服即业务入口**：RAG 检索回答 + Function Calling 订单查询/下单，多轮记忆让「问答→查询→下单」闭环成立。
6. **GEO 工程化**：自动 Sitemap + Schema.org 结构化数据，为自然流量增长提供可复现资产。
7. **低耦合扩展**：Connector、Adapter、VectorStore、Scheduler 全部接口化，替换实现不影响上游。
8. **零成本可演示**：demo 模式不依赖任何外部服务，面试可现场跑通全链路。

## Roadmap

- [x] 热点抓取与多源聚合
- [x] RAG 多轮客服 + Function Calling 订单闭环
- [x] 人工审核流
- [x] Sitemap / Schema.org 结构化数据
- [x] 生成与发布指标采集
- [ ] 接入真实微信/知乎/CMS 适配器与 Token 刷新
- [ ] 增加 RAGAS 离线评测（忠实度/答案相关性/上下文相关性）
- [ ] 效果数据回流到 Prompt A/B 实验平台
- [ ] 增加 Alembic 数据库迁移与 Grafana 监控面板
- [ ] 接入 BGE-M3 多粒度 Embedding 与 Milvus 集群

## License

[MIT](LICENSE)
