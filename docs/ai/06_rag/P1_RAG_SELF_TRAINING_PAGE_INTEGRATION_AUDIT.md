# P1-RAG-SELF-TRAINING-PAGE-INTEGRATION-AUDIT

## 1. 审计结论摘要

本轮只读审计 `E:\work\project\used-car-main` 中与“知识库 / RAG 自助训练”相关的页面和接口，并对照 `auto_wechat` 当前 9000 / 9100 RAG 能力。除新增本文档外，未修改 `used-car-main`，未修改 `auto_wechat` 业务代码，未触发训练、LLM、Milvus 或抖音发送。

结论：

| 检查项 | 结论 |
|---|---|
| 页面是否存在 | 存在，页面 ID 为 `knowledge-base`，入口文案为“知识库” |
| 是否是完整甲方自助训练页 | 否。当前更接近 NewCarProject 模块知识库只读查看 / 运营沉淀查看页 |
| 是否可直接复用给甲方 | 不建议直接复用。权限、数据源、向量库、商户隔离和训练链路均与 `auto_wechat` 现有边界不一致 |
| 是否直连 9100 | 未发现直连 9100 |
| 是否直连 Milvus | 未发现直连 Milvus；`used-car-main` 使用自身后端和 Qdrant |
| 是否接 NewCar 登录态 | 是，前端 API client 使用 cookie session / CSRF 机制，后端用 `require_permission("knowledge:read")` |
| 是否传 `merchant_id` | 是，页面查询 `/api/knowledge-base` 时传 `merchant_id`，后端会做 scope 校验 |
| 是否传 `tenant_id` | 未发现该页面传 `tenant_id` |
| 当前是否能给甲方使用 | 否。应先通过 9000 新增商户自助 RAG API，并由 9000 注入可信商户上下文 |

核心判断：`used-car-main` 的“知识库”页面可以作为信息架构参考，但不能直接作为 `auto_wechat` 的甲方自助训练页。`auto_wechat` 需要通过 9000 暴露商户侧受控 API，由 9000 解析 NewCar 登录态、决定可信 `merchant_id` / `tenant_id` / `account_open_id` / `category_key`，再代理 9100 训练和 Milvus 写入。

## 2. used-car-main 页面定位

| 类型 | 位置 | 说明 |
|---|---|---|
| 页面类型定义 | `E:\work\project\used-car-main\src\types.ts` | `InternalPage` 包含 `"knowledge-base"` |
| 页面权限映射 | `E:\work\project\used-car-main\src\App.vue` | `"knowledge-base": ["knowledge:read"]` |
| 权限树 | `E:\work\project\used-car-main\src\App.vue` | 包含 `knowledge:menu` / `knowledge:read` |
| 菜单入口 | `E:\work\project\used-car-main\src\App.vue` | 导航项 `{ id: "knowledge-base", label: "知识库", permission: "knowledge:read" }` |
| 页面模板 | `E:\work\project\used-car-main\src\App.vue` | `activePage === 'knowledge-base'` 分支 |
| API client | `E:\work\project\used-car-main\src\api.ts` | `VITE_API_BASE`，开发默认 `http://127.0.0.1:8790` |
| 后端接口 | `E:\work\project\used-car-main\backend\app.py` | `GET /api/knowledge-base`、`POST /api/knowledge-base/reindex` |
| 向量库实现 | `E:\work\project\used-car-main\backend\rag_qdrant.py` | Qdrant client / search |
| 配置 | `E:\work\project\used-car-main\backend\config.py` | `QDRANT_URL`、各模块 collection |

页面支持的模块：

| module | 页面文案 |
|---|---|
| `ai_director` | AI 编导 |
| `operation_plan` | 全案策划 |
| `account_position` | 账号定位 |
| `benchmark_account` | 对标账号 |

页面支持的状态筛选：

| status | 页面文案 |
|---|---|
| `all` | 全部 |
| `indexed` | 已进入知识库 |
| `queued` | 等待入库 |
| `indexing` | 入库中 |
| `skipped` | 未达到入库标准 |
| `failed` | 入库失败 |

