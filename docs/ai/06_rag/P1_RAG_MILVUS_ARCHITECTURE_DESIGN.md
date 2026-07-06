# P1-RAG-MILVUS-ARCHITECTURE-DESIGN-1

## 1. 背景与目标

本方案为 auto_wechat 后续接入外部 Milvus 向量数据库提供架构设计，不修改当前业务代码，不新增数据库迁移，不连接真实 Milvus，不调用真实 LLM。

目标是让后续管理员可以通过受控训练入口维护“小高知识库”内容，由 9100 完成切片、向量化和向量检索；抖音 AI 客服回复建议继续通过 9000 可信代理调用 9100，基于检索结果生成回复建议。

对甲方解释时，“训练 AI 客服自动回复内容”不是训练大模型参数，而是把企业知识、话术、常见问题和业务规则整理成可检索知识，切成小段后写入向量库。后续 AI 回复时先查这些知识，再组织回答。

## 2. 当前 RAG 链路现状

### 2.1 管理员训练链路

```text
管理员 / 内部工具
  -> 9000 POST /knowledge-training/ask
  -> 9000 IP 白名单校验
  -> 9000 XgDouyinAiCsClient
  -> 9100 POST /knowledge-training/ask
  -> 9100 knowledge_training_service.ask()
  -> 9100 RagSearchRequest(category_keys=["base"])
  -> 9100 SQLite knowledge_chunks.embedding_json / 词法 fallback
  -> 9100 LLM 或 fallback answer
  -> 9100 knowledge_training_sessions
  -> 9000 返回脱敏后的训练问答结果
```

反馈链路：

```text
管理员 / 内部工具
  -> 9000 POST /knowledge-training/{training_id}/feedback
  -> 9000 IP 白名单校验
  -> 9100 POST /knowledge-training/{training_id}/feedback
  -> 9100 校验 training_id 的 tenant_id / merchant_id
  -> 9100 knowledge_training_feedbacks
```

事实依据：
- [app/routers/knowledge_training.py](/e:/work/project/auto_wechat/app/routers/knowledge_training.py)
- [apps/xg_douyin_ai_cs/services/knowledge_training_service.py](/e:/work/project/auto_wechat/apps/xg_douyin_ai_cs/services/knowledge_training_service.py)

### 2.2 AI 客服回复建议链路

```text
前端工作台
  -> 9000 POST /integrations/douyin-ai-cs/conversations/{conversation_id}/reply-suggestion
  -> 9000 NewCar 登录态 / auto_wechat:douyin_ai_cs 权限
  -> 9000 校验 merchant_id、企业号、Agent 绑定
  -> 9000 读取 Agent 知识范围 allowed_category_keys
  -> 9000 注入 agent_config.rag_enabled
  -> 9100 /douyin/reply-suggestion
  -> 9100 reply_decision_service.build_reply_suggestion()
  -> 9100 RagSearchRequest(category_keys=allowed_category_keys)
  -> 9100 SQLite 向量检索 / 词法 fallback
  -> 9100 LLM / direct fallback
  -> 9100 强制或返回 auto_send=false 语义
  -> 9000 再次强制 auto_send=false 并记录 ai_reply_decision_logs
  -> 前端只读展示回复建议
```

事实依据：
- [app/routers/douyin_ai_cs_proxy.py](/e:/work/project/auto_wechat/app/routers/douyin_ai_cs_proxy.py)
- [apps/xg_douyin_ai_cs/services/reply_decision_service.py](/e:/work/project/auto_wechat/apps/xg_douyin_ai_cs/services/reply_decision_service.py)

### 2.3 自动回复链路

当前系统仍不是自动发送系统。后续如果进入托管或自动回复试点，链路也必须保持：

```text
webhook / 调度
  -> 9000 可信上下文、权限、企业号、Agent 绑定
  -> 9100 RAG search / LLM decision
  -> 9000 自动发送 gate / dry-run / 审计
  -> 发送候选或真实发送
```

Milvus 只能影响“查知识”的质量和速度，不能绕过 `auto_send=false`、人工确认、dry-run、审计日志和发送 gate。

## 3. 产品边界

1. 商户端不直接管理 Milvus。
2. 前端不直连 Milvus。
3. 9000 不直连 Milvus。
4. 9100 是唯一 RAG runtime 和 Milvus client 所在服务。
5. 管理员训练入口仍由 9000 受控代理到 9100。
6. 商户 Agent 只配置“是否参考小高知识库 / 知识范围”，不管理知识库内容。
7. SQLite 本地向量检索必须继续作为默认值或 fallback。
8. 本方案不改变 `/knowledge-training/ask` 和 `/feedback` schema。
9. 本方案不放开商户端 RAG 写入、上传、训练或 debug 入口。
10. 本方案不改变 NewCar 登录、live-check、Local Agent / 19000、自动发送链路。

## 4. 总体架构

```text
frontend
  -> 9000 auto_wechat
       - NewCar 登录态
       - RequestContext.merchant_id
       - 权限码校验
       - 企业号归属 / Agent 绑定
       - allowed_category_keys 注入
       - auto_send=false 最终门禁
       - AI 回复决策日志
  -> 9100 xg_douyin_ai_cs
       - RAG 文档标准化
       - chunk 切片
       - embedding
       - VectorStore 抽象
       - SQLite 默认向量检索
       - Milvus 可选向量检索
       - LLM 回复建议
  -> Milvus
       - 仅 9100 内网访问
       - 存储 chunk embedding 和检索 metadata
```

职责边界：

| 组件 | 职责 | 不负责 |
|---|---|---|
| 前端 | 触发回复建议、配置 Agent 知识范围、展示 source_chunks | 不传可信 merchant_id，不传可信 allowed_category_keys，不直连 Milvus |
| 9000 | 登录、权限、商户上下文、企业号归属、Agent 绑定、可信代理、安全门禁 | 不做向量检索，不直连 Milvus，不训练大模型 |
| 9100 | RAG runtime、向量化、VectorStore、LLM 回复建议 | 不信任前端上下文，不管理 NewCar 权限，不决定真实发送 |
| Milvus | 向量存储和近似向量检索 | 不承载业务权限，不决定商户范围，不暴露给前端 |

## 5. VectorStore 抽象设计

后续在 9100 内引入最小 VectorStore 抽象，默认实现仍为 SQLite。

建议接口：

```python
class VectorStore:
    def upsert_chunks(self, chunks: list[VectorChunk]) -> UpsertResult: ...
    def search(self, request: VectorSearchRequest) -> list[VectorSearchItem]: ...
    def deactivate_document(self, document_id: str, scope: VectorScope) -> None: ...
    def deactivate_scope(self, scope: VectorScope) -> None: ...
```

设计原则：

1. `SqliteVectorStore` 复用当前 `knowledge_chunks.embedding_json` 和 `cosine_similarity`。
2. `MilvusVectorStore` 只在 `RAG_VECTOR_BACKEND=milvus` 时启用。
3. 上层 `reply_decision_service` 只依赖 `repository.search()` 或后续 `VectorStore.search()`，不关心底层是 SQLite 还是 Milvus。
4. 配置缺失时不影响本地开发启动；只有显式 `RAG_VECTOR_BACKEND=milvus` 且 Milvus 关键配置缺失时才报配置错误。
5. Milvus 查询失败时可以降级到 SQLite 或 direct LLM，但不得放宽自动发送 gate。

