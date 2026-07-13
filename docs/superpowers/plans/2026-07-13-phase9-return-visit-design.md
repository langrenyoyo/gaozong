# Phase 9 微信到抖音回访设计（冻结）

- 文档日期：2026-07-13
- 文档性质：冻结设计落盘（仅文档，不含代码改动）
- 修订：FIX2（收紧幂等键、发送底层复用、崩溃恢复分层、内部协议与审计、迁移回滚合同）
- 验收口径：代码与自动测试闭环 `DONE`；Phase 9 `DONE_WITH_CONCERNS`，唯一 concern 为 `baota_production_send_not_verified`
- 关联阶段：Phase 8-B `PARTIAL_BLOCKED_DEFERRED`（不恢复）；Phase 11 一键过审 `CANCELLED_BY_CUSTOMER`（不恢复）
- 既有契约（FIX2 对齐）：
  - `app/models.py:921` `ReturnVisitPrompt` / `app/models.py:941` `ReturnVisitRun` / `app/models.py:361` `DouyinPrivateMessageSend`（已建，迁移 0027/0008）
  - `app/models.py:514` `AutoReplyRolloutConfig.real_send_enabled`（DB 全局真实发送开关）
  - `app/services/douyin_private_message_send_service.py:94` `_send_private_message_with_context`（底层发送，接受 `send_source` / `auto_reply_run_id`，内置违禁词替换 + context 24h 校验 + 流水写入）
  - `app/services/autoreply_admin_rollout_service.py:287` `record_admin_audit`（带 `reason` 参数）
  - `app/services/douyin_autoreply_gate_service.py` `evaluate_*_gates`（manual_takeover / latest_message_not_customer / frequency / context 漂移）
  - 权威范围：`docs/superpowers/plans/2026-07-10-xiaogao-ai-phase1-master-plan.md` Phase 9（行 473-513）

---

## 1. 背景与目标

### 1.1 业务背景

auto_wechat 现有链路：客户在抖音私信留资 → Webhook 入库 → 分配销售 → 通过主机微信向销售下发派单通知 → 销售在微信回复 → ReplyCheck 检测销售是否回复。

Phase 9 在该链路之后增加"回访"能力（master plan 行 475）：当销售在微信侧产生符合特定场景的新回复时，由 9100 LLM 判定是否命中三类固定场景，生成回访话术，经违禁词替换后**调用抖音私信发送底层服务**主动回访客户。

### 1.2 目标

1. 锚定派单通知之后销售侧（微信 `sender=friend`）的新文本，作为回访判定的唯一输入信号（master plan 行 494-495）。
2. 由 9100 LLM 严格判定（LLM 优先，关键字兜底），输出置信度、回访话术、模型与风险标记。
3. 复用既有 `ReturnVisitRun` 持久化后异步处理（BackgroundTasks + 分层启动对账），不阻塞 Local Agent，不丢失已持久化任务。
4. **实现完整真实发送代码路径**：复用底层 `_send_private_message_with_context`（`send_source="return_visit_auto"`，扩展 `return_visit_run_id`）→ 写 `douyin_private_message_sends` + `return_visit_runs`（master plan 行 502-506）。本阶段自动测试以桩替换所有真实网络调用，真实网络调用数为 0；宝塔生产真实验证后置。
5. 提供管理页编辑三场景提示词（`/admin/return-visit-prompts`，PUT 带变更原因 + 审计）与查看只读运行记录（`/admin/return-visit-runs`）；提供内部判定接口（`/internal/return-visits/decide-and-generate`）。

### 1.3 冻结结论清单（十三条）

| 编号 | 冻结结论 |
|------|----------|
| C1 | 三类场景固定键：`retain_contact_conversion` / `finance_plan_followup` / `silent_customer_wakeup` |
| C2 | 不做抖音会话时间扫描；沉默客户唤醒仍由销售微信反馈触发 |
| C3 | 仅锚定派单通知之后的新 `sender=friend` 文本 |
| C4 | ReplyCheck 状态与回访触发解耦 |
| C5 | 持久化 `ReturnVisitRun` 后异步处理（BackgroundTasks + 分层启动对账），不阻塞 Local Agent；不引入周期高频 worker；**不丢失已持久化任务** |
| C6 | LLM 输出 `confidence` 范围 `0～1`；配置 `confidence_threshold` 范围 `0.50～1.00` 初始 `0.90`；**阈值仅约束 LLM 的 `completed` 分支**，关键词兜底不参与阈值门禁 |
| C7 | LLM 优先；LLM `failed/not_configured` 时关键词兜底；关键词分**触发词**与**抑制词**（抑制语义优先阻断）；多场景命中记 `ambiguous` 不发送；单场景触发词命中直接用 `fallback_message`，`confidence=0.5` 仅作审计值；关键词固定代码不入 DB |
| C8 | 消息级永久幂等键 = `sha256(merchant_id + dispatch_notification_id + trigger_message_fp)`（不含 `prompt_key`，避免循环依赖）；会话级 24h 冷却按 `(merchant_id, account_open_id, conversation_short_id, customer_open_id, prompt_key)` 统计，**仅 `sent` run 计入** |
| C9 | 安全熔断使用抖音 env 总熔断 + `AutoReplyRolloutConfig.real_send_enabled`；**不使用**微信 `is_automation_allowed`；**不使用**账号/客户灰度白名单 |
| C10 | 状态机 11 态：`pending_judgement / processing / not_needed / confidence_low / prompt_disabled / rate_limited / blocked / send_authorized / sent / send_unknown / failed`；崩溃恢复分层：`pending_judgement` 重调度、未授权 `processing` 回 `pending_judgement`、`send_authorized` 只核对发送流水（已发送→`sent`，否则→`send_unknown`），**绝不重发** |
| C11 | 管理 API：`/admin/return-visit-prompts`（PUT 要求变更原因 + `record_admin_audit`）+ `/admin/return-visit-runs`（只读）+ 内部 `/internal/return-visits/decide-and-generate`；权限码 `auto_wechat:admin:return_visit_prompts`；不提供重试或立即发送 |
| C12 | 本阶段实现完整真实发送代码路径（复用底层 `_send_private_message_with_context`，`send_source="return_visit_auto"`，不经过上层 `ai_auto_reply_send_service` 与其 `AiAutoReplyRun`/白名单绑定），自动测试 OpenAPI 调用全部替换（真实网络调用为 0）；宝塔生产真实验证后置 |
| C13 | 验收状态目标：代码与自动测试闭环 `DONE`，Phase 9 `DONE_WITH_CONCERNS`，唯一 concern 为 `baota_production_send_not_verified` |

