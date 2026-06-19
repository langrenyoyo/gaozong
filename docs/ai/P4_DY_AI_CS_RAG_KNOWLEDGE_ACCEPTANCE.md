# Phase 4-E 抖音AI客服 RAG 分类知识库闭环验收报告

更新时间：2026-06-19

## 1. 验收范围

本报告验收 Phase 1 到 Phase 4-D-C 的抖音AI客服 RAG 分类知识库后端闭环与前端最小配置入口。

覆盖范围：

1. `9100` RAG 向量检索、分类数据模型、分类过滤检索。
2. `9000` Agent 分类绑定、可信 `allowed_category_keys` 注入。
3. `9100` reply-suggestion 消费 `allowed_category_keys` 并约束 RAG 检索。
4. `9000` RAG 文档创建和训练可信代理。
5. 前端 Agent 分类多选、RAG 文档创建和训练改走 `9000` 可信代理。

不覆盖范围：

1. 不验收自动发送抖音私信，`auto_send=false` 仍是强安全边界。
2. 不验收正式知识库管理页面。
3. 不验收分类创建 UI。
4. 不验收 19000 本地微信 Agent。
5. 不验收生产环境真实迁移执行。

## 2. Phase 实现链路汇总

### Phase 1：真实向量检索

完成项：

1. `rag.repository.search()` 从文本重叠优先升级为向量相似度优先。
2. 使用现有 embedding 能力生成 query embedding。
3. 使用 `knowledge_chunks.embedding_json` 做余弦相似度排序。
4. embedding 失败、chunk embedding 缺失或非法时保留 lexical fallback。
5. `reply_decision_service.build_reply_suggestion()` 继续注入 RAG 结果到 LLM prompt。

关键结论：RAG 成熟度从“仅有链路形态”升级为“真实向量检索 MVP”。

### Phase 2-B：分类数据模型

完成项：

1. `9100` 新增 `knowledge_categories`。
2. `knowledge_documents` 增加 `category_id` / `category_key`，保留旧 `category` 自由文本字段。
3. `knowledge_chunks` 增加 `category_id` / `category_key`。
4. 文档写入支持 `category_id` / `category_key`。
5. `/rag/train` 生成 chunk 时同步 document 分类字段。

关键结论：分类字段已落到 document 和 chunk 两层，为检索过滤提供数据基础。

### Phase 2-C：RAG search 分类过滤

完成项：

1. `RagSearchRequest` 支持 `category_ids` / `category_keys`。
2. `search()` 在 SQL 候选读取层过滤 `knowledge_chunks`。
3. category 过滤同时作用于 vector strategy 和 lexical fallback。
4. 未传分类时保持旧行为。

关键结论：9100 已具备按分类约束召回候选 chunk 的能力。

### Phase 3-B：9000 Agent 分类绑定模型

完成项：

1. `9000` 新增 `agent_knowledge_categories` 模型和迁移文件。
2. 服务层支持绑定、查询、替换、软删 Agent 分类 key。
3. 商户隔离由 `RequestContext.merchant_id` 和 `AiAgent.merchant_id` 校验。
4. base 不强制落绑定行，留给后续注入策略。

关键结论：9000 成为 Agent 分类绑定权威源，避免把绑定关系塞进 Agent JSON 字段。

### Phase 3-C：9000 注入 allowed_category_keys

完成项：

1. reply-suggestion 代理链路构造 `agent_config.allowed_category_keys`。
2. 默认注入 `["base"]`。
3. 追加 Agent active 手动绑定分类 key。
4. 忽略前端伪造的 `allowed_category_keys`。
5. 绑定读取失败时 warning + fallback 到 `["base"]`，不阻断主链路。

关键结论：分类授权上下文由 9000 可信生成，并随 agent_config 传给 9100。

### Phase 3-D：9100 消费 allowed_category_keys

完成项：

1. `AgentConfig` 支持 `allowed_category_keys`。
2. `build_reply_suggestion()` 构造 `RagSearchRequest(category_keys=...)`。
3. 缺失或空数组时保持旧调用方兼容，不启用分类过滤。
4. 9100 不反查 9000 数据库，不自行补 base。

关键结论：Agent 允许分类已经真正参与 reply-suggestion 的 RAG 检索。

### Phase 4-B：9000 分类与绑定 API