建议配置：

```text
RAG_VECTOR_BACKEND=sqlite|milvus
MILVUS_URI=
MILVUS_USERNAME=
MILVUS_PASSWORD=
MILVUS_DB_NAME=
MILVUS_COLLECTION=xg_douyin_ai_cs_chunks
MILVUS_DIMENSION=
MILVUS_TIMEOUT_SECONDS=3
MILVUS_INDEX_TYPE=HNSW
MILVUS_METRIC_TYPE=COSINE
```

默认值必须保持 `RAG_VECTOR_BACKEND=sqlite`。

## 6. Milvus Collection / Schema 设计

推荐使用单 collection + metadata filter，而不是每商户一个 collection。

推荐理由：

1. collection 数量可控，运维简单。
2. 便于保留系统级 base 知识。
3. 便于统一索引、统一备份、统一灰度。
4. 后续多商户扩展不需要动态建大量 collection。

必须约束：

1. 所有 search 必须带 `tenant_id` / `merchant_id` / `category_key` 等过滤条件。
2. 禁止裸搜全库。
3. `allowed_category_keys=[]` 不能退化为全库搜索。
4. Milvus metadata filter 只是技术执行层，业务范围仍由 9000 注入。

建议字段：

| 字段 | 类型建议 | 用途 |
|---|---|---|
| vector_id | VarChar 主键 | 全局唯一向量 ID，建议 `chunk:{chunk_id}` 或稳定 UUID |
| embedding | FloatVector | 向量 |
| chunk_text | VarChar / JSON metadata | chunk 原文，建议限制长度 |
| document_id | VarChar | 文档 ID |
| chunk_index | Int64 | 文档内切片序号 |
| tenant_id | VarChar | 租户 / 来源系统 |
| merchant_id | VarChar | 商户隔离 |
| douyin_account_id | VarChar | 企业号隔离，可选但推荐保留 |
| agent_id | VarChar | 后续 Agent 专属知识可用，当前可为空 |
| category_key | VarChar | Agent 知识范围过滤主字段 |
| category_id | VarChar | 历史兼容，可选 |
| source_type | VarChar | manual / qa / import / system |
| source_title | VarChar | 来源标题 |
| source_hash | VarChar | 文档来源 hash |
| content_hash | VarChar | chunk 内容 hash，用于幂等 |
| status | VarChar | active / inactive / deleted |
| created_at | Int64 | 创建时间戳 |
| updated_at | Int64 | 更新时间戳 |

索引建议：

| 项 | 建议 |
|---|---|
| metric | COSINE，与当前余弦相似度语义一致 |
| index | HNSW 或 IVF_FLAT，首期可按数据量压测后确认 |
| partition | 首期不按商户分区，避免分区爆炸 |
| filter | `tenant_id == ... and merchant_id == ... and status == "active" and category_key in [...]` |

## 7. Metadata 与隔离设计

查询 scope 必须来自可信链路：

```text
前端
  -> 不传可信 merchant_id / allowed_category_keys
9000 RequestContext
  -> merchant_id / source_system
9000 Agent 绑定
  -> allowed_category_keys / rag_enabled
9100
  -> 只消费 9000 注入值
Milvus
  -> 执行 metadata filter
```

隔离规则：

1. `tenant_id` 表示来源系统，当前主要是 `new_car_project`。
2. `merchant_id` 是商户隔离硬条件，缺失时拒绝检索或降级为空结果，不允许全库搜索。
3. `category_key` 是知识范围过滤硬条件，来自 Agent 绑定。
4. `agent_id` 当前不作为硬过滤条件，后续如支持 Agent 私有知识再加入。
5. `douyin_account_id` 当前链路已存在，建议继续作为企业号隔离条件之一；是否必选取决于知识库是否允许商户级共享。
6. base 分类是否默认包含由 9000 的 Agent 绑定策略决定，Milvus 不自行决定。

缺失处理：

| 缺失项 | 建议行为 |
|---|---|
| merchant_id 缺失 | 拒绝或返回空 RAG，记录 `fallback_reason=merchant_context_missing` |
| allowed_category_keys 为空列表 | 不查 Milvus，`source_chunks=[]`，`rag_used=false` |
| rag_enabled=false | 不查 Milvus，不查 SQLite，允许 direct LLM 但仍走安全后处理 |
| category_key 不可见 | 由 9000 在绑定 / 配置阶段拦截 |

## 8. 训练 / Ingestion 流程

目标流程：

```text
管理员提交知识内容
  -> 9000 IP 白名单 / 管理员边界
  -> 9000 转发 9100
  -> 9100 标准化文档
  -> 计算 document_hash / source_hash
  -> chunk 切片
  -> 对 chunk 计算 content_hash
  -> embedding
  -> upsert SQLite metadata
  -> upsert Milvus vector
  -> 返回 training_run_id / document_count / chunk_count / status
```

新增文档：

1. 标准化 title / content / category_key / source_type。
2. 写入 SQLite `knowledge_documents`。
3. 切片后写入 SQLite `knowledge_chunks` metadata。
4. 写入 Milvus collection。
5. training_run 状态为 `completed`。

更新文档：

1. 根据 `document_id` 或 `source_hash` 找到旧文档。
2. 新内容生成新 `content_hash`。
3. 旧 chunk 标记 `inactive`。
4. 新 chunk upsert。
5. Milvus 旧向量 status 改为 `inactive` 或按 `document_id` 删除后重写。

删除文档：

1. SQLite `knowledge_documents.is_active=0`。
2. SQLite `knowledge_chunks.is_active=0`。
3. Milvus 对应 `document_id` 标记 `status=inactive`，不建议首期物理删除。

重训分类：

1. scope 包含 `tenant_id + merchant_id + category_key`。
2. 只重建该分类 active 文档。
3. Milvus filter 同步按 scope 置旧向量 inactive。

全量重训：

1. scope 至少包含 `tenant_id + merchant_id`。
2. 不允许无 merchant_id 的全库重训。
3. 先写新向量，再切换 active 状态，降低中间态影响。

一致性策略：

| 场景 | 建议 |
|---|---|
| SQLite 成功、Milvus 失败 | training_run 标记 partial_failed，SQLite 可作为 fallback |
| Milvus 成功、SQLite 失败 | 回滚本次 Milvus upsert 或标记 inactive |
| 单 chunk embedding 失败 | 记录失败数量，训练 run failed 或 partial_failed，不静默吞掉 |
| 重复提交 | `content_hash` 幂等 upsert |

## 9. 搜索 / Reply-Suggestion 流程

```text
9000
  -> 校验权限、商户、企业号、Agent
  -> 注入 allowed_category_keys
  -> 注入 rag_enabled
9100
  -> 如果 rag_enabled=false：不查向量库
  -> 如果 category_keys 为空：不查向量库
  -> query embedding
  -> VectorStore.search()
  -> metadata filter
  -> score threshold / rerank
  -> prompt context
  -> LLM
  -> 结构化回复建议
9000
  -> 强制 auto_send=false
  -> 记录 AI 回复决策日志
```

