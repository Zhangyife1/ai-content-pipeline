# 从 Mock / Demo 切换到真实生产环境

本项目的 demo 模式（确定性 Embedding + MockLLM + 内存队列）用于面试演示与本地验证；接入真实业务时，按本指南逐项替换即可，**业务代码无需改动**——所有组件都通过接口 + 配置切换。

## 1. 替换总览

| 组件 | Demo 实现 | 真实生产实现 | 切换方式 |
| --- | --- | --- | --- |
| 知识库源文件 | `examples/sample_kb/`（虚构产品） | 你的真实文档目录（FAQ/产品手册/PDF/网页） | `run_kb_pipeline.py --kb-dir <真实目录>` 或 POST `/api/v1/kb/ingest` |
| 内容生成 LLM | `MockLLM`（模板输出） | **DeepSeek**（默认）或 Qwen | `.env` 填 `DEEPSEEK_API_KEY`，`LLM_PROVIDER=deepseek` |
| Embedding | `DeterministicEmbedder`（hash 向量） | `BGE-large-zh-v1.5`（本地语义向量） | `pip install -e ".[ml]"`，`USE_DETERMINISTIC_EMBEDDINGS=false` |
| 向量库 | `NumpyVectorStore`（内存） | `FaissVectorStore` / 自研 Milvus 实现 | 实现 `VectorStore` 协议后注入 |
| 关系数据库 | SQLite `data/*.db` | PostgreSQL | `DATABASE_URL=postgresql+psycopg://...` |
| 热点选题源 | `MockHotTopicSource` | RSS / 官方 API / 自建爬虫 | 实现 `HotTopicSource` 加入 `HotTopicAggregator` |
| 订单/工具 | `MockOrderService`（内存假数据） | `HttpOrderService`（真实订单 API） | `FunctionCallRouter(order_service=HttpOrderService(...))` |
| 会话存储 | 进程内 `SessionStore` | Redis（TTL 24h） | 实现 `SessionStore` 同接口的 Redis 版本 |
| 发布平台 | `MockAdapter` | 微信/知乎/CMS 适配器 | `PUBLISH_MODE=real` + 实现真实 Adapter |
| 延时调度 | `InMemoryScheduler` | Redis ZSET + Celery Worker | `pip install -e ".[worker]"`，docker compose |
| 任务执行 | 同步/线程池 | Celery + 独立调度循环 | `workers/celery_app.py` |

## 2. 步骤一：准备真实知识库

推荐目录结构（脚本已支持任意目录，增量更新按文件内容指纹识别）：

```text
知识库/
├── FAQ/               # 客服常见问题（txt/md）
├── 产品手册/           # 产品说明书（PDF/HTML）
├── 行业文章/           # 行业资料（txt/md）
├── 竞品与政策/         # 可选
└── 生成内容_待审核/    # 管线输出（脚本自动跳过，不会污染知识库）
```

注意事项：

- 文件名即文档标题，建议去掉日期/版本后缀或保留为 `产品名_版本.md`；
- PDF 优先提供**文字版 PDF**（扫描件需要先 OCR：PaddleOCR / 百度 OCR）；
- 单个文档建议不超过 10 万字符，超长文档会被自动按标题层级切分；
- 敏感信息（手机号、合同条款）在投喂前脱敏；
- 每次重跑 `scripts/run_kb_pipeline.py` 只处理变更片段（BLAKE3 指纹），可安全反复执行。

## 3. 步骤二：切换内容生成 LLM 到 DeepSeek

`.env` 配置（项目已默认 DeepSeek）：

```bash
LLM_PROVIDER=deepseek
DEEPSEEK_API_KEY=sk-你的密钥
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-chat      # 推理场景可换 deepseek-reasoner
```

密钥安全：`DEEPSEEK_API_KEY` 只写入本地 `.env`（已被 gitignore，不会上传 GitHub），
程序自动加载；CI 使用 GitHub Actions Secrets；生产使用云密钥管理服务注入环境变量。

验证：

```bash
python -m ai_content_pipeline.cli generate "如何购买机器人"
```

