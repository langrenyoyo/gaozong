# P1-RAG-UNIFIED-KB-TRAINING-9000-API-RUNTIME-SMOKE

## 1. 验证目标

本轮对已提交的 auto_wechat 9000 `/knowledge-training/*` 统一知识库训练 API 做运行态 smoke 验证。

本轮只做运行态验证和文档记录，不修改业务代码，不触发真实训练，不连接真实 Milvus / Qdrant，不调用真实 LLM，不调用抖音发送。

## 2. 环境与启动方式

验证对象：

```text
http://127.0.0.1:9000
```

启动方式：

```text
用户已重新构建并启动 docker compose 容器。
auto-wechat-api-dev 监听 9000。
```

容器检查摘要：

```text
auto-wechat-api-dev: running
xg-douyin-ai-cs-dev: running
```

上游配置确认：

```text
XG_DOUYIN_AI_CS_BASE_URL 指向 compose 内 xg-douyin-ai-cs:9100。
KNOWLEDGE_TRAINING_INTERNAL_TOKENS 已设置，但本轮未打印其值。
KNOWLEDGE_TRAINING_IP_WHITELIST 为默认本机白名单。
```

安全说明：

```text
由于 9000 当前上游是开发环境真实 9100，而不是 fake 9100，本轮没有执行会进入 9100 的正向 categories / create / search-preview 请求。
```

## 3. OpenAPI 路由验证

执行：

```powershell
Invoke-RestMethod http://127.0.0.1:9000/openapi.json
```

运行中 9000 已包含目标 `/knowledge-training/*` 路由：

```text
/knowledge-training/categories = get
/knowledge-training/documents = get,post
/knowledge-training/documents/{document_id} = delete,get,put
/knowledge-training/documents/{document_id}/train = post
/knowledge-training/training-runs/{run_id} = get
/knowledge-training/training-runs = get
/knowledge-training/search-preview = post
```

保留旧接口：

```text
/knowledge-training/ask
/knowledge-training/{training_id}/feedback
```

确认结果：

```text
/merchant/rag/* 不存在。
/admin/rag/* 主路径不存在。
```

## 4. 认证验证

### 4.1 未带 token

执行：

```powershell
Invoke-WebRequest http://127.0.0.1:9000/knowledge-training/categories
```

结果：

```text
status=403
```

结论：

```text
未带内部 token 且未命中容器内白名单时，被拒绝访问。
```

### 4.2 仅带 actor headers

执行时仅携带：

```text
X-Operator-Source: car-project-main
X-Operator-Id: smoke-admin
X-Operator-Account: smoke-admin
X-Request-Id: smoke-actor-only
```

结果：

```text
status=403
```

结论：

```text
actor headers 只作为审计字段，不替代认证。
```

### 4.3 带内部 token

运行态未执行。

原因：

```text
容器中 token 已设置，但本轮不打印真实值。
若使用有效 token 访问 categories，会进入 9000 -> 9100 调用链。
当前 9100 是真实开发服务，不是 fake 9100；为避免连接真实上游，本轮跳过正向 categories 运行态调用。
```

单元测试覆盖：

```text
tests/test_knowledge_training_unified_api.py 已覆盖内部 token 可访问 categories。
```

## 5. 固定上下文验证

执行：

```powershell
POST /knowledge-training/documents
```

请求体携带：

```json
{
  "title": "smoke test",
  "content": "smoke test content",
  "category_key": "base",
  "source_type": "manual_text",
  "tenant_id": "evil",
  "merchant_id": "evil"
}
```

运行态结果：

```text
status=403
```

结论：

```text
该请求在认证层被拒绝，未进入上下文字段校验，也未调用 9100。
```

补充说明：

```text
由于本轮不使用真实 token，无法在运行态验证 KNOWLEDGE_TRAINING_CONTEXT_FORBIDDEN。
单元测试已覆盖请求体携带 tenant_id 时返回 KNOWLEDGE_TRAINING_CONTEXT_FORBIDDEN，且 fake 9100 未被调用。
```

## 6. categories 验证

运行态未执行正向 categories。

原因：

```text
GET /knowledge-training/categories 在认证通过后会调用 9100。
当前 9000 上游是 compose 内真实 xg-douyin-ai-cs:9100，不是 fake 9100。
为遵守“不连接真实 9100 / Milvus / Qdrant / LLM”的 smoke 边界，本轮只验证 OpenAPI 和认证负向路径。
```

单元测试覆盖：

```text
tests/test_knowledge_training_unified_api.py 已覆盖 categories 返回 base。
返回结构不包含 Milvus / Qdrant collection。
返回结构不包含 vector_id。
```

## 7. search-preview 安全验证

运行态未调用 `/knowledge-training/search-preview`。

原因：

```text
search-preview 认证通过后会进入 9000 -> 9100 -> RAG 检索链路。
当前没有 fake 9100 运行态上游，本轮避免触发真实向量服务。
```

