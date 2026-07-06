# P1-RAG-UNIFIED-KB-TRAINING-9000-API-PROXY

## 1. 本轮目标

本轮在 auto_wechat 9000 增加受控的统一知识库训练 API 代理能力，供 car-project-main 后端调用。

正确调用链：

```text
car-project-main 页面
  -> car-project-main 后端
  -> auto_wechat 9000 /knowledge-training/*
  -> auto_wechat 9100 RAG 能力
```

本轮没有修改 car-project-main、NewCarProject、auto_wechat 前端，也没有触发真实训练、LLM、Milvus、Qdrant 或抖音发送。

## 2. P1 已实现 API

本轮在 9000 的 `/knowledge-training/*` namespace 下补齐以下代理接口：

| 方法 | 路径 | 状态 |
|---|---|---|
| GET | `/knowledge-training/categories` | 已实现 |
| GET | `/knowledge-training/documents` | 已实现 |
| GET | `/knowledge-training/documents/{document_id}` | 已实现 |
| POST | `/knowledge-training/documents` | 已实现 |
| PUT | `/knowledge-training/documents/{document_id}` | 已实现 |
| POST | `/knowledge-training/documents/{document_id}/train` | 已实现 |
| GET | `/knowledge-training/training-runs/{run_id}` | 已实现 |
| GET | `/knowledge-training/training-runs` | 已实现 |
| DELETE | `/knowledge-training/documents/{document_id}` | 已实现 |
| POST | `/knowledge-training/search-preview` | 已实现 |

保留已有接口：

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/knowledge-training/ask` | 旧内部训练问答接口，响应结构未改 |
| POST | `/knowledge-training/{training_id}/feedback` | 旧训练反馈接口，响应结构未改 |

P1 未实现：

| 路径 | 状态 |
|---|---|
| `/knowledge-training/documents/upload` | 暂不实现 |
| `/knowledge-training/audit-logs` | 暂不实现 |

## 3. 认证规则

新增统一知识库管理接口采用服务间调用校验：

1. 命中 `KNOWLEDGE_TRAINING_IP_WHITELIST` 可访问。
2. 或通过 `Authorization: Bearer <internal_token>` / `X-Internal-Token` 命中 `KNOWLEDGE_TRAINING_INTERNAL_TOKENS` 可访问。
3. `X-Operator-Id`、`X-Operator-Account`、`X-Request-Id`、`X-Operator-Source` 仅作为后续审计字段，不替代认证。

默认值保持安全：`KNOWLEDGE_TRAINING_INTERNAL_TOKENS` 默认为空。未命中白名单且没有有效内部 token 时返回：

```text
403 KNOWLEDGE_TRAINING_PERMISSION_DENIED
```

旧 `ask` / `feedback` 仍沿用原 IP 白名单校验，不改旧响应 schema。

## 4. 固定上下文

9000 固定统一知识库上下文：

```text
tenant_id = xiaogao_system
merchant_id = xiaogao_base
category_key = base
```

请求体或查询参数出现 `tenant_id` / `merchant_id` 时直接拒绝：

```text
400 KNOWLEDGE_TRAINING_CONTEXT_FORBIDDEN
```

9000 不信任 car-project-main 或前端传入的租户、商户上下文。

## 5. 9100 边界

9000 只通过 `XgDouyinAiCsClient` 调用 9100，不直连 Milvus / Qdrant。

单元测试中所有 9100 调用均使用 fake client，不连接真实 9100、Milvus、Qdrant 或 LLM。

如果 9100 返回 4xx 且带业务错误码，9000 保留业务错误；如果 9100 或向量服务异常，9000 返回脱敏错误：

```text
502 KNOWLEDGE_TRAINING_UPSTREAM_UNAVAILABLE
```

## 6. search-preview 安全规则

`POST /knowledge-training/search-preview` 只做检索预览：

1. 不调用 LLM。
2. 不触发真实发送。
3. `category_keys` 默认 `["base"]`。
4. `category_keys=[]` 时直接返回空 matches。
5. `top_k` 上限为 10。
6. 返回结果会移除 `collection`、`vector_id` 等底层向量字段。

## 7. 错误码

本轮已覆盖的主要错误码：

| 错误码 | 说明 |
|---|---|
| `KNOWLEDGE_TRAINING_PERMISSION_DENIED` | 来源未通过白名单或内部 token |
| `KNOWLEDGE_TRAINING_CONTEXT_FORBIDDEN` | 请求携带禁止的 tenant_id / merchant_id |
| `KNOWLEDGE_TRAINING_INVALID_DOCUMENT` | 文档、训练或 search-preview 参数不合法 |
| `KNOWLEDGE_TRAINING_DOCUMENT_NOT_FOUND` | 下游文档不存在 |
| `KNOWLEDGE_TRAINING_UPSTREAM_UNAVAILABLE` | 下游服务失败，已脱敏 |

## 8. 未改内容

本轮未做以下事项：

1. 未实现 `/merchant/rag/*`。
2. 未把 `/admin/rag/*` 作为当前主路径。
3. 未新增 NewCar 权限码。
4. 未使用 `auto_wechat:douyin_ai_cs` 作为知识库训练权限。
5. 未修改自动回复真实发送 gate。
6. 未修改 9000 对外既有 ask / feedback schema。
7. 未修改 auto_wechat 前端。
8. 未修改 car-project-main。
9. 未触发真实训练、LLM、Milvus、Qdrant 或抖音发送。

## 9. 测试结果

本轮新增测试：

```text
python -m pytest tests/test_knowledge_training_unified_api.py -q
11 passed
```

兼容旧知识训练接口测试：

```text
python -m pytest tests/test_knowledge_training_api.py -q
10 passed
```

完整任务回归命令见最终输出报告。

## 10. car-project-main 后续调用方式

car-project-main 后端应以服务间方式调用 9000：

```text
Authorization: Bearer <internal_token>
X-Operator-Id: <operator_id>
X-Operator-Account: <operator_account>
X-Request-Id: <request_id>
X-Operator-Source: car-project-main
```

car-project-main 不应向 9000 传可信 `tenant_id` / `merchant_id`，不应直连 9100 / Milvus / Qdrant，也不应展示底层 collection 或 vector id。