返回字段继续兼容当前语义：

| 字段 | 说明 |
|---|---|
| reply_text | 建议回复 |
| source_chunks | 检索命中的 chunk |
| rag_sources | 结构化来源 |
| rag_used | 是否使用 RAG |
| match_level | 命中等级 |
| manual_required | 是否需要人工确认 |
| auto_send | 继续保持 false 或由 9000 强制 false |

安全要求：

1. `category_keys` 过滤不能丢。
2. `allowed_category_keys=[]` 不能搜索全库。
3. `rag_enabled=false` 不查 Milvus。
4. direct LLM fallback 不能变成自动发送放行。
5. source_chunks 返回前端时建议截断文本，避免大段敏感内容泄露。

## 10. 权限、商户隔离与安全

1. 前端不能传入可信 `merchant_id` 影响检索范围。
2. 9000 使用 `RequestContext.merchant_id` 注入商户。
3. 9000 校验 `auto_wechat:douyin_ai_cs`、企业号归属和 Agent 绑定。
4. 9000 注入 `allowed_category_keys`，不接受前端覆盖。
5. 9100 只信任 9000 注入的 `agent_config` 和 scope。
6. 9100 遇到缺失 `merchant_id` 或空分类过滤时不得查全库。
7. Milvus 账号密码只存在 9100 环境变量，不进入前端和 9000；甲方当前提供的是 username/password 鉴权模式。
8. 生产环境 Milvus 必须走内网或私网，不建议公网暴露。
9. 日志不得打印完整客户私信、手机号、微信号、完整 prompt、Milvus 密码。
10. source_chunks 返回给前端时建议保留标题、chunk_id、短摘要和 score，不直接返回超长原文。

## 11. Fallback 策略

| 场景 | 行为 |
|---|---|
| `RAG_VECTOR_BACKEND=sqlite` | 使用当前 SQLite 向量检索和词法 fallback |
| `RAG_VECTOR_BACKEND=milvus` 且配置完整 | 优先 Milvus |
| Milvus 查询超时 | 记录 `fallback_reason=milvus_timeout`，降级 SQLite 或 direct LLM |
| Milvus 返回异常 | 记录 `fallback_reason=milvus_error`，降级 SQLite 或 direct LLM |
| query embedding 失败 | 保留当前词法 fallback 或 direct LLM |
| SQLite fallback 也失败 | `source_chunks=[]`，`rag_used=false`，走 direct LLM 安全后处理 |

自动发送门禁不受 fallback 影响：任何 fallback 都不能放宽 `auto_send=false`、manual_required、风险标记和 9000 后处理。

## 12. 可观测性

建议指标：

| 指标 | 说明 |
|---|---|
| training_run_id | 训练批次 |
| document_count | 本次文档数 |
| chunk_count | 本次 chunk 数 |
| embedding_count | 向量化数量 |
| milvus_upsert_count | Milvus 写入数量 |
| milvus_search_latency_ms | Milvus 检索耗时 |
| milvus_top_k | top_k |
| rag_hit_count | RAG 命中次数 |
| rag_miss_count | RAG 未命中次数 |
| fallback_reason | fallback 原因 |
| source_chunk_count | 返回来源数量 |
| category_filter_keys | 分类过滤数量或脱敏摘要 |
| vector_backend | sqlite / milvus |

日志要求：

1. 训练链路带 `training_run_id`。
2. 搜索链路带 `request_id` 或当前请求追踪 ID。
3. 只记录 scope 摘要、数量、耗时、状态，不记录敏感明文。
4. 错误日志不要包含完整 prompt、完整私信、token、Authorization。

## 13. 部署配置

建议部署清单：

| 配置项 | development | staging | production |
|---|---|---|---|
| RAG_VECTOR_BACKEND | sqlite | sqlite 或 milvus | 显式配置，灰度期建议 milvus |
| MILVUS_URI | 可空 | 必填于 milvus | 必填 |
| MILVUS_USERNAME | 可空 | 按环境配置 | 必填 |
| MILVUS_PASSWORD | 可空 | 按环境配置 | 必填，禁止写入代码和日志 |
| MILVUS_DB_NAME | 可空 | 建议独立库 | 必填 |
| MILVUS_COLLECTION | 默认 `xg_douyin_ai_cs_chunks` | 显式配置 | 显式配置 |
| MILVUS_DIMENSION | 可空 | 必须匹配 embedding 模型 | 必须匹配 embedding 模型 |
| MILVUS_METRIC_TYPE | COSINE | COSINE | COSINE |
| MILVUS_INDEX_TYPE | HNSW 或 IVF_FLAT | 压测后确认 | 压测后确认 |
| MILVUS_TIMEOUT_SECONDS | 3 | 3 到 5 | 3 到 5 |

上线前要求：

1. 本地默认仍为 SQLite。
2. staging 可开启 Milvus 做 E2E。
3. production 开启前必须完成搜索 E2E、fallback 演练和回滚方案。
4. collection 初始化脚本要可重复执行。
5. 备份策略覆盖 Milvus collection 和 SQLite metadata。
6. Milvus 不可用时 9100 不应整体不可用，除非显式选择 fail-fast 策略。

## 14. 风险与待确认项

| 风险 / 待确认 | 影响 | 建议 |
|---|---|---|
| embedding 维度未固定 | Milvus collection dimension 一旦建错需重建 | 上线前确认 embedding 模型和维度 |
| category filter 丢失 | 可能跨知识范围检索 | VectorStore.search 强制校验 category_keys |
| merchant_id 缺失 | 可能跨商户 | 缺失即拒绝或空结果 |
| Milvus 与 SQLite 不一致 | 结果不稳定 | training_run 记录 upsert 状态，支持重训修复 |
| source_chunks 过长 | 前端泄露敏感内容 | 返回摘要或截断 |
| Milvus 公网暴露 | 凭据和数据风险 | 生产走内网 / 私网 / TLS |
| “训练”被误解为训练大模型 | 甲方预期偏差 | 对外统一解释为维护知识库并写入向量库 |

## 15. 后续任务拆分

1. `P1-RAG-VECTORSTORE-ABSTRACTION-1`
   - 在 9100 抽象 `VectorStore`。
   - 默认 SQLite 实现保持当前行为。
   - 不接真实 Milvus。

2. `P1-RAG-MILVUS-CONFIG-SCAFFOLD-1`
   - 增加 Milvus 配置读取和校验。
   - 默认 `sqlite`。
   - 配置缺失时仅在显式 `milvus` 模式报错。

3. `P1-RAG-MILVUS-COLLECTION-INIT-1`
   - 设计并实现 collection 初始化脚本。
   - 支持幂等创建、字段校验、索引校验。

4. `P1-RAG-MILVUS-UPsert-INGESTION-1`
   - 训练时同步写 SQLite metadata 和 Milvus。
   - 覆盖新增、更新、删除、重训、partial_failed。

5. `P1-RAG-MILVUS-SEARCH-FALLBACK-1`
   - reply-suggestion 优先 Milvus。
   - Milvus 失败 fallback SQLite / direct LLM。
   - 保持 `auto_send=false`。

