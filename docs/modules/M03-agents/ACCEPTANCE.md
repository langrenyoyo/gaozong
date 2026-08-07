# M03 验收基线

> source_baseline: c26ec227e70d
> 本任务只制定验收基线，不要求为了通过验收修改代码。

## E2E 验真结果（2-M03.2 + 2-M03.2B，2026-08-07）

### 本地 TestClient 验证

| E2E | 域 | 结果 | 证据 |
|---|---|---|---|
| 1 | Agent CRUD | PASS | Create→Read→Update→Read→Delete→Confirm-Deleted 全链路 |
| 2 | 商户隔离 | PASS | list 只返回 dev-merchant；跨商户 agent_id → 404 |
| 3 | Knowledge Binding | PASS | bind base → read-back `['base']` 一致 |
| 专项2 | 路径歧义 | **PASS** | POST /agents/preview → 200；GET → 404。UNKNOWN-M03-001 关闭 |

### Docker compose 集成验证（2-M03.2B）

环境：docker compose dev（9000 + 9100 + PG + 能力中心 9201-9206），9100 走 docker 内部域名 `xg-douyin-ai-cs:9100`

| E2E | 域 | 结果 | 证据 |
|---|---|---|---|
| 5 | Preview 真实 9100+LLM | **PASS** | LLM 真实回复"老板，20万左右的奔驰C级确实是热门选择。您留个联系方式..."；llm_used=True；auto_send=False |
| 5 | Preview 不触发发送 | **PASS** | auto_send=False 硬编码；AiAutoReplyRun=0 |
| 7 | 三场景污染测试 | **PASS（Preview 事实隔离）** | Preview 输入"想看宝马5系" → 回复"咱们店主营奔驰，宝马5系我需要帮您核实下..." 不含奥迪A6/10-15万/深圳（关键门通过） |
| 7 | 三场景整体事实隔离 | **PARTIAL / PENDING STAGING E2E** | Preview 事实隔离 PASS；Auto Reply 事实隔离 NOT VERIFIED；Training 事实隔离 NOT VERIFIED |
| 8 | 9100 真实集成 | **PASS** | docker 内部域名可达，非 Mock |
| ISSUE-004 | 四层定位 | **已定位** | E 层断言取错（测试脚本用 persona_prompt 调 Create/Update，但前端实际用 prompt）；非真实 Bug，已关闭 |

### 仍 SKIP（需生产/staging 环境）

| E2E | 域 | 原因 |
|---|---|---|
| 4 | Douyin Binding → Auto Reply 真实消费 | docker dev 有抖音账号但无 Agent↔账号绑定；需真实 webhook 触发 auto-reply 链路（binding.agent 读取 → 9100 → 日志证明正确 Agent） |
| 6 | Agent Contract → Auto Reply 消费一致性 | 需真实 webhook 触发 auto-reply，对比 binding.agent DB 配置与 preview 草稿值 |
| 7b | Auto Reply 客户事实隔离 | 需真实 DB 客户档案（车型/预算/城市）+ webhook 触发 auto-reply，证明可读可信事实（与 Preview 不读形成对比） |
| 7c | Training 客户事实/商户变量隔离 | 需真实知识库训练端调用，证明不读取真实客户事实/不注入真实商户变量 |
| 9 | Compute | BASELINE KNOWN GAP，留 M07 |
| 专项1 | super_admin | POLICY_PENDING，留 RBAC 基线 |

### Staging E2E 缺口说明

3 个核心缺口（Agent 绑定→Auto Reply / Auto Reply 事实隔离 / Training 事实隔离）需要：
- 真实抖音授权账号 + Agent 绑定（docker dev 有账号但无绑定关系）
- 真实 webhook 事件触发 auto-reply 完整链路（dev 环境 LEADS_WEBHOOK_INTERNAL_ENABLED=false，无真实回调）
- 真实 DB 客户档案（customer_profiles 表有数据）+ 会话历史

这些在 docker dev 环境无法完整验证，需 staging/生产环境补验证。不构成 BLOCKER（功能链路已通过代码核查 + Preview E2E 间接验证），但 Auto Reply/Training 事实隔离是关键门，staging E2E 必须通过后才能冻结 Baseline。

**E2E 状态：`M03_DOCKER_E2E_VERIFIED_PENDING_STAGING_INTEGRATION`**（无 BLOCKER，Preview 事实隔离通过，三场景整体事实隔离 PARTIAL 待 staging E2E）

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