单元测试覆盖：

```text
tests/test_knowledge_training_unified_api.py 已覆盖：
- category_keys 默认 ["base"]。
- top_k 上限校验。
- 返回 matches 会移除 collection / vector_id。
- 上游错误脱敏后映射为 KNOWLEDGE_TRAINING_UPSTREAM_UNAVAILABLE。
```

## 8. 上游隔离确认

本轮没有调用以下真实能力：

```text
训练接口
search-preview 正向接口
真实 LLM
Milvus
Qdrant
抖音发送上游
私信发送
```

本轮运行态请求止步于：

```text
/openapi.json
GET /knowledge-training/categories -> 403
POST /knowledge-training/documents -> 403
```

因此未进入 9100 正向业务调用。

## 9. 风险与遗留项

已确认：

```text
运行中 9000 已加载新的统一知识库训练管理路由。
认证负向路径可阻断无 token / actor-only 请求。
/merchant/rag/* 和 /admin/rag/* 主路径不存在。
```

遗留项：

```text
1. 可在后续配置收口任务中补 .env.example 的 KNOWLEDGE_TRAINING_INTERNAL_TOKENS 占位说明。
```

## 10. 未改内容

本轮未修改：

```text
auto_wechat 业务代码
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
真实 9100 写入 / 检索
真实抖音发送
真实私信发送
```

## 11. 测试结果

执行：

```powershell
python -m pytest tests/test_knowledge_training_unified_api.py -q
```

结果：

```text
11 passed
```

执行：

```powershell
python -m pytest tests/test_knowledge_training_api.py -q
```

结果：

```text
10 passed
```

执行：

```powershell
git diff --check
```

结果：

```text
通过。
```

## 12. Fake 9100 正向 smoke

### 12.1 启动方式

本轮使用宿主机临时 fake 9100：

```text
http://127.0.0.1:19100
```

fake 9100 只返回固定假数据，不写向量库，不训练，不调用 LLM。

9000 运行方式：

```text
临时本机 uvicorn 进程监听 127.0.0.1:9000。
```

说明：

```text
尝试用同镜像临时 Docker 容器启动 9000 时，Docker 返回 Cannot allocate memory。
为避免继续消耗 Docker 资源，本轮改为本机临时 9000 进程完成 smoke。
```

9000 临时配置：

```text
XG_DOUYIN_AI_CS_BASE_URL=http://127.0.0.1:19100
KNOWLEDGE_TRAINING_INTERNAL_TOKENS 使用 dev 假 token
KNOWLEDGE_TRAINING_DEFAULT_TENANT_ID=xiaogao_system
KNOWLEDGE_TRAINING_DEFAULT_MERCHANT_ID=xiaogao_base
```

未打印、未提交任何真实 token / cookie / secret / password / Milvus 凭据。

### 12.2 带 token categories

请求：

```text
GET /knowledge-training/categories
Authorization: Bearer <dev fake token>
```

结果：

```text
status=200
包含 base 分类
不包含 collection / vector_id / qdrant / milvus 连接信息
```

fake 9100 收到的上下文：

```text
tenant_id=xiaogao_system
merchant_id=xiaogao_base
```

### 12.3 tenant_id / merchant_id 禁止

请求：

```text
POST /knowledge-training/documents
```

请求体包含：

```text
tenant_id=evil
merchant_id=evil
```

结果：

```text
status=400
error_code=KNOWLEDGE_TRAINING_CONTEXT_FORBIDDEN
```

确认：

```text
fake 9100 未收到该 create 请求。
```

### 12.4 create 固定上下文

请求：

```text
POST /knowledge-training/documents
```

请求体只包含 title / content / category_key / source_type，不包含可信上下文字段。

结果：

```text
status=201
document_id=fake-doc-001
```

fake 9100 收到的上下文：

```text
tenant_id=xiaogao_system
merchant_id=xiaogao_base
category_key=base
```

### 12.5 search-preview 脱敏结构

请求：

```text
POST /knowledge-training/search-preview
```

请求体：

```text
category_keys=base
top_k=5
```

fake 9100 返回的 match 中故意包含 collection / vector_id / qdrant / milvus 字段。

9000 返回结果：

```text
status=200
matches 非空
不包含 collection
不包含 vector_id
不包含 qdrant
不包含 milvus
```

fake 9100 收到的上下文：

```text
tenant_id=xiaogao_system
merchant_id=xiaogao_base
category_keys=base
```

### 12.6 上游隔离确认

本轮 fake smoke 未连接：

```text
真实 xg-douyin-ai-cs:9100
真实 Milvus
真实 Qdrant
真实 LLM
抖音发送上游
真实私信发送
```

本轮未触发：

```text
真实训练
自动回复 gate 修改
数据库 migration
/merchant/rag/*
/admin/rag/*
```
