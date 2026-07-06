# P2 抖音AI小高客服商户知识库管理 API 规格

## 1. 背景与边界

当前 9100 抖音AI小高客服已经完成 SQLite RAG MVP、OpenAI-compatible LLM client、OpenRouter chat 本地联调和 `/douyin-ai-cs-test` 测试面板。P1 / P2 边界如下：

- P1：将 `/douyin-ai-cs-test` 的能力融合进正式抖音AI小高客服页面，重点覆盖会话消息、RAG 命中、AI 回复建议、人工确认/复制，不自动发送。
- P2：补齐商户知识库管理 API 和接口文档，交给管理员前端/同事对接。

当前 auto_wechat / 9100 侧负责提供商户知识库管理 API 和接口文档。管理员前端 UI 由同事侧对接，不由当前抖音AI客服页面直接承载。

## 2. 服务地址

本地开发默认地址：

```text
http://127.0.0.1:9100
```

本地 Docker 开发环境启动 `9000 + 9100 + frontend`，`19000` 小高AI微信助手仍在 Windows 宿主机单独运行，不进入 Docker。

## 3. 租户/商户/抖音账号隔离规则

所有知识库接口必须按以下三元组隔离：

```text
tenant_id + merchant_id + douyin_account_id
```

要求：

- 不得跨 tenant 返回知识。
- 不得跨 merchant 返回知识。
- 不得跨 douyin_account_id 返回知识。
- 查询文档、chunk、训练记录、反馈记录时都必须带隔离条件。
- `reply-suggestion` 使用 `account_id` 作为当前抖音账号维度，语义上应与 RAG 的 `douyin_account_id` 对齐。

## 4. 当前已实现接口

### 4.1 POST /rag/documents

用途：创建知识文档。

是否已实现：是。

请求示例：

```json
{
  "tenant_id": "demo_tenant",
  "merchant_id": "demo_bba",
  "douyin_account_id": 1,
  "title": "精品BBA话术",
  "content": "我们主要做宝马、奔驰、奥迪等精品BBA车型。客户咨询奥迪A6时，应引导客户留下联系方式。",
  "source_type": "manual",
  "category": "sales_script",
  "brand": "奥迪",
  "vehicle_name": "奥迪A6"
}
```

响应示例：

```json
{
  "document_id": 1,
  "status": "created"
}
```

当前能力确认：

| 项目 | 状态 |
| --- | --- |
| tenant_id + merchant_id + douyin_account_id 隔离 | 已写入 |
| is_active | 表字段已存在，创建时默认 true |
| category / brand / vehicle_name | 已支持写入 |
| document_id | 已返回 |
| chunk_id | 不涉及 |
| training_run_id | 不涉及 |

### 4.2 POST /rag/train

用途：对某个 `tenant_id + merchant_id + douyin_account_id` 范围内的 active 知识文档执行训练和切片。

是否已实现：是。

请求示例：

```json
{
  "tenant_id": "demo_tenant",
  "merchant_id": "demo_bba",
  "douyin_account_id": 1
}
```

响应示例：

```json
{
  "training_run_id": 1,
  "status": "completed",
  "document_count": 1,
  "chunk_count": 3
}
```

当前能力确认：

| 项目 | 状态 |
| --- | --- |
| tenant_id + merchant_id + douyin_account_id 隔离 | 已按 scope 训练 |
| is_active | 只训练 active 文档；训练前会将当前 scope 下旧 chunk 置为 inactive |
| category / brand / vehicle_name | 不作为训练请求字段，来自文档 |
| document_id | 当前不支持按单文档训练 |
| chunk_id | 训练后写入 chunk 表，不在响应中逐条返回 |
| training_run_id | 已返回 |

### 4.3 POST /rag/search

用途：在某个 `tenant_id + merchant_id + douyin_account_id` 范围内搜索 active chunk。

是否已实现：是。

请求示例：

```json
{
  "tenant_id": "demo_tenant",
  "merchant_id": "demo_bba",
  "douyin_account_id": 1,
  "query": "客户问奥迪A6怎么回复",
  "top_k": 5
}
```

响应示例：

```json
{
  "items": [
    {
      "chunk_id": 1,
      "document_id": 1,
      "title": "精品BBA话术",
      "chunk_text": "我们主要做宝马、奔驰、奥迪等精品BBA车型。客户咨询奥迪A6时，应引导客户留下联系方式。",
      "score": 0.4123
    }
  ]
}
```

当前能力确认：

| 项目 | 状态 |
| --- | --- |
| tenant_id + merchant_id + douyin_account_id 隔离 | 已按 scope 检索 |
| is_active | 只检索 active document + active chunk |
| category / brand / vehicle_name | 当前不支持作为 search filter |
| document_id | 响应中返回 |
| chunk_id | 响应中返回 |
| training_run_id | 不涉及 |

