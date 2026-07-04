# P1-RAG-SELF-TRAINING-PAGE-INTEGRATION-AUDIT

## 0. 口径更正

1. 上一轮误审计了 `E:\work\project\used-car-main`，该路径审计结论已作废。
2. 本轮正确审计路径是 `E:\work\project\car-porject-main`。
3. `car-porject-main` 审计事实有效：它是独立 `KnowledgeTrain` 项目，包含“抖音客服训练”和“知识库”页面能力。
4. “商户自助训练当前商户私有知识”的产品方向已暂停，本阶段不开放。
5. 当前正确方向是：管理员训练统一知识库。
6. `car-porject-main` 只能作为管理员统一知识库训练页面交互参考，不能直接作为甲方普通商户页面。
7. 不再进入 `P1-RAG-SELF-TRAINING-API-CONTRACT-1`。
8. 下一步改为：`P1-RAG-ADMIN-UNIFIED-KB-API-CONTRACT-1`。

## 1. 审计结论摘要

本轮结论不是“甲方商户自助训练页面对接”，而是“管理员统一知识库训练页面参考审计”。

| 项目 | 结论 |
|---|---|
| 页面是否存在 | 存在。`car-porject-main` 是独立 `KnowledgeTrain` 项目，包含“抖音客服训练”和“知识库”页面。 |
| 当前定位 | 可作为管理员统一知识库训练页面的交互参考。 |
| 是否可直接给甲方普通商户使用 | 不可。项目 README 明确“不需要登录”，前端还会创建 `KnowledgeTrain` 本地超管用户。 |
| 是否接 NewCar 登录态 | 未接真实 NewCar token/cookie。前端使用 localStorage 用户对象和 `X-User-Id` / `X-User-Role` 请求头。 |
| 是否传 `merchant_id` | 是。页面和接口会传 `merchant_id`，但它不是 `auto_wechat` / NewCar 权威商户上下文。 |
| 前端是否直连 9100 | 未发现前端直连 9100；前端调用自身同源 `/api/...`。 |
| 后端是否直连 9100 | 是。`car-porject-main` 后端默认 `direct_9100`，会由自身后端直连 9100。 |
| 是否直连 Milvus | 未发现。 |
| 是否直连 Qdrant | 是。`car-porject-main` 后端会直连 Qdrant。 |
| 是否暴露向量库细节 | 是。知识库页会展示 Qdrant 状态、URL、collection 和错误信息。 |
| 是否适合照搬 | 不适合。必须由 9000 作为唯一可信网关重新收口权限、上下文、脱敏和审计。 |

## 2. car-porject-main 页面定位

| 项 | 位置 / 事实 |
|---|---|
| 项目路径 | `E:\work\project\car-porject-main` |
| Git 状态 | 该目录不是 Git 仓库，`git status --short` 返回 `fatal: not a git repository` |
| 页面入口 | `frontend/index.html` 引入 `/assets/app.js` |
| 页面组件 | `frontend/assets/app.js`，单文件原生 JavaScript |
| 训练壳入口 | `renderKnowledgeTrain()` / `initKnowledgeTrainApp()` |
| 菜单 | `KNOWLEDGE_TRAIN_MODULES`：AI编导训练、抖音客服训练、账号定位训练、对标账号训练、全案策划训练、知识库 |
| 抖音客服训练页面 | `renderDouyinCsTrainingModule()` + `submitDouyinTrainingAsk()` |
| 知识库页面 | `renderKnowledgeBase()` / `renderKnowledgeBaseModule()` / `loadKnowledgeBase()` |
| API client | `api(path, options)`，同源 `/api/...`，本地可 fallback 到 `http://127.0.0.1:8788` |
| 认证头 | `apiAuthHeaders()` 发送 `X-User-Id`、`X-User-Role` |
| env / 配置 | `backend/app.py` 的 `load_ai_config()`，以及 `DOUYIN_CS_TRAINING_*`、`QDRANT_*`、`AI_DIRECTOR_RAG_*` |