---

## 2. 非目标与禁止事项

### 2.1 非目标

- N1：不扫描抖音会话历史或会话时间序列（C2）。
- N2：不依据 `ReplyCheck.check_status` 触发回访（C4）。
- N3：不在自动测试中发起任何真实抖音 OpenAPI 网络调用（C12）。
- N4：不在管理页提供"重试""立即发送"等写操作（C11）。
- N5：不做账号级或客户级的灰度白名单判定（C9）。
- N6：不新建表；提示词为全局配置，复用既有 `ReturnVisitPrompt`（`scope='global'`）。
- N7：不把关键词存入数据库或暴露为前端可编辑项（C7）。
- N8：不经过上层 `ai_auto_reply_send_service`（其绑定 `AiAutoReplyRun` 与白名单逻辑，与回访语义不符）。

### 2.2 禁止事项

- F1：禁止重复创建既有表；迁移只能 ALTER 或安全重建既有表。
- F2：禁止使用微信 `is_automation_allowed` 作为回访发送熔断（C9）。
- F3：禁止使用账号/客户灰度白名单（C9）。
- F4：禁止跨商户读取或写入 `ReturnVisitRun`。
- F5：禁止在 `send_unknown` 状态下重发；禁止对 `send_authorized` 重发（C10）。
- F6：禁止发送未过违禁词替换的回访话术（底层函数已内置，master plan 行 196）。
- F7：禁止在 Local Agent 线程内同步执行 LLM 判定。
- F8：禁止回写原始销售回复正文到管理页或日志（仅指纹与摘要）。
- F9：禁止引入周期高频 worker；崩溃恢复只靠 BackgroundTasks + 启动对账。
- F10：禁止迁移 seed 写空占位；`fallback_message` 必须 NOT NULL 并回填具体安全默认话术。
- F11：禁止幂等键依赖判定前未知的 `prompt_key`（循环依赖）。
- F12：禁止启动对账把可恢复的 `pending_judgement`/未授权 `processing` 标记 `failed`（会因永久幂等丢失任务）。
- F13：禁止 SQLite downgrade 保留新增列；downgrade 必须安全重建真实恢复迁移前结构。

---

## 3. 端到端数据流

### 3.1 主链路（完整发送路径，复用底层发送，自动测试替换网络）

```
派单通知下发（auto_wechat → 主机微信 → 销售）
        │  记录 lead_notifications 锚点 + 抖音 send_msg context（account_open_id /
        │  conversation_short_id / customer_open_id / server_message_id）
        ▼
销售在微信回复（主机微信出现 sender=friend 新文本）
        │  Local Agent 只读检测读取销售新文本 → 回写 9000
        ▼
9000 回访触发预筛
        │  锚点校验：存在已下发派单通知 + 可用 send_msg context
        │  场景预筛：sender=friend + 派单通知之后（C3）
        │  标准化回复包 → trigger_message_fp（sha256）
        │  幂等预检：idempotency_key = sha256(merchant + dispatch_notification_id + trigger_message_fp)
        │  会话级 24h 冷却预检（仅 sent 计入）
        ▼
持久化 ReturnVisitRun（send_status=pending_judgement，trigger_text 存摘要、trigger_message_fp 存指纹、
        account_open_id/conversation_short_id/customer_open_id/context_server_message_id 落库）
        │  ★ 持久化即返回 run_id，不阻塞 Local Agent（C5）
        ▼
FastAPI BackgroundTasks 异步判定（claim: pending_judgement → processing）
        │
        ▼  调用内部协议 /internal/return-visits/decide-and-generate（内部鉴权）
9100 LLM 判定（LLM 优先，关键字兜底，C7）
        │  输出：prompt_key / confidence(0-1) / suggested_message / judgement_source /
        │        judgement_result / model / risk_flags / ambiguous
        │  抑制词命中 → 直接 not_needed（suppress_hit）
        │  多场景命中 → ambiguous，不发送
        ▼
判定结果分流
        │  未命中 → not_needed
        │  LLM completed 但 confidence < 阈值 → confidence_low（阈值仅约束 LLM）
        │  场景 prompt disabled → prompt_disabled
        │  抑制词命中 → not_needed（suppress_hit）
        │  risk_flags 命中 → blocked（风险阻断）
        │  单场景命中（LLM 过阈值 或 关键词触发词命中）→ 继续
        ▼
门禁检查（C-安全版 12 项，见第 7 节）
        │  抖音 env kill switch / DB real_send_enabled / 商户隔离 / 人工接管 /
        │  触发后无新增客户消息 / context_server_message_id 未漂移 / 账号每小时限频(缺省60) /
        │  会话级 24h 冷却 / 消息级幂等 / 话术安全
        │  任一不过 → blocked / rate_limited，last_failure_stage 记录
        ▼
send_status=send_authorized（话术 generated_content 已生成、门禁已过）
        ▼
调用底层 _send_private_message_with_context（send_source="return_visit_auto"，return_visit_run_id=本run）
        │  ★ 底层内置：sanitize / 违禁词替换(source=douyin_return_visit) / context 24h 校验 /
        │    account 归属校验 / call_douyin_openapi("/send_msg") / 写 DouyinPrivateMessageSend 流水
        │  ★ 完整真实发送代码路径（C12）；自动测试中 call_douyin_openapi 被桩替换
        ▼
结果回写 ReturnVisitRun（发送后结果处理，非发送前门禁）
        │  OpenAPI code=0 → send_status=sent，send_id=upstream msg_id
        │  结果不确定（超时/响应不可解析）→ send_status=send_unknown（禁止重发，C10）
        │  明确失败 → send_status=failed，error_message + last_failure_stage
```

### 3.2 关键边界

- 锚点：每个 `ReturnVisitRun` 必须关联派单通知记录与可用 `send_msg context`（master plan 行 496）。
- 发送底层：复用 `_send_private_message_with_context`（`douyin_private_message_send_service.py:94`），**不经过** `ai_auto_reply_send_service`（避免 `AiAutoReplyRun` 与白名单绑定）。
- 真实发送边界：发送代码路径完整实现并复用底层；本阶段所有自动测试以桩替换 `call_douyin_openapi`，真实网络调用数为 0（C12）。宝塔生产环境真实验证后置。

---

## 4. 数据模型增量与状态机（ALTER 既有表）

### 4.1 既有表 `return_visit_prompts`（不重建，ALTER 增量）

