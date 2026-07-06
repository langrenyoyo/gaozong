# P1-RAG-UNIFIED-KB-TRAINING-9100-CONTRACT-CHECK

## 1. 目标与边界

本轮只读核对 auto_wechat 9000 `/knowledge-training/*` 代理能力与 9100 抖音 AI 客服 RAG 服务真实接口契约是否匹配。

本轮结论：

```text
9000 已实现统一知识库训练代理入口。
9100 当前同名前缀 /knowledge-training/* 只实现 ask / feedback。
9100 旧 /rag/* 只覆盖文档创建、scope 训练、search，不能直接匹配 9000 新代理契约。
```

本轮未修改业务代码，未触发真实训练，未连接真实 Milvus / Qdrant，未调用 LLM，未调用抖音发送。

## 2. 审计范围

只读查看文件：

```text
app/services/xg_douyin_ai_cs_client.py
app/routers/knowledge_training.py
tests/test_knowledge_training_unified_api.py
tests/test_knowledge_training_api.py
apps/xg_douyin_ai_cs/main.py
apps/xg_douyin_ai_cs/dependencies.py
apps/xg_douyin_ai_cs/config.py
apps/xg_douyin_ai_cs/routers/knowledge_training.py
apps/xg_douyin_ai_cs/routers/rag.py
apps/xg_douyin_ai_cs/routers/categories.py
apps/xg_douyin_ai_cs/services/knowledge_training_service.py
apps/xg_douyin_ai_cs/rag/models.py
apps/xg_douyin_ai_cs/rag/repository.py
apps/xg_douyin_ai_cs/rag/database.py
apps/xg_douyin_ai_cs/services/vector_store.py
tests/test_xg_douyin_ai_cs_rag.py
tests/test_xg_douyin_ai_cs_rag_workflow.py
docs/ai/06_rag/P1_RAG_UNIFIED_KB_TRAINING_API_CONTRACT_FOR_CAR_PROJECT.md
docs/ai/06_rag/P1_RAG_UNIFIED_KB_TRAINING_9000_API_PROXY.md
docs/ai/06_rag/P1_RAG_UNIFIED_KB_TRAINING_9000_API_RUNTIME_SMOKE.md
```

运行态只读检查：

```text
GET http://127.0.0.1:9100/health
GET http://127.0.0.1:9100/openapi.json
```

未调用训练、search、写入或真实向量服务。

## 3. 9000 client 契约摘要

9000 外部暴露路径均在 `app/routers/knowledge_training.py` 中，调用 9100 均经 `XgDouyinAiCsClient`。