6. `P1-RAG-MILVUS-SECURITY-OBSERVABILITY-1`
   - 强制 scope/filter 校验。
   - 增加指标和脱敏日志。
   - 覆盖 category_keys 为空不查全库。

7. `P1-RAG-MILVUS-STAGING-E2E-1`
   - staging 连接真实 Milvus。
   - 验证训练、检索、fallback、回滚。

## 16. 本轮未改内容

1. 未修改业务代码。
2. 未新增 migration。
3. 未修改 `/knowledge-training/ask` 和 `/knowledge-training/{training_id}/feedback` schema。
4. 未修改 NewCar 登录。
5. 未修改 live-check。
6. 未修改 Local Agent / 19000。
7. 未修改自动发送 gate。
8. 未调用真实 Milvus。
9. 未调用真实 LLM。
10. 未上传真实客户数据。

## 17. 验证

本轮为 docs-only 任务，验证方式：

```bash
git diff --check
```

## 18. P1-RAG-MILVUS-CONFIG-ADAPTER-SKELETON-1

### 18.1 本轮目标

本轮在 9100 抖音 AI 小高客服服务中落地 Milvus 接入底座，只做配置项、向量库抽象和可测试工厂，不切换当前生产检索结果，不连接真实 Milvus，不做 collection 初始化，不做真实 upsert/search。

### 18.2 新增配置项

新增 9100 RAG 向量库后端配置：

```text
RAG_VECTOR_BACKEND=sqlite|milvus
MILVUS_URI=
MILVUS_USERNAME=
MILVUS_PASSWORD=
MILVUS_DB_NAME=
MILVUS_COLLECTION=
MILVUS_DIMENSION=
MILVUS_TIMEOUT_SECONDS=
MILVUS_INDEX_TYPE=
MILVUS_METRIC_TYPE=
```

默认值仍为 `RAG_VECTOR_BACKEND=sqlite`。sqlite 模式下，`MILVUS_*` 可以为空，也不要求安装 `pymilvus`。只有显式设置 `RAG_VECTOR_BACKEND=milvus` 时，才校验 `MILVUS_URI`、`MILVUS_USERNAME`、`MILVUS_PASSWORD`、`MILVUS_COLLECTION`、`MILVUS_DIMENSION` 和 `pymilvus` 依赖。

甲方当前提供 Milvus username/password 鉴权模式；账号密码只进入 9100 环境变量，前端和 9000 不接触。配置错误不会打印 `MILVUS_PASSWORD`。

### 18.3 VectorStore 抽象位置

新增文件：

```text
apps/xg_douyin_ai_cs/services/vector_store.py
```

当前包含：

1. `VectorStore` 协议。
2. `SQLiteVectorStore`：默认实现，`search()` 继续代理现有 `rag.repository.search()`，保持 SQLite 行为不变。
3. `MilvusVectorStore`：骨架实现，只做配置和依赖门禁；`search` / `upsert_chunks` / `delete_document` 均明确未实现，不会假成功。
4. `get_vector_store(settings)`：根据 `RAG_VECTOR_BACKEND` 返回对应实现。

### 18.4 当前行为

`RAG_VECTOR_BACKEND=sqlite` 时，现有 RAG 搜索、reply-suggestion、`source_chunks`、`rag_sources`、`allowed_category_keys`、`rag_enabled=false` 等行为保持原路径，不经过真实 Milvus。

`RAG_VECTOR_BACKEND=milvus` 时，本轮只允许进入骨架门禁：

1. 缺少必要配置时报 `MILVUS_CONFIG_MISSING`。
2. 未安装 `pymilvus` 时报 `MILVUS_DEPENDENCY_MISSING`。
3. 配置和依赖都满足后也不连接 Milvus，真实连接留给后续 collection 初始化任务。

### 18.5 本轮未实现

1. 未新增 Milvus collection。
2. 未连接真实 Milvus。
3. 未做真实 Milvus upsert。
4. 未做真实 Milvus search。
5. 未把 reply-suggestion 主链路切换到 Milvus。
6. 未修改 `/knowledge-training/ask` 和 `/feedback` schema。
7. 未修改 9000、前端、NewCar 登录、live-check、Local Agent / 19000、自动发送 gate。

### 18.6 下一步任务

建议后续拆分为：

1. `P1-RAG-MILVUS-COLLECTION-INIT-1`：在 staging 中实现幂等 collection 初始化和 schema 校验。
2. `P1-RAG-MILVUS-UPSERT-INGESTION-1`：训练链路写入 SQLite metadata 后同步 upsert Milvus。
3. `P1-RAG-MILVUS-SEARCH-FALLBACK-1`：在显式 Milvus backend 下接入 search，并保留 SQLite / direct LLM fallback。
4. `P1-RAG-MILVUS-SECURITY-OBSERVABILITY-1`：补充 scope/filter 强制校验、耗时指标和脱敏日志。
## 19. P1-RAG-MILVUS-COLLECTION-INIT-1

### 19.1 本轮目标

本轮在 9100 RAG 服务内补齐 Milvus collection 初始化、schema 校验和连接探测能力。默认仍为 `RAG_VECTOR_BACKEND=sqlite`，sqlite 模式不连接 Milvus，不要求安装 `pymilvus`，也不改变现有 RAG / reply-suggestion 检索链路。

真实 Milvus URI、用户名、密码只允许放在本地 `.env`、容器环境变量或部署平台环境变量中，不写入仓库、文档、测试、日志或提交信息。

### 19.2 collection schema

当前采用单 collection + metadata filter 设计，collection 名称来自 `MILVUS_COLLECTION`，向量维度来自 `MILVUS_DIMENSION`。

| 字段 | 类型 | 说明 |
|---|---|---|
| chunk_id | VarChar 主键 | chunk 唯一标识，max_length=128 |
| embedding | FloatVector | 向量字段，dim=`MILVUS_DIMENSION` |
| chunk_text | VarChar | chunk 文本，max_length=4096 |
| document_id | VarChar | 文档标识 |
| chunk_index | Int64 | 文档内 chunk 序号 |
| tenant_id | VarChar | 租户隔离字段 |
| merchant_id | VarChar | 商户隔离字段 |
| douyin_account_id | VarChar | 抖音企业号范围字段，可为空字符串 |
| category_key | VarChar | 知识范围过滤字段 |
| category_id | VarChar | 可选分类标识，可为空字符串 |
| source_type | VarChar | 来源类型 |
| source_title | VarChar | 来源标题 |
| source_hash | VarChar | 来源哈希 |
| content_hash | VarChar | 内容哈希 |
| status | VarChar | chunk 状态，后续 search 只允许 active |
| created_at | Int64 | Unix timestamp |
| updated_at | Int64 | Unix timestamp |

可空字段先使用空字符串兼容，暂不依赖高版本 Milvus nullable / JSON 能力。

### 19.3 index / metric 策略

`MILVUS_INDEX_TYPE` 和 `MILVUS_METRIC_TYPE` 继续由环境变量控制。当前默认沿用上一轮配置骨架：`MILVUS_INDEX_TYPE=AUTOINDEX`，`MILVUS_METRIC_TYPE=COSINE`。本轮只做可初始化能力，不追求压测后的最优索引参数。

