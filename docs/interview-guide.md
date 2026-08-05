# AI 增长工程师面试指南

结合本项目回答面试官最常问的问题。每个回答都给出“一句话结论 + 展开 + 代码落点”。

## 1. 请介绍一下这个项目

**一句话**：一套从知识库到多平台发布的 AI 内容生产管线，核心是“投喂可增量、生成可校验、发布可重试、效果可回流”。

**展开**：四层架构——投喂层把异构文档统一为 `SourceDocument`，清洗分块后走双轨存储；生成层用 HyDE 检索 + 多步 Chain 产出文章/摘要/FAQ/SEO；质量层用 SimHash、RAG 事实校验、格式检查把关；分发层通过平台适配器 + 延时队列 + 状态机发布，最后效果数据回流驱动 Prompt 优化。

**代码落点**：`src/ai_content_pipeline/` 下 `ingestion/`、`generation/`、`quality/`、`distribution/` 四个包。

## 2. 为什么用 RAG？直接让 LLM 写不行吗？

**一句话**：企业内容需要事实准确、风格统一、可追溯，RAG 把“记忆”外置到知识库。

**展开**：直接生成有两个问题：模型知识滞后、编造参数（幻觉）。RAG 让每个事实声明都能回溯到原始 chunk，同时知识更新只需增量投喂，不用微调模型。成本上，检索 + 生成远低于持续微调。

## 3. 向量库为什么不直接存全文？

**一句话**：向量库擅长近似检索，不擅长聚合、事务和版本管理。

**展开**：双轨存储——向量库只存 `doc_id + embedding + chunk_index`，全文/元数据/版本历史在 PostgreSQL。事实校验需要精确回溯“某参数在 2026-03-15 至 2026-06-01 有效”，这是关系库的强项。代码见 `storage/database.py` 的时序字段 `valid_from/valid_to`。

## 4. 增量更新怎么实现？

**一句话**：BLAKE3 内容指纹比对，只重建变化的 chunk。

**展开**：每个 chunk 入库时计算 `content_hash`；源文档变更后，按 chunk_index 对比新旧 hash，分三类处理：新增直接写、变更更新并重建向量、删除做逻辑删除（`is_active=false`）。向量库低峰期物理重建。代码见 `ingestion/pipeline.py::ingest`。

## 5. 中文场景分块要注意什么？

**一句话**：语义完整比长度整齐更重要。

**展开**：默认 512 tokens、overlap 128；分隔符按“段落 → 句子 → 子句 → 词”递归；结构化文档（API 文档）按标题层级切分。overlap 防止跨边界信息断裂，标题感知保证章节完整性。代码见 `ingestion/chunker.py`。

## 6. 如何提升召回率？

**一句话**：HyDE 把查询转成假设文档 + 向量与 BM25 混合加权。

**展开**：用户口语化查询（“怎么配密钥”）直接检索效果差，先用 LLM 生成一段假设回答再检索；同时 BM25 兜底专有名词精确匹配。融合权重可配置。代码见 `generation/hyde.py`、`ingestion/vector_store.py::HybridRetriever`。

## 7. 如何保证生成内容不重复？

**一句话**：SimHash 64 位指纹 + Hamming 距离，≤3 判定高度相似。

**展开**：生成完成后与历史内容比对，重复直接触发重写；历史指纹预计算，分桶优化后百万级比对延迟低于 100ms。代码见 `quality/duplicate_check.py`。

## 8. 事实性校验怎么做？

**一句话**：声明抽取 → 知识库取证 → 数值精确比对 + 包含度判断。

**展开**：正则抽取数值型声明（价格/日期/版本），向知识库检索证据；声明中的数字必须出现在证据里，否则判 contradiction；核心词重合度 ≥60% 判 entailment；找不到证据判 neutral（人工确认）。生产可叠加 NLI 模型与 LLM 声明抽取。代码见 `quality/fact_check.py`。

