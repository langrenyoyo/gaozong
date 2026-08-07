# M03 验收基线

> source_baseline: c26ec227e70d
> 本任务只制定验收基线，不要求为了通过验收修改代码。

## 当前已有验收能力

### 已覆盖（测试证据）

| 能力 | 测试文件 | 关键用例 |
|---|---|---|
| CRUD | test_ai_agents.py:108,133,196 | create/get/update/delete |
| merchant isolation | test_ai_agents.py:120,254 | 列表隔离/跨商户 404 |
| knowledge binding | test_ai_agents.py:291 | base 保存/清空 |
| Agent 绑定（删除阻断） | test_ai_agents.py:215,233 | active binding 阻断/ignore inactive |
| preview | test_ai_agents.py:316,378,418 | draft 配置/auto_send=False/历史脱敏/跨商户 404 |
| Prompt（training-chat） | test_ai_agents.py:264,282 | 不调 LLM/空 message |
| 权限 | test_ai_agents.py:169,178,187 | 无权限 403/旧码不再放行 |
| 错误路径 | test_ai_agents.py:215,254,418,169 | active binding/跨商户/空 message/缺权限 |
| 知识库绑定 service | test_agent_knowledge_categories.py:86,111,140,177,193,213,279 | 绑定/替换/解绑/列表/跨商户/禁用 Agent/缺 merchant |
| 抖音账号绑定 service | test_douyin_account_agent_binding_service.py:81,105,133,151,178,207,229,248,351 | 绑定/重绑/解绑/复活/换绑/去重/跨商户 Agent/跨商户账号 |

### 部分覆盖

| 能力 | 现状 | 缺什么 |
|---|---|---|
| M01 集成 | PARTIAL — preview 用 FakeClient mock（test_ai_agents.py:319-337） | 真实 M01 集成测试（9100 真实调用） |
| Agent 绑定（创建/解绑完整） | PARTIAL — 仅覆盖删除阻断 | 绑定创建/解绑/换绑的完整 router 层测试 |

### 缺失

| 能力 | 现状 |
|---|---|
| 9100 集成 | MISSING — 无 xg_douyin_ai_cs_client 真实调用集成测试 |
| super_admin bypass | MISSING — binding service super_admin 绕过路径无测试 |
| 停用/启用 | MISSING — 后端支持但前端无控件，无测试 |

## 后续 E2E 应验证项目

1. **Preview 真实调 9100**：验证 preview 走 RAG + LLM + 算力消耗上报 + auto_send=False
2. **Auto-reply agent_config 来源**：验证 binding.agent DB 模型与 preview 草稿值字段一致
3. **商户隔离 E2E**：super_admin 跨商户访问 Agent 的真实行为（binding service 绕过路径）
4. **三场景隔离**：preview / auto-reply / training 确认事实来源隔离（代码路径存在共享，事实来源隔离尚待 E2E 验证）
5. **知识库绑定 E2E**：Agent 绑定 category_key → 9100 RAG 检索 → rag_results 注入
6. **删除有 active 绑定的 Agent**：确认 409 阻断 + 硬删除（含 agent_knowledge_categories 级联清理）

## 三场景正式隔离规则

代码路径存在共享（preview 与 auto-reply 共用 9100 `build_reply_suggestion` LLM 链路），**事实来源隔离尚待 E2E 验证**。共用 9100 LLM 代码本身没问题，真正要 E2E 证明的是"同一套策略，不同事实源"。

| 场景 | 客户事实 | 商户/Agent 变量 | DB 真实客户档案 | 真实发送 |
|---|---|---|---|---|
| Preview | 当前预览会话允许 | 允许 | **禁止** | **禁止** |
| Auto Reply | 当前消息+历史 | 允许 | 允许可信事实 | Gate 通过后允许 |
| Training | 通用训练上下文 | **禁止商户变量污染** | **禁止** | **禁止** |
