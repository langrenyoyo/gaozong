# P1-RAG-UNIFIED-KB-9100-MINIMAL-TRAINING-API

## 1. 本轮目标

在 9100 抖音 AI 客服服务中新增最小统一知识库训练管理 API adapter，对齐 9000 `XgDouyinAiCsClient` 当前调用的 `/knowledge-training/*` 路径。

本轮不是重做 RAG，不接 `car-porject-main` 页面，不新增 `/merchant/rag/*` 或 `/admin/rag/*`，不调用真实 LLM，不触发抖音私信发送。

## 2. 新增 / 修改的 9100 路由

本轮在既有 `apps/xg_douyin_ai_cs/routers/knowledge_training.py` 中新增：

```text
GET    /knowledge-training/categories
GET    /knowledge-training/documents
POST   /knowledge-training/documents
GET    /knowledge-training/documents/{document_id}
PUT    /knowledge-training/documents/{document_id}
DELETE /knowledge-training/documents/{document_id}
POST   /knowledge-training/documents/{document_id}/train
GET    /knowledge-training/training-runs/{run_id}
GET    /knowledge-training/training-runs
POST   /knowledge-training/search-preview
```

保留既有接口不变：

```text
POST /knowledge-training/ask
POST /knowledge-training/{training_id}/feedback
POST /rag/documents
POST /rag/train
POST /rag/search
GET  /categories
```

## 3. 与 9000 client 的对齐

9000 当前通过 `app/services/xg_douyin_ai_cs_client.py` 调用同名 9100 路径。本轮未修改 9000 client。

9100 adapter 接收 9000 注入的：

```text
tenant_id=xiaogao_system
merchant_id=xiaogao_base
category_key=base
```

统一知识库内部固定：

```text
douyin_account_id=0
```

该值仅用于复用现有 RAG 表的账号维度隔离，不暴露给 car-project-main。

## 4. 数据库 / 表变化

本轮复用既有 9100 SQLite RAG 表：

```text
knowledge_categories
knowledge_documents
knowledge_chunks
rag_training_runs
```

没有新增独立 migration 文件。为支持单文档训练 run 查询，本轮沿用 9100 现有 `init_db + _ensure_column` 兼容策略，为 `rag_training_runs` 补充：

```text
document_id INTEGER
```

文档状态不新增字段，按现有字段推导：

```text
is_active=0                  -> deleted
is_active=1 且无 active chunk -> draft
is_active=1 且有 active chunk -> active
```

## 5. 已真实可用能力

在 SQLite backend 下，本轮已实现：

1. 返回 base 分类。
2. 创建 `manual_text` 文档。
3. 文档列表、详情、更新、软删除。
4. 单文档 `rebuild_document` 同步训练。
5. training run 详情与列表。
6. search-preview 检索预览。
7. search-preview `category_keys=[]` 时直接返回空结果。
8. 响应不返回 collection / vector_id / qdrant / milvus 连接信息。

## 6. Fake / Mock 覆盖与 TODO

单元测试使用临时 SQLite 和 fake embedding，不连接真实 Milvus / Qdrant / LLM。

Milvus 相关真实闭环仍留到下一任务：

```text
P1-RAG-UNIFIED-KB-9100-MILVUS-BACKEND-VERIFY-1
```

需要后续验证：

1. 单文档训练在 Milvus backend 下的 upsert 可见性。
2. soft_delete 后 Milvus delete 可见性。
3. search-preview 在真实 Milvus 下的字段脱敏。
4. 向量服务异常时错误码和 run 状态是否符合预期。

## 7. 错误码

本轮 9100 adapter 新增 / 使用以下错误码：

```text
RAG_DOCUMENT_NOT_FOUND
RAG_INVALID_DOCUMENT
RAG_RUN_NOT_FOUND
RAG_SEARCH_FAILED
RAG_UNSUPPORTED_OPERATION
RAG_VECTOR_DELETE_FAILED
```

错误响应格式：

```json
{
  "detail": {
    "code": "RAG_DOCUMENT_NOT_FOUND",
    "message": "统一知识库文档不存在"
  }
}
```

## 8. search-preview 脱敏规则

`POST /knowledge-training/search-preview` 只返回：

```text
document_id
title
category_key
chunk_text
score
```

不返回：

```text
chunk_id
collection
vector_id
qdrant
milvus
内部路径
token / secret / password / cookie
```

`chunk_text` 在 adapter 层最多保留 500 字符。

## 9. 未改内容

本轮未修改：

```text
9000 对外 API schema
9000 XgDouyinAiCsClient
auto_wechat 前端
car-porject-main
NewCarProject
/merchant/rag/*
/admin/rag/*
自动回复真实发送 gate
```

本轮未触发：

```text
真实 Milvus
真实 Qdrant
真实 LLM chat
抖音发送上游
真实私信发送
文件上传
批量导入
rebuild_all
```

## 10. 测试结果

已执行：

```text
python -m pytest tests/test_xg_douyin_ai_cs_unified_knowledge_training_api.py -q
8 passed

python -m pytest tests/test_xg_douyin_ai_cs_rag.py tests/test_xg_douyin_ai_cs_rag_workflow.py tests/test_knowledge_training_api.py -q
41 passed

python -m pytest tests/test_knowledge_training_unified_api.py -q
11 passed

python -m pytest tests/test_xg_douyin_ai_cs_unified_knowledge_training_api.py tests/test_xg_douyin_ai_cs_rag.py tests/test_xg_douyin_ai_cs_rag_workflow.py tests/test_knowledge_training_unified_api.py tests/test_knowledge_training_api.py -q
60 passed
```

最终回归与 `git diff --check` 结果以任务输出报告为准。

## 11. 下一步

建议进入：

```text
P1-RAG-UNIFIED-KB-9100-MILVUS-BACKEND-VERIFY-1
```

目标是在不使用真实业务数据、不调用 LLM、不触发发送的前提下，用 synthetic 数据验证 9100 新 adapter 在真实 Milvus backend 下的训练、检索和删除闭环。