输出不再出现「Mock 输出」，即为真实生成。代码路径：`generation/llm.py::DeepSeekLLMClient`，与 Qwen 共用同一个 OpenAI 兼容客户端，切换只改环境变量。

## 4. 步骤三：切换语义 Embedding 与向量库

```bash
pip install -e ".[ml]"
```

```bash
USE_DETERMINISTIC_EMBEDDINGS=false
EMBEDDING_MODEL=BAAI/bge-large-zh-v1.5
```

向量库生产建议：

- 单机 <100 万片段：`FaissVectorStore`（本项目已内置，`pip install faiss-cpu`）；
- 集群/多副本：自研 `MilvusVectorStore` 实现同一个 `VectorStore` 协议（`add/delete_by_doc_ids/search`），其余代码零改动；
- 检索阈值（`RETRIEVAL_THRESHOLD`）换真实 Embedding 后需重新标定：先跑 50 个查询看分数分布，再定阈值；RAGAS 的 context precision/recall 可直接指导调参。

## 5. 步骤四：数据库与队列

```bash
DATABASE_URL=postgresql+psycopg://user:pass@localhost:5432/content_pipeline
REDIS_URL=redis://localhost:6379/0
```

```bash
pip install -e ".[worker]"
docker compose up -d redis postgres
celery -A ai_content_pipeline.workers.celery_app worker --loglevel=INFO
python -m ai_content_pipeline.workers.scheduler_loop   # 发布调度循环
```

## 6. 步骤五：替换业务 Mock

### 热点源（`ingestion/hot_topics.py`）

```python
from ai_content_pipeline.ingestion.hot_topics import HotTopicAggregator, RSSHotTopicSource

aggregator = HotTopicAggregator([
    RSSHotTopicSource("https://your-feed.com/rss"),          # 行业 RSS
    YourOfficialApiSource(api_key=...),                     # 官方热点 API
])
```

### 订单服务（`conversation/function_calling.py`）

```python
from ai_content_pipeline.conversation.function_calling import FunctionCallRouter, HttpOrderService

router = FunctionCallRouter(order_service=HttpOrderService(
    base_url="https://your-site.com", api_key="..."
))
```

真实接入时注意：订单查询/下单必须加**用户身份校验 + 幂等键**，并对 `ChatTurn.tools_called` 做审计日志。

### 发布适配器（`distribution/adapters.py`）

```bash
PUBLISH_MODE=real
```

实现微信/知乎/CMS 的 `authenticate / upload_image / publish / get_stats` 四件套；Token 刷新与限流重试逻辑沿用现有状态机，不需要改主流程。

## 7. RAGAS 评测检索与生成质量

项目提供评测脚手架 `scripts/evaluate_ragas.py`：

```bash
# 第一步：从真实知识库导出评测数据集（问题 + 检索上下文 + 答案 + 参考答案）
python scripts/evaluate_ragas.py \
  --kb-dir "C:/Users/YIFEI/Desktop/官网ai bot项目/知识库" \
  --questions "如何购买机器人" "软件怎么升级" "发票如何开具" \
  --output data/ragas_dataset.jsonl

# 第二步：在安装了 ragas 的环境中运行评测（可本地或 CI）
pip install ragas
python scripts/evaluate_ragas.py --run-ragas --dataset data/ragas_dataset.jsonl
```

核心指标与优化映射：

| 指标 | 含义 | 低分时优先排查 |
| --- | --- | --- |
| Faithfulness（忠实度） | 答案是否全部有上下文支撑 | Prompt 约束、上下文截断、生成温度 |
| Answer Relevancy（答案相关性） | 答案是否切题 | 生成 Chain 的 Outline/Section Prompt |
| Context Precision（上下文精确率） | 检索结果是否包含答案所需信息 | 检索阈值、Top-K、重排模型 |
| Context Recall（上下文召回率） | 答案所需信息是否被检索到 | 分块策略、Embedding 模型、HyDE 开关、BM25 权重 |

建议每周跑一次 100 问评测集，把低分样本回流到 Prompt A/B 与知识库补全，形成数据驱动的优化闭环（对应仓库 Roadmap 中的 RAGAS 项）。
