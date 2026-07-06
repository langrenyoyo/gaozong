# P1-RAG-UNIFIED-KB-TRAINING-API-CONTRACT-FOR-CAR-PROJECT

## 1. 方向修正

本轮修正 `P1-RAG-ADMIN-UNIFIED-KB-API-CONTRACT-1` 的方向偏差。

上一轮将契约表述为“auto_wechat 自己提供管理员前端 `/admin/rag/*` 契约”。该口径已修正，本阶段正确方向是：

```text
car-project-main 负责统一训练端页面和操作入口
    -> 调用 auto_wechat 9000 统一知识库训练 API
auto_wechat 9000 负责权限、白名单、统一知识库上下文、训练编排和安全边界
    -> 内部调用 auto_wechat 9100 RAG 能力
auto_wechat 9100 负责文档处理、chunk、embedding、Milvus 写入、删除和检索
```

因此，本阶段推荐主路径不是 `/admin/rag/*`，而是面向训练端调用的：

```text
/knowledge-training/*
```

`/admin/rag/*` 仅作为未来 auto_wechat 自建管理员页面时的备选命名，本阶段不采用。

本轮只修正文档，不实现 API，不修改前端，不触发真实训练。

## 2. 角色边界

### 2.1 car-project-main

`car-project-main` 是统一训练端页面和管理员操作入口。

职责：

1. 提供统一训练端页面。
2. 提供管理员操作入口。
3. 负责 UI 交互、上传入口、训练按钮、训练状态展示和检索预览展示。
4. 调用 auto_wechat 9000 的训练 API。

明确不负责：

1. 不直接调用 9100。
2. 不直接调用 Milvus / Qdrant。
3. 不展示底层 collection / vector store 状态。
4. 不传可信 `tenant_id` / `merchant_id`。
5. 不把自身权限体系直接照搬为 auto_wechat 权限体系。

### 2.2 auto_wechat 9000

`auto_wechat` 9000 是统一知识库训练 API 服务方，也是唯一可信网关。

职责：

1. 对外提供统一知识库训练 API。
2. 校验来源、白名单、内部服务 token 或管理员权限。
3. 固定统一知识库上下文。
4. 编排调用 9100。
5. 记录训练 run 和审计日志。
6. 返回安全脱敏错误。
7. 保证训练流程不触发真实发送。

### 2.3 auto_wechat 9100

`auto_wechat` 9100 是内部 RAG 能力服务。

职责：

1. RAG 文档处理。
2. 文本切分。
3. embedding。
4. Milvus upsert / delete / search。
5. SQLite fallback 和训练 run 底座能力。

当前推荐仍走 9000，不允许 `car-project-main` 前端或后端直接调用 9100。后续如产品明确要改为内部服务间专线，也必须单独冻结服务认证、审计和脱敏契约。

## 3. 不做事项

本阶段明确不做：

1. 不实现 API。
2. 不改 auto_wechat 前端。
3. 不改 `car-project-main`。
4. 不触发真实训练。
5. 不调用真实 LLM。
6. 不连接真实 Milvus。
7. 不连接真实 Qdrant。
8. 不调用真实抖音发送上游。
9. 不触发真实私信发送。
10. 不改自动回复真实发送 gate。
11. 不改 NewCarProject 服务端。
12. 不新增 migration。
13. 不提交 token / cookie / secret / password。
14. 不把 `/admin/rag/*` 写成当前推荐主路径。
15. 不设计商户 RAG 管理接口。
16. 不把 `auto_wechat:douyin_ai_cs` 作为知识库训练权限。
17. 不让 `car-project-main` 直连 9100 / Milvus / Qdrant。
18. 不让 `car-project-main` 传入可信 `tenant_id` / `merchant_id`。

## 4. 统一知识库上下文

统一知识库上下文由 auto_wechat 9000 固定封装：

```text
tenant_id = xiaogao_system
merchant_id = xiaogao_base
category_key = base
```

规则：