## 3. 当前页面功能清单

| 功能 | 是否已有 | 文件位置 | 备注 |
|---|---|---|---|
| 知识库列表 | 已有 | `src\App.vue` | 调 `GET /api/knowledge-base` |
| 模块筛选 | 已有 | `src\App.vue` | 四个 NewCarProject 模块 |
| 商户筛选 | 已有 | `src\App.vue` | 前端传 `merchant_id`，后端校验 scope |
| 状态筛选 | 已有 | `src\App.vue` | `indexed/queued/indexing/skipped/failed` |
| 关键词 / 标签筛选 | 已有 | `src\App.vue` | 查询 title/content/source_prompt/metadata |
| 详情查看 | 已有 | `src\App.vue` | 查看知识条目详情 |
| Qdrant 状态展示 | 已有 | `src\App.vue` / `backend\app.py` | 返回脱敏 `qdrant_url` 和 points 状态 |
| 文件上传 | 未发现 | - | 不是当前页面能力 |
| 文本新增 | 未发现 | - | 不是当前页面能力 |
| 文本编辑 | 未发现 | - | 不是当前页面能力 |
| 分类选择 | 部分已有 | `src\App.vue` | 仅 NewCarProject module 维度，不是 `auto_wechat` 的 `category_key` |
| 训练按钮 | 未开放 | `backend\app.py` | `POST /api/knowledge-base/reindex` 第一行直接 403 |
| 训练状态查询 | 未发现 | - | 无 `training_run` 概念 |
| 训练历史 | 未发现 | - | 无训练 run 列表 |
| 删除 / 禁用 | 未发现 | - | 无商户自助删除或禁用入口 |
| 重训 | 未开放 | `backend\app.py` | reindex 接口禁用 |
| 检索预览 | 未发现 | - | 页面不提供训练后预览 |
| Agent 绑定分类 | 未发现 | - | 与 `auto_wechat` Agent 分类绑定不是同一套 |
| 错误提示 | 已有 | `src\App.vue` | 加载失败 toast |
| 空状态 | 已有 | `src\App.vue` | 列表为空时可展示 |
| 大文件限制 | 未发现 | - | 页面无上传能力 |
| 文件类型限制 | 未发现 | - | 页面无上传能力 |
| 敏感内容提示 | 未发现 | - | 需要产品补充 |
| 训练后生效说明 | 未发现 | - | 需要产品补充 |

补充：`used-car-main` 中存在“保存训练样本”类埋点，例如 `recordModuleImplicitFeedback("account_position", ...)`、`recordModuleImplicitFeedback("benchmark_account", ...)`。这些更像模块使用反馈 / 样本沉淀，不等同于面向甲方的 RAG 自助上传、训练、预览、删除闭环。

## 4. 当前 API 调用清单

| method | path | baseURL | request | response | token / 登录态 | merchant_id | tenant_id | 风险 |
|---|---|---|---|---|---|---|---|---|
| GET | `/api/knowledge-base` | `VITE_API_BASE`，开发默认 `http://127.0.0.1:8790` | query：`module`、`merchant_id`、`status`、`keyword`、`tag`、`limit` | `module`、`collection`、脱敏 `qdrant_url`、`qdrant`、`items`、`stats` | cookie session / CSRF；后端 `knowledge:read` | 前端传入，后端校验 scope | 未传 | 可作为只读列表参考，但不能照搬为 `auto_wechat` 可信商户来源 |
| POST | `/api/knowledge-base/reindex` | `VITE_API_BASE` | query：`module`、`merchant_id` | 当前直接 403：知识库重建已关闭 | cookie session；后端 `knowledge:read` | 前端传入，后端后续逻辑会校验 scope，但已被 403 短路 | 未传 | 训练能力未开放，不能作为自助训练入口 |

未发现：