## 3. 当前页面功能清单

| 功能 | 是否已有 | 文件位置 | 当前判断 |
|---|---|---|---|
| 管理员训练问答 | 有 | `frontend/assets/app.js` | 可参考交互，但必须改走 9000 受控管理员接口。 |
| 回答反馈 | 有 | `/api/douyin-cs-training/feedback` | 可参考“有用 / 一般 / 不准”反馈体验。 |
| 训练历史 | 有 | `/api/ai-chat-sessions`、`/api/ai-chat-messages` | 保存问答历史到本地 `ai_chat_*`。 |
| 统一知识库记录展示 | 部分有 | `frontend/assets/app.js` 知识库区域 | 展示 Qdrant / SQLite 里的知识记录，不是 9100 `knowledge_documents` 管理页。 |
| Qdrant 状态展示 | 有 | `/api/knowledge-base` | 不应给普通商户展示；管理员页也应脱敏展示。 |
| 文档新增 | 缺失 | - | 未发现独立文档新增表单。 |
| 文件上传 | 缺失 | - | 该训练页没有上传知识文件。 |
| 文本编辑 | 缺失 | - | 抖音客服训练是问答式输入，不是文档编辑。 |
| 分类选择 | 缺失 | - | 没有 `category_key` / `allowed_category_keys` 选择。 |
| 训练状态 | 部分有 | `douyinTrainingPendingRequest` | 只有前端 pending 和返回状态，不是正式 training run 状态机。 |
| 删除 / 禁用 | 缺失 | - | 未发现统一知识文档删除 / 禁用入口。 |
| 重训 | 部分有 | `/api/knowledge-base/requeue` | 仅对本地知识记录重新入库到 Qdrant，不是 9100 文档重训。 |
| 检索预览 | 缺失 | - | 管理员无法通过页面验证统一知识训练是否命中。 |
| Agent 绑定分类 | 缺失 | - | 未对接 auto_wechat 的 Agent 分类绑定。 |
| 错误提示 | 有 | 前端 toast + 后端错误透传 | 可能暴露上游错误文案，需要 9000 统一脱敏。 |
| 空状态 | 有 | `knowledgeBaseMarkup()` / `renderDouyinCsTrainingModule()` | 可参考。 |
| 大文件限制 | 不适用 | - | 当前没有知识文件上传。 |
| 敏感内容提示 | 缺失 | - | 没有客户隐私、手机号、微信号等训练前提示。 |
| 训练后生效说明 | 部分有 | README / 页面文案 | 缺少“训练可能影响统一 base 知识，但不绕过真实发送 gate”的说明。 |

## 4. 当前 API 调用清单

| method | path | baseURL | request | response | token | `merchant_id` | 风险 |
|---|---|---|---|---|---|---|---|
| GET | `/api/bootstrap` | 同源或 `127.0.0.1:8788` | 无 | 配置摘要 | 否 | 否 | 公共配置读取。 |
| GET | `/api/ai-chat-sessions?merchant_id=&module=douyin_cs_training` | 同源 | query | 会话列表 | `X-User-*` | 是 | 前端传 `merchant_id`，但该上下文不是 NewCar 权威来源。 |
| GET | `/api/ai-chat-messages?merchant_id=&module=douyin_cs_training&session_key=&limit=` | 同源 | query | 消息列表 | `X-User-*` | 是 | 依赖本项目内角色，不是 NewCar token。 |
| POST | `/api/douyin-cs-training/ask` | 同源 | `merchant_id`、`session_key`、`session_title`、`question`、`prompt`、`douyin_account_id`、`use_xiaogao_knowledge_base` | `answer`、`training_id`、`used_knowledge_base`、本地 message id | `X-User-*` | 是 | 默认后端再直连 9100，并使用固定 tenant / merchant。 |
| POST | `/api/douyin-cs-training/feedback` | 同源 | `message_id`、`training_id`、`rating`、`comment` | `training_id`、`rating`、`status` | `X-User-*` | 间接 | 会转发到 9100 `/knowledge-training/{training_id}/feedback`。 |
| GET | `/api/knowledge-base?module=&merchant_id=&status=&keyword=&tag=&limit=` | 同源 | query | `items`、`stats`、`qdrant` | `X-User-*` | 是 / all | 会返回 Qdrant URL、collection、状态，不适合给普通商户。 |
| POST | `/api/knowledge-base/requeue` | 同源 | `knowledge_id`、`force`、`module` | `ok`、`message`、`module` | `X-User-*` | 间接 | 重新入库 Qdrant，属于管理员操作。 |