1. `car-project-main` 请求体即使带 `tenant_id` / `merchant_id`，也不得被信任。
2. P1 推荐对请求体中的 `tenant_id` / `merchant_id` 返回 `400 KNOWLEDGE_TRAINING_SCOPE_FIELD_FORBIDDEN`，并记录审计摘要。
3. 普通商户不能训练 `base` / 统一知识库。
4. 当前不开放商户私有知识训练。
5. 统一知识库训练结果会影响使用 `base` 分类的 Agent。
6. 训练命中不等于允许自动发送；自动回复仍由既有真实发送 gate 最终判断。

## 5. 认证与权限策略

本轮比较两种方式，并推荐短期采用方案 A。

### 5.1 方案 A：服务间调用

调用链：

```text
car-project-main 前端
    -> car-project-main 后端
    -> auto_wechat 9000 /knowledge-training/*
```

规则：

1. `car-project-main` 前端继续使用它自己的登录态和管理员入口。
2. `car-project-main` 后端调用 auto_wechat 9000。
3. auto_wechat 9000 校验内部服务 token、IP 白名单或签名。
4. 请求头携带脱敏 actor 信息用于审计：
   - `X-Operator-Id`
   - `X-Operator-Account`
   - `X-Request-Id`
5. actor 字段只用于审计，不替代服务认证。

优点：

1. 符合当前“car-project-main 做训练端，auto_wechat 做训练 API”的职责拆分。
2. 不要求 NewCarProject 立即新增权限码。
3. 可以复用现有 `/knowledge-training/*` 内部训练能力和白名单思路。

风险：

1. 必须保证服务间 token / 白名单 / 签名配置安全。
2. actor 只能用于审计，不能作为鉴权依据。
3. 需要防止 `car-project-main` 透传可信 scope。

### 5.2 方案 B：转发 NewCar 管理员 token

调用链：

```text
car-project-main 前端或后端
    -> auto_wechat 9000 /knowledge-training/*
    -> auto_wechat 9000 校验 NewCar 管理员 token
```

规则：

1. auto_wechat 9000 直接校验 NewCar token。
2. 后续可能需要新增 NewCar 权限：

```text
auto_wechat:admin:knowledge_training
```

3. 当前不立即新增该权限码，除非产品重新确认。

风险：

1. 需要 NewCarProject 权限体系配合。
2. 需要明确 token 校验、权限同步、错误码和过期处理。
3. 实现成本高于方案 A。

### 5.3 本轮推荐

短期采用方案 A：服务间调用 + 白名单 / 内部 token / actor 审计。

中长期可升级方案 B：NewCar 权限 `auto_wechat:admin:knowledge_training`。

明确不使用：

1. `auto_wechat:douyin_ai_cs`
2. `auto_wechat:admin:autoreply`
3. `auto_wechat:admin:ai_reply_records`
4. `auto_wechat:admin:return_visit_prompts`
5. `auto_wechat:admin:compute_config`
6. `auto_wechat:admin:accounts`
7. `auto_wechat:admin:forbidden_words`

## 6. API 总览

当前推荐主路径为 `/knowledge-training/*`。

| 方法 | 路径 | P1/P2 | 用途 |
|---|---|---|---|
| GET | `/knowledge-training/categories` | P1 必做 | `car-project-main` 获取统一知识库分类。 |
| GET | `/knowledge-training/documents` | P1 必做 | 查询统一知识库文档列表。 |
| GET | `/knowledge-training/documents/{document_id}` | P1 必做 | 查询统一知识库文档详情。 |
| POST | `/knowledge-training/documents` | P1 必做 | 创建手工文本知识。 |
| PUT | `/knowledge-training/documents/{document_id}` | P1 必做 | 更新手工文本知识。 |
| POST | `/knowledge-training/documents/upload` | P1 可选 | 上传文件生成统一知识库文档。 |
| POST | `/knowledge-training/documents/{document_id}/train` | P1 必做 | 触发单文档训练。 |
| GET | `/knowledge-training/training-runs/{run_id}` | P1 必做 | 查询训练状态。 |
| GET | `/knowledge-training/training-runs` | P1 可选 | 查询训练历史列表。 |
| DELETE | `/knowledge-training/documents/{document_id}` | P1 必做 | 软删除 / 禁用统一知识库文档。 |
| POST | `/knowledge-training/search-preview` | P1 必做 | 检索预览。 |
| GET | `/knowledge-training/audit-logs` | P1 可选 / P2 必做 | 查询训练审计日志。 |