| 能力 | 9000 暴露路径 | 9000 调 9100 路径 | 方法 | 请求字段 | 9000 固定注入 | 禁止透传 | 错误映射 | 测试覆盖 |
|---|---|---|---|---|---|---|---|---|
| categories | `/knowledge-training/categories` | `/knowledge-training/categories` | GET | 无业务 body | `tenant_id`, `merchant_id` | 查询参数 `tenant_id`, `merchant_id` | 4xx 透传 detail，其他 502 脱敏 | 已覆盖 |
| documents list | `/knowledge-training/documents` | `/knowledge-training/documents` | GET | `category_key`, `status`, `keyword`, `page`, `page_size` | `tenant_id`, `merchant_id`, 默认 `category_key=base` | 查询参数 `tenant_id`, `merchant_id` | 同上 | 已覆盖 |
| document detail | `/knowledge-training/documents/{document_id}` | `/knowledge-training/documents/{document_id}` | GET | `document_id` | `tenant_id`, `merchant_id` | 查询参数 `tenant_id`, `merchant_id` | 可透传 `KNOWLEDGE_TRAINING_DOCUMENT_NOT_FOUND` | 已覆盖 |
| document create | `/knowledge-training/documents` | `/knowledge-training/documents` | POST | `title`, `content`, `category_key`, `source_type`, `metadata` | `tenant_id`, `merchant_id`, 默认 `category_key=base` | body `tenant_id`, `merchant_id` | 本地校验 `KNOWLEDGE_TRAINING_INVALID_DOCUMENT` | 已覆盖 |
| document update | `/knowledge-training/documents/{document_id}` | `/knowledge-training/documents/{document_id}` | PUT | `title`, `content`, `category_key`, `metadata` | `tenant_id`, `merchant_id` | body `tenant_id`, `merchant_id` | 本地校验 `KNOWLEDGE_TRAINING_INVALID_DOCUMENT` | 已覆盖 |
| document delete | `/knowledge-training/documents/{document_id}` | `/knowledge-training/documents/{document_id}` | DELETE | `mode`, `reason` | `tenant_id`, `merchant_id` | body `tenant_id`, `merchant_id` | 4xx 透传 detail，其他 502 脱敏 | 已覆盖 |
| document train | `/knowledge-training/documents/{document_id}/train` | `/knowledge-training/documents/{document_id}/train` | POST | `mode`, `dry_run` | `tenant_id`, `merchant_id` | body `tenant_id`, `merchant_id`；P1 禁止 `rebuild_all` | 本地校验 `KNOWLEDGE_TRAINING_INVALID_DOCUMENT` | 已覆盖 |
| training run detail | `/knowledge-training/training-runs/{run_id}` | `/knowledge-training/training-runs/{run_id}` | GET | `run_id` | `tenant_id`, `merchant_id` | 查询参数 `tenant_id`, `merchant_id` | 4xx 透传 detail，其他 502 脱敏 | 已覆盖 |
| training run list | `/knowledge-training/training-runs` | `/knowledge-training/training-runs` | GET | `document_id`, `status`, `page`, `page_size` | `tenant_id`, `merchant_id` | 查询参数 `tenant_id`, `merchant_id` | 4xx 透传 detail，其他 502 脱敏 | 已覆盖 |
| search-preview | `/knowledge-training/search-preview` | `/knowledge-training/search-preview` | POST | `query`, `category_keys`, `top_k` | `tenant_id`, `merchant_id`, 默认 `category_keys=["base"]` | body `tenant_id`, `merchant_id` | 本地校验参数；上游 5xx 转 502 脱敏 | 已覆盖 |

9000 search-preview 已做响应剥离，只保留：

```text
document_id
title
category_key
chunk_text
score
```

因此 fake 9100 返回的 `collection` / `vector_id` / `qdrant` / `milvus` 不会透出。

## 4. 9100 现有 RAG 接口摘要

### 4.1 运行态 OpenAPI

运行中 9100 OpenAPI 只读检查显示与本轮相关的路径为：

```text
/categories
/knowledge-training/ask
/knowledge-training/{training_id}/feedback
/rag/documents
/rag/search
/rag/train
```

未发现：

```text
/knowledge-training/categories
/knowledge-training/documents
/knowledge-training/documents/{document_id}
/knowledge-training/documents/{document_id}/train
/knowledge-training/training-runs
/knowledge-training/search-preview
```

### 4.2 `/knowledge-training/*`

9100 `apps/xg_douyin_ai_cs/routers/knowledge_training.py` 当前只实现：

```text
POST /knowledge-training/ask
POST /knowledge-training/{training_id}/feedback
```

该模块用于训练问答和反馈素材池，不是统一知识库 CRUD / 训练管理接口。

### 4.3 `/rag/*`

9100 `apps/xg_douyin_ai_cs/routers/rag.py` 当前实现：

```text
POST /rag/documents
POST /rag/train
POST /rag/search
```

能力说明：

1. `/rag/documents` 支持文档创建，使用 `KnowledgeDocumentCreate`。
2. `/rag/train` 支持按 `tenant_id + merchant_id + douyin_account_id` 训练整个 scope。
3. `/rag/search` 支持按 `tenant_id + merchant_id + douyin_account_id + category_ids/category_keys` 检索。
4. 不支持文档列表、详情、更新、删除。
5. 不支持单文档 train 路径。
6. 不支持 training_run 详情 / 列表查询路径。
7. 不支持 `/knowledge-training/search-preview` 形态。

### 4.4 `/categories`

9100 还有 `GET /categories`，但它来自 `routers/categories.py`，返回的是固定分类配置，不是 RAG `knowledge_categories` 表，也不接收 `tenant_id / merchant_id`。

