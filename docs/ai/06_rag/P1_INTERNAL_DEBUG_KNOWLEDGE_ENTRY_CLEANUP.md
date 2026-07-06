# P1-INTERNAL-DEBUG-KNOWLEDGE-ENTRY-CLEANUP-1

## 1. 任务边界

本轮目标是清理知识库相关内部 debug、历史入口和误导性商户入口，确保商户端不暴露知识库训练、上传、写入、调试入口。

本轮未改：

1. 9100 RAG 检索、向量检索、embedding 逻辑。
2. `/knowledge-training/ask` 和 `/knowledge-training/{training_id}/feedback` 请求 / 响应 schema。
3. NewCar 登录、Local Agent / 19000、live-check、自动发送链路。
4. Agent 是否参考小高知识库、知识范围绑定的业务能力。

## 2. 审计矩阵

| 入口 / 文件 | 类型 | 是否运行态可访问 | 面向用户 | 当前保护 | 是否与产品边界冲突 | 建议处理 |
|---|---|---|---|---|---|---|
| 9000 `POST /knowledge-training/ask` | 管理员训练问答代理 | 是 | 管理员 / 内部人员 | IP 白名单；生产未显式配置白名单时不沿用本机默认值 | 否 | 保留，schema 不改 |
| 9000 `POST /knowledge-training/{training_id}/feedback` | 管理员训练反馈代理 | 是 | 管理员 / 内部人员 | IP 白名单；反馈归属仍由 9100 校验 | 否 | 保留，schema 不改 |
| 9000 `GET /knowledge-categories` | Agent 知识范围只读接口 | 是 | 商户端 Agent 配置 | NewCar 登录 + `auto_wechat:ai_agents` 或 `auto_wechat:agent` | 否 | 保留为“知识范围”读取 |
| 9000 `POST /knowledge-categories` | 历史商户分类创建入口 | 是 | 不应面向商户 | 固定 403 `KNOWLEDGE_CATEGORY_CREATE_DISABLED` | 否，已锁定 | 保留锁定状态 |
| 9000 `POST /integrations/douyin-ai-cs/rag/documents` | 历史 RAG 写入代理 | 是 | 不应面向商户 | 固定 403 `RAG_MERCHANT_WRITE_DISABLED`，不调用 9100 | 否，已锁定 | 保留锁定状态 |
| 9000 `POST /integrations/douyin-ai-cs/rag/train` | 历史 RAG 训练代理 | 是 | 不应面向商户 | 固定 403 `RAG_MERCHANT_TRAIN_DISABLED`，不调用 9100 | 否，已锁定 | 保留锁定状态 |
| 9206 `apps/knowledge` `GET /api/knowledge/categories` | 过渡服务只读分类 | 仅独立启动 9206 时可访问 | 内部 / gateway | Gateway header 上下文；本轮移除历史 `auto_wechat:knowledge` 权限，保留 `auto_wechat:ai_agents` / `auto_wechat:agent` | 否 | 保留只读过渡能力 |
| 9206 `POST /api/knowledge/categories` | 过渡服务分类写入 | 仅独立启动 9206 时可访问 | 不应面向商户 | 固定 403 `KNOWLEDGE_APP_CATEGORY_WRITE_DISABLED` | 否，已锁定 | 保留锁定状态 |
| 9206 `POST /api/knowledge/rag/documents` | 过渡服务 RAG 写入 | 仅独立启动 9206 时可访问 | 不应面向商户 | 固定 403 `KNOWLEDGE_APP_RAG_WRITE_DISABLED`；本轮移除历史权限注入 | 否，已锁定 | 保留锁定状态 |
| 9206 `POST /api/knowledge/rag/train` | 过渡服务 RAG 训练 | 仅独立启动 9206 时可访问 | 不应面向商户 | 固定 403 `KNOWLEDGE_APP_RAG_TRAIN_DISABLED`；本轮移除历史权限注入 | 否，已锁定 | 保留锁定状态 |
| `packages/clients/knowledge_client.py` | 9206 内部 client | 代码可用，未接入商户正式路径 | 内部服务调用 | Gateway header；本轮不再注入 `auto_wechat:knowledge` | 原历史权限容易误导 | 收口权限注入 |
| `frontend/src/features/knowledge/*` | 历史商户知识库页面 / API | 正式路由未挂载，但源码仍存在 | 不应面向商户 | 旧路由已重定向；后端写入训练已 403 | 是，源码文案和 API 容易被误挂回商户端 | 本轮删除 |
| `frontend/src/features/douyin-cs/pages/DouyinAiCsTestPage.tsx` | 历史内部 RAG 调试页 | 正式路由已重定向，但源码仍存在 | 不应面向商户 | 旧路由 `/douyin-ai-cs-test` 重定向 | 是，含创建 / 训练 / 搜索知识库调试动作 | 本轮删除 |
| `frontend/src/pages/KnowledgeBasePage.tsx` / `KnowledgeCategoriesPage.tsx` / `DouyinAiCsTestPage.tsx` | 历史 re-export | 正式路由未引用 | 不应面向商户 | 无单独保护，依赖未挂路由 | 是，容易被误恢复 | 本轮删除 |
| 前端 `SideNav` / `capabilities.ts` | 商户菜单 | 是 | 商户 | 仅五个正式能力中心；无知识库管理中心；不含 `auto_wechat:knowledge` | 否 | 保持 |
| Agent 编辑页知识范围 | 商户配置 | 是 | 商户 | NewCar 登录 + Agent 权限；只写 Agent 分类绑定表 | 否 | 保留，文案为“AI 客服知识范围 / 参考小高知识库” |