统一响应外壳建议：

```json
{
  "success": true,
  "data": {},
  "message": "success"
}
```

统一错误响应建议：

```json
{
  "success": false,
  "error": {
    "code": "KNOWLEDGE_TRAINING_DOCUMENT_NOT_FOUND",
    "message": "统一知识库文档不存在"
  }
}
```

## 7. API 详细契约

### 7.1 查询分类

```text
GET /knowledge-training/categories
```

用途：`car-project-main` 获取统一知识库分类。

响应：

```json
{
  "success": true,
  "data": {
    "categories": [
      {
        "key": "base",
        "name": "小高知识库",
        "description": "统一基础知识分类",
        "document_count": 12,
        "updated_at": "2026-07-04T10:00:00+08:00"
      }
    ]
  },
  "message": "success"
}
```

规则：

1. `base` 是统一知识库默认分类。
2. 不返回 Milvus / Qdrant collection。
3. 不展示底层向量库状态。

### 7.2 查询文档列表

```text
GET /knowledge-training/documents
```

查询参数：

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `category_key` | string | 否 | 默认 `base`。 |
| `status` | string | 否 | `draft` / `active` / `disabled` / `deleted` / `failed`。 |
| `keyword` | string | 否 | 标题或摘要关键词。 |
| `page` | integer | 否 | 默认 1。 |
| `page_size` | integer | 否 | 默认 20，最大 100。 |

响应：

```json
{
  "success": true,
  "data": {
    "items": [
      {
        "document_id": "doc_123",
        "title": "基础接待规则",
        "category_key": "base",
        "status": "active",
        "chunk_count": 20,
        "last_training_run_id": "run_456",
        "last_training_status": "completed",
        "updated_at": "2026-07-04T10:00:00+08:00",
        "created_at": "2026-07-04T09:00:00+08:00"
      }
    ],
    "total": 1,
    "page": 1,
    "page_size": 20
  },
  "message": "success"
}
```

规则：

1. 只返回统一知识库文档。
2. 不返回商户私有知识。
3. 不返回 collection / vector id。
4. 列表不返回完整正文。

### 7.3 查询文档详情

```text
GET /knowledge-training/documents/{document_id}
```

响应：

```json
{
  "success": true,
  "data": {
    "document_id": "doc_123",
    "title": "基础接待规则",
    "content": "用于管理员维护的统一知识正文。",
    "category_key": "base",
    "status": "active",
    "chunk_count": 20,
    "last_training_run": {
      "training_run_id": "run_456",
      "status": "completed",
      "chunk_count": 20
    },
    "created_at": "2026-07-04T09:00:00+08:00",
    "updated_at": "2026-07-04T10:00:00+08:00"
  },
  "message": "success"
}
```

规则：

1. 只能查询统一知识库上下文内的文档。
2. 找不到返回 `404 KNOWLEDGE_TRAINING_DOCUMENT_NOT_FOUND`。
3. 不泄露内部路径、vector id、服务 token 或堆栈。

### 7.4 创建手工文本知识

```text
POST /knowledge-training/documents
```

请求：

```json
{
  "title": "基础接待规则",
  "content": "用于管理员维护的统一知识正文。",
  "category_key": "base",
  "source_type": "manual_text",
  "metadata": {
    "remark": "本次新增原因"
  }
}
```

响应：

```json
{
  "success": true,
  "data": {
    "document_id": "doc_123",
    "status": "draft",
    "category_key": "base"
  },
  "message": "success"
}
```

规则：

