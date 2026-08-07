# M01 问题登记

> source_baseline: c26ec227e70d | 本轮只登记不修复

## LOW

### ISSUE-M01-004 AiAutoReplyRun duplicate-insert under concurrency

- **位置**：`ai_auto_reply_outbox_service.py:139-194` enqueue_auto_reply_run
- **区分**：
  - Docker controlled duplicate webhook（串行重复投递）：**PASS**（E2E-A 验证，trigger_event_key 唯一约束阻止重复创建）
  - Production duplicate-insert under concurrency/race：**KNOWN ISSUE**（保持开放，并发/竞争场景下 trigger_event_key 唯一约束可能产生 IntegrityError→需 SAVEPOINT 恢复，待 staging 并发双投递测试验证）
- **处理**：后续 staging 追加并发双投递测试

### ISSUE-M01-001 agent_config 三处重复组装逻辑（与 ISSUE-M03-002 同源）

- **位置**：① `agents.py:241-262`（preview）② `douyin_ai_cs_proxy.py:322-343`（会话预览）③ `dry_run_service.py:315-336`（auto-reply）
- **事实**：三处字段完全一致（13 基础+10 商家变量），仅取值方式不同
- **影响**：任一字段变更需同步改三处
- **建议**：解耦候选，需 M01 验真后处理

### ISSUE-M01-002 unfounded_contact_followup_commitment 已停用

- **位置**：`apps/.../reply_hard_rules.py:116-125`（返回 None）
- **事实**：2026-08-04 甲方诉求放开"安排同事联系您"
- **影响**：HARD_BLOCK_RISK_FLAGS 从 4 个降为 3 个
- **状态**：已知设计决策，非 Bug

### ARCHITECTURE_OBSERVATION-M01-001 prompt_injection 安全边界分层设计

- **位置**：`reply_decision_service.py:2392`（9100 侧确定性检测）vs `gate_service.py:30-36`（9000 HARD_BLOCK 仅 3 flag）
- **观察**：prompt_injection 在 9100 侧确定性检测（C 类风险无条件阻断，manual_required=True），不进 9000 HARD_BLOCK_RISK_FLAGS
- **架构解读**：安全边界设计可能是 9100 负责 LLM 输入安全，9000 负责业务上下文/调度。这是分层设计，不是"9000 漏检"
- **真正需验证的**：所有进入 LLM 的路径是否 100% 经过 9100 该保护（而非"为什么 9000 没有再检查一次"）
- **升级条件**：E2E 发现绕过 9100 安全处理的 LLM 入口才升级为真正 ISSUE
- **状态**：ARCHITECTURE_OBSERVATION（待验证），非 LOW ISSUE

## DRIFT

### DRIFT-M01-001 run_ai_auto_reply_job / run_ai_auto_reply_dry_run Legacy 入口

- **位置**：`dry_run_service.py:50` / `:92`（注释"兼容旧调用名"）
- **事实**：当前主路径为 outbox enqueue + wake，这两个函数是 Legacy 兼容入口
- **处理**：登记为 DRIFT（COMPAT），引用 LEGACY_REGISTER

### DRIFT-M01-002 会话无游标渐进窗口 Legacy

- **位置**：`douyin_workbench_conversation_service.py:317`（注释"超过 2 万条应升级为独立会话索引表"）
- **事实**：无 after_event_id 时用 event_limit 渐进扩展窗口，属 Legacy 兼容
- **处理**：登记为 DRIFT

### DRIFT-M01-003 models.py send_source 注释口径过时

- **位置**：`models.py:474`（comment="manual/ai_auto"）
- **事实**：实际白名单已扩展为 4 值（manual/ai_auto/return_visit_auto/contact_invalid_followup）
- **处理**：登记为 DRIFT

### DRIFT-M01-004 CONTACT_INVALID_FOLLOWUP_ENABLED CONFIG_BYPASS

- **位置**：`main.py:236`（直接读 os.environ 未进 config.py）
- **事实**：唯一直接读 os.environ 的调度器开关（其他都走 config.py）
- **处理**：引用 LEGACY_REGISTER LEGACY-014（ACTIVE + quality_flags=CONFIG_BYPASS）

## TECH_DEBT

### TECH_DEBT-M01-001 @app.on_event 非 lifespan

- **位置**：`main.py:171`（startup）/ `main.py:240`（shutdown）
- **事实**：FastAPI 已废弃 API，10 个启动项+8 个关闭项挂在此
- **处理**：引用 LEGACY_REGISTER LEGACY-015（ACTIVE + quality_flags=TECH_DEBT）

### TECH_DEBT-M01-002 latest_message_changed 仅在发送服务

- **位置**：`send_service.py:268-288`（发送服务二次校验）vs `gate_service.py:99-100`（pre-LLM 仅查 latest_is_customer_message）
- **事实**：latest_message_changed/server_message_id 比对在 send_processing 之后，不在 pre-LLM gate
- **影响**：LLM 处理期间客户发新消息，pre-LLM gate 不拦，发送服务二次校验才拦——设计意图（减少 LLM 浪费），但存在窗口

## TEST_GAP

### TEST_GAP-M01-001 9100 集成测试缺失

- **事实**：dry_run 测试用 mock（FakeClient），无真实 9100 调用集成测试
- **状态**：已知 9100 存在/调用合同存在/路径存在，未知的是行为是否满足验收标准——由 E2E 消除，不是生命周期 UNKNOWN
- **处理**：待 2-M01.2 E2E 验证真实 9100 suggest_reply → RAG → LLM → 算力上报完整链路

## 总结

| 级别 | 数量 |
|---|---|
| BLOCKER | 0 |
| HIGH | 0 |
| MEDIUM | 0 |
| LOW | 3（重复组装 / unfounded停用 / duplicate-insert under concurrency） |
| ARCHITECTURE_OBSERVATION | 1（prompt_injection 安全边界分层，待验证） |
| DRIFT | 4（Legacy入口 / 渐进窗口 / 注释口径 / CONFIG_BYPASS） |
| TECH_DEBT | 2（@on_event / latest_message 窗口） |
| TEST_GAP | 1（9100 集成测试缺失，由 E2E 消除） |