### 19.4 check / init 入口

新增内部 CLI：

```bash
python -m apps.xg_douyin_ai_cs.scripts.milvus_collection_check --check
python -m apps.xg_douyin_ai_cs.scripts.milvus_collection_check --init
```

行为：

1. `--check` 只检查 collection，不创建。
2. `--init` 在 collection 缺失时创建 collection、索引并 load。
3. `RAG_VECTOR_BACKEND` 不是 `milvus` 时只提示 Milvus 未启用，不连接、不创建。
4. 输出只包含 backend、collection_exists、created、schema_match、dimension、metric_type 等脱敏字段。
5. 失败只输出错误码，不输出 password、真实 URI 或真实用户名。

### 19.5 schema mismatch 策略

collection 已存在时会校验：

1. 主键字段 `chunk_id` 存在。
2. 向量字段 `embedding` 存在。
3. `embedding` dimension 与 `MILVUS_DIMENSION` 一致。
4. 关键 metadata 字段存在：`tenant_id`、`merchant_id`、`douyin_account_id`、`category_key`、`status` 等。

schema 不匹配时返回 `MILVUS_SCHEMA_MISMATCH`，不静默继续，避免后续跨商户、跨知识范围或错误维度检索。

### 19.6 本轮未实现

1. 未接入 reply-suggestion 主检索链路。
2. 未实现真实 upsert / search / delete 业务逻辑。
3. 未写入真实业务知识。
4. 未调用真实 LLM。
5. 未修改 9000 业务接口 schema。
6. 未修改 `/knowledge-training/ask` 和 `/feedback` schema。
7. 未修改 NewCar 登录、live-check、Local Agent / 19000 或自动发送 gate。

### 19.7 下一步任务

建议后续拆分：

1. `P1-RAG-MILVUS-UPSERT-INGESTION-1`：训练链路写 SQLite metadata 后同步 upsert Milvus。
2. `P1-RAG-MILVUS-SEARCH-FALLBACK-1`：显式 Milvus backend 下接入 search，并保留 SQLite / direct LLM fallback。
3. `P1-RAG-MILVUS-SECURITY-OBSERVABILITY-1`：补齐 scope/filter 强校验、指标和脱敏日志。
## P1-RAG-MILVUS-CHECK-DIAGNOSTICS-1

本轮只增强 9100 Milvus collection check/init 的脱敏诊断能力，不改变默认 `RAG_VECTOR_BACKEND=sqlite` 行为，不接入真实 upsert/search，不调用真实 LLM。

新增诊断字段：

- `connected`
- `collection_exists`
- `schema_match`
- `phase`
- `error_code`
- `error_type`
- `error_message`

阶段枚举覆盖配置、依赖、连接、collection 查询、schema 校验、索引检查、collection 创建、索引创建和 load。CLI 输出会脱敏异常文本，不打印 `MILVUS_PASSWORD`、完整 `MILVUS_URI` 或真实 `MILVUS_USERNAME`。

当前仍使用 PyMilvus `connections.connect` 旧式 API。弃用提示不是连接失败原因，CLI 已避免该 warning 干扰人工判断；后续如需迁移到新客户端，单独拆分 `P1-RAG-MILVUS-MILVUSCLIENT-MIGRATION-1`。

## P1-RAG-MILVUS-MILVUSCLIENT-PROBE-1

本轮新增 Milvus 连接探测入口：

```bash
python -m apps.xg_douyin_ai_cs.scripts.milvus_collection_check --probe-connect
```

探测只验证连接，不检查 collection，不创建 collection，不写入业务知识，不执行 upsert/search，也不调用 LLM。

新增配置项：

```text
MILVUS_CONNECT_STRATEGY=orm|client_token
```

默认仍为 `orm`，因此现有 `--check` 行为不变。本轮只是为后续把正式 collection check 切换到 `MilvusClient` 连接策略做准备。

`--probe-connect` 当前按顺序探测：

1. `milvus_client_token`：使用 `pymilvus.MilvusClient(uri=..., token="username:password", db_name=..., timeout=...)`，这是甲方 Milvus 当前确认可用的主探测策略。
2. `orm_connections_user_password`：使用 `pymilvus.connections.connect(uri=..., user=..., password=..., db_name=..., timeout=...)`，仅作为旧 ORM API 对照策略。

安全规则：

1. `MILVUS_URI` 必须以 `http://` 或 `https://` 开头，否则返回 `MILVUS_URI_INVALID`。
2. CLI 输出只包含 `strategy`、`connected`、`phase`、`error_code`、`error_type`。
3. 输出和异常脱敏，不打印完整 URI、host、username、password 或拼接后的 token。
4. 真实 Milvus URI、用户名、密码仍只允许放在本地 `.env`、shell 环境变量、容器环境变量或部署平台环境变量中，不写入仓库、文档、测试或提交信息。

未改内容：

1. 默认 `RAG_VECTOR_BACKEND=sqlite` 行为不变。
2. `--check` 仍保持现有 ORM 连接策略，不在本轮切换。
3. 未接入 reply-suggestion 主检索链路。
4. 未实现真实 upsert/search/delete。
5. 未修改 9000、前端、NewCar、live-check、Local Agent / 19000 或自动发送 gate。

## P1-RAG-MILVUS-UPSERT-INGESTION-1

本轮在 9100 RAG 服务中新增 Milvus 写入能力，只覆盖训练后的 chunk 同步写入、按文档范围删除和幂等 upsert，不接入 reply-suggestion 搜索链路。

### upsert 字段映射

训练链路仍先写 SQLite `knowledge_documents` / `knowledge_chunks` / `rag_training_runs`。当 `RAG_VECTOR_BACKEND=milvus` 时，再把本次训练生成的 SQLite chunk 转换为 Milvus row：

| Milvus 字段 | 来源 |
|---|---|
| `chunk_id` | `knowledge_chunks.id` 字符串 |
| `embedding` | 本次 embedding 结果 |
| `chunk_text` | `knowledge_chunks.chunk_text` |
| `document_id` | `knowledge_chunks.document_id` 字符串 |
| `chunk_index` | `knowledge_chunks.chunk_index` |
| `tenant_id` | `knowledge_chunks.tenant_id` |
| `merchant_id` | `knowledge_chunks.merchant_id` |
| `douyin_account_id` | `knowledge_chunks.douyin_account_id` 字符串 |
| `category_key` | `knowledge_chunks.category_key` |
| `category_id` | `knowledge_chunks.category_id` 字符串，空值写空字符串 |
| `source_type` | `knowledge_documents.source_type` |
| `source_title` | `knowledge_documents.title` |
| `source_hash` | 文档内容 hash |
| `content_hash` | `knowledge_chunks.content_hash` |
| `status` | active / inactive |
| `created_at` / `updated_at` | 当前 Unix 秒级时间戳 |

### delete / 更新 / 幂等策略