- 前端直连 9100。
- 前端直连 Milvus。
- 代理到 `auto_wechat` 9000。
- 文档上传 API。
- 删除 / 禁用文档 API。
- 训练 run 查询 API。
- 检索预览 API。
- Agent 分类绑定 API。

## 5. 与 auto_wechat 后端能力对照

| 前端自助训练需要 | auto_wechat 当前已有 | 缺口 | 建议 |
|---|---|---|---|
| 可信商户上下文 | 9000 `RequestContext`、NewCar 登录态解析链路 | 需要为自助训练定义稳定商户侧 API | 所有商户自助 RAG 入口必须走 9000 |
| 创建 RAG 文档 | 9000 `POST /integrations/douyin-ai-cs/rag/documents` 代理骨架；9100 `/rag/documents` | 9000 商户管理入口当前 `_deny_merchant_rag_management()` 直接 403 | 后续任务显式打开受控商户写入，不要让前端直连 9100 |
| 触发训练 | 9000 `POST /integrations/douyin-ai-cs/rag/train` 代理骨架；9100 `/rag/train` | 同上，当前商户训练入口关闭 | 增加训练 run 查询和错误展示 |
| Milvus 写入 | 9100 `MilvusVectorStore.upsert_chunks()` 已接入训练链路 | 需要由 9000 约束谁能触发训练 | 训练失败必须明确展示，不假成功 |
| Milvus 搜索 | 9100 `MilvusVectorStore.search()` 已接入 RAG search / reply-suggestion fallback | 自助页面缺 search-preview | 增加只读预览，不触发真实发送 |
| 文档删除 / 禁用 | 9100 Milvus delete 能力存在 | 9000 缺商户自助删除契约 | 删除必须带可信 `document_id + tenant_id + merchant_id` |
| 知识分类 | 9000 `/knowledge-categories`、`/agents/{agent_id}/knowledge-categories` | 当前分类管理 API 权限偏 Agent 管理；分类写入也被显式关闭 | 商户侧只读分类可用，写分类需单独确认 |
| Agent 分类绑定 | 9000 已有 Agent 知识分类绑定 | 页面未接 | 后续页面只展示 / 配置当前商户 Agent 的允许分类 |
| source_chunks 兼容 | reply-suggestion 已保持 `source_chunks` / `rag_sources` 结构 | 自助页面还没有验证入口 | search-preview 返回应复用同一 chunk 结构 |

当前 `auto_wechat` 关键事实：

1. 9000 正式 reply-suggestion 代理位于 `app\routers\douyin_ai_cs_proxy.py`，会注入可信 `allowed_category_keys` 和 `rag_enabled`，不接受前端覆盖。
2. 9000 RAG 文档创建和训练代理骨架已存在，但开头调用 `_deny_merchant_rag_management()`，当前返回 `RAG_MERCHANT_WRITE_DISABLED` / `RAG_MERCHANT_TRAIN_DISABLED`。
3. 9100 RAG / Milvus 底座已覆盖 SQLite 默认、Milvus 配置、collection check、canary、upsert、search、fallback 和 source_chunks 兼容。
4. 默认 `RAG_VECTOR_BACKEND=sqlite` 行为保持不变；`RAG_VECTOR_BACKEND=milvus` 才走 Milvus。

## 6. 权限与商户隔离分析

### 6.1 used-car-main

事实：

1. 前端 API client 使用 `VITE_API_BASE` 调自身后端，`credentials: "include"`，并在非 cookie 模式下才加 `Authorization`。
2. `GET /api/knowledge-base` 使用 `require_permission("knowledge:read")`。
3. 当 `merchant_id != "all"` 时，后端调用 `ensure_merchant()` 和 `require_merchant_scope(auth, target_merchant_id)`。
4. 当普通用户传 `merchant_id=all` 时，后端按 `auth.merchant_ids` 过滤。
5. 内部 `rag_search(module, merchant_id, ...)` 明确 `del merchant_id`，按 module collection 复用全 collection 知识。

风险判断：