9100 RAG repository 中有 `list_categories(tenant_id, merchant_id)`，但当前没有对应 HTTP 路由暴露给 9000 新 client。

## 5. 契约矩阵

| 能力 | 9000 已实现调用 | 9100 是否存在 | 路径是否匹配 | 请求字段是否匹配 | 响应字段是否匹配 | 差距 | 建议 |
|---|---|---|---|---|---|---|---|
| categories | 是 | 部分存在 repository；HTTP 只有 `/categories` | 否 | 否，`/categories` 不接收 scope | 否 | `PATH_MISMATCH`, `REQUEST_SCHEMA_MISMATCH`, `RESPONSE_SCHEMA_MISMATCH` | 9100 新增 `/knowledge-training/categories` 或 9000 adapter 调 repository 专用 API |
| documents list | 是 | 否 | 否 | 否 | 否 | `MISSING_9100_API` | 9100 新增列表接口 |
| document detail | 是 | 否 | 否 | 否 | 否 | `MISSING_9100_API` | 9100 新增详情接口 |
| document create | 是 | `/rag/documents` 存在 | 否 | 否，9000 用 `source_type=manual_text`，9100 当前模型默认 `manual` 且要求 `douyin_account_id` | 部分匹配，9100 返回 int `document_id` + `created` | `PATH_MISMATCH`, `REQUEST_SCHEMA_MISMATCH`, `RESPONSE_SCHEMA_MISMATCH`, `NEEDS_ADAPTER` | 优先新增 9100 `/knowledge-training/documents` adapter，固定 `douyin_account_id=0` 或统一值 |
| document update | 是 | 否 | 否 | 否 | 否 | `MISSING_9100_API` | 9100 新增更新接口，更新后置 draft/需重训状态 |
| document delete | 是 | 否；Milvus store 有 delete_document 能力 | 否 | 否 | 否 | `MISSING_9100_API`, `NEEDS_9100_MINIMAL_API` | 9100 新增软删除 + 向量删除接口 |
| document train | 是 | `/rag/train` 存在 scope 训练 | 否 | 否，9000 是 document_id + mode；9100 是 scope train 且需要 `douyin_account_id` | 否，9100 返回 `training_run_id`, `status`, `document_count`, `chunk_count` | `PATH_MISMATCH`, `REQUEST_SCHEMA_MISMATCH`, `NEEDS_ADAPTER` | 9100 新增单文档 rebuild API，内部可复用 train_scope 或补 train_document |
| training run detail | 是 | 表存在；HTTP 不存在 | 否 | 否 | 否 | `MISSING_9100_API` | 9100 新增 run detail |
| training run list | 是 | 表存在；HTTP 不存在 | 否 | 否 | 否 | `MISSING_9100_API` | 9100 新增 run list |
| search-preview | 是 | `/rag/search` 存在 | 否 | 否，9000 不传 `douyin_account_id`，9100 `/rag/search` 必填 | 否，9100 返回 `items`，9000 期望 `matches` | `PATH_MISMATCH`, `REQUEST_SCHEMA_MISMATCH`, `RESPONSE_SCHEMA_MISMATCH`, `NEEDS_ADAPTER`, `REAL_VECTOR_RISK` | 9100 新增 `/knowledge-training/search-preview`，固定 `douyin_account_id=0` 或统一值，并剥离底层字段 |

总体判断：

```text
MATCH：0/10
GAP：10/10
```

这不表示 9100 没有 RAG 底座，而是表示 9000 新增的统一知识库管理契约与 9100 当前 HTTP 契约尚未对齐。

## 6. 统一知识库上下文核对

9000 已固定：

```text
tenant_id=xiaogao_system
merchant_id=xiaogao_base
category_key=base
```

9100 静态核对：