外部转发事实：

- `direct_9100`：`backend/app.py` 的 `douyin_cs_training_request()` 直接请求 `service_base_url + /knowledge-training/ask`，默认 `service_base_url=http://127.0.0.1:9100`。
- `gateway_9000`：同函数支持先请求 `gateway_base_url`，并从 payload 删除 `tenant_id` / `merchant_id`，但当前默认不是该模式。
- 直连 9100 时，后端会注入 `fixed_tenant_id`、`fixed_merchant_id`，默认分别是 `new_car_project` 和 `1`。
- 知识库页面的 Qdrant 使用 `backend/rag_qdrant.py`，不是 Milvus。

这些事实可作为管理员统一知识库页面设计参考，但 `direct_9100` 不能照搬到 `auto_wechat` 前端或甲方页面。

## 5. 与 auto_wechat 后端能力对照

| 管理员统一知识库需要 | auto_wechat 已有 | 缺口 | 建议 |
|---|---|---|---|
| 9000 可信网关 | `app.auth.context.RequestContext`、`get_request_context_required`、`XgDouyinAiCsClient` | 缺管理员统一知识库正式契约 | 下一步冻结管理员 API 契约，不开放商户自助训练。 |
| 内部训练问答 | 9000 `/knowledge-training/ask`，9100 `/knowledge-training/ask` | 当前偏内部白名单 / 固定上下文，缺管理员控制台契约 | 可评估复用，但必须经 9000 固定或受控封装统一知识库上下文。 |
| RAG 文档创建 | `POST /integrations/douyin-ai-cs/rag/documents` 代理骨架 | 当前被 `_deny_merchant_rag_management("RAG_MERCHANT_WRITE_DISABLED")` 关闭 | 不为普通商户打开；管理员统一知识库另行设计。 |
| RAG 训练 | `POST /integrations/douyin-ai-cs/rag/train` 代理骨架 | 当前被 `_deny_merchant_rag_management("RAG_MERCHANT_TRAIN_DISABLED")` 关闭 | 不作为商户训练入口；管理员入口需补 training run。 |
| 分类与 Agent 绑定 | `knowledge_categories`、`agent_knowledge_categories`、`allowed_category_keys` | 管理员训练统一知识后，仍需确认哪些 Agent 使用 base / 分类 | 管理员页只训练统一知识；Agent 分类绑定继续走既有链路。 |
| Milvus 写入 / 检索 | 9100 `MilvusVectorStore`、`RAG_VECTOR_BACKEND` | 管理员页面不应知道 Milvus | 前端和 9000 不直连 Milvus，由 9100 内部处理。 |
| 检索预览 | 9100 有底层 RAG search 能力 | 缺管理员统一知识 search-preview 契约 | 新增管理员 search-preview 建议，但本轮不实现。 |
| 文档删除 / 重训 | 9100 有文档 / chunk / Milvus 底座 | 缺统一知识文档列表、删除、训练记录查询 | 在下一任务冻结契约。 |

## 6. 权限与统一知识库边界