既有字段：`id / prompt_key(UNIQUE) / name / scene_type / template_text / scope='global' / enabled / sort_order / created_at / updated_at`。既有 seed（0027/0008，冻结）：三场景 `retain_contact_conversion` / `finance_plan_followup` / `silent_customer_wakeup`。

Phase 9 增量字段（ALTER ADD COLUMN）：

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| confidence_threshold | FLOAT | NOT NULL DEFAULT 0.90 | 场景置信度阈值 0.50～1.00，**仅约束 LLM**（C6） |
| fallback_message | TEXT | NOT NULL | LLM 故障且关键词触发词命中时使用的兜底文案，管理员可编辑 |

`fallback_message` 初始安全默认话术（迁移内回填，NOT NULL，基于 master plan 场景语义；管理员可在 `/admin/return-visit-prompts` 编辑；若甲方另有批准文案，替换迁移 seed 文本即可）：

| prompt_key | fallback_message 初始安全默认 |
|------------|-------------------------------|
| `retain_contact_conversion` | 您好，关于您之前咨询的车型，这边整理了最新的报价和到店礼遇信息，方便的话可以留个联系方式，我给您详细发一份。 |
| `finance_plan_followup` | 您好，关于购车的金融方案，我们有多种首付和分期组合可以按您的实际情况来匹配，需要的话我可以帮您算一份具体的方案供参考。 |
| `silent_customer_wakeup` | 您好，之前给您介绍的车型信息不知您是否方便看到，近期店里有新的活动安排，想再跟您同步一下，您看什么时候方便沟通。 |

Seed UPDATE（迁移内）：`confidence_threshold=0.90`；`fallback_message` = 上表三条（WHERE fallback_message IS NULL OR fallback_message 为旧占位）。

### 4.2 既有表 `return_visit_runs`（不重建，ALTER 增量）

既有字段（复用，不新增重复语义字段）：`id / merchant_id / lead_id / staff_id / reply_check_id / prompt_key / trigger_source / trigger_text / judgement_source / judgement_result / generated_content / final_content / send_status / send_id / error_message / created_at / updated_at`。

**复用映射**（FIX2，避免重复新增）：
- `judgement_source`（既有）= `llm` / `keyword_fallback`（不新增 `decision_source`）。
- `judgement_result`（既有）= 命中 `prompt_key` / `ambiguous` / `no_match` / `below_threshold` / `prompt_disabled` / `suppress_hit`（不新增 `reason_code`）。
- `prompt_key`（既有）= 命中场景 key。
- `generated_content`（既有）= LLM/关键词生成话术。
- `final_content`（既有）= 违禁词替换后话术。
- `send_status`（既有）= 11 态状态机（扩充取值）。

Phase 9 增量字段（ALTER ADD COLUMN）：

| 分组 | 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|------|
| 触发键 | dispatch_notification_id | INTEGER | NULL | 派单通知锚点（lead_notifications.id） |
| 触发键 | trigger_message_fp | VARCHAR(64) | NULL | 标准化回复包 sha256 指纹（脱敏） |
| 触发键 | idempotency_key | VARCHAR(128) | UNIQUE | 消息级永久幂等键（C8，不含 prompt_key） |
| 抖音上下文 | account_open_id | VARCHAR(255) | NULL | 抖音账号 open_id（既有体系，非 INTEGER id） |
| 抖音上下文 | conversation_short_id | VARCHAR(255) | NULL | 抖音会话短 ID |
| 抖音上下文 | customer_open_id | VARCHAR(255) | NULL | 客户 open_id |
| 抖音上下文 | context_server_message_id | VARCHAR(255) | NULL | 发送上下文锚定消息 ID（漂移检测） |
| 判定 | confidence | FLOAT | NULL | LLM/关键词置信度 0～1（关键词=0.5 审计值，不参与阈值门禁） |
| 判定 | model | VARCHAR(128) | NULL | LLM 模型名（对齐 ComputeTransaction.model） |
| 门禁 | gate_results_json | TEXT | NULL | 门禁通过/拦截摘要（含 risk_flags） |
| 门禁 | last_failure_stage | VARCHAR(100) | NULL | 最近失败阶段码 |
| 门禁 | manual_takeover | BOOLEAN | NOT NULL DEFAULT 0 | 人工接管标记 |
| 租约 | lease_owner | VARCHAR(64) | NULL | BackgroundTasks owner |
| 租约 | lease_expires_at | DATETIME | NULL | 租约过期 |
| 租约 | attempt_count | INTEGER | NOT NULL DEFAULT 0 | 判定尝试次数 |

删除相比初版的字段（语义并入既有）：`decision_source` / `reason_code` / `llm_raw_status` / `ambiguous_hit` / `last_run_at` / `douyin_account_id`（改为 `account_open_id`）。

索引增量：
- UNIQUE(idempotency_key)（SQLite 安全重建 / PG ADD CONSTRAINT）
- INDEX(merchant_id, account_open_id, conversation_short_id, customer_open_id, prompt_key)（会话级 24h 冷却查询）
- INDEX(dispatch_notification_id)

**幂等键**（C8，无循环依赖）：
```
trigger_message_fp = sha256(normalize(销售回复文本包))   # 标准化：去首尾空白、合并连续空白、统一全角半角
idempotency_key = sha256(merchant_id + ":" + dispatch_notification_id + ":" + trigger_message_fp)
```
持久化 `pending_judgement` 时即可计算（商户、派单锚点、回复包均已知），不依赖判定后的 `prompt_key`。

**会话级 24h 冷却**（C8，仅 sent 计入）：
```
count = SELECT COUNT(*) FROM return_visit_runs
  WHERE merchant_id=:m AND account_open_id=:a AND conversation_short_id=:c
    AND customer_open_id=:u AND prompt_key=:p
    AND send_status='sent' AND created_at >= NOW() - INTERVAL 24 HOUR
if count >= 1: blocked / session_cooldown
```
不使用 `last_run_at` 字段；冷却判据 = 已成功 `sent` run 的 `created_at`。

### 4.3 既有表 `douyin_private_message_sends`（不重建，ALTER 增量）

既有 `auto_reply_run_id INTEGER UNIQUE`（防重模式）。Phase 9 增量：

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| return_visit_run_id | INTEGER | UNIQUE | 回访 run ID，防重复发送（镜像 auto_reply_run_id） |

### 4.4 既有底层发送函数扩展（代码改动，非迁移）

`_send_private_message_with_context`（`douyin_private_message_send_service.py:94`）扩展：
- 新增参数 `return_visit_run_id: int | None = None`。
- `send_source` 接受 `"return_visit_auto"`。
- 内部违禁词替换 `source` 扩展：`"douyin_return_visit"`（当前仅 `douyin_ai_auto` / `douyin_manual`）。
- 写 `DouyinPrivateMessageSend` 时填 `return_visit_run_id`。