### 4.4 POST /douyin/conversations/{conversation_id}/reply-suggestion

用途：基于最新私信内容、商户 prompt 和 RAG 命中结果生成 AI 回复建议。

是否已实现：是。

请求示例：

```json
{
  "tenant_id": "demo_tenant",
  "merchant_id": "demo_bba",
  "account_id": 1,
  "latest_message": "你们有奥迪A6吗？",
  "max_history_messages": 20
}
```

响应示例：

```json
{
  "reply_text": "您好，我们主要做精品BBA车型，奥迪A6可以帮您看近期车源。方便留个联系方式吗？顾问给您发车源和价格参考。",
  "match_level": "high",
  "target_category": "sales_script",
  "target_vehicle_name": "奥迪A6",
  "recommended_vehicles": [],
  "lead_capture_required": true,
  "confidence": 0.82,
  "manual_required": false,
  "auto_send": false,
  "llm_used": true,
  "rag_used": true,
  "source_chunks": [
    {
      "chunk_id": 1,
      "document_id": 1,
      "title": "精品BBA话术",
      "score": 0.4123
    }
  ],
  "warnings": []
}
```

当前能力确认：

| 项目 | 状态 |
| --- | --- |
| tenant_id + merchant_id + douyin_account_id 隔离 | 通过 tenant_id + merchant_id + account_id 调用 RAG |
| is_active | 依赖 RAG search，只使用 active chunk |
| category / brand / vehicle_name | 响应中可能返回 target_category / target_vehicle_name；当前无 target_brand schema 字段 |
| document_id | source_chunks 中返回 |
| chunk_id | source_chunks 中返回 |
| training_run_id | 不涉及 |
| auto_send | 恒为 false |

## 5. P2 建议新增接口

### 5.1 知识文档管理

#### GET /rag/documents

用途：查询某商户某抖音账号下的知识文档列表。

是否已实现：否，P2 待实现。

Query：

```text
tenant_id: string
merchant_id: string
douyin_account_id: int
category?: string
brand?: string
vehicle_name?: string
is_active?: bool
page?: int
page_size?: int
```

响应示例：

```json
{
  "items": [
    {
      "document_id": 1,
      "title": "精品BBA话术",
      "source_type": "manual",
      "category": "sales_script",
      "brand": "奥迪",
      "vehicle_name": "奥迪A6",
      "is_active": true,
      "chunk_count": 3,
      "created_at": "2026-06-17T10:00:00",
      "updated_at": "2026-06-17T10:00:00"
    }
  ],
  "total": 1,
  "page": 1,
  "page_size": 20
}
```

#### GET /rag/documents/{document_id}

用途：查看知识文档详情。

是否已实现：否，P2 待实现。

Query：

```text
tenant_id: string
merchant_id: string
douyin_account_id: int
```

响应示例：

```json
{
  "document_id": 1,
  "tenant_id": "demo_tenant",
  "merchant_id": "demo_bba",
  "douyin_account_id": 1,
  "title": "精品BBA话术",
  "content": "我们主要做宝马、奔驰、奥迪等精品BBA车型。",
  "source_type": "manual",
  "category": "sales_script",
  "brand": "奥迪",
  "vehicle_name": "奥迪A6",
  "is_active": true,
  "chunk_count": 3,
  "created_at": "2026-06-17T10:00:00",
  "updated_at": "2026-06-17T10:00:00"
}
```

#### PATCH /rag/documents/{document_id}

用途：编辑知识文档标题、内容、分类、品牌、车型或启停状态。

是否已实现：否，P2 待实现。

请求示例：

```json
{
  "tenant_id": "demo_tenant",
  "merchant_id": "demo_bba",
  "douyin_account_id": 1,
  "title": "精品BBA奥迪话术",
  "content": "客户咨询奥迪A6时，应引导客户留下联系方式，由顾问发送近期车源和价格参考。",
  "category": "sales_script",
  "brand": "奥迪",
  "vehicle_name": "奥迪A6",
  "is_active": true,
  "updated_by": "admin_user"
}
```

响应示例：

```json
{
  "document_id": 1,
  "status": "updated",
  "requires_retrain": true
}
```

说明：内容、分类、品牌、车型变更后应提示重新训练。P2 第一版可以只返回 `requires_retrain=true`，训练仍由 `POST /rag/train` 显式触发。

#### DELETE /rag/documents/{document_id}

用途：删除或禁用知识文档。

是否已实现：否，P2 待实现。

建议：第一版使用软删除，即 `is_active=false`，避免误删知识和历史训练追溯断裂。

请求示例：

```json
{
  "tenant_id": "demo_tenant",
  "merchant_id": "demo_bba",
  "douyin_account_id": 1,
  "deleted_by": "admin_user"
}
```

响应示例：