1. `car-porject-main` 未读取 NewCar token。它的 README 明确项目“不需要登录”，前端通过 `knowledgeTrainUser()` 构造 `{ id: 1, role: "super_admin", name: "KnowledgeTrain" }`。
2. `car-porject-main` 后端的 `request_actor()` 信任 `X-User-Id` / `X-User-Role` 或 query/body 里的 `_user_id` / `_role`。这只能用于该项目本地训练后台，不可作为 `auto_wechat` 权限来源。
3. 页面和接口都会传 `merchant_id`。该字段不能作为可信上下文；统一知识库训练上下文应由 9000 后端固定或受控决定。
4. 当前确认不开放普通商户训练当前商户私有知识。
5. 当前确认不让商户训练 `base` / 统一知识库。
6. 当前不把 `auto_wechat:douyin_ai_cs` 用作知识库训练权限；该权限仍可作为商户 AI 客服权限。
7. 当前不新增权限码。后续如需 NewCar 权限，再单独确认是否新增 `auto_wechat:admin:knowledge_training`。

当前可选策略：

- A. 继续沿用内部白名单 / 管理员受控 API。
- B. 后续如需 NewCar 权限，再单独确认管理员知识训练权限码。

统一知识库建议上下文：

```text
tenant_id = xiaogao_system
merchant_id = xiaogao_base
```

或由 9000 后端固定封装。前端不能传可信 `tenant_id` / `merchant_id`，也不能展示或操作 Milvus / Qdrant 底层 collection。

## 7. 建议 9000 管理员统一知识库 API 契约草案

只做设计，本轮不实现。最终接口必须在 `P1-RAG-ADMIN-UNIFIED-KB-API-CONTRACT-1` 中冻结。

| method | path | 用途 | 关键规则 |
|---|---|---|---|
| GET | `/admin/rag/categories` | 管理员查看统一知识分类 | 只返回允许管理员维护的统一知识分类。 |
| GET | `/admin/rag/documents` | 管理员查看统一知识文档 | 不暴露 Milvus / Qdrant collection 细节。 |
| POST | `/admin/rag/documents` | 管理员新增统一知识文档 | 9000 注入固定或受控统一知识库上下文。 |
| POST | `/admin/rag/documents/{document_id}/train` | 管理员触发训练 | 返回 training run id，不直接假成功。 |
| GET | `/admin/rag/training-runs/{run_id}` | 查询训练状态 | 支持 queued/running/succeeded/failed/partial_failed。 |
| DELETE | `/admin/rag/documents/{document_id}` | 删除 / 禁用统一知识文档 | 必须同步 9100 SQLite 和 Milvus 删除；不允许裸删全库。 |
| POST | `/admin/rag/search-preview` | 管理员检索预览 | 不触发 LLM，不触发发送，只验证统一知识召回。 |

补充说明：

1. 可以评估复用现有 `/knowledge-training/*` 内部接口，但不能让管理员前端直连 9100。
2. 9000 仍是唯一可信网关。
3. 前端不得传可信 `tenant_id` / `merchant_id`。
4. 前端不得展示或操作 Milvus / Qdrant 底层 collection。
5. `direct_9100` 不能照搬到 `auto_wechat` 前端。

当前暂停 / 不作为本阶段建议：

- 商户自助训练当前商户私有知识。
- 旧的商户 RAG 管理接口草案。
- `P1-RAG-SELF-TRAINING-API-CONTRACT-1`。
- `P1-RAG-SELF-TRAINING-9000-PROXY-1`。
- `P1-RAG-SELF-TRAINING-PAGE-WIRE-1`。
- `P1-RAG-SELF-TRAINING-SYNTHETIC-E2E-1`。

## 8. 风险清单

