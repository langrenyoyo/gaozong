# P1-RAG-UNIFIED-KB-9000-PROXY-GATE-RUNTIME-FIX

## 1. 目标与遗留问题

本轮目标是修复并验证 9000 `/knowledge-training/*` 运行态可信来源 gate，使 9000 可以通过 internal token 正常放行后端调用，并完成：

```text
9000 /knowledge-training/*
-> 9100 /knowledge-training/*
-> Milvus
-> synthetic create/train/search-preview/delete
```

上一轮遗留问题：

```text
9000 -> 9100 代理链路未通过。
9000 gate 返回 KNOWLEDGE_TRAINING_PERMISSION_DENIED。
```

本任务不是 car-porject-main 接入，不做页面联调，不修改 NewCarProject、前端或自动回复真实发送 gate。

## 2. 9000 gate 逻辑核对

9000 gate 位于：

```text
app/routers/knowledge_training.py
```

已确认：

1. 统一知识库管理接口使用 `require_unified_knowledge_training_access`。
2. 放行条件为：
   - 命中 `KNOWLEDGE_TRAINING_IP_WHITELIST`。
   - 或 `Authorization: Bearer <token>` 命中 `KNOWLEDGE_TRAINING_INTERNAL_TOKENS`。
   - 或 `X-Internal-Token` 命中 `KNOWLEDGE_TRAINING_INTERNAL_TOKENS`。
3. `KNOWLEDGE_TRAINING_INTERNAL_TOKENS` 支持英文逗号分隔，并会 trim 空格。
4. `Authorization` 的 Bearer scheme 大小写不敏感。
5. `X-Operator-*`、`X-Request-Id` 只作为审计上下文，不作为认证依据。
6. 默认空 token 安全关闭。
7. Docker / 反代下 IP 白名单不作为本轮主验证路径，本轮使用 internal token。

## 3. 运行态 env 注入

根因：

```text
docker-compose.dev.yml 的 9000 service 未透传 KNOWLEDGE_TRAINING_INTERNAL_TOKENS。
```

本轮修复：

```text
docker-compose.dev.yml
  auto-wechat-api.environment 增加：
  KNOWLEDGE_TRAINING_INTERNAL_TOKENS: "${KNOWLEDGE_TRAINING_INTERNAL_TOKENS:-}"

.env.example
  增加 KNOWLEDGE_TRAINING_INTERNAL_TOKENS= 空占位和说明。
```

运行态重启 9000 时使用 dev 假 token：

```text
KNOWLEDGE_TRAINING_INTERNAL_TOKENS=dev_knowledge_training_token
```

该 token 是开发 smoke 用假 token，不是真实密钥，未写入 `.env`。

9000 容器脱敏确认：

```text
KNOWLEDGE_TRAINING_INTERNAL_TOKENS.present=true
KNOWLEDGE_TRAINING_IP_WHITELIST=127.0.0.1,::1,localhost
KNOWLEDGE_TRAINING_TRUST_PROXY_HEADERS=false
XG_DOUYIN_AI_CS_BASE_URL=http://xg-douyin-ai-cs:9100
MILVUS_URI.present=false
RAG_VECTOR_BACKEND=<unset>
```

说明：

```text
9000 不需要 Milvus 配置；Milvus 属于 9100。
```

9100 Milvus check：

```text
connected=True
collection_exists=True
schema_match=True
dimension=2048
metric_type=COSINE
```

## 4. categories 正向验证

请求：

```text
GET http://127.0.0.1:9000/knowledge-training/categories
Authorization: Bearer dev_knowledge_training_token
X-Operator-Source: car-project-main
X-Operator-Id: smoke-admin
X-Operator-Account: smoke-admin
X-Request-Id: smoke-9000-gate-001
```

结果：

```text
status=200
categories_has_base=True
categories_has_collection=False
categories_has_vector_id=False
categories_has_milvus=False
categories_has_qdrant=False
```

确认：

```text
9100 被正常调用。
未调用 LLM。
未触发发送。
```

## 5. context forbidden 验证

请求：

```text
POST /knowledge-training/documents
Authorization: Bearer dev_knowledge_training_token
```

请求体携带伪造上下文：

```text
tenant_id=evil
merchant_id=evil
```

结果：

```text
status=400
code=KNOWLEDGE_TRAINING_CONTEXT_FORBIDDEN
```

确认：