完成项：

1. `GET /knowledge-categories` 返回当前商户可见分类，包含 `base`。
2. `GET /agents/{agent_id}/knowledge-categories` 返回手动绑定和 effective 分类。
3. `PUT /agents/{agent_id}/knowledge-categories` 替换手动绑定分类。
4. 请求中包含 base 时不保存为手动绑定行。

关键结论：前端具备读取分类与保存 Agent 分类绑定的可信 API。

### Phase 4-C：前端 Agent 分类多选

完成项：

1. Agent 编辑弹窗加载知识分类列表。
2. base 展示为默认启用且不可取消。
3. merchant 分类支持多选。
4. 创建 Agent 后再保存分类绑定；分类保存失败不回滚 Agent 创建。
5. 编辑时分类加载失败不清空已有绑定，避免误删。
6. 分类不塞进 Agent 基础 payload。

关键结论：Agent 分类绑定具备最小产品化配置入口。

### Phase 4-D-B：9000 RAG 文档/训练可信代理

完成项：

1. `POST /integrations/douyin-ai-cs/rag/documents`。
2. `POST /integrations/douyin-ai-cs/rag/train`。
3. 只接受 `account_open_id`、业务内容和 `category_key` 等非可信字段。
4. `merchant_id` 来自 `RequestContext`。
5. `tenant_id` 使用现有 9000 调 9100 口径。
6. `douyin_account_id` 由已校验的 `account_open_id` 注入。
7. documents 和 train 都校验账号属于当前商户。
8. `category_key` 缺失默认 `base`，非法或不可见分类拒绝。
9. 显式构造转发 payload，不透传浏览器原始 body。

关键结论：知识写入和训练入口不再信任浏览器传 scope 字段。

### Phase 4-D-C：前端 RAG 文档/训练改走 9000

完成项：

1. `createRagDocument()` 改为调用 `9000 /integrations/douyin-ai-cs/rag/documents`。
2. `trainRag()` 改为调用 `9000 /integrations/douyin-ai-cs/rag/train`。
3. 前端请求类型移除 `tenant_id` / `merchant_id` / `douyin_account_id`。
4. `searchRag()` 可保留直连 9100，但标注为内部调试，不作为正式产品入口。
5. 前端不向 reply-suggestion 传 `allowed_category_keys`。

关键结论：前端写入和训练链路已转为 9000 可信代理。

## 3. 当前真实调用链

### 3.1 Agent 分类绑定

```text
前端 SuperMerchantAgent
  -> GET /knowledge-categories
  -> GET /agents/{agent_id}/knowledge-categories
  -> PUT /agents/{agent_id}/knowledge-categories
  -> 9000 agent_knowledge_categories
```

### 3.2 回复建议 RAG 分类过滤

```text
前端 DouyinAiCsWorkbenchPage
  -> 9000 /integrations/douyin-ai-cs/conversations/{conversation_id}/reply-suggestion
  -> 9000 校验企业号归属和 Agent 绑定
  -> 9000 读取 agent_knowledge_categories
  -> 9000 注入 agent_config.allowed_category_keys
  -> 9100 /reply-suggestion
  -> 9100 build_reply_suggestion()
  -> RagSearchRequest(category_keys=allowed_category_keys)
  -> 9100 rag.repository.search()
  -> SQL 层按 category_key 过滤 knowledge_chunks
  -> query embedding + chunk embedding_json 余弦相似度排序
  -> lexical fallback
  -> LLM prompt 注入 RAG context
  -> 返回 suggested_reply / auto_send=false
```

### 3.3 知识文档写入与训练

```text
前端 DouyinAiCsTestPage
  -> createRagDocument()
  -> 9000 /integrations/douyin-ai-cs/rag/documents
  -> 9000 校验 account_open_id 属于当前商户
  -> 9000 校验 category_key 可见性，缺失默认 base
  -> 9000 显式构造 tenant_id / merchant_id / douyin_account_id / category_key
  -> 9100 /rag/documents
  -> knowledge_documents(category_key)

前端 DouyinAiCsTestPage
  -> trainRag()
  -> 9000 /integrations/douyin-ai-cs/rag/train
  -> 9000 校验 account_open_id 属于当前商户
  -> 9000 校验 category_key 可见性，缺失默认 base
  -> 9100 /rag/train
  -> knowledge_chunks(category_key, embedding_json)
```