### 4.5 状态机（`return_visit_runs.send_status`，复用既有字段，11 态）

```
pending_judgement ──claim──▶ processing
                                 │
          ┌────────┬────────┬────┴─────┬──────────┬──────────┐
          ▼        ▼        ▼          ▼          ▼          ▼
      not_needed confidence_low prompt_disabled rate_limited blocked  send_authorized
      (未命中/   (LLM低置信)  (场景禁用)    (24h/限频)  (门禁)    (话术生成+门禁过)
       suppress)                                                      │
                                                            ┌──────────┴──────────┐
                                                            ▼                     ▼
                                                         sent                send_unknown
                                                     (OpenAPI code=0)      (结果不确定，禁重发)

failed：LLM/发送明确失败（终态）
```

- 终态（不可重试）：`not_needed` / `sent` / `send_unknown` / `failed`。
- 可由新消息触发新 run（受幂等与会话冷却约束）：`confidence_low` / `prompt_disabled` / `rate_limited` / `blocked`。

---

## 5. 9100 严格判定协议

### 5.1 协议入口

冻结内部接口 `/internal/return-visits/decide-and-generate`（内部鉴权，复用既有 internal token 机制，如 `COMPUTE_INTERNAL_TOKEN` 模式），由 9000 BackgroundTasks 调用。实现复用 `apps/xg_douyin_ai_cs/services/reply_decision_service.py` 既有 LLM 客户端，新增 `judge_return_visit(request)`。

### 5.2 输入

```
ReturnVisitJudgeRequest:
  tenant_id / merchant_id / lead_id
  prompts: dict[prompt_key, {template_text, fallback_message, confidence_threshold, enabled}]
  sales_reply_text: str          # 仅内存，不落盘
  dispatch_context: dict          # 派单锚点摘要
```

### 5.3 输出（复用既有字段名 + 新增 model/risk_flags）

```
ReturnVisitJudgment:
  prompt_key: str | None
  confidence: float               # 0～1（C6）
  should_trigger: bool
  suggested_message: str | None
  judgement_source: str           # llm / keyword_fallback（复用既有字段）
  judgement_result: str           # 命中key / ambiguous / no_match / below_threshold / prompt_disabled / suppress_hit（复用既有字段）
  model: str | None               # LLM 模型名（新增审计）
  risk_flags: list[str]           # 风险标记，命中则发送门禁阻断
  ambiguous: bool
```

### 5.4 判定顺序（严格，抑制优先，LLM 优先）

1. **抑制词预检**（最高优先级，C7）：扫描销售回复是否命中抑制词（`不是手机号不对` / `已联系上` / `客户已回复` / `无需回访` 等）。命中 → `judgement_result=suppress_hit`，`should_trigger=false`，直接 `not_needed`。
2. **LLM 优先**：调用 LLM，`judgement_source=llm`：
   - LLM 正常：取 `prompt_key` + `confidence`(0～1) + `model` + `risk_flags`。
     - `risk_flags` 非空 → 发送门禁阻断（不在此阶段拦截判定，但在门禁 G11 拦截发送）。
     - 多场景命中 → `judgement_result=ambiguous`，`should_trigger=false`（C7，不发送）。
     - 单场景 + `confidence >= prompts[key].confidence_threshold` → 命中，`suggested_message` 用 LLM 基于 `template_text` 生成，`judgement_result=命中 prompt_key`。
     - 单场景 + `confidence < 阈值` → `judgement_result=below_threshold`，`should_trigger=false`（阈值仅约束 LLM，C6）。
     - 未命中 → `judgement_result=no_match`。
     - 场景 `enabled=false` → `judgement_result=prompt_disabled`。
   - LLM 异常/超时/格式错误/未配置 → 进入步骤 3。
3. **关键词兜底**（仅 LLM 不可用时，C7；`judgement_source=keyword_fallback`）：
   - 关键字**固定代码常量**（`app/services/return_visit_run_service.py` 模块级，不入 DB）。
   - 分**触发词**与**抑制词**（抑制已在步骤 1 处理；此处仅触发词）。
   - 多场景触发词同时命中 → `judgement_result=ambiguous`，`should_trigger=false`（不发送）。
   - 单场景触发词命中 → **直接触发**，`suggested_message=prompts[key].fallback_message`，`confidence=0.5`（**仅审计值，不参与阈值门禁**，C6/C7），`judgement_result=命中 prompt_key`。
   - 全未命中 → `judgement_result=no_match`。

### 5.5 判定结果到状态的映射

| judgement_result | send_status |
|------------------|-------------|
| 命中 prompt_key（LLM 过阈值 或 关键词触发词） | 继续 → 门禁 → send_authorized |
| `below_threshold` | `confidence_low` |
| `prompt_disabled` | `prompt_disabled` |
| `ambiguous` | `not_needed` |
| `no_match` | `not_needed` |
| `suppress_hit` | `not_needed` |
| `risk_flags` 非空 | `blocked`（风险阻断） |

### 5.6 严格性约束

- LLM 输出受控结构（prompt_key 枚举 + confidence 0～1 + should_trigger 布尔 + 话术 + model + risk_flags）；解析失败视为 LLM 不可用 → 关键词兜底。
- 9100 内部日志只记 `lead_id` / `prompt_key` / `confidence` / `judgement_source` / `judgement_result` / `model` / `risk_flags`，不记原文。

---

## 6. 关键词与回访话术

### 6.1 关键词（固定代码，触发词 + 抑制词，抑制优先，C7）

关键字定义在 `app/services/return_visit_run_service.py` 模块级常量，不入 DB、不前端可编辑。基于 master plan 行 492-495 场景语义：

**抑制词**（最高优先级，命中即 `suppress_hit`，阻断所有场景）：
`不是手机号不对`、`号码没问题`、`已联系上`、`客户已回复`、`客户回消息了`、`无需回访`、`不用回访`、`已成交`、`已到店`

**触发词**（按场景，否定语义优先）：

| prompt_key | 否定触发词（优先） | 肯定触发词 |
|------------|--------------------|------------|
| `retain_contact_conversion` | `手机号不对`、`号码错了`、`联系方式不对`、`空号` | `留资`、`加微信`、`留电话` |
| `finance_plan_followup` | `金融方案不合适`、`首付太高`、`月供太高`、`利息高` | `金融方案`、`贷款`、`分期`、`首付`、`月供` |
| `silent_customer_wakeup` | `客户长期未回复`、`联系不上`、`失联`、`不回消息`、`找不到人` | （沉默场景以否定语义为主） |

