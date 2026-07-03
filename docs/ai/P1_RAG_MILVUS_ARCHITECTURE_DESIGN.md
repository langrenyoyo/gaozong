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
MILVUS_TOKEN=
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
7. Milvus token 只存在 9100 环境变量，不进入前端和 9000。
8. 生产环境 Milvus 必须走内网或私网，不建议公网暴露。
9. 日志不得打印完整客户私信、手机号、微信号、完整 prompt、Milvus token。
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
| MILVUS_TOKEN | 可空 | 按环境配置 | 必填或使用内网鉴权 |
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
MILVUS_TOKEN=
MILVUS_DB_NAME=
MILVUS_COLLECTION=
MILVUS_DIMENSION=
MILVUS_TIMEOUT_SECONDS=
MILVUS_INDEX_TYPE=
MILVUS_METRIC_TYPE=
```

默认值仍为 `RAG_VECTOR_BACKEND=sqlite`。sqlite 模式下，`MILVUS_*` 可以为空，也不要求安装 `pymilvus`。只有显式设置 `RAG_VECTOR_BACKEND=milvus` 时，才校验 `MILVUS_URI`、`MILVUS_COLLECTION`、`MILVUS_DIMENSION` 和 `pymilvus` 依赖。

配置错误不会打印 `MILVUS_TOKEN`。

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