## 4. 一期 PRD 对照

| 模块 | 状态 | 说明 |
|------|------|------|
| 抖音AI客服 RAG/LLM 回复建议 | 已完成 | 已具备 RAG 检索、LLM 回复建议、人工确认边界。 |
| RAG 真实向量检索 | 已完成 | query embedding + `knowledge_chunks.embedding_json`，lexical fallback 保留。 |
| RAG 分类数据模型 | 已完成 | 9100 已有分类主表，document/chunk 分类字段已落地。 |
| Agent 多分类绑定 | 已完成 | 9000 作为绑定权威源，前端 Agent 编辑页支持 merchant 分类多选。 |
| 分类权限参与检索 | 已完成 | 9000 注入 `allowed_category_keys`，9100 search 按分类过滤。 |
| 知识文档写入可信代理 | 已完成 | documents/train 已通过 9000 注入可信 scope。 |
| 前端 RAG 写入/训练安全化 | 已完成 | 文档创建和训练不再由浏览器传 `tenant_id` / `merchant_id` / `douyin_account_id`。 |
| 正式知识库管理页面 | 未完成 | 当前只完成最小入口，未做完整知识库列表、编辑、删除、训练记录页面。 |
| 分类创建 UI | 未完成 | 当前没有产品化分类创建入口。 |
| 9000 分类主表 | 未完成 | 当前 `GET /knowledge-categories` 基于 base + 已绑定分类；如需完整分类管理，需要后续设计表和迁移。 |
| 抖音 AI 自动托管发送 | 安全暂缓 | 当前 `auto_send=false`，不自动发送私信。 |
| 19000 本地微信 Agent | 不涉及 | 本链路不修改 19000。 |

## 5. RAG 分类知识库闭环验收结论

当前已经形成以下闭环：

```text
分类定义
  -> 文档写入 category_key
  -> 训练同步 category_key 到 chunk
  -> Agent 绑定 merchant 分类
  -> 9000 默认注入 base + 手动绑定分类
  -> 9100 reply-suggestion 按 allowed_category_keys 检索
  -> RAG context 注入 LLM
  -> 返回 AI 回复建议
```

验收结论：

1. 后端闭环已成立。
2. Agent 分类权限已经真正影响 RAG 检索候选集。
3. 文档写入和训练入口已经通过 9000 可信代理收口。
4. 前端已经具备 Agent 分类多选和测试页写入/训练代理调用。
5. 自动发送安全边界未放开。

## 6. 测试记录

本阶段引用前序阶段已记录通过的命令：

1. `python -m pytest tests/test_xg_douyin_ai_cs_rag.py -v`
2. `python -m pytest tests/test_xg_douyin_ai_cs_app.py -v`
3. `python -m pytest tests/test_agent_knowledge_categories.py tests/test_douyin_ai_cs_proxy.py -v`
4. `python -m pytest tests/test_knowledge_categories_api.py -v`
5. `cd frontend && npm run build`

Phase 4-E 本身只做文档和上下文更新，不新增业务代码测试。

## 7. 安全边界复核

必须继续保持：

1. `auto_send=false`。
2. 前端不向 reply-suggestion 传 `allowed_category_keys`。
3. 浏览器不能传可信 `tenant_id` / `merchant_id` / `douyin_account_id`。
4. 9000 不直连或反查 9100 SQLite。
5. 9100 不反查 9000 数据库。
6. searchRag 直连 9100 只作为内部调试，不作为正式产品入口。
7. 未执行数据库迁移前，不得把新表能力视为生产可用。

## 8. 剩余事项

优先级从高到低：

1. 执行并验收 9000 / 9100 相关数据库迁移。
2. 设计 9000 正式 `knowledge_categories` 主表或明确由 9100 分类主表代理展示。
3. 增加正式知识库页面：分类选择、文档列表、创建、编辑、删除、训练状态。
4. 将 `searchRag()` 从内部调试能力收口到可信代理或移出产品入口。
5. 补充生产环境端到端验收：账号归属、分类绑定、文档写入、训练、回复建议、人工发送边界。
6. 明确 NewCarProject 权限、菜单、套餐消耗与知识库管理入口的正式契约。