## 9. 质检不通过怎么办？

**一句话**：按失败类型分流：重复/格式自动重写，事实矛盾转人工。

**展开**：`QualityReport` 带结构化 issues（code/level/evidence），Dify 条件分支据此路由；连续生成失败 3 次进入“需人工处理”队列。代码见 `quality/orchestrator.py`。

## 10. 如何控制成本与并发？

**一句话**：并发限流 + 指数退避 + 熔断阈值。

**展开**：LLM API 用信号量限流（如 10 并发），错误率 >5% 或延迟 >10s 触发熔断；Embedding 服务按 GPU 利用率保护；发布重试用 1s/2s/4s 退避。代码中 `QwenLLMClient` 已接入 tenacity 重试，生产可按文档扩展熔断器。

## 11. 发布失败如何保证不丢任务、不重复发布？

**一句话**：状态机 + 延时队列 + 发布日志。

**展开**：状态流 `pending -> queued -> publishing -> published/failed`，失败按错误类型重试（网络退避、限流等待、认证刷新）；所有状态写入 `publish_log`。生产接 Redis ZSET 后，Worker 消费需要幂等键（`task_id`）防止重复发布。代码见 `distribution/publisher.py`、`scheduler.py`。

## 12. 如何做多平台适配？

**一句话**：Adapter 模式，每个平台实现同一组方法。

**展开**：`authenticate / upload_image / publish / get_stats` 四件套；格式转换（Markdown → 公众号富文本/知乎 HTML/CMS JSON）与封面尺寸规则在 `converter.py` 的 `PLATFORM_SPECS`。新增平台只写一个新 Adapter，主流程零改动。

## 13. Prompt 如何管理？

**一句话**：模板入库、版本化、可回滚、支持 A/B。

**展开**：`PromptTemplate` 有 `prompt_id/version/template/variables/output_schema/is_active/weight`；同 id 多版本 active 时按 weight 分流，效果数据回标签后决定胜出版本。代码见 `prompts/registry.py`。

## 14. Dify 和自研系统怎么分工？

**一句话**：Dify 管流程可见性，自研管工程深度。

**展开**：Dify 做编排、条件分支、人工审核；自研 API 提供检索、质检、发布等强工程能力（增量、双轨、重试、日志）。Dify 通过 HTTP 工具节点调用，Prompt 从 Registry 拉取。详见 [Dify 集成指南](dify-integration.md)。

## 15. 如果流量扩大 10 倍，系统哪里会先挂？怎么扩容？

**一句话**：LLM API 配额和向量检索内存最先成为瓶颈。

**展开**：横向扩容 Worker + Redis 队列；向量库换 Milvus 集群并做分片；PostgreSQL 加连接池与只读副本；检索结果加 Redis 缓存；Embedding 与生成任务拆成独立服务，分别按吞吐伸缩。

## 16. 如何评估这套系统的效果？

**一句话**：生成侧看 RAGAS 三指标，发布侧看阅读/互动/转化。

**展开**：离线用忠实度（faithfulness）、答案相关性（answer relevancy）、上下文相关性（context relevancy）评估 RAG；线上按 UTM 归因阅读量、互动率、转化，回流到 Prompt A/B 与知识库补全，形成闭环。

## 17. 数据隐私怎么处理？

**一句话**：本地部署 Embedding 与向量库，企业数据不离开内网。

**展开**：BGE 系列本地部署（`BgeEmbedder`），知识文档不用于模型训练；支持私有化部署；敏感字段在投喂前可脱敏。若用云端 LLM，只传检索后的上下文片段而非全量知识库。

## 18. 项目里最值得骄傲的工程细节是什么？

**推荐角度**：可测试性。demo 模式用确定性 Embedding + Mock LLM + 内存队列，全链路可在无任何外部依赖下运行与测试；接口与生产一致，切换只改环境变量。这直接证明了“依赖抽象”不是纸面设计——CI 里 28 个测试每天都在跑。