1. P1 优先支持 `manual_text`。
2. `tenant_id` / `merchant_id` 由 9000 固定。
3. 请求体出现 `tenant_id` / `merchant_id` 时，P1 推荐返回 `400 KNOWLEDGE_TRAINING_SCOPE_FIELD_FORBIDDEN`。
4. `title` 必填，建议长度 1 到 100。
5. `content` 必填，建议长度 1 到 200000，最终上限在实现任务中确认。
6. `category_key` 必须存在且允许训练端维护。
7. 创建后不自动训练。
8. `metadata` 只允许保存非敏感摘要，不保存 token、cookie、secret、password、完整客户私信、手机号、微信号。

### 7.5 更新文档

```text
PUT /knowledge-training/documents/{document_id}
```

请求：

```json
{
  "title": "基础接待规则",
  "content": "更新后的统一知识正文。",
  "category_key": "base",
  "metadata": {
    "remark": "修正旧内容"
  }
}
```

响应：

```json
{
  "success": true,
  "data": {
    "document_id": "doc_123",
    "status": "draft",
    "category_key": "base",
    "updated_at": "2026-07-04T10:30:00+08:00"
  },
  "message": "success"
}
```

规则：

1. 更新不会自动触发训练。
2. 更新后需要重新训练才能保证最新知识进入检索。
3. 更新必须记录审计。

### 7.6 文件上传

```text
POST /knowledge-training/documents/upload
```

P1 建议先不做文件上传，或列为可选。

如果定义该接口，请求为 `multipart/form-data`：

| 字段 | 必填 | 说明 |
|---|---|---|
| `file` | 是 | 上传文件。 |
| `category_key` | 是 | 默认 `base`。 |
| `title` | 否 | 不传时可由文件名生成。 |
| `remark` | 否 | 操作原因。 |

规则：

1. 文件类型必须白名单。
2. 必须限制单文件大小。
3. 文件名必须安全处理。
4. 解析失败返回脱敏错误。
5. 不保存危险路径。
6. 不触发真实发送。

### 7.7 单文档训练

```text
POST /knowledge-training/documents/{document_id}/train
```

请求：

```json
{
  "mode": "rebuild_document",
  "dry_run": false
}
```

响应：

```json
{
  "success": true,
  "data": {
    "training_run_id": "run_456",
    "document_id": "doc_123",
    "status": "queued"
  },
  "message": "success"
}
```

规则：

1. `rebuild_document` 表示删除该 document 旧向量后重建。
2. P1 不开放 `rebuild_all`。
3. 不触发真实发送。
4. 不调用抖音上游。
5. 训练失败必须写入 run 状态。
6. 即使当前实现可同步完成，契约仍保留 `queued` / `running` / `completed` / `failed` 状态。

### 7.8 查询训练状态

```text
GET /knowledge-training/training-runs/{run_id}
```

响应：

```json
{
  "success": true,
  "data": {
    "training_run_id": "run_456",
    "document_id": "doc_123",
    "status": "completed",
    "chunk_count": 20,
    "error_code": null,
    "error_message": null,
    "started_at": "2026-07-04T10:31:00+08:00",
    "completed_at": "2026-07-04T10:31:08+08:00"
  },
  "message": "success"
}
```

规则：

1. 错误信息必须脱敏。
2. 不返回上游 token、内部堆栈、本地路径。
3. 只允许查询统一知识库 run。

### 7.9 查询训练历史列表

```text
GET /knowledge-training/training-runs
```

查询参数：

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `document_id` | string | 否 | 按文档过滤。 |
| `status` | string | 否 | 按 run 状态过滤。 |
| `page` | integer | 否 | 默认 1。 |
| `page_size` | integer | 否 | 默认 20，最大 100。 |

P1 可选；P1 如不做列表，至少要支持单 run 查询和文档最近训练状态展示。

### 7.10 软删除 / 禁用文档

```text
DELETE /knowledge-training/documents/{document_id}
```

请求可选：

```json
{
  "mode": "soft_delete",
  "reason": "旧知识不再适用"
}
```

响应：

```json
{
  "success": true,
  "data": {
    "document_id": "doc_123",
    "status": "deleted"
  },
  "message": "success"
}
```

规则：