```json
{
  "document_id": 1,
  "status": "disabled",
  "requires_retrain": true
}
```

### 5.2 训练管理

#### POST /rag/train

用途：触发训练。

是否已实现：是。P2 建议保留当前 scope 训练，并评估是否增加 `document_id` 增量训练能力。

P2 可选扩展请求：

```json
{
  "tenant_id": "demo_tenant",
  "merchant_id": "demo_bba",
  "douyin_account_id": 1,
  "document_id": 1,
  "mode": "incremental"
}
```

#### GET /rag/training-runs

用途：查询训练历史。

是否已实现：否，P2 待实现。

Query：

```text
tenant_id: string
merchant_id: string
douyin_account_id: int
status?: running | completed | failed
page?: int
page_size?: int
```

响应示例：

```json
{
  "items": [
    {
      "training_run_id": 1,
      "status": "completed",
      "document_count": 1,
      "chunk_count": 3,
      "error": null,
      "created_at": "2026-06-17T10:00:00",
      "finished_at": "2026-06-17T10:00:02"
    }
  ],
  "total": 1,
  "page": 1,
  "page_size": 20
}
```

#### GET /rag/training-runs/{run_id}

用途：查看单次训练结果和错误摘要。

是否已实现：否，P2 待实现。

Query：

```text
tenant_id: string
merchant_id: string
douyin_account_id: int
```

响应示例：

```json
{
  "training_run_id": 1,
  "tenant_id": "demo_tenant",
  "merchant_id": "demo_bba",
  "douyin_account_id": 1,
  "status": "completed",
  "document_count": 1,
  "chunk_count": 3,
  "error": null,
  "created_at": "2026-06-17T10:00:00",
  "finished_at": "2026-06-17T10:00:02"
}
```

### 5.3 搜索和调试

#### GET /rag/documents/{document_id}/chunks

用途：查看某知识文档切片，供管理员排查 RAG 命中来源。

是否已实现：否，P2 待实现。

Query：

```text
tenant_id: string
merchant_id: string
douyin_account_id: int
is_active?: bool
```

响应示例：

```json
{
  "items": [
    {
      "chunk_id": 1,
      "document_id": 1,
      "chunk_index": 1,
      "chunk_text": "我们主要做宝马、奔驰、奥迪等精品BBA车型。",
      "embedding_model": "mock_for_test_only",
      "is_active": true,
      "created_at": "2026-06-17T10:00:00",
      "updated_at": "2026-06-17T10:00:00"
    }
  ]
}
```

#### GET /rag/chunks

用途：按 scope 查询 chunk 列表，可结合 `document_id`、`query` 做排查。

是否已实现：否，P2 待实现。

Query：

```text
tenant_id: string
merchant_id: string
douyin_account_id: int
document_id?: int
is_active?: bool
query?: string
page?: int
page_size?: int
```

响应示例：

```json
{
  "items": [
    {
      "chunk_id": 1,
      "document_id": 1,
      "title": "精品BBA话术",
      "chunk_index": 1,
      "chunk_text": "客户咨询奥迪A6时，应引导客户留下联系方式。",
      "is_active": true
    }
  ],
  "total": 1,
  "page": 1,
  "page_size": 20
}
```

### 5.4 反馈能力

#### POST /rag/feedback

用途：记录管理员或客服对 RAG 命中、AI 回复建议的反馈。

是否已实现：否，P2 后续建议接口，暂未实现。

请求示例：

```json
{
  "tenant_id": "demo_tenant",
  "merchant_id": "demo_bba",
  "douyin_account_id": 1,
  "conversation_id": 1,
  "document_id": 1,
  "chunk_id": 1,
  "rating": "useful",
  "comment": "这条话术可以继续保留，但建议补充首付和分期说明。",
  "created_by": "admin_user"
}
```

响应示例：

```json
{
  "feedback_id": 1,
  "status": "created"
}
```

建议字段：

```text
tenant_id
merchant_id
douyin_account_id
conversation_id?
document_id?
chunk_id?
rating: useful | normal | inaccurate
comment
created_by
created_at
```

#### GET /rag/feedback

用途：查询反馈列表，供后续知识优化和训练复盘。

是否已实现：否，P2 后续建议接口，暂未实现。

Query：

```text
tenant_id: string
merchant_id: string
douyin_account_id: int
rating?: useful | normal | inaccurate
document_id?: int
chunk_id?: int
page?: int
page_size?: int
```

响应示例：

```json
{
  "items": [
    {
      "feedback_id": 1,
      "conversation_id": 1,
      "document_id": 1,
      "chunk_id": 1,
      "rating": "useful",
      "comment": "这条话术可以继续保留。",
      "created_by": "admin_user",
      "created_at": "2026-06-17T10:10:00"
    }
  ],
  "total": 1,
  "page": 1,
  "page_size": 20
}
```