```text
9000 固定封装 tenant_id=xiaogao_system。
9000 固定封装 merchant_id=xiaogao_base。
调用方不得传入 tenant_id / merchant_id。
该请求未写入 9100 / SQLite / Milvus。
```

## 6. 9000 -> 9100 -> Milvus synthetic 闭环

最终 synthetic 验证结果：

```text
document_id=12
document_status=draft
category_key=base
training_run_id=15
training_status=completed
chunk_count=1
final_training_status=completed
final_chunk_count=1
search_match_count=1
search_hit=True
delete_status=deleted
search_after_delete_match_count=0
search_after_delete_hit=False
```

说明：

1. synthetic 内容为非业务测试文本。
2. 9000 不接受调用方 tenant / merchant。
3. 9000 代理到 9100 后成功写入 Milvus。
4. search-preview 命中当前 synthetic 文档。
5. soft_delete 后同 token 不再命中。

## 7. delete 后检索验证

delete 后复查：

```text
search_after_delete_match_count=0
search_after_delete_hit=False
```

结论：

```text
本轮没有发现 active synthetic 数据残留。
```

补充 sanitization smoke：

```text
sanitize_document_id=13
sanitize_training_status=completed
sanitize_search_match_count=1
sanitize_has_collection=False
sanitize_has_vector_id=False
sanitize_has_milvus=False
sanitize_has_qdrant=False
sanitize_cleanup=deleted
```

说明：

```text
主 synthetic token 按任务命名包含 MILVUS 字样，因此命中 chunk_text 时响应文本中自然包含该业务测试标识。
为排除底层字段泄露，额外使用不含 milvus 字样的 synthetic 文本完成 sanitization smoke，确认响应不包含 collection / vector_id / milvus / qdrant。
```

## 8. Qdrant 排除确认

本轮确认：

```text
9000 不连接 Qdrant。
9100 本轮不连接 Qdrant。
car-project-main 的 knowledge-train-qdrant 未被调用。
9000 categories / search-preview 响应不包含 qdrant 字段。
```

## 9. 测试结果

已执行：

```text
python -m pytest tests/test_knowledge_training_unified_api.py -q
13 passed

python -m pytest tests/test_knowledge_training_api.py -q
10 passed

python -m pytest tests/test_xg_douyin_ai_cs_unified_knowledge_training_api.py -q
8 passed

python -m py_compile app\main.py app\config.py app\routers\knowledge_training.py app\services\xg_douyin_ai_cs_client.py
passed

python -m py_compile apps\xg_douyin_ai_cs\main.py apps\xg_douyin_ai_cs\routers\knowledge_training.py apps\xg_douyin_ai_cs\rag\repository.py
passed

git diff --check
passed
```

敏感扫描说明：

```text
本地 .env 含真实运行配置，但 .env 未提交。
本轮 git diff 只包含变量名、空占位和 dev 假 token 测试值。
未提交真实 token / cookie / secret / password / Milvus URI。
```

## 10. 修改内容

修改文件：

```text
docker-compose.dev.yml
.env.example
tests/test_knowledge_training_unified_api.py
docs/ai/06_rag/P1_RAG_UNIFIED_KB_9000_PROXY_GATE_RUNTIME_FIX.md
```

修改摘要：

1. 9000 compose 增加 `KNOWLEDGE_TRAINING_INTERNAL_TOKENS` env 透传。
2. `.env.example` 增加 `KNOWLEDGE_TRAINING_INTERNAL_TOKENS=` 空占位和安全说明。
3. 测试补充：
   - `X-Internal-Token` 可通过。
   - token CSV trim 生效。
   - Bearer scheme 大小写不敏感。
4. 新增本轮运行态验证文档。

## 11. 未改内容

本轮未修改：

```text
car-porject-main
NewCarProject
auto_wechat 前端
自动回复真实发送 gate
/merchant/rag/*
/admin/rag/*
NewCar 权限码
```

本轮未触发：

```text
真实 LLM
Qdrant
抖音发送上游
真实私信发送
自动回复真实发送
```

## 12. 后续任务

建议下一步进入：

```text
P1-RAG-UNIFIED-KB-CAR-PROJECT-WIRING-AUDIT-1
```

目标：

1. 审计 car-porject-main 后端如何调用 9000 `/knowledge-training/*`。
2. 确认 car-porject-main 不直连 9100 / Milvus / Qdrant。
3. 确认页面只作为统一知识库训练入口，不引入商户自助私有知识库。
