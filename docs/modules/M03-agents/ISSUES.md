# M03 问题登记

> source_baseline: c26ec227e70d | 本轮只登记不修复

## UNKNOWN

### ISSUE-M03-001 super_admin 回复建议路径可绕过商户绑定校验（POLICY_PENDING）

- **位置**：`app/services/douyin_ai_cs_binding_service.py:42-47`
- **事实**：`if context.super_admin: return allowed=True` with warning `SUPER_ADMIN_BYPASS_REQUIRES_AUDIT`，绕过商户绑定校验
- **当前定性**：UNKNOWN / POLICY_PENDING（Security-sensitive，不能仅凭 `if super_admin: bypass` 就判断成漏洞）
- **为什么不是 MEDIUM**：是否是 Bug 取决于正式权限设计——(A) super_admin 可跨商户管理是设计意图？还是 (B) super_admin 仍必须明确 merchant context？当前无正式 RBAC 基线可比对
- **测试**：MISSING — 无 `super_admin=True` 用例
- **需要的 E2E**：把实际行为跑出来（super_admin=True 时能否访问他商户 Agent 的回复建议），再与 RBAC 正式基线比对
- **建议**：等 2-M03.2 E2E 专项 1 跑出实际行为后再定性

## LOW

### ISSUE-M03-002 agent_config 三处重复组装逻辑

- **位置**：① `agents.py:241-262`（preview，前端草稿）② `douyin_ai_cs_proxy.py:322-343`（会话预览，DB）③ `ai_auto_reply_dry_run_service.py:315-336`（auto-reply，DB binding.agent）
- **事实**：三处近乎相同的 agent_config dict 组装，字段结构一致仅来源不同
- **影响**：任一字段变更需同步改三处，易遗漏
- **建议**：解耦候选（提取共享组装函数），但需等行为基线冻结后

### ISSUE-M03-003 停用/启用前端不可达

- **位置**：`AgentEditor` 表单（SuperMerchantAgent.tsx:208-366）无 status 字段控件
- **事实**：后端 `update_agent` 支持 status 字段（services.py:109-110），`updateAiAgent` TS 签名也允许（api/aiAgents.ts:110），但前端从不传
- **影响**：disabled 状态的 Agent 仍可在列表中看到（list_agents 查 active/disabled），但商户无法切换
- **建议**：确认是否需要停用/启用能力；如需要补前端控件，如不需要考虑移除后端支持

## DRIFT

### DRIFT-M03-001 agent-create / agent-edit navId 历史残留死分支

- **位置**：`Index.tsx:766-768` 识别 `agent-create`/`agent-edit` navId
- **事实**：这两个 navId 未在 routes.ts 注册（无独立 path），未在 capabilities.ts children 注册（侧栏不出现），全仓库除 Index.tsx 外无引用
- **影响**：代码存在但运行时不可达；所有创建/编辑在 SuperMerchantAgent 单页弹窗完成
- **处理**：登记为 DRIFT，不在本轮删除（遵循 LEGACY_REGISTER Lifecycle 规则）

### DRIFT-M03-002 test_agent_knowledge_categories.py 用旧权限码

- **位置**：`tests/test_agent_knowledge_categories.py:36` 用 `permission_codes=["auto_wechat:ai_agents"]`
- **事实**：router 实际权限码是 `auto_wechat:douyin_ai_cs`；service 层不校验权限码所以无影响
- **影响**：小瑕疵，不影响测试通过
- **处理**：登记为 DRIFT，不在本轮修复

### DRIFT-M03-003 ai_agent_service.py 是兼容 re-export 壳

- **位置**：`app/services/ai_agent_service.py:1-16`
- **事实**：真实逻辑在 `apps/agents/services.py`，ai_agent_service.py 仅 re-export
- **影响**：CODE_INDEX 标记的 `entrypoints: ["create_agent", "update_agent", "bind_agent"]` 实际指向 `apps/agents/services.py`
- **处理**：登记为 DRIFT（COMPAT，参考 LEGACY_REGISTER LEGACY-012 算力兼容入口同类）

## UNKNOWN

### UNKNOWN-M03-001 preview 端点路径与 {agent_id} 潜在歧义

- **位置**：`agents.py:194` `POST /agents/preview` 在 `agents.py:101` `GET /agents/{agent_id}` 之后声明
- **事实**：FastAPI 路由匹配能区分字面段 `preview` 与参数段 `{agent_id}`，当前不构成 bug
- **缺什么证据**：需确认 `GET /agents/preview` 不会命中 `GET /agents/{agent_id}` 导致 404
- **处理**：UNKNOWN，需 E2E 验证

## 总结

| 级别 | 数量 |
|---|---|
| BLOCKER | 0 |
| HIGH | 0 |
| MEDIUM | 0 |
| LOW | 2（重复组装 / 停用不可达） |
| DRIFT | 3（死分支 navId / 旧权限码 / 兼容壳） |
| UNKNOWN | 2（super_admin bypass POLICY_PENDING / 路径歧义） |