1. `MilvusVectorStore.upsert_chunks()` 会先复用 `ensure_collection(create_if_missing=False)`，确认 collection 存在、schema 匹配、向量维度匹配。
2. `embedding` 长度必须等于 `MILVUS_DIMENSION`，否则返回 `MILVUS_VECTOR_DIMENSION_MISMATCH`。
3. `chunk_id`、`document_id`、`tenant_id`、`merchant_id`、`category_key` 必须非空，否则返回 `MILVUS_CHUNK_METADATA_MISSING`。
4. 文档更新时，训练链路先调用 `delete_document(document_id, tenant_id, merchant_id)`，再 upsert 新 chunks。
5. `delete_document()` 的过滤条件必须同时包含 `document_id`、`tenant_id`、`merchant_id`，不提供裸删全库能力。
6. 同一个 `chunk_id` 重复 upsert 交给 Milvus upsert 语义覆盖或保持一致。

### sqlite 与 milvus backend 行为

1. `RAG_VECTOR_BACKEND=sqlite`：现有训练、搜索、reply-suggestion 行为不变，不初始化、不调用 Milvus。
2. `RAG_VECTOR_BACKEND=milvus`：训练完成 SQLite chunk/embedding 后，同步写入 Milvus；SQLite metadata 仍保留，后续 search 可继续回退。
3. 本轮不改变 `/rag/train`、`/knowledge-training/ask`、`/feedback` 的请求和响应 schema。

### 失败策略

Milvus delete/upsert 失败时，`train_scope()` 不会返回 completed；`rag_training_runs.status` 会记录为 `failed`，`error` 写入脱敏后的错误摘要。当前不做 silent fallback，避免外部向量库与 SQLite metadata 状态被误判为一致。

### 本轮未接入

1. 未接入 reply-suggestion / auto-reply 搜索链路。
2. 未实现 Milvus search。
3. 未调用真实 LLM。
4. 未写入真实业务知识。
5. 未修改 9000、前端、NewCar、live-check、Local Agent / 19000 或自动发送 gate。

### 测试结果

已通过：

```bash
python -m pytest tests/test_xg_douyin_ai_cs_vector_store.py -q
python -m pytest tests/test_xg_douyin_ai_cs_rag.py -q
python -m pytest tests/test_knowledge_training_api.py -q
python -m pytest tests/test_douyin_ai_cs_proxy.py -q
python -m py_compile apps\xg_douyin_ai_cs\services\vector_store.py apps\xg_douyin_ai_cs\scripts\milvus_collection_check.py
```

下一步建议进入 `P1-RAG-MILVUS-SEARCH-FALLBACK-1`，在显式 Milvus backend 下接入 search，并保留 SQLite / direct LLM fallback。

## P1-RAG-MILVUS-SEARCH-FALLBACK-1

本轮在 9100 RAG 服务中接入 Milvus search。只有 `RAG_VECTOR_BACKEND=milvus` 时才优先走 Milvus；默认 `sqlite` 行为保持不变。

### search 接入点

1. `apps/xg_douyin_ai_cs/rag/repository.py` 继续作为 `/rag/search` 和 reply-suggestion 的统一检索入口。
2. `RAG_VECTOR_BACKEND=sqlite` 时仍走原 SQLite 向量检索和词法 fallback。
3. `RAG_VECTOR_BACKEND=milvus` 时由 `MilvusVectorStore.search()` 检索；失败后回落到 SQLite 原路径。

### metadata filter 规则

Milvus search 表达式强制包含：

1. `tenant_id == 当前请求 tenant_id`
2. `merchant_id == 当前请求 merchant_id`
3. `douyin_account_id == 当前请求 douyin_account_id`
4. `status == "active"`
5. `category_key in allowed_category_keys`

`category_key` 多值使用 Milvus in 表达式，字符串值会做引号和反斜杠转义，避免表达式拼接错误。

### 空分类和 RAG 关闭

1. `category_keys=[]` 或未提供可信分类范围时，Milvus backend 直接返回空结果，不查 Milvus，不裸搜全库。
2. `rag_enabled=false` 仍由 reply-suggestion 层在调用 `repository.search()` 前拦截，因此不会触发 Milvus。
3. `tenant_id` / `merchant_id` 缺失时，Milvus backend 直接返回空结果。

### fallback 策略

1. Milvus search 成功：使用 Milvus 返回的 chunk。
2. Milvus search 抛错或 query embedding 生成失败：记录 `fallback_reason=milvus_search_failed`，回落到 SQLite 检索。
3. fallback 不改变 reply-suggestion 响应 schema，不放宽 `auto_send`、`manual_required` 或 9000 后处理门禁。

### source_chunks / rag_sources 兼容性

Milvus 命中会归一化为既有 `RagSearchItem`，字段继续包含：

1. `chunk_id`
2. `document_id`
3. `title`
4. `chunk_text`
5. `score`

reply-suggestion 仍沿用现有 `source_chunks` / `rag_sources` 映射逻辑，不新增前端字段。

### 本轮未接入

1. 未调用真实 LLM 做测试。
2. 未做真实 Milvus canary search。
3. 未修改 9000 接口 schema。
4. 未修改 `/knowledge-training/ask` 和 `/feedback` schema。
5. 未修改 NewCar、live-check、Local Agent / 19000 或自动发送 gate。

### 测试结果

已通过：

```bash
python -m pytest tests/test_xg_douyin_ai_cs_vector_store.py -q
python -m pytest tests/test_xg_douyin_ai_cs_rag.py -q
python -m pytest tests/test_douyin_ai_cs_proxy.py -q
python -m pytest tests/test_knowledge_training_api.py -q
python -m pytest tests/test_agent_knowledge_categories.py -q
python -m py_compile apps\xg_douyin_ai_cs\services\vector_store.py apps\xg_douyin_ai_cs\scripts\milvus_collection_check.py
```

下一步建议进入 `P1-RAG-MILVUS-CANARY-E2E-VERIFY-1`，使用非业务 synthetic canary 数据做一次真实写入、检索和删除闭环验证。
## P1-RAG-MILVUS-CANARY-E2E-VERIFY-1

本轮新增独立 canary 运行态验证脚本：

```bash
python -m apps.xg_douyin_ai_cs.scripts.milvus_canary_e2e --run
python -m apps.xg_douyin_ai_cs.scripts.milvus_canary_e2e --cleanup-only <canary_document_id>
```

验证范围：

1. 只使用 synthetic canary 文档，不使用真实客户数据、真实销售话术、手机号、微信号或业务知识。
2. 执行顺序为 `collection check -> upsert -> search -> delete -> search_after_delete`。
3. 检索使用同一条 deterministic fake embedding，不调用真实 LLM，不触发 reply-suggestion，不触发 auto-reply。
4. canary 固定 scope 为 `tenant_id=xiaogao_system`、`merchant_id=xiaogao_base`、`douyin_account_id=canary_account`、`category_key=base`。
5. `finally` 中会尽力调用 `delete_document(document_id, tenant_id, merchant_id)`，避免留下 canary 脏数据。

输出脱敏规则：

1. CLI 只输出 `canary_document_id` 的短标识、`connected`、`collection_exists`、`schema_match`、`upsert_ok`、`search_hit`、`delete_ok`、`search_after_delete_hit`、`cleanup_ok`、`phase`、`error_code`、`error_type`。
2. 不输出 Milvus URI、host、username、password、token。
3. 不输出完整 canary chunk 文本。