- `used-car-main` 的列表接口有商户 scope 校验，作为只读页面相对可控。
- 但其内部 RAG 检索按模块 collection 全局复用，不按商户隔离。这是 NewCarProject 模块知识复用策略，不能照搬到 `auto_wechat` 商户私有知识场景。

### 6.2 auto_wechat 推荐边界

商户自助 RAG 页面必须满足：

1. 前端不能直连 9100。
2. 前端不能直连 Milvus。
3. 前端传入的 `merchant_id` 不能作为可信来源；9000 必须从 NewCar 登录态 / `RequestContext` / 商户绑定关系决定。
4. 商户只能训练当前商户私有知识。
5. 普通商户不能修改统一 `base` 知识库，除非后续产品明确拆分“管理员统一知识库”和“商户私有知识库”。
6. 商户自助训练权限建议使用 `auto_wechat:douyin_ai_cs`，避免另起一套不一致的权限。
7. 分类命中和 Agent 绑定必须由 9000 后端校验，不能只靠前端隐藏。

## 7. 建议 9000 API 契约草案

本节只做设计，不实现。

| method | path | 说明 | 权限 | 可信字段来源 |
|---|---|---|---|---|
| GET | `/merchant/rag/categories` | 返回当前商户可用知识分类 | `auto_wechat:douyin_ai_cs` | `merchant_id` 从 `RequestContext` |
| GET | `/merchant/rag/documents` | 查询当前商户知识文档，支持分页、`category_key`、`status` | `auto_wechat:douyin_ai_cs` | `merchant_id` 从 `RequestContext` |
| POST | `/merchant/rag/documents` | 创建文本知识或上传文档元信息 | `auto_wechat:douyin_ai_cs` | `tenant_id` / `merchant_id` / `account_open_id` 后端校验 |
| POST | `/merchant/rag/documents/{document_id}/train` | 触发训练，9000 调 9100，9100 写 SQLite / Milvus | `auto_wechat:douyin_ai_cs` | `document_id` 必须属于当前商户 |
| GET | `/merchant/rag/training-runs/{run_id}` | 查询训练状态 | `auto_wechat:douyin_ai_cs` | `run_id` 必须属于当前商户 |
| DELETE | `/merchant/rag/documents/{document_id}` | 软删除文档，并通知 9100 删除 / 禁用向量 | `auto_wechat:douyin_ai_cs` | 删除过滤必须包含 `document_id + tenant_id + merchant_id` |
| POST | `/merchant/rag/search-preview` | 训练后检索预览，不触发真实发送 | `auto_wechat:douyin_ai_cs` | 分类范围由 9000 计算 |

可选接口：

| method | path | 说明 |
|---|---|---|
| POST | `/merchant/rag/documents/{document_id}/retrain` | 重训。也可复用 train 接口，通过状态判断幂等 |
| GET | `/merchant/rag/agents` | 返回当前商户可配置知识范围的 Agent |
| PUT | `/merchant/rag/agents/{agent_id}/categories` | 复用或封装现有 Agent 分类绑定能力 |

接口原则：

1. 所有写接口必须审计操作人、商户、账号、分类、文档 ID 和结果。
2. 文件上传必须限制类型、大小、文本抽取方式和超时。
3. search-preview 不调用真实 LLM，不触发 reply-suggestion 自动发送，不放宽 gate。
4. 9100 只作为内部 RAG 服务，不暴露给甲方前端。

## 8. 风险清单