## 3. 本轮真实发现

1. 前端历史知识库页面虽然未进入正式路由，但源码仍保留“新增知识”“整理小高知识库”“创建商户分类”等文案和调用函数，存在后续误挂回商户端的风险。
2. 历史内部测试页 `DouyinAiCsTestPage` 仍保留 RAG 创建、训练、搜索动作，虽已通过旧路由重定向隔离，但源码仍是误导性入口。
3. 9206 过渡服务和 `packages.clients.knowledge_client` 仍使用历史权限 `auto_wechat:knowledge`，不符合当前 NewCar 权限口径。
4. 9000 主应用的 RAG 写入 / 训练代理已固定 403，`/knowledge-training/*` 已按 IP 白名单保护，未发现需要扩大修改的运行态写入口。

## 4. 本轮变更

1. 删除前端历史知识库管理页面和 re-export：
   - `frontend/src/features/knowledge/api.ts`
   - `frontend/src/features/knowledge/routes.ts`
   - `frontend/src/features/knowledge/types.ts`
   - `frontend/src/features/knowledge/pages/KnowledgeBasePage.tsx`
   - `frontend/src/features/knowledge/pages/KnowledgeCategoriesPage.tsx`
   - `frontend/src/pages/KnowledgeBasePage.tsx`
   - `frontend/src/pages/KnowledgeCategoriesPage.tsx`
   - `frontend/src/api/knowledge.ts`
2. 删除历史 RAG 调试页：
   - `frontend/src/features/douyin-cs/pages/DouyinAiCsTestPage.tsx`
   - `frontend/src/pages/DouyinAiCsTestPage.tsx`
3. 9206 过渡服务权限收口：
   - 分类只读不再接受 `auto_wechat:knowledge`。
   - RAG 过渡上下文不再接受 `auto_wechat:knowledge`。
4. 内部 client 权限收口：
   - `list_categories()` 改为注入 `auto_wechat:ai_agents`。
   - RAG 写入 / 训练 client 改为只注入 `auto_wechat:douyin_ai_cs`。
5. 测试更新：
   - 增加前端历史知识库 / 调试页文件缺失断言。
   - 增加 9206 拒绝历史 `auto_wechat:knowledge` 权限断言。
   - 增加 client 不注入历史权限断言。

## 5. 保留入口

1. `/knowledge-training/ask`：管理员 / 内部人员训练问答，IP 白名单准入，schema 不变。
2. `/knowledge-training/{training_id}/feedback`：管理员 / 内部人员训练反馈，IP 白名单准入，schema 不变。
3. `/knowledge-categories` `GET`：Agent 知识范围只读能力。
4. `/agents/{agent_id}/knowledge-categories` `GET/PUT`：Agent 可参考知识范围配置，只写 9000 绑定表，不写 RAG 文档。
5. 9100 `/rag/search` 与 reply-suggestion 内部检索：继续服务正式回复建议链路，不作为商户知识库管理入口。

## 6. 历史权限结论

1. `auto_wechat:knowledge_training` 不在 NewCar mock 默认权限中，不作为正式权限码。
2. `auto_wechat:knowledge` 不在 NewCar mock 默认权限中，不作为正式权限码。
3. 本轮已从 9206 过渡服务权限判断和 `KnowledgeClient` 注入中移除 `auto_wechat:knowledge`。
4. 代码中仅允许在负向测试或历史审计文档中出现 `auto_wechat:knowledge` / `auto_wechat:knowledge_training`。

## 7. 测试结果

本节记录本轮已执行测试：

| 命令 | 结果 |
|---|---|
| `python -m pytest tests/test_frontend_capability_navigation.py -q` | 10 passed |
| `python -m pytest tests/test_auth_context.py -q` | 27 passed, 78 warnings |
| `python -m pytest tests/test_knowledge_app.py -q` | 6 passed, 1 warning |
| `python -m pytest tests/test_agent_knowledge_categories.py -q` | 9 passed |
| `python -m pytest tests/test_douyin_ai_cs_proxy.py -q` | 50 passed, 189 warnings |
| `python -m pytest tests/test_knowledge_client.py -q` | 3 passed |
| `python -m pytest tests/test_knowledge_training_api.py -q` | 10 passed, 45 warnings |
| `cd frontend; npm run auth:check` | passed |
| `cd frontend; npm run build` | passed；仅保留既有字体引用和大 chunk 提示 |
| `git diff --check` | passed；仅保留 Git 换行提示 |

warnings 均为既有 FastAPI / TestClient 弃用提示或前端构建体积提示，本轮未处理。