当前执行状态：

1. 本地 shell 未注入真实 `RAG_VECTOR_BACKEND=milvus`、`MILVUS_URI`、`MILVUS_USERNAME`、`MILVUS_PASSWORD`、`MILVUS_COLLECTION`、`MILVUS_DIMENSION`，因此未执行真实 collection check 和真实 canary 写入。
2. 已完成 fake Milvus 单元测试，覆盖 canary upsert、search 命中、delete、delete 后不命中、异常时 finally cleanup 和 CLI 脱敏输出。
3. 未调用真实 LLM，未触发自动发送，未修改 9000 schema、ask / feedback schema、NewCar、live-check、Local Agent / 19000 或自动发送 gate。

后续在用户本机注入真实 Milvus 环境变量后，可执行：

```bash
python -m apps.xg_douyin_ai_cs.scripts.milvus_collection_check --check
python -m apps.xg_douyin_ai_cs.scripts.milvus_canary_e2e --run
```

预期脱敏结果为：

```text
connected=True
collection_exists=True
schema_match=True
upsert_ok=True
search_hit=True
delete_ok=True
search_after_delete_hit=False
cleanup_ok=True
```

## P1-RAG-MILVUS-CANARY-DELETE-VISIBILITY-VERIFY-1

本轮修复 Milvus canary E2E 工具的删除后验证与可清理性问题，不修改业务 RAG search、9000 schema、默认 sqlite 行为、reply-suggestion 或自动发送链路。

### 修复内容

1. `canary_document_id` 改为完整输出。该 ID 是 synthetic 测试 ID，不属于 Milvus 凭据，方便后续 `--cleanup-only` 精确清理。
2. `--run` 新增可选参数 `--document-id <id>`，用于复测同一个 synthetic 文档或保留可清理 ID。
3. `--cleanup-only <document_id>` 会按固定 canary scope 调用 `delete_document(document_id, tenant_id, merchant_id)`，并在删除后重新 search 验证当前 document_id 不再命中。
4. delete 后验证从单次 search 改为最多 5 次重试，每次间隔 1 秒；只要当前 canary 不再命中，即认为 `search_after_delete_hit=False`。
5. `search_after_delete_hit` 只基于当前 canary 的 `document_id` / `chunk_id` 判断，不再用 marker 文本、category_key 或 source_type 做宽泛判断。
6. `cleanup_ok=True` 仅表示 delete 调用成功且最终验证不再命中；如果 delete 成功但 5 次后仍命中，返回 `phase=verify_delete`、`error_code=CANARY_DELETE_NOT_VISIBLE`、`cleanup_verified=False`、`cleanup_ok=False`。

### 输出字段

CLI 继续只输出脱敏运行态字段：

```text
connected
collection_exists
schema_match
canary_document_id
upsert_ok
search_hit
delete_ok
search_after_delete_hit
cleanup_ok
cleanup_verified
delete_verify_attempts
phase
error_code
error_type
```

仍禁止输出 Milvus URI、host、username、password、token 和完整 canary chunk 文本。

### 测试结果

已补充 fake Milvus 单元测试覆盖：

1. 完整输出 `canary_document_id`。
2. `--document-id` 复用指定 synthetic ID。
3. `--cleanup-only` 使用完整 document_id。
4. delete 后第一次 search 仍命中、第二次不命中时最终 `cleanup_ok=True`。
5. delete 后 5 次仍命中时最终 `cleanup_ok=False`。
6. marker 文本不再作为 canary 命中依据。
7. CLI 输出不包含 URI、host、username、password、token 或完整 chunk 文本。

## P1-RAG-MILVUS-CANARY-UPSERT-SEARCH-VISIBILITY-FIX-1

本轮修复真实 Milvus canary E2E 中 `upsert_ok=True` 但 `search_hit=False` 的验证问题，不修改 9000 schema、不改变默认 sqlite 行为、不触发 reply-suggestion / auto-reply、不调用真实 LLM。

### 根因

canary 写入时使用 `canary_doc_...` / `canary_chunk_...` 这类 synthetic 字符串 ID；但 Milvus search 统一返回 `RagSearchItem` 时会把 `document_id` / `chunk_id` 转为整型。字符串 ID 转换失败后变成 `0`，导致 canary 脚本无法用当前 document_id / chunk_id 判断命中。

### 修复内容

1. canary search 显式请求保留原始字符串 ID，仅用于 canary 验证；正常 RAG search 仍保持既有 `RagSearchItem` 返回结构。
2. upsert 后增加 search 可见性重试，最多 5 次，每次间隔 1 秒；只要当前 canary `document_id` 或 `chunk_id` 命中，即 `search_hit=True`。
3. canary embedding 保持 deterministic 非零向量，长度等于 `MILVUS_DIMENSION`，避免 COSINE / IP / L2 自检索时被全零向量影响。
4. canary search 使用固定 scope：`tenant_id=xiaogao_system`、`merchant_id=xiaogao_base`、`douyin_account_id=canary_account`、`category_key=base`，与 upsert metadata 一致。
5. canary search `top_k=10`，不设置额外 score threshold。
6. 如果 search 返回非空但缺少 `document_id` / `chunk_id`，输出脱敏诊断字段：`result_count`、`has_document_id_field`、`has_chunk_id_field`，不输出完整 chunk 文本。
7. 如果 5 次 search 后仍未命中，返回 `phase=verify_search`、`error_code=CANARY_SEARCH_NOT_VISIBLE`，但仍继续执行 delete 和 delete 后可见性验证。

### 未改内容

1. 未改业务 RAG search 主链路。
2. 未改 9000 接口 schema。
3. 未改 `/knowledge-training/ask` 和 `/feedback` schema。
4. 未改默认 `RAG_VECTOR_BACKEND=sqlite` 行为。
5. 未调用真实 LLM。
6. 未触发 reply-suggestion、auto-reply 或真实发送。
7. 未写入真实业务数据。

### 验证口径

真实 Milvus 环境变量只允许通过本地 shell / 部署环境注入。运行：

```bash
python -m apps.xg_douyin_ai_cs.scripts.milvus_canary_e2e --run
```

通过标准：

```text
connected=True
collection_exists=True
schema_match=True
upsert_ok=True
search_hit=True
delete_ok=True
search_after_delete_hit=False
cleanup_verified=True
cleanup_ok=True
```

## P1-AI-CS-RAG-AUTOREPLY-TRAINING-WORKFLOW-1

本轮验证并收口“AI 客服知识训练 -> Milvus 写入 -> reply-suggestion 检索 source_chunks -> 生成建议回复”的 workflow。测试全部使用 fake Milvus 和 fake LLM，不连接真实 Milvus，不调用真实 LLM，不触发 reply-suggestion 之外的自动回复或真实发送。

### 训练到 Milvus 工作流

workflow 测试通过 `repository.create_document()` 写入 synthetic 非业务知识，再通过 `repository.train_scope()` 生成 chunk / embedding。`RAG_VECTOR_BACKEND=milvus` 时，训练链路会调用同一个 fake VectorStore：