## 6. 请求/响应字段说明

### 6.1 已有数据表字段

当前 SQLite RAG 已有表：

- `knowledge_documents`
- `knowledge_chunks`
- `rag_training_runs`
- `llm_call_logs`

`knowledge_documents` 当前字段：

```text
id
tenant_id
merchant_id
douyin_account_id
title
content
source_type
category
brand
vehicle_name
is_active
created_at
updated_at
```

`knowledge_chunks` 当前字段：

```text
id
document_id
tenant_id
merchant_id
douyin_account_id
chunk_text
chunk_index
embedding_json
embedding_model
content_hash
is_active
created_at
updated_at
```

`rag_training_runs` 当前字段：

```text
id
tenant_id
merchant_id
douyin_account_id
status
document_count
chunk_count
error
created_at
finished_at
```

### 6.2 P2 建议补充字段

如需完整支持管理员知识库管理，建议后续评估以下字段或表：

| 对象 | 字段/表 | 用途 |
| --- | --- | --- |
| knowledge_documents | created_by / updated_by | 操作人追踪 |
| knowledge_documents | disabled_at / disabled_by | 软删除追踪 |
| knowledge_documents | last_trained_at | 列表展示训练状态 |
| knowledge_documents | training_status | 标记 pending / trained / failed |
| rag_feedback | 新表 | 记录 useful / normal / inaccurate 与文字反馈 |

注意：本轮只输出接口规格，不创建迁移，不修改数据库。

## 7. 错误码建议

| HTTP 状态 | code | 场景 |
| --- | --- | --- |
| 400 | invalid_request | 请求字段缺失、格式错误、content 为空 |
| 403 | scope_forbidden | 当前用户无权访问该 tenant / merchant / douyin_account |
| 404 | document_not_found | 文档不存在或不在当前 scope 内 |
| 404 | training_run_not_found | 训练记录不存在或不在当前 scope 内 |
| 409 | document_requires_retrain | 文档已更新但未重新训练 |
| 500 | internal_error | 服务内部错误，不能把上游完整错误或密钥信息透出 |

错误响应建议：

```json
{
  "code": "document_not_found",
  "message": "知识文档不存在或无权访问",
  "request_id": "optional-request-id"
}
```

## 8. UI 对应关系

参考 AI 编导训练 UI 截图，P2 API 对应关系建议如下：

| UI 能力 | API |
| --- | --- |
| 顶部训练模块切换 | 前端路由/状态，不一定需要 9100 API |
| 知识/训练内容展示 | `GET /rag/documents`、`GET /rag/documents/{document_id}` |
| 历史任务 | `GET /rag/training-runs`、`GET /rag/training-runs/{run_id}` |
| 继续生成或补充内容 | P2 暂不默认纳入，后续可评估 AI 生成知识草稿接口 |
| 有用 / 一般 / 不准反馈 | `POST /rag/feedback` |
| 文字反馈输入 | `POST /rag/feedback` 的 `comment` |
| 查看知识切片 | `GET /rag/documents/{document_id}/chunks` |
| 知识召回测试 | `POST /rag/search` |

## 9. 安全边界

- 9100 当前只生成回复建议。
- `auto_send` 恒为 `false`。
- 不自动发送抖音私信。
- 商户知识库管理 API 只能管理知识，不应触发私信发送。
- 管理员端写入知识后，应通过 `POST /rag/train` 显式训练。
- 文档、接口示例和测试中不得写真实 API Key。

## 10. embedding 策略

当前建议：

```env
XG_DOUYIN_AI_LLM_EMBEDDING_ENABLED=false
```

说明：

- OpenRouter 当前只用于 chat。
- 不默认使用 OpenRouter 做 embedding。
- `/rag/train` 在关闭真实 embedding provider 时使用本地 `mock_for_test_only` embedding。
- 真实 embedding provider 后续单独接入，并需要重新验证跨 `tenant_id + merchant_id + douyin_account_id` 隔离。

## 11. 后续待确认

1. 管理员前端是按固定 `merchant_id` 进入，还是允许切换商户。
2. 知识分类是固定枚举，还是自由文本。
3. 是否需要知识模板接口，例如常用销售话术模板、车型 FAQ 模板。
4. 反馈接口是否在 P2 第一版落库，还是只先做 API 预留。
5. `DELETE /rag/documents/{document_id}` 是否统一按软删除实现。
6. 训练是否需要支持按 `document_id` 增量训练。
7. 是否需要操作人字段 `created_by / updated_by / deleted_by`。
8. 是否需要接入 NewCarProject 权限字典或管理员身份体系。
9. 文档更新后是否自动标记 `requires_retrain`，以及由谁触发训练。
10. 管理员端是否需要展示 `embedding_model`，还是仅作为排障字段返回。
