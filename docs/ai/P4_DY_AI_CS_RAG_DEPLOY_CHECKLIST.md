# Phase 4-E 抖音AI客服 RAG 分类知识库部署前检查清单

更新时间：2026-06-19

## 1. 部署前总原则

上线前必须确认：

1. 不以本地 SQLite 测试数据作为生产依据。
2. 不跳过数据库迁移验收。
3. 不允许浏览器传可信 scope 字段。
4. 不放开 `auto_send=false`。
5. 不把内部调试页当作正式产品入口。

## 2. 禁止项

上线前禁止：

1. 未执行迁移就依赖 `agent_knowledge_categories`。
2. 未执行迁移就依赖 9100 `knowledge_categories`、document/chunk 分类字段。
3. 前端向 reply-suggestion 传 `allowed_category_keys`。
4. 前端向 RAG documents/train 传 `tenant_id` / `merchant_id` / `douyin_account_id`。
5. 9100 反查 9000 数据库。
6. 9000 直连或反查 9100 SQLite。
7. 开启 AI 自动发送私信。
8. 把 `searchRag()` 直连 9100 能力作为正式商户功能宣传。

## 3. 服务检查

### 3.1 9000 主后端

检查项：

1. 服务可启动。
2. `GET /health` 或现有健康检查可用。
3. `XG_DOUYIN_AI_CS_BASE_URL` 指向正确 9100 地址。
4. 9000 调 9100 的超时配置符合预期。
5. 认证上下文能提供 `RequestContext.merchant_id`。
6. `POST /integrations/douyin-ai-cs/rag/documents` 可用。
7. `POST /integrations/douyin-ai-cs/rag/train` 可用。
8. `GET /knowledge-categories` 可用。
9. `GET /agents/{agent_id}/knowledge-categories` 可用。
10. `PUT /agents/{agent_id}/knowledge-categories` 可用。

### 3.2 9100 抖音AI客服

检查项：

1. 服务可启动。
2. `GET /health` 可用。
3. RAG SQLite 路径指向预期环境。
4. embedding provider 配置符合当前环境策略。
5. LLM provider 配置符合当前环境策略。
6. `/rag/documents` 可用。
7. `/rag/train` 可用。
8. `/rag/search` 支持 `category_keys`。
9. `/reply-suggestion` 能消费 `agent_config.allowed_category_keys`。
10. 所有回复建议返回 `auto_send=false`。

### 3.3 前端

检查项：

1. `npm run build` 通过。
2. `VITE_AUTO_WECHAT_API_BASE_URL` 指向 9000。
3. Agent 编辑页能加载分类。
4. Agent 编辑页能保存 merchant 分类绑定。
5. base 显示为默认启用且不可取消。
6. RAG 文档创建调用 9000 代理。
7. RAG 训练调用 9000 代理。
8. RAG 写入/训练请求体不包含 `tenant_id` / `merchant_id` / `douyin_account_id`。
9. reply-suggestion 请求体不包含 `allowed_category_keys`。
10. 搜索直连 9100 的文案明确为内部调试。

## 4. 数据库检查

### 4.1 9000 数据库

必须确认：

1. `agent_knowledge_categories` 迁移文件已纳入发布包。
2. 迁移在目标环境执行成功。
3. 表结构包含 `merchant_id`、`agent_id`、`category_key`、`scope_type`、`is_base`、`status`、`created_at`、`updated_at`、`deleted_at`。
4. active 绑定不会重复。
5. 软删记录不会被 `list_agent_category_keys()` 返回。
6. 跨商户 Agent 绑定被拒绝。

### 4.2 9100 数据库

必须确认：

1. `knowledge_categories` 已存在。
2. `knowledge_documents.category_id` 已存在。
3. `knowledge_documents.category_key` 已存在。
4. `knowledge_chunks.category_id` 已存在。
5. `knowledge_chunks.category_key` 已存在。
6. `knowledge_chunks.embedding_json` 保留。
7. 训练后 document 分类能同步到 chunk。
8. search SQL 候选读取层按 `category_key` 过滤。

## 5. 权限与隔离检查

必须验证：

1. 当前用户必须有当前商户上下文。
2. 前端不能通过传 `merchant_id` 查询其他商户分类。
3. Agent 必须属于当前商户。
4. 企业号 `account_open_id` 必须属于当前商户。
5. documents 和 train 都必须校验账号归属。
6. `category_key` 必须属于当前商户可见分类或 `base`。
7. 其他商户同名分类不得越权读取知识。
8. 前端伪造 `allowed_category_keys` 不会透传到 9100。

## 6. 手工验收路径

建议按以下顺序验收：

1. 创建或确认一个 active Agent。
2. 确认 `GET /knowledge-categories` 返回 `base`。
3. 给 Agent 绑定一个 merchant 分类。
4. 打开 Agent 编辑页，确认 base 默认启用、merchant 分类已回显。
5. 用当前商户企业号 `account_open_id` 创建一条 `base` 文档。
6. 用同一账号创建一条 merchant 分类文档。
7. 分别触发 `base` 和 merchant 分类训练。
8. 给 Agent 只绑定 `base`，发起 reply-suggestion，确认不会召回未授权 merchant 分类内容。
9. 给 Agent 追加 merchant 分类，再发起 reply-suggestion，确认可召回该分类内容。
10. 确认 reply-suggestion 返回 `auto_send=false`。
11. 尝试使用其他商户账号创建文档，应被拒绝。
12. 尝试传不存在分类，应被拒绝。

## 7. 自动化回归建议

发布前建议运行：

```bash
python -m pytest tests/test_xg_douyin_ai_cs_rag.py -v
python -m pytest tests/test_xg_douyin_ai_cs_app.py -v
python -m pytest tests/test_agent_knowledge_categories.py tests/test_knowledge_categories_api.py tests/test_douyin_ai_cs_proxy.py -v
cd frontend && npm run build
```

如时间允许，再补跑主后端相关回归：

```bash
python -m pytest tests/test_ai_agents.py tests/test_douyin_ai_cs_proxy.py -v
```

## 8. 日志检查

上线观察时重点查看：

1. 9000 RAG documents/train 是否记录账号归属校验失败。
2. 9000 是否出现分类绑定读取失败 warning。
3. 9000 转发 9100 是否超时。
4. 9100 search 是否记录 `category filter` 启用情况。
5. 9100 是否记录 vector / lexical fallback 策略。
6. 日志不得打印完整 embedding。
7. 日志不得打印完整用户私信或完整 chunk 内容。

## 9. 回滚方案

如果上线后出现问题：

1. 前端可回退到上一版本，保留后端代理不影响旧 reply-suggestion。
2. 9000 reply-suggestion 如分类绑定服务异常，会 fallback 到 `["base"]`。
3. 9100 若收到空 `allowed_category_keys`，保持旧行为不启用分类过滤。
4. 如 RAG 写入/训练代理异常，可暂停知识写入入口，不影响已存在回复建议链路。
5. 不建议回滚数据库迁移；如必须回滚，先停写，再备份，再按迁移方案处理。

## 10. 发布结论门槛

满足以下条件才建议进入生产联调：

1. 9000 和 9100 迁移已在目标库执行并备份。
2. 自动化回归通过。
3. 前端构建通过。
4. 手工验收路径通过。
5. `auto_send=false` 已复核。
6. 前端不再向 documents/train 提交可信 scope 字段。
7. 9000 和 9100 职责边界未被破坏。