| 项 | 结果 |
|---|---|
| 是否接受 `tenant_id` | 是，RAG models 和 ask/feedback 都接受 |
| 是否接受 `merchant_id` | 是，RAG models 和 ask/feedback 都接受 |
| 是否接受 `category_key` | 是，`KnowledgeDocumentCreate` 和 `RagSearchRequest.category_keys` 支持 |
| 是否使用 `category_key` 过滤 | 是，SQLite search 和 Milvus search 均支持 |
| 是否存在默认 category | 代码支持创建 system base；但没有启动时自动创建 base 的证据 |
| 是否允许请求体透传 `tenant_id / merchant_id` | 9100 内部 API 会接受；对外可信边界应由 9000 拦截 |
| 是否需要字段改名 | 需要。create 可用 `category_key`，search-preview 需 `category_keys`；run 字段和 response 需要 adapter |
| 是否需要 xiaogao_system / xiaogao_base 兼容 | 需要确保 9100 数据库中存在对应统一知识库数据和 base 分类 |

额外差距：

```text
9100 /rag/* 当前仍要求 douyin_account_id。
9000 统一知识库代理没有向 car-project-main 暴露 douyin_account_id，也没有在新代理中固定 douyin_account_id。
如果继续复用 /rag/*，必须在 9000 或 9100 adapter 中固定统一知识库 account 维度，例如 0 或 xiaogao_unified。
```

## 7. Milvus / Qdrant 静态核对

### 7.1 默认 backend

9100 `Settings.rag_vector_backend` 默认：

```text
sqlite
```

Docker compose 也默认：

```text
RAG_VECTOR_BACKEND=sqlite
```

### 7.2 Milvus 支持

9100 已支持：

```text
RAG_VECTOR_BACKEND=milvus
apps/xg_douyin_ai_cs/services/vector_store.py
MilvusVectorStore.upsert_chunks
MilvusVectorStore.search
MilvusVectorStore.delete_document
MilvusVectorStore.health_check / ensure_collection
```

训练链路：

```text
repository.train_scope
  -> SQLite knowledge_chunks 写入
  -> settings.rag_vector_backend == "milvus" 时 delete_document + upsert_chunks
```

检索链路：

```text
repository.search
  -> settings.rag_vector_backend == "milvus" 时调用 MilvusVectorStore.search
  -> 失败时 fallback SQLite
```

删除 / rebuild：

```text
train_scope 在 milvus backend 下会对 scope 内 docs 逐个 delete_document 后 upsert chunks。
但当前没有 HTTP 层 document delete / single document rebuild API。
```

### 7.3 Qdrant

auto_wechat 9100 代码中未发现 Qdrant backend 作为默认或正式向量库实现。

Qdrant 风险主要来自 car-porject-main / KnowledgeTrain 参考项目，不应暴露到 auto_wechat 统一训练 API。

### 7.4 向量细节泄露

9100 `/rag/search` response model `RagSearchItem` 只包含：

```text
chunk_id
document_id
title
chunk_text
score
```

不直接返回 collection / vector_id。

但 `chunk_id` 是底层 chunk id；9000 当前 search-preview 会剥离不在白名单内的字段，但不会剥离 chunk_id，因为 fake 返回中没有白名单 chunk_id。后续如果 9100 search-preview 返回 chunk_id，需要明确是否允许对 car-project-main 暴露。

### 7.5 Milvus 后续风险

需要单独进入：

```text
P1-RAG-UNIFIED-KB-9100-MILVUS-BACKEND-VERIFY-1
```

原因：

1. 本轮未连接真实 Milvus。
2. 9100 Milvus 能力已有 fake 单测和 canary 历史验证，但统一知识库 HTTP 契约尚未接入。
3. 单文档删除 / 重训的 Milvus 可见性需要在 9100 最小 API 完成后再次验证。

## 8. 错误映射核对

9000 当前对新统一知识库代理使用：

```text
KNOWLEDGE_TRAINING_PERMISSION_DENIED
KNOWLEDGE_TRAINING_CONTEXT_FORBIDDEN
KNOWLEDGE_TRAINING_INVALID_DOCUMENT
KNOWLEDGE_TRAINING_DOCUMENT_NOT_FOUND
KNOWLEDGE_TRAINING_UPSTREAM_UNAVAILABLE
```

契约文档中还规划：