匹配规则：
- 抑制词优先：先扫抑制词，命中即阻断（不发送）。
- 否定触发词优先于肯定触发词：先扫否定，命中即归类对应场景。
- 多场景触发词同时命中 → `ambiguous`，不发送（C7）。
- 关键字调整走代码评审 + 提交，不在管理页暴露。

### 6.2 回访话术（template_text + fallback_message NOT NULL，管理员编辑）

- **正常话术**：`ReturnVisitPrompt.template_text`（既有字段）。LLM 命中后基于该模板生成 `generated_content`，底层违禁词替换得 `final_content` 发送。
- **兜底话术**：`ReturnVisitPrompt.fallback_message`（Phase 9 增量，NOT NULL，三条初始安全默认见 §4.1）。LLM 不可用且关键词触发词命中时使用。
- **编辑入口**：`/admin/return-visit-prompts`（权限 `auto_wechat:admin:return_visit_prompts`，PUT 必须 `reason` + `record_admin_audit`，见 §8）。
- **长度与安全**：`template_text` / `fallback_message` 长度上限 500 字符；提交时过违禁词预检（不替换，仅告警，命中记 `forbidden_word_hit_logs` source=`return_visit_prompt_edit`）。

---

## 7. 真实发送门禁（C-安全版 12 项，C9）

完整实现真实发送代码路径（C12），复用底层 `_send_private_message_with_context`（不经过上层 `ai_auto_reply_send_service`），自动测试替换网络。门禁在 `send_authorized` 之前评估；**失败回写是发送后结果处理，不是发送前门禁**（G7 移除，见 §3.1 结果回写）。

| 序 | 门禁 | 不过处置 | 说明 |
|----|------|----------|------|
| G1 | 抖音 env 总熔断（既有 autoreply kill switch） | blocked / env_kill_switch | 抖音侧全局熔断 |
| G2 | `AutoReplyRolloutConfig.real_send_enabled`(scope=global) | blocked / real_send_disabled | DB 全局真实发送开关（C9） |
| G3 | 商户隔离 `merchant_id` 校验 | blocked / cross_merchant | 跨商户不可见 |
| G4 | 人工接管 `manual_takeover`（既有 `evaluate_manual_takeover_gate`） | blocked / manual_takeover | 销售已人工接管 |
| G5 | 触发后无新增客户消息/出站消息（`latest_message_state.latest_is_customer_message is False`，既有 gate） | blocked / latest_not_customer | 防止基于过期触发发送 |
| G6 | 上下文完整性 + `context_server_message_id` 未漂移（发送时校验仍是当前会话最新锚定消息） | blocked / context_drifted | 防止基于漂移上下文发送 |
| G7 | 账号每小时限频（Phase 9 独立缺省 **60**，不复用既有 300） | blocked / frequency_account_exceeded | 复用 `_frequency_snapshot`，阈值用 Phase 9 配置 |
| G8 | 会话级 24h 冷却（按 merchant+account+conversation+customer+prompt_key，仅 sent 计入，C8） | blocked / session_cooldown | 同会话同场景 24h 仅一次成功 |
| G9 | 消息级幂等 `idempotency_key` UNIQUE | 跳过（返回既有 run） | 永久幂等（C8） |
| G10 | LLM `confidence >= confidence_threshold`（**仅约束 LLM completed 分支**；关键词兜底直接放行，C6/C7） | `confidence_low`（LLM 分支） | 阈值不约束关键词 |
| G11 | 话术安全 + `risk_flags` 风险阻断 + 违禁词替换（底层内置 source=`douyin_return_visit`） | blocked / message_invalid 或 blocked / risk_flags | risk_flags 非空或话术不合规 |
| G12 | `send_authorized → send_unknown` 禁重发 | send_unknown 终态 | 结果不确定时进入，禁止重发（C10） |

明确排除（C-安全版不检查）：
- 账号级灰度白名单
- 客户级灰度白名单
- 微信 `is_automation_allowed`（回访走抖音发送，不走微信自动化）
- 上层 `ai_auto_reply_send_service` 的 `AiAutoReplyRun` 绑定与白名单逻辑

---

## 8. 管理 API 与内部协议（C11）

### 8.1 管理 API（权限 `auto_wechat:admin:return_visit_prompts`，跨商户统一 404）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/admin/return-visit-prompts` | 列出三场景全局提示词 |
| PUT | `/admin/return-visit-prompts/{prompt_key}` | 编辑单场景（template_text / fallback_message / confidence_threshold / enabled）；**请求体必须含 `reason`（变更原因）**；事务内 `record_admin_audit(action="return_visit_prompt_update", target_type="return_visit_prompt", target_id=prompt_key, before=旧值摘要, after=新值摘要, reason=reason)` |
| GET | `/admin/return-visit-runs` | 只读运行记录列表（分页，按 send_status / prompt_key / judgement_source 筛选） |
| GET | `/admin/return-visit-runs/{id}` | 只读单条详情 |
| GET | `/admin/return-visit-runs/stats` | 统计聚合 |

明确不提供（C11）：不提供 `retry` / `send` 写接口。

响应脱敏：不返回销售回复原文（`trigger_text` 仅长度摘要，`trigger_message_fp` 指纹）；不返回客户手机号；`customer_open_id` 仅详情可见；`generated_content`/`final_content` 仅详情可见。

