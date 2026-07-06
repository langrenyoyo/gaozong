# P1-CAR-PROJECT-DOUYIN-CS-AUTOREPLY-RAG-9000-RUNTIME-SMOKE

## 1. 目标与边界

本轮验证已经提交的 `car-porject-main` 中“AI 抖音客服自动回复训练”专用链路：

```text
car-porject-main 后端
-> auto_wechat 9000 /knowledge-training/*
-> auto_wechat 9100
-> Milvus
```

本轮只做运行态 smoke 和文档记录，不修改业务代码，不触发 LLM、抖音发送或私信发送，不使用真实业务知识。

## 2. 运行态环境

已确认运行态服务：

- auto_wechat 9000：运行中，`GET /openapi.json` 返回 200。
- auto_wechat 9100：运行中，`GET /openapi.json` 返回 200。
- car-porject-main：8788 端口存在旧进程，但未加载专用接口；本轮在 8791 临时启动后端进程用于 smoke，验证后已停止。

本轮使用的环境变量名：

```text
AUTO_WECHAT_KNOWLEDGE_TRAINING_BASE_URL
AUTO_WECHAT_KNOWLEDGE_TRAINING_INTERNAL_TOKEN
AUTO_WECHAT_KNOWLEDGE_TRAINING_OPERATOR_SOURCE
KNOWLEDGE_TRAINING_INTERNAL_TOKENS
XG_DOUYIN_AI_CS_BASE_URL
```

未记录任何真实 token、URI、账号、密码或 Milvus 连接信息。

## 3. 健康检查

9000 openapi 已包含：

- `/knowledge-training/categories`
- `/knowledge-training/documents`
- `/knowledge-training/documents/{document_id}/train`
- `/knowledge-training/training-runs/{run_id}`
- `/knowledge-training/search-preview`

9100 openapi 已包含同名 `/knowledge-training/*` 路由。

9100 容器内 Milvus collection check 结果：

```text
backend=milvus
connected=True
collection_exists=True
schema_match=True
dimension=2048
metric_type=COSINE
```

## 4. knowledge-base 列表 smoke

请求：

```text
GET /api/douyin-cs-autoreply/knowledge-base
```

结果：

```text
status=200
categories_count>=1
documents_count>=1
```

字段名扫描未发现以下底层字段：

```text
qdrant
collection
vector
point
milvus
token
password
```

说明：历史 synthetic 文档标题中可能含有 `TOKEN` 字样，这是测试数据标识，不是 internal token。

## 5. synthetic create/train/run/search/delete

本轮创建 synthetic 非业务文档：

```text
document_id=14
training_run_id=17
category_key=base
source_type=manual_text
```

未传入可信 `tenant_id` / `merchant_id`，由 auto_wechat 9000 后端固定统一知识库上下文。

训练结果：

```text
train_status=completed
chunk_count=1
error_code=None
```

检索结果：

```text
search_hit=True
search_result_count=1
```

删除结果：

```text
delete_ok=True
```

## 6. delete 后检索验证

删除后复查同一 synthetic 标识：

```text
search_after_delete_hit=False
cleanup_ok=True
```

结论：本轮没有遗留 synthetic 向量数据。

## 7. 其他训练标签影响检查

本轮未修改其他训练标签。轻量检查结果：

- `frontend/assets/app.js` 中其他 Qdrant 展示仍存在，属于其他训练模块或旧知识库页面，本轮允许保留。
- `backend/app.py` 中 Qdrant 客户端和旧链路仍存在，属于其他训练模块，本轮未触碰。
- `douyin_cs_training_request` 已不再使用 `direct_9100`。
- `douyin-cs-autoreply` 专用 API 未调用 Qdrant。

## 8. internal token 前端泄露检查

在 `car-porject-main/frontend` 执行：

```text
rg "AUTO_WECHAT_KNOWLEDGE_TRAINING_INTERNAL_TOKEN|dev_knowledge_training_token|Authorization: Bearer" frontend
```

结果：未命中。

结论：internal token 仅在后端运行态环境中使用，未进入前端代码。

## 9. Qdrant / direct_9100 排除确认

本模块主路径确认：

- `douyin_cs_training_request` 不再拼接 direct_9100。
- `douyin-cs-autoreply` 专用 knowledge-base API 通过 auto_wechat 9000。
- 列表响应字段名未暴露 Qdrant / Milvus / collection / vector / point 等底层字段。
- Qdrant 在 README、旧脚本或其他训练模块中的残留不属于本轮失败项。

## 10. 测试结果

car-porject-main：

```text
python tests\test_douyin_cs_autoreply_9000_proxy.py -v
结果：3 tests OK

python -m py_compile backend\app.py
结果：通过

python -m unittest discover -s gold\tests -v
结果：11 tests OK
```

auto_wechat：

```text
git diff --check
结果：通过
```

## 11. 残留风险

1. 8788 端口原有 car-porject-main 进程仍是旧进程，未加载专用接口；实际部署需重启 car-porject-main 后端。
2. 其他训练模块仍保留 Qdrant 链路和页面展示，这是本轮明确保留范围。
3. 本轮只验证后端专用 API，没有做浏览器页面端到端点击验证。

## 12. 未改内容

- 未修改 car-porject-main 业务代码。
- 未修改 auto_wechat 业务代码。
- 未修改 NewCarProject。
- 未修改自动回复 gate。
- 未新增 `/merchant/rag/*`。
- 未把 `/admin/rag/*` 作为主路径。
- 未调用 LLM。
- 未调用抖音发送上游。
- 未触发私信发送。
- 未使用 Qdrant。
- 未提交真实 token / cookie / secret / password / Milvus URI / Qdrant URI。

## 13. 下一步任务

建议进入：

```text
P1-CAR-PROJECT-DOUYIN-CS-AUTOREPLY-RAG-PAGE-WIRE-1
```

目标：在不暴露 internal token、不绕过 9000 后端代理的前提下，将 car-porject-main 页面中的“AI 抖音客服自动回复训练”文档管理交互接入本轮已验证的专用 knowledge-base API。