1. 默认 `soft_delete`。
2. 必须同步禁用或删除对应向量。
3. 向量删除失败要可追踪，不允许假成功。
4. 不做硬删除作为默认行为。
5. 禁止不带 `document_id` 的全库删除。

### 7.11 检索预览

```text
POST /knowledge-training/search-preview
```

请求：

```json
{
  "query": "客户问：这台车还有吗？",
  "category_keys": ["base"],
  "top_k": 5
}
```

响应：

```json
{
  "success": true,
  "data": {
    "matches": [
      {
        "document_id": "doc_123",
        "title": "基础接待规则",
        "category_key": "base",
        "chunk_text": "命中的知识片段摘要。",
        "score": 0.82
      }
    ]
  },
  "message": "success"
}
```

规则：

1. 只做 RAG 检索预览。
2. P1 不调用 LLM 生成答案。
3. 不触发真实发送。
4. 不返回 collection / vector id。
5. `category_keys` 为空时直接返回空结果，不查底层向量库。
6. `chunk_text` 必须限制长度。

### 7.12 审计日志

```text
GET /knowledge-training/audit-logs
```

用途：查询训练审计日志。

建议字段：

| 字段 | 说明 |
|---|---|
| `actor` | 操作人摘要。 |
| `action` | `create_document` / `update_document` / `train_document` / `delete_document` / `search_preview`。 |
| `document_id` | 关联文档。 |
| `category_key` | 关联分类。 |
| `before_summary` | 修改前摘要，不保存敏感全文。 |
| `after_summary` | 修改后摘要，不保存敏感全文。 |
| `reason` | 操作原因。 |
| `created_at` | 操作时间。 |

P1 可选，P2 必做。P1 即使不提供列表接口，也建议先落基础审计记录。

## 8. 状态机

### 8.1 document.status

| 状态 | 含义 |
|---|---|
| `draft` | 已创建或已编辑，尚未训练或需要重训。 |
| `active` | 当前文档已训练并可被检索。 |
| `disabled` | 管理员禁用，文档保留但不参与检索。 |
| `deleted` | 软删除，不参与检索。 |
| `failed` | 最近一次训练或解析失败，需要处理。 |

### 8.2 training_run.status

| 状态 | 含义 |
|---|---|
| `queued` | 已创建任务，等待执行。 |
| `running` | 正在切分、生成 embedding 或写入向量库。 |
| `completed` | 训练完成。 |
| `failed` | 训练失败。 |
| `cancelled` | 已取消。 |

## 9. 错误码

| 错误码 | HTTP 状态 | 说明 |
|---|---:|---|
| `KNOWLEDGE_TRAINING_UNAUTHENTICATED` | 401 | 未认证。 |
| `KNOWLEDGE_TRAINING_PERMISSION_DENIED` | 403 | 无训练权限或服务认证失败。 |
| `KNOWLEDGE_TRAINING_DOCUMENT_NOT_FOUND` | 404 | 文档不存在。 |
| `KNOWLEDGE_TRAINING_CATEGORY_NOT_FOUND` | 404 | 分类不存在。 |
| `KNOWLEDGE_TRAINING_INVALID_DOCUMENT` | 422 | 文档参数不合法。 |
| `KNOWLEDGE_TRAINING_SCOPE_FIELD_FORBIDDEN` | 422 | 请求体包含禁止由调用方传入的 scope 字段。 |
| `KNOWLEDGE_TRAINING_FILE_TOO_LARGE` | 422 | 文件过大。 |
| `KNOWLEDGE_TRAINING_FILE_TYPE_NOT_ALLOWED` | 422 | 文件类型不允许。 |
| `KNOWLEDGE_TRAINING_RUN_NOT_FOUND` | 404 | 训练 run 不存在。 |
| `KNOWLEDGE_TRAINING_STATUS_CONFLICT` | 409 | 当前状态不允许该操作。 |
| `KNOWLEDGE_TRAINING_FAILED` | 502 | 训练失败。 |
| `KNOWLEDGE_TRAINING_VECTOR_DELETE_FAILED` | 502 | 向量删除失败。 |
| `KNOWLEDGE_TRAINING_SEARCH_FAILED` | 502 | 检索预览失败。 |
| `KNOWLEDGE_TRAINING_UPSTREAM_UNAVAILABLE` | 502 | 9100 或向量服务不可用。 |