| 风险 | 当前发现 | 管理员统一知识库方向建议 |
|---|---|---|
| `direct_9100` 被照搬 | `car-porject-main` 后端默认 direct_9100 | `auto_wechat` 前端只调 9000，管理员训练也由 9000 转发。 |
| Qdrant 状态泄露 | `/api/knowledge-base` 返回 qdrant.url、collection、error | 普通商户不得看到；管理员页也应脱敏展示。 |
| 前端传 `merchant_id` | 当前页面大量传 `merchant_id` | 9000 忽略可信 scope 字段，统一知识上下文后端固定。 |
| 统一知识影响面大 | 统一知识训练可能影响所有商户 / 所有 Agent 的 base 知识 | 必须管理员权限、审计日志、预览验证和回滚说明。 |
| 训练影响回复建议 | RAG 命中会影响 AI 回复建议 | 不得绕过真实发送 gate；训练命中不等于自动发送。 |
| 缺 search-preview | 当前页面没有管理员统一知识检索预览 | 增加管理员 preview，避免训练后无法确认效果。 |
| 删除 / 重训残留 | 当前页面不处理 Milvus 残留 | 删除 / 重训必须覆盖 9100 SQLite 与 Milvus，并保留诊断。 |
| 分类未绑定 Agent | 当前页面没有分类绑定概念 | 管理员页面需提示：训练后仍可能因 Agent 分类未绑定导致 `source_chunks` 为空。 |
| 错误信息泄露 | 可能暴露内部服务、路径、向量库配置 | 9000 统一脱敏错误码和诊断字段。 |
| 大文件成本 / 超时 | 当前无文件上传与异步状态设计 | 后续文件训练必须限制类型、大小、解析耗时，并走 training run。 |

## 9. 推荐实施路径

建议进入：

1. `P1-RAG-ADMIN-UNIFIED-KB-API-CONTRACT-1`
2. `P1-RAG-ADMIN-UNIFIED-KB-9000-PROXY-1`
3. `P1-RAG-ADMIN-UNIFIED-KB-PAGE-WIRE-1`
4. `P1-RAG-ADMIN-UNIFIED-KB-SYNTHETIC-E2E-1`
5. `P1-RAG-TRAINING-OPS-RUNBOOK-1`

明确暂停：

- `P1-RAG-SELF-TRAINING-API-CONTRACT-1`
- `P1-RAG-SELF-TRAINING-9000-PROXY-1`
- `P1-RAG-SELF-TRAINING-PAGE-WIRE-1`
- `P1-RAG-SELF-TRAINING-SYNTHETIC-E2E-1`

## 10. 未改内容

- 未修改 `E:\work\project\car-porject-main` 任何文件。
- 未修改 `auto_wechat` 业务代码。
- 未实现 API。
- 未触发真实训练。
- 未调用 LLM。
- 未连接 Milvus。
- 未连接 Qdrant。
- 未调用抖音发送上游。
- 未触发私信发送。
- 未修改自动回复真实发送 gate。
- 未修改 NewCarProject 服务端。
- 未提交 token / cookie / secret / password。

## 11. 验证记录

| 命令 / 检查 | 结果 |
|---|---|
| `git status --short`，目录 `E:\work\project\auto_wechat` | 本轮开始前仅有 `?? docs/ai/P1_RAG_SELF_TRAINING_PAGE_INTEGRATION_AUDIT.md`。 |
| `git status --short`，目录 `E:\work\project\car-porject-main` | 上轮记录：失败，`fatal: not a git repository`。本轮未修改该目录。 |
| 人工检查 | 文档明确 `used-car-main` 结论作废，并以 `car-porject-main` 审计事实为准。 |
| 人工检查 | 文档明确当前不开放商户自助训练，只允许管理员训练统一知识库。 |
| 人工检查 | 旧商户 RAG 管理草案已降级为暂停，不作为当前阶段推荐接口。 |
| `git diff --check` | 已执行，通过。 |
| `git diff --no-index --check -- NUL docs\ai\P1_RAG_SELF_TRAINING_PAGE_INTEGRATION_AUDIT.md` | 已执行，未发现空白错误；仅有 LF/CRLF 提示。 |