| 风险 | 等级 | 说明 | 建议 |
|---|---|---|---|
| 前端直连 9100 | 高 | 绕过 9000 权限和商户上下文 | 禁止；只能走 9000 |
| 前端直连 Milvus | 高 | 暴露向量库和凭据，无法做租户隔离 | 禁止 |
| 信任前端 `merchant_id` | 高 | 可导致越权训练 / 删除 / 预览 | 9000 从登录态决定可信商户 |
| 商户误改统一 base 知识库 | 高 | 影响所有商户自动回复 | 拆分管理员统一知识与商户私有知识 |
| 训练后立即影响真实自动回复 | 中 | 甲方可能上传错误知识后影响发送建议 | 增加预览、状态、回滚和禁用 |
| 缺少 search-preview | 中 | 甲方无法验证训练是否生效 | 新增只读预览接口 |
| 文件上传安全 | 高 | 大文件、恶意文件、敏感内容、抽取失败 | 限类型、限大小、异步训练、脱敏错误 |
| 大文件导致训练超时 / 成本失控 | 中 | 训练链路和 embedding 可能耗时 | 限额、分页、后台 run |
| 重复训练覆盖策略不清 | 中 | 可能重复 chunk 或旧向量残留 | 定义 document update：先按文档删除再 upsert |
| 删除文档后 Milvus 残留 | 中 | search 仍命中旧 chunk | 删除必须带 `document_id + tenant_id + merchant_id` 并验证 |
| category 未绑定 Agent | 中 | 训练成功但 reply-suggestion 无 source_chunks | 页面提示 Agent 分类绑定状态 |
| RAG 命中但 auto-send gate 阻断 | 中 | 甲方误以为训练无效 | 页面区分“知识命中”和“发送 gate” |
| 页面权限与 NewCar 权限不一致 | 高 | 可见性和后端权限不一致 | 商户侧统一 `auto_wechat:douyin_ai_cs` |
| 多商户数据串读 | 高 | 私有知识泄露 | Milvus filter 强制 `tenant_id + merchant_id + category_key + status` |
| 错误信息泄露内部路径 / token | 高 | 泄露部署和凭据细节 | 所有错误脱敏 |

## 9. 推荐实施路径

1. `P1-RAG-SELF-TRAINING-API-CONTRACT-1`
   - 冻结 9000 商户自助 RAG API 契约、权限、状态、错误码和审计字段。

2. `P1-RAG-SELF-TRAINING-9000-PROXY-1`
   - 打开受控的 9000 文档创建 / 训练 / 删除代理，不让前端直连 9100。

3. `P1-RAG-SELF-TRAINING-PAGE-WIRE-1`
   - 在 `auto_wechat/frontend` 内实现商户自助知识页，接 9000 API；仅使用可信代理。

4. `P1-RAG-SELF-TRAINING-SYNTHETIC-E2E-1`
   - 使用 synthetic 非业务文本验证创建、训练、预览、删除闭环，不调用真实 LLM，不触发发送。

5. `P1-RAG-TRAINING-OPS-RUNBOOK-1`
   - 输出甲方运营手册：上传限制、训练状态、预览、回滚、分类绑定、为什么 RAG 命中不等于自动发送。

## 10. 未改内容

本轮未修改：

1. `used-car-main` 任何代码。
2. `auto_wechat` 业务代码。
3. 9000 接口 schema。
4. 9100 RAG / Milvus 代码。
5. NewCar 登录、权限、商户开通、默认跳转。
6. 自动回复真实发送 gate。
7. `/knowledge-training/ask` 和 `/feedback` schema。
8. `reply-suggestion`、`source_chunks`、`rag_sources` 结构。
9. 任何 token、cookie、secret、password 或真实配置。

本轮未执行：

1. 真实训练。
2. 真实 LLM 调用。
3. 真实 Milvus 连接。
4. 真实抖音发送上游调用。
5. 前端构建或服务启动。

## 11. 验证记录

| 命令 | 结果 | 备注 |
|---|---|---|
| `git status --short`（auto_wechat） | 工作区初始干净 | 新增本文档后仅应出现本文档 |
| `git status --short`（used-car-main） | 失败：不是 git 仓库 | 按源码快照只读扫描 |
| `rg ... used-car-main` | 已执行 | 定位知识库页面、接口、Qdrant、权限 |
| `rg ... auto_wechat` | 已执行 | 定位 9000 代理、9100 RAG/Milvus、分类和 reply-suggestion |
| `git diff --check` | 待最终执行 | 仅检查新增文档空白问题 |