错误信息规则：

1. 不返回 token、cookie、secret、password。
2. 不返回完整客户私信、手机号、微信号。
3. 不返回 Milvus / Qdrant URI、host、collection。
4. 不返回 Python 堆栈、本地路径、上游原始异常全文。
5. 可返回阶段化错误码和脱敏短消息。

## 10. 安全边界

1. 训练不会触发真实私信发送。
2. 训练不会修改自动回复真实发送 gate。
3. 检索预览不会调用真实发送。
4. 检索预览 P1 不调用 LLM。
5. 统一知识库训练会影响所有使用 `base` 的 Agent，因此必须有认证、审计和预览。
6. 不能暴露 Milvus / Qdrant collection。
7. 不能让 `car-project-main` 决定 `tenant_id` / `merchant_id`。
8. `direct_9100` 不能照搬。
9. 文件上传必须限制类型和大小。
10. 错误信息必须脱敏。
11. 删除 / 重训必须有 `document_id`、审计原因和状态追踪。
12. 统一知识命中不等于允许自动发送。

## 11. car-project-main 对接建议

可复用：

1. 页面布局。
2. 知识库列表交互。
3. 训练按钮。
4. 状态展示。
5. 检索预览交互。

不可复用：

1. `direct_9100`。
2. Qdrant 状态展示。
3. collection 暴露。
4. 前端传 `merchant_id`。
5. 自身权限体系直接照搬。
6. 直接把 `car-project-main` 当 auto_wechat 商户自助页。

推荐对接方式：

1. `car-project-main` 前端调自己的后端。
2. `car-project-main` 后端以服务间方式调用 `auto_wechat 9000 /knowledge-training/*`。
3. auto_wechat 9000 固定统一知识库上下文。
4. auto_wechat 9000 内部调用 9100。
5. 页面只展示业务状态，不展示底层向量库状态。

## 12. P1/P2 范围切分

P1 必做：

1. 手工文本知识创建 / 编辑。
2. 文档列表 / 详情。
3. 单文档训练。
4. training run 查询。
5. search-preview。
6. 软删除 / 禁用。
7. 固定统一知识库上下文。
8. 服务间认证 / 白名单。
9. 基础审计记录。

P1 可选：

1. 文件上传。
2. 训练历史列表。
3. 分类管理。

P2：

1. 批量导入。
2. `rebuild_all`。
3. 富文本 / 多格式解析增强。
4. 审批流。
5. 版本回滚。
6. 多语言知识。
7. 更细粒度权限。

## 13. 后续任务

建议后续执行：

1. `P1-RAG-UNIFIED-KB-TRAINING-9000-PROXY-1`
2. `P1-RAG-UNIFIED-KB-TRAINING-CAR-PROJECT-WIRE-1`
3. `P1-RAG-UNIFIED-KB-TRAINING-SYNTHETIC-E2E-1`
4. `P1-RAG-TRAINING-OPS-RUNBOOK-1`

继续暂停：

1. `P1-RAG-SELF-TRAINING-API-CONTRACT-1`
2. `P1-RAG-SELF-TRAINING-9000-PROXY-1`
3. `P1-RAG-SELF-TRAINING-PAGE-WIRE-1`
4. `P1-RAG-SELF-TRAINING-SYNTHETIC-E2E-1`

## 14. 未改内容

本轮仅调整文档，未做以下事项：

1. 未修改 auto_wechat 业务代码。
2. 未修改 auto_wechat 前端。
3. 未修改 `car-project-main`。
4. 未实现 API。
5. 未新增数据库 migration。
6. 未新增权限码。
7. 未触发真实训练。
8. 未调用真实 LLM。
9. 未连接真实 Milvus。
10. 未连接真实 Qdrant。
11. 未调用真实抖音发送上游。
12. 未触发真实私信发送。
13. 未修改自动回复真实发送 gate。
14. 未提交 token / cookie / secret / password。