```text
KNOWLEDGE_TRAINING_CATEGORY_NOT_FOUND
KNOWLEDGE_TRAINING_RUN_NOT_FOUND
KNOWLEDGE_TRAINING_FAILED
KNOWLEDGE_TRAINING_VECTOR_DELETE_FAILED
KNOWLEDGE_TRAINING_SEARCH_FAILED
```

9100 当前真实错误：

```text
TRAINING_SESSION_NOT_FOUND
TRAINING_SESSION_FORBIDDEN
MILVUS_UPSERT_FAILED
MILVUS_SEARCH_FAILED
MILVUS_DELETE_FAILED
```

缺口：

1. 9100 新 CRUD / run / search-preview API 尚不存在，因此还没有对应 `KNOWLEDGE_TRAINING_*` 错误码。
2. 9000 当前对 9100 4xx 且带 detail 的错误会原样透传；这要求 9100 后续新增 API 直接返回统一错误码，或 9000 adapter 做映射。
3. 9100 原始错误不得直接透出 traceback / internal path / token / vector config。
4. 9000 对外应继续保持：

```json
{
  "detail": {
    "code": "...",
    "message": "..."
  }
}
```

5. 502 上游失败应继续返回脱敏 `KNOWLEDGE_TRAINING_UPSTREAM_UNAVAILABLE`。

## 9. 差距清单

### 9.1 需要 9000 修正或确认的点

1. 如果临时复用 9100 `/rag/*`，9000 client path 与 request / response schema 均需 adapter。
2. 需要确认统一知识库的 `douyin_account_id` 固定值，否则 9100 RAG scope 无法完整定位。
3. search-preview 如果后续 9100 返回 `chunk_id`，需决定是否对 car-project-main 暴露。
4. 9000 目前 4xx detail 透传依赖 9100 自身错误码规范，后续如 9100 仍返回旧错误码，需要在 9000 映射。

### 9.2 需要 9100 修正的点

建议优先在 9100 新增最小 `/knowledge-training/*` adapter，而不是让 9000 直接适配旧 `/rag/*`：

1. `GET /knowledge-training/categories`
2. `GET /knowledge-training/documents`
3. `GET /knowledge-training/documents/{document_id}`
4. `POST /knowledge-training/documents`
5. `PUT /knowledge-training/documents/{document_id}`
6. `DELETE /knowledge-training/documents/{document_id}`
7. `POST /knowledge-training/documents/{document_id}/train`
8. `GET /knowledge-training/training-runs/{run_id}`
9. `GET /knowledge-training/training-runs`
10. `POST /knowledge-training/search-preview`

这些 API 应复用现有 `rag.repository`、`vector_store` 和 SQLite 表，不新增外部依赖。

### 9.3 可以留到 P2 的点

1. 文件上传。
2. audit logs 查询。
3. `rebuild_all`。
4. 批量导入。
5. 多格式解析。
6. 版本回滚。
7. 审批流。
8. 更细粒度管理员权限。

## 10. 下一步建议

推荐下一步：

```text
P1-RAG-UNIFIED-KB-9100-MINIMAL-TRAINING-API-1
```

理由：

```text
9100 缺口较大，当前不是小范围 path adapter 能完全解决。
```

并行后续：

```text
P1-RAG-UNIFIED-KB-9100-MILVUS-BACKEND-VERIFY-1
```

理由：

```text
9100 已有 Milvus backend，但统一知识库 HTTP API 尚未绑定真实 Milvus 闭环。
最小 API 完成后，应再次验证写入、检索、删除和 search-preview 的脱敏输出。
```

不建议下一步直接进入 car-project-main 页面 wiring。当前 9000 -> 9100 真实契约未对齐，直接接页面会得到运行态 404 / 422。

## 11. 未改内容

本轮未修改：

```text
auto_wechat 业务代码
auto_wechat 前端
apps/xg_douyin_ai_cs 9100 代码
car-porject-main
NewCarProject
/merchant/rag/*
/admin/rag/*
自动回复真实发送 gate
数据库 migration
.env.example
```

本轮未触发：

```text
真实训练
真实 LLM
真实 Milvus
真实 Qdrant
真实抖音发送
真实私信发送
```

本轮只新增本文档，用于冻结 9000 新代理与 9100 当前契约之间的差距。