1. `delete_document(document_id, tenant_id, merchant_id)` 清理旧向量范围。
2. `upsert_chunks(chunks)` 写入本次训练 chunk。
3. SQLite metadata 继续保留，作为后续 fallback 和审计基础。

训练失败策略保持不变：Milvus upsert 抛错时 training run 记录 failed，不假成功。

### reply-suggestion 消费 Milvus source_chunks

workflow 测试使用同一个 fake VectorStore 保存训练 chunk，随后调用 `build_reply_suggestion()`。当 `agent_config.rag_enabled=true` 且 `allowed_category_keys=["base"]` 时，reply-suggestion 会调用 `repository.search()`，再命中刚训练的 synthetic 文档，并返回兼容既有结构的：

1. `source_chunks`
2. `rag_sources`
3. `rag_used=true`
4. `llm_used=true`

响应 schema 未改变，`source_chunks` / `rag_sources` 仍包含 `chunk_id`、`document_id`、`title`、`score` 等既有字段。

### allowed_category_keys / rag_enabled 安全边界

本轮新增 workflow 测试覆盖：

1. `allowed_category_keys=["base"]`：可命中 base synthetic 文档。
2. `allowed_category_keys=[]`：不查 Milvus，`source_chunks=[]`。
3. `allowed_category_keys=["other"]`：会按 other 分类查询，但不能命中 base 知识。
4. `rag_enabled=false`：不查 Milvus，`source_chunks=[]`。

Milvus search 失败时继续 fallback 到 SQLite，日志包含 `fallback_reason=milvus_search_failed`，且不会把 direct LLM fallback 当成 RAG 命中。

### auto_send gate 收口

本轮发现并修复一个正式 Agent fallback 缺口：带 `agent_config` 的正式 AI 客服链路在 RAG 未命中、分类为空或 `rag_enabled=false` 时会走 direct LLM fallback，旧逻辑可能返回 `auto_send=true`。现在 `reply_decision_service` 会在带 `agent_config` 的 direct fallback 响应上强制：

1. `auto_send=false`
2. `manual_required=true`
3. `manual_required_reason=RAG未命中或关闭，需要人工确认`
4. `risk_flags` 增加 `agent_config_fallback_auto_send_blocked`

该收口不改变 9000 对外接口 schema，不改变 `/knowledge-training/ask` 和 `/feedback` schema，不改默认 sqlite 行为，也不放开任何真实发送链路。

### 测试结果

已通过：

```bash
python -m pytest tests/test_xg_douyin_ai_cs_rag_workflow.py -q
python -m pytest tests/test_xg_douyin_ai_cs_rag.py -q
python -m pytest tests/test_douyin_ai_cs_proxy.py -q
python -m pytest tests/test_knowledge_training_api.py -q
python -m pytest tests/test_xg_douyin_ai_cs_vector_store.py -q
```

本轮未做真实 synthetic Milvus 验证；真实 canary 已在前置任务完成。本轮未写入真实业务知识，未调用真实 LLM，未触发真实私信发送。

下一步建议：如要继续推进自动回复训练工作流，应单独进入托管 dry-run / 自动发送 gate 审计任务，不与 RAG workflow 验证混合。

## P1-AUTOREPLY-DRYRUN-GATE-AUDIT-1

本轮系统审计 AI 客服自动回复 gate，覆盖 reply-suggestion、RAG 命中、RAG 未命中、Milvus fallback、direct LLM fallback、dry-run candidate 和 real-send candidate。测试全部使用 fake LLM / fake sender / fake Milvus，不连接真实 Milvus，不调用真实 LLM，不触发真实私信发送。

### gate 链路

1. `reply-suggestion`：9100 `build_reply_suggestion()` 只生成建议回复，不直接发送私信。
2. webhook dry-run 编排：9000 `run_ai_auto_reply_dry_run()` 读取企业号绑定、账号自动回复配置、会话状态和 Agent 知识范围，再调用 9100。
3. post-LLM gate：9000 `evaluate_post_llm_gates()` 统一判断 `manual_required`、`risk_flags`、`fallback_reason`、RAG、source、confidence、intent 和账号发送开关。
4. real-send gate：只有 `run.mode=real_send_candidate` 且 decision log `final_auto_send=1` 时，`send_ai_auto_reply_for_run()` 才会继续检查全局开关、真实发送开关、rollout / whitelist、账号配置、绑定、人工接管、最新消息和 send context。
5. 最终 sender：真实发送入口仍是 `douyin_private_message_send_service._send_private_message_with_context()`；本轮测试只用 fake OpenAPI sender。

### dry-run 与 real-send 边界

dry-run 可以生成 run、decision log 和 would-send 候选，但不能调用真实 sender，也不能把消息状态改成 sent。real-send candidate 必须同时满足：

1. 账号 `enabled=true`、`send_enabled=true`、`dry_run_enabled=false`。
2. 9100 返回 `auto_send=true`、`manual_required=false`。
3. `rag_used=true`，且 `rag_sources` / `source_chunks` 有命中。
4. 无 `fallback_reason`、无 `risk_flags`。
5. `confidence >= min_confidence`。
6. allowed intent 命中或未配置 intent 限制。
7. 全局自动回复、真实发送、rollout / whitelist 和会话 send context 全部通过。

### 阻断规则

以下路径会阻断真实发送候选，`send_ai_auto_reply_for_run()` 不会被调用，或真实发送服务返回 `send_skipped`：

1. `manual_required=true`。
2. `risk_flags` 非空。
3. `fallback_reason` 存在，例如 `milvus_search_failed`。
4. `require_rag=true` 且 `rag_used!=true`。
5. `require_rag_sources=true` 且 source 为空。
6. `confidence < min_confidence`。
7. configured allowed intents 不命中。
8. `account.send_enabled=false`。
9. 上游未明确返回 `auto_send=true`。
10. dry-run 模式。
11. 全局真实发送 gate、白名单、人工接管、最新消息、send context 任一不通过。

### 正向放行

新增正向测试覆盖：RAG 命中 `source_chunks`、fake LLM 返回 `auto_send=true/manual_required=false`、全局和账号 gate 均开启、full rollout 允许、会话未人工接管、send context 合法、`dry_run=false`。预期结果：

1. `run.mode=real_send_candidate`。
2. `run.status=sent`。
3. `decision_log.final_auto_send=1`。
4. `gate_results.real_send.send_gate_passed=true`。
5. fake sender 被调用一次。
6. 不调用真实上游 sender。

### 未改内容

1. 未改 9000 对外 schema。
2. 未改 `/knowledge-training/ask` 和 `/feedback` schema。
3. 未改 NewCar、live-check、Local Agent / 19000。
4. 未改默认 sqlite RAG 行为。
5. 未连接真实 Milvus。
6. 未调用真实 LLM。
7. 未触发真实私信发送。

### 测试结果

本轮执行：

```bash
python -m pytest tests/test_ai_auto_reply_dry_run.py -q
python -m pytest tests/test_ai_auto_reply_send_service.py -q
python -m pytest tests/test_xg_douyin_ai_cs_rag_workflow.py -q
```

下一步建议：如要继续推进自动回复真实发送，需要单独做生产环境 rollout / whitelist 配置验收和真实发送审计演练，仍应使用测试账号与人工确认流程。