### 8.2 内部协议（内部鉴权）

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/internal/return-visits/decide-and-generate` | 内部鉴权（复用既有 internal token）；入参 `ReturnVisitJudgeRequest`；出参 `ReturnVisitJudgment`（含 model / risk_flags）；仅 9000 BackgroundTasks 调用，不暴露公网 |

### 8.3 前端设计

复用既有超管后台导航（`auto_wechat:admin:return_visit_prompts`），新增：
1. **回访提示词配置页**：三场景卡片，编辑 `template_text` / `fallback_message` / `confidence_threshold`(0.50～1.00) / `enabled`；PUT 必填变更原因 `reason`（前端校验非空）；提交显示违禁词预检告警与审计摘要。
2. **回访运行记录页（只读）**：列表（prompt_key / send_status / judgement_source / judgement_result / confidence / model / last_failure_stage / created_at），详情抽屉（generated_content / final_content / trigger_message_fp / risk_flags via gate_results_json）。不提供重试/立即发送。

前端约束：`confidence_threshold ∈ [0.50, 1.00]`；`template_text` / `fallback_message` 长度 ≤ 500；`reason` 非空。

---

## 9. 崩溃恢复与幂等（分层对账，C5/C10，不丢失任务）

### 9.1 崩溃恢复（BackgroundTasks + 分层启动对账，无周期高频 worker）

- **持久化优先**：持久化 `ReturnVisitRun(send_status=pending_judgement)` 后立即返回 `run_id`，不等待 LLM。
- **BackgroundTasks claim**：`UPDATE ... SET send_status='processing', lease_owner=:owner, lease_expires_at=NOW()+:lease WHERE id=:id AND send_status='pending_judgement'`，`affected_rows=1` 才继续。
- **分层启动对账**（服务启动时执行一次，唯一 reclaim 路径，F9/F12）：
  1. `pending_judgement`：**重新调度**（投递到 BackgroundTasks 重新判定），不标记 failed。
  2. `send_status='processing' AND lease_expires_at < NOW`（未授权 `send_authorized`）：**安全回到 `pending_judgement`**（`attempt_count += 1`），重新判定。这是安全的，因为尚未调用发送，不构成重复发送。
  3. `send_status='send_authorized'`：**不重发**，只核对发送流水 `douyin_private_message_sends WHERE return_visit_run_id=:id`：
     - 存在 `status='sent'` 流水 → `send_status='sent'`，补 `send_id`。
     - 否则 → `send_status='send_unknown'`（终态，禁重发）。
- **不丢失任务**：`pending_judgement` 重调度 + 未授权 `processing` 回 `pending_judgement` 保证已持久化任务不会因崩溃丢失（F12）。永久幂等不阻止重调度（同 `idempotency_key` 的 run 状态推进，不创建新 run）。
- **不自动重试**：`send_authorized` 绝不重发；`sent`/`send_unknown`/`failed` 终态。

### 9.2 幂等（C8）

- **消息级永久幂等**：`idempotency_key = sha256(merchant_id + ":" + dispatch_notification_id + ":" + trigger_message_fp)`，UNIQUE。INSERT 冲突返回既有 run，不重复判定/发送。
- **会话级 24h 冷却**：`(merchant_id, account_open_id, conversation_short_id, customer_open_id, prompt_key)` 维度，仅 `sent` run 计入（§4.2 查询）。
- **判定顺序**：先消息级 `idempotency_key`（永久），再会话级冷却（仅 sent）。两者都过才创建新 run。
- **失败 run 不计入冷却**：`failed`/`blocked`/`not_needed`/`confidence_low`/`prompt_disabled`/`rate_limited`/`send_unknown` 不计入，允许新消息重新触发。

---

## 10. SQLite `0030` / PostgreSQL `0011` 迁移边界（ALTER + 真实回滚）

### 10.1 SQLite `0030_return_visit_phase9.py`

**不重复建表**（F1）。所有改动为 ALTER 或安全重建既有表。

1. `return_visit_prompts`：直接 `ALTER TABLE ... ADD COLUMN confidence_threshold FLOAT NOT NULL DEFAULT 0.90` + `ADD COLUMN fallback_message TEXT NOT NULL DEFAULT '<场景语义占位>'`（SQLite 不支持运行时计算默认，先加 NOT NULL 带占位默认，再 UPDATE 三行回填 §4.1 具体话术）。安全重建模式：因 `fallback_message` NOT NULL 需精确回填，采用 `ADD COLUMN` + 三条 UPDATE。
2. `return_visit_runs`：多数字段直接 `ALTER TABLE ... ADD COLUMN`（SQLite 支持）。`idempotency_key UNIQUE` + 会话冷却索引：SQLite 无法直接 ADD UNIQUE，采用**安全重建模式**（复用 0028/0029 `_backup/_new/_guard`）：CREATE `_new`（全部旧列 + 新列 + idempotency_key + UNIQUE + 索引）→ INSERT SELECT 旧数据 → 行数 + max(id) + 双向 GROUP BY 守卫 → RENAME 旧 `_backup`、`_new` 正式 → DROP `_backup`。CHECK 违反 ROLLBACK 不登记 0030。
3. `douyin_private_message_sends`：`return_visit_run_id` + UNIQUE，安全重建同上（既有 `auto_reply_run_id UNIQUE` 保留）。
4. 守卫：复用 0028/0029 多重集守卫（表/列/约束存在性 + seed 行数 = 3），失败 ROLLBACK 不登记。
5. 幂等：所有 ALTER try/except 检测列已存在则跳过；seed UPDATE 用 `WHERE fallback_message IS NULL` 或版本守卫。

**downgrade（F13，真实恢复迁移前结构）**：
- 不保留新增列。采用安全重建：CREATE `_new_pre`（仅迁移前列结构）→ INSERT SELECT 旧列数据 → 行数/max(id) 守卫 → RENAME 替换 → DROP 旧。回滚 `return_visit_prompts` 三表到 0027/0008 原始结构，回滚 seed（移除 confidence_threshold/fallback_message）。
- 注明 ceiling：SQLite downgrade 安全重建需精确重建原列顺序与约束，测试覆盖。

### 10.2 PostgreSQL `0011_return_visit_phase9.py`

**不重复建表**（F1）。PG 支持 `ADD COLUMN` + `ADD CONSTRAINT`。

1. `return_visit_prompts`：`ADD COLUMN confidence_threshold FLOAT NOT NULL DEFAULT 0.90` + `ADD COLUMN fallback_message TEXT NOT NULL DEFAULT '<占位>'`；UPDATE 三行回填 §4.1 话术。
2. `return_visit_runs`：`ADD COLUMN` 全部新列 + `ADD CONSTRAINT uk_return_visit_runs_idempotency_key UNIQUE (idempotency_key)` + 会话冷却索引 + dispatch_notification_id 索引。
3. `douyin_private_message_sends`：`ADD COLUMN return_visit_run_id INTEGER` + `ADD CONSTRAINT uk_..._return_visit_run_id UNIQUE (return_visit_run_id)`。
4. 权限：0008 表级 GRANT 覆盖新列，无需额外授权。
5. 幂等：`ADD COLUMN IF NOT EXISTS`（PG 14+）+ `DO $$ ... IF NOT EXISTS ... END $$` 守卫约束。

**downgrade（F13）**：`DROP COLUMN confidence_threshold, fallback_message`（return_visit_prompts）+ `DROP COLUMN` 全部新列 + `DROP CONSTRAINT` + 回滚 seed。PG 支持 DROP COLUMN 真实恢复。

### 10.3 迁移边界（硬约束）

- 仅 ALTER 或安全重建既有 3 表 + seed UPDATE，**不创建新表**（F1）。
- 不修改既有列类型/约束（`send_status` 扩充取值，字段不动）。
- SQLite 与 PostgreSQL 字段定义一致（FLOAT/TEXT/VARCHAR(255)/INTEGER；`gate_results_json` 用 TEXT）。
- **downgrade 必须真实恢复迁移前结构**，不保留新增列（F13）。
- 迁移测试：ALTER + 新列 + UNIQUE + seed 行数 = 3 + 与 0029/0010 共存 + upgrade/downgrade 往返（见 §11）。

---

## 11. 自动化测试矩阵

### 11.1 真实网络调用为零（C12 硬约束）

- 所有抖音 OpenAPI HTTP 调用（`call_douyin_openapi`）在测试中以桩/monkeypatch 替换，真实网络调用数 = 0。
- 断言：`_send_private_message_with_context` 调用参数（`send_source="return_visit_auto"`、`return_visit_run_id`、final_content）、写 `douyin_private_message_sends`（return_visit_run_id UNIQUE）、不经过上层 `ai_auto_reply_send_service`。

### 11.2 9100 判定协议单元测试

| 用例 | 期望 |
|------|------|
| LLM 单场景 + confidence >= 阈值 | judgement_source=llm，judgement_result=命中key，suggested_message 基于 template_text，返回 model |
| LLM 单场景 + confidence < 阈值 | judgement_result=below_threshold（阈值仅约束 LLM） |
| LLM 不可用 → 否定触发词命中 retain_contact_conversion | judgement_source=keyword_fallback，confidence=0.5（审计值），suggested_message=fallback_message，**不过阈值门禁直接放行** |
| 抑制词命中（"已联系上"） | judgement_result=suppress_hit，should_trigger=false |
| 多场景触发词命中 | judgement_result=ambiguous，不发送 |
| risk_flags 非空 | 判定返回，发送门禁 G11 阻断 |
| LLM 输出格式错误 | 视为不可用 → 关键词兜底 |

### 11.3 幂等与状态机单元测试

| 用例 | 期望 |
|------|------|
| 同 idempotency_key 第二次插入 | 返回既有 run |
| 会话级 24h 内已有 sent run | blocked / session_cooldown |
| 仅 failed/not_needed run 存在 | 不计冷却，新消息可触发 |
| 幂等键不含 prompt_key（持久化时可算） | 无循环依赖 |
| pending_judgement → processing → send_authorized → sent | 流转正确 |
| send_authorized → send_unknown | 终态禁重发 |

### 11.4 门禁集成测试（C-安全版，G1-G12）

| 用例 | 期望 |
|------|------|
| 抖音 env kill switch 关闭 | blocked / env_kill_switch |
| DB real_send_enabled=false | blocked / real_send_disabled |
| 人工接管标记 | blocked / manual_takeover |
| 触发后有出站消息（latest_is_customer_message=False） | blocked / latest_not_customer |
| context_server_message_id 漂移 | blocked / context_drifted |
| 账号每小时限频 >= 60（Phase 9 缺省） | blocked / frequency_account_exceeded |
| 会话级 24h 冷却（已 sent） | blocked / session_cooldown |
| 消息级幂等冲突 | 跳过 |
| LLM confidence < 阈值 | confidence_low |
| 关键词命中（confidence=0.5） | **过阈值门禁**（不约束关键词）→ send_authorized |
| risk_flags 非空 | blocked / risk_flags |
| 话术为空 | blocked / message_invalid |
| 发送路径调用底层（不经过 ai_auto_reply_send_service） | send_source=return_visit_auto |
| OpenAPI code=0 | sent |
| OpenAPI 结果不确定 | send_unknown |
| **不使用**微信 is_automation_allowed / 白名单 | 不查询 |

### 11.5 崩溃恢复分层测试

| 用例 | 期望 |
|------|------|
| 启动时 pending_judgement 存在 | 重新调度（不 failed） |
| 启动时 processing 过期（未授权） | 回 pending_judgement，attempt_count+1 |
| 启动时 send_authorized + 有 sent 流水 | sent（不重发） |
| 启动时 send_authorized + 无流水 | send_unknown（不重发） |
| 永久幂等 + 重调度 | 同 idempotency_key run 状态推进，不丢任务 |

### 11.6 管理 API + 内部协议测试

| 用例 | 期望 |
|------|------|
| GET /admin/return-visit-prompts 返回三场景 | 200，含 fallback_message（NOT NULL） |
| PUT 缺 reason | 422 |
| PUT 带 reason | 200，record_admin_audit 写入（含 before/after/reason） |
| PUT confidence_threshold=0.3 | 422 |
| GET /admin/return-visit-runs 列表不返回原文 | 无 trigger_text 原文 |
| /internal/return-visits/decide-and-generate 无内部鉴权 | 401/403 |
| /internal 带鉴权 | 200，返回 model/risk_flags |
| 跨商户 GET runs/{id} | 404 |
| 权限码校验 | 无权限 403 |

### 11.7 迁移测试

| 用例 | 期望 |
|------|------|
| SQLite 0030 ALTER + 新列 + UNIQUE | 存在 |
| SQLite 0030 安全重建 idempotency_key UNIQUE | 数据保留，守卫通过 |
| SQLite 0030 seed fallback_message NOT NULL 三行 | 行数=3，非空 |
| **SQLite 0030 downgrade 真实恢复** | 新列移除，结构回 0027 |
| SQLite 0030 与 0029 共存 | 迁移链不中断 |
| PG 0011 ADD COLUMN/CONSTRAINT | 可重入 |
| **PG 0011 downgrade DROP COLUMN** | 真实恢复 |

### 11.8 端到端闭环（网络桩）

| 用例 | 期望 |
|------|------|
| 派单通知 → 销售回复"手机号不对" → 持久化 → 判定 → 底层发送桩 → sent | 全链路，真实网络=0 |
| 销售回复"已联系上" | suppress_hit → not_needed |
| 三场景分别命中 | 各 prompt_key 正确 |
| ReplyCheck.check_status=timeout 仍可触发 | C4 解耦 |
| 服务重启分层对账 | pending/processing/send_authorized 各自正确恢复 |

---

## 12. 宝塔真实验证后置说明（C12）

- 本阶段所有回访发送在自动测试中以桩替换 `call_douyin_openapi`，真实网络调用数为 0。
- **真实抖音发送代码路径完整实现并复用底层 `_send_private_message_with_context`**（master plan 行 502-506），只是未在宝塔生产环境真实验证。
- 宝塔生产验证后置内容：账号鉴权 / env 熔断 / `AutoReplyRolloutConfig.real_send_enabled` 开启 / 限频配置（Phase 9 缺省 60）/ 违禁词服务 / 监控；`send_authorized → 真实 im_send_msg` 观测；`sent`/`send_unknown` 分布。
- 后置不阻塞：Phase 9 验收以"代码与自动测试闭环 DONE"为准，`baota_production_send_not_verified` 作为唯一 concern。
- 宝塔真实发送验证需另开执行包 + 生产检查点。

---

## 13. 风险与最终状态口径

### 13.1 风险

| 风险 | 等级 | 缓解 |
|------|------|------|
| `baota_production_send_not_verified` | 中 | 唯一 concern；发送代码路径已实现，宝塔验证另开 |
| LLM 故障导致关键词兜底覆盖率 | 中 | 触发词基于 master plan 样例；管理页观测 judgement_source 分布 |
| BackgroundTasks 崩溃丢 in-flight | 低 | 分层启动对账：pending 重调度、processing 回 pending、send_authorized 核对流水；持久化不丢已落盘 run |
| Qt 微信 UIA 限制影响回访 | 无 | 锚定 sender=friend 文本读取，不依赖文件气泡（与 Phase 8-B 正交） |
| 配置误改回访风暴 | 中 | 24h 冷却 + 账号每小时 60 + DB real_send_enabled + env kill switch + 管理页无立即发送 |
| fallback_message 默认话术需甲方确认 | 低 | 初始安全默认基于 master plan 语义（§4.1），管理员可编辑；甲方另有文案替换 seed |

### 13.2 最终状态口径（冻结）

| 项目 | 状态 |
|------|------|
| Phase 9 代码与自动测试闭环 | `DONE` |
| Phase 9 | `DONE_WITH_CONCERNS`（唯一 concern = `baota_production_send_not_verified`） |
| Phase 8-B | `PARTIAL_BLOCKED_DEFERRED`（不恢复） |
| Phase 11 一键过审 | `CANCELLED_BY_CUSTOMER`（不恢复） |
| Task 8（日报真实分发） | `NOT_STARTED` |
| 真实抖音回访发送（宝塔验证） | 后置（另开执行包 + 生产检查点） |

### 13.3 自检（术语 / 状态 / 阈值 / 限频 / 验收一致性）

- 三场景固定键：`retain_contact_conversion` / `finance_plan_followup` / `silent_customer_wakeup`（与 0027/0008、master plan 一致）。
- 状态机 11 态（C10）：`pending_judgement / processing / not_needed / confidence_low / prompt_disabled / rate_limited / blocked / send_authorized / sent / send_unknown / failed`。
- LLM `confidence` 0～1；`confidence_threshold` 0.50～1.00 初始 0.90，**仅约束 LLM**（C6）。
- 会话级冷却 24h，按 `(merchant, account_open_id, conversation_short_id, customer_open_id, prompt_key)`，仅 `sent` 计入（C8）。
- 账号每小时限频 Phase 9 缺省 60（G7）。
- 幂等键 = `sha256(merchant + dispatch_notification_id + trigger_message_fp)`，不含 prompt_key（C8/F11）。
- 熔断：抖音 env + `AutoReplyRolloutConfig.real_send_enabled`（C9），不用微信 is_automation_allowed/白名单。
- 关键词：触发词+抑制词，抑制优先，ambiguous 不发送，固定代码（C7）。
- 发送：复用底层 `_send_private_message_with_context`，send_source=`return_visit_auto`，不经上层 ai_auto_reply_send_service（C12）。
- 复用既有 `judgement_source`/`judgement_result`，不新增 decision_source/reason_code。
- 权限码 `auto_wechat:admin:return_visit_prompts`；API `/admin/return-visit-prompts` + `/admin/return-visit-runs` + `/internal/return-visits/decide-and-generate`（C11）。
- 崩溃恢复分层：pending 重调度、未授权 processing 回 pending、send_authorized 核对流水不重发（C10/F12）。
- PUT 必带 reason + record_admin_audit（C11）。
- fallback_message NOT NULL 回填三条默认（F10）。
- 迁移 downgrade 真实恢复，不保留新列（F13）。
- 自动测试真实网络调用为 0（C12）。
- 无 TODO/TBD/未定义字段。

---

## 附录 A：与既有体系的边界

- `ReturnVisitPrompt`（models.py:921）：补 `confidence_threshold` / `fallback_message`(NOT NULL)。
- `ReturnVisitRun`（models.py:941）：补触发键/抖音上下文(account_open_id VARCHAR(255))/判定/confidence/model/门禁/租约；复用 `judgement_source`/`judgement_result`/`prompt_key`/`generated_content`/`final_content`/`send_status`。
- `DouyinPrivateMessageSend`（models.py:361）：补 `return_visit_run_id UNIQUE`（镜像 auto_reply_run_id）。
- `_send_private_message_with_context`（douyin_private_message_send_service.py:94）：扩展 `return_visit_run_id` 参数 + `send_source="return_visit_auto"` + 违禁词 source `douyin_return_visit`。
- `AutoReplyRolloutConfig`（models.py:514）：复用 `real_send_enabled`(scope=global)。
- `record_admin_audit`（autoreply_admin_rollout_service.py:287）：提示词 PUT 审计，带 reason。
- `evaluate_*_gates`（douyin_autoreply_gate_service.py）：复用 manual_takeover / latest_message_not_customer / `_frequency_snapshot` / context 漂移逻辑。
- 迁移：SQLite 0030 接续 0029；PG 0011 接续 0010。

## 附录 B：后续执行包拆分建议（仅供参考，不在本设计范围）

1. 迁移：SQLite 0030 / PG 0011（ALTER + 安全重建 + seed 回填 + 真实回滚）。
2. 底层发送扩展：`_send_private_message_with_context` 加 `return_visit_run_id` + send_source/违禁词 source。
3. 9100 `judge_return_visit` + `/internal/return-visits/decide-and-generate`（内部鉴权，model/risk_flags）。
4. 关键词常量（触发词+抑制词，抑制优先，ambiguous 不发送）。
5. 9000 回访触发 + 持久化 + BackgroundTasks + 分层启动对账 + 幂等（无 prompt_key 循环）。
6. C-安全版 12 门禁（抖音 env + DB real_send_enabled + 人工接管 + 消息漂移 + 限频60 + 冷却）。
7. 管理 API + 前端（PUT reason + record_admin_audit）。
8. 测试矩阵落地（11.1～11.8，真实网络为 0）。
9. 宝塔真实发送验证（另开执行包 + 生产检查点）。
