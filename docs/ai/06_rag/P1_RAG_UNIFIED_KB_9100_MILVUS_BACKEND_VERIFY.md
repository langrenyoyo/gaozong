# P1-RAG-UNIFIED-KB-9100-MILVUS-BACKEND-VERIFY

## 1. 目标与边界

本轮验证 9100 新增统一知识库 `/knowledge-training/*` adapter 在 Milvus backend 下的 synthetic 闭环：

```text
manual_text document create
-> rebuild_document
-> Milvus upsert
-> search-preview 命中
-> soft_delete
-> search-preview 不再命中
```

本轮只使用 synthetic 非业务数据，未使用真实客户数据、真实业务知识、真实 LLM、Qdrant、抖音发送上游、真实私信发送或自动回复真实发送 gate。

## 2. 运行态前置

9100 OpenAPI 已出现新 adapter 路由：

```text
/knowledge-training/categories
/knowledge-training/documents
/knowledge-training/documents/{document_id}
/knowledge-training/documents/{document_id}/train
/knowledge-training/training-runs
/knowledge-training/training-runs/{run_id}
/knowledge-training/search-preview
```

Milvus collection check 脱敏结果：

```text
backend=milvus
connected=True
collection_exists=True
created=False
schema_match=True
dimension=2048
metric_type=COSINE
```

Qdrant 未参与本轮验证；运行中的 `knowledge-train-qdrant` 属于 car-project-main / KnowledgeTrain 侧服务，本轮未连接、未调用。

## 3. 本轮最小修复

为完成真实 Milvus 闭环，本轮做了以下最小修复：

1. `docker-compose.dev.yml` 为 9100 容器补齐 Milvus 环境变量透传占位：
   - `MILVUS_URI`
   - `MILVUS_DB_NAME`
   - `MILVUS_COLLECTION`
   - `MILVUS_DIMENSION`
   - `MILVUS_TIMEOUT_SECONDS`
   - `MILVUS_INDEX_TYPE`
   - `MILVUS_METRIC_TYPE`
   - `MILVUS_CONNECT_STRATEGY`
2. `requirements-docker.txt` 增加 `pymilvus==2.6.12`，避免容器内 Milvus backend 缺依赖。
3. mock embedding 在 `RAG_VECTOR_BACKEND=milvus` 且真实 embedding 关闭时按 `MILVUS_DIMENSION` 输出，避免 synthetic 训练因 16 维 mock 向量与 2048 维 collection 不匹配。
4. Milvus 写入 / 删除后调用已有 `flush()`，提升 upsert / delete 对 search 的可见性。
5. 修复统一知识库 `douyin_account_id=0` 写入 Milvus 时被 `or ""` 转为空字符串的问题，保证 search filter 中的 `douyin_account_id == "0"` 能命中。

以上修复均未写入真实 URI、host、username、password、token；默认 `RAG_VECTOR_BACKEND` 仍由环境变量控制，不改变默认 sqlite 行为。

## 4. 9100 直连 synthetic 结果

最终通过的 9100 直连验证：

```text
document_id=11
training_run_id=14
document_status=draft
category_key=base
training_status=completed
chunk_count=1
search_match_count=1
search_hit=True
search_result_has_collection=False
search_result_has_qdrant=False
delete_status=deleted
search_after_delete_match_count=0
search_after_delete_hit=False
```

说明：

1. create / train / search-preview / soft_delete / search-after-delete 闭环通过。
2. search-preview 响应未暴露 collection / qdrant 字样。
3. 未输出完整 chunk_text。
4. synthetic document 已删除。

## 5. 过程缺口与根因

过程中遇到并修复的缺口：

1. 容器未透传完整 Milvus 配置，导致 collection check 报 `MILVUS_CONFIG_MISSING`。
2. 容器未安装 `pymilvus`，导致 `MILVUS_DEPENDENCY_MISSING`。
3. mock embedding 默认 16 维，导致训练失败：`VECTOR_DIMENSION_MISMATCH`。
4. Milvus upsert 成功但 search-preview 不命中，根因是统一知识库 `douyin_account_id=0` 写入 Milvus 时被转为空字符串，search filter 查 `"0"`，两者不一致。

过程中创建的失败 synthetic 文档均已 soft_delete；最终 search-after-delete 对最终文档不再命中。

## 6. 9000 -> 9100 代理链路结果

9000 OpenAPI 已出现统一知识库训练代理路由，但从宿主机直接调用被 9000 权限 / 白名单 gate 拦截：

```text
code=KNOWLEDGE_TRAINING_PERMISSION_DENIED
message=当前来源不允许访问统一知识库训练接口
```

本轮未绕过 9000 权限 gate，未创建 9000 synthetic 文档。9000 -> 9100 链路需要后续在允许来源 / 测试白名单 / 可信网关上下文配置正确后复验。

## 7. 测试结果

已执行：

```text
python -m pytest tests/test_xg_douyin_ai_cs_unified_knowledge_training_api.py -q
8 passed

python -m pytest tests/test_knowledge_training_unified_api.py -q
11 passed

python -m pytest tests/test_knowledge_training_api.py -q
10 passed

python -m pytest tests/test_xg_douyin_ai_cs_rag.py tests/test_xg_douyin_ai_cs_rag_workflow.py -q
32 passed

python -m py_compile apps\xg_douyin_ai_cs\main.py apps\xg_douyin_ai_cs\routers\knowledge_training.py apps\xg_douyin_ai_cs\rag\repository.py apps\xg_douyin_ai_cs\rag\database.py apps\xg_douyin_ai_cs\llm\client.py
passed

git diff --check
passed
```

另执行合并回归：

```text
python -m pytest tests/test_xg_douyin_ai_cs_llm.py tests/test_xg_douyin_ai_cs_unified_knowledge_training_api.py tests/test_knowledge_training_unified_api.py tests/test_knowledge_training_api.py tests/test_xg_douyin_ai_cs_rag.py tests/test_xg_douyin_ai_cs_rag_workflow.py -q
120 passed
```

## 8. 未改内容

本轮未修改：

```text
car-porject-main
NewCarProject
auto_wechat 前端
/merchant/rag/*
/admin/rag/*
自动回复真实发送 gate
真实发送链路
```

本轮未触发：

```text
真实 LLM
Qdrant
抖音发送上游
真实私信发送
自动回复真实发送
```

本轮未提交、未输出真实 Milvus URI / host / username / password / token。

## 9. 下一步建议

建议下一步进入：

```text
P1-RAG-UNIFIED-KB-9000-PROXY-GATE-RUNTIME-FIX-1
```

目标：

1. 明确 9000 `/knowledge-training/*` 代理的可信来源 / 白名单 / 测试调用方式。
2. 在不放宽生产 gate 的前提下完成 9000 -> 9100 synthetic 闭环。
3. 通过后再进入 car-project-main wiring 审计与页面联调。
