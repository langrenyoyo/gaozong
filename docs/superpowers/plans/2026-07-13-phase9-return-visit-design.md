# Phase 9 微信到抖音回访设计（冻结）

- 文档日期：2026-07-13
- 文档性质：冻结设计落盘（仅文档，不含代码改动）
- 修订：FIX3（闭合恢复输入、启动执行器、限频/冷却时间基准、消息漂移三条件、内部鉴权与终态合同）
- 验收口径：代码与自动测试闭环 `DONE`；Phase 9 `DONE_WITH_CONCERNS`，唯一 concern 为 `baota_production_send_not_verified`
- 关联阶段：Phase 8-B `PARTIAL_BLOCKED_DEFERRED`（不恢复）；Phase 11 一键过审 `CANCELLED_BY_CUSTOMER`（不恢复）
- 既有契约（FIX3 对齐）：
  - `app/models.py:921` `ReturnVisitPrompt` / `:941` `ReturnVisitRun` / `:361` `DouyinPrivateMessageSend`（已建，迁移 0027/0008）
  - `app/models.py:389` `DouyinPrivateMessageSend.sent_at`（实际成功时间，频率统计基准）
  - `app/models.py:509` `DouyinAccountAutoreplySetting.max_replies_per_account_per_hour`（账号每小时上限，复用）
  - `app/models.py:514` `AutoReplyRolloutConfig.real_send_enabled`
  - `app/services/douyin_private_message_send_service.py:94` `_send_private_message_with_context`（底层发送）
  - `app/services/autoreply_admin_rollout_service.py:287` `record_admin_audit`
  - `app/services/douyin_autoreply_gate_service.py:301` `_frequency_snapshot`（**查 AiAutoReplyRun 含 blocked/failed，不用于 Phase 9**）
  - `app/services/conversation_autopilot_state_service.py` `evaluate_manual_takeover_gate`
  - `app/services/xg_douyin_ai_cs_client.py:32` `XgDouyinAiCsClient` + `X-Internal-Service-Token`(:213) + `XG_DOUYIN_AI_CS_SERVICE_TOKEN`(config.py:268)
  - `require_internal_service_token`（9100 既有内部鉴权依赖；phase8 plan 行 881：不得另造第二套令牌）
  - `app/main.py:161` `@app.on_event("startup")`（既有启动钩子）
  - 权威范围：`docs/superpowers/plans/2026-07-10-xiaogao-ai-phase1-master-plan.md` Phase 9（行 473-513）

---

## 1. 背景与目标

### 1.1 业务背景

auto_wechat 现有链路：客户在抖音私信留资 → Webhook 入库 → 分配销售 → 通过主机微信向销售下发派单通知 → 销售在微信回复 → ReplyCheck 检测销售是否回复。

Phase 9 在该链路之后增加"回访"能力（master plan 行 475）：当销售在微信侧产生符合特定场景的新回复时，由 9100 LLM 判定是否命中三类固定场景，生成回访话术，经违禁词替换后**调用抖音私信发送底层服务**主动回访客户。

### 1.2 目标

1. 锚定派单通知之后销售侧（微信 `sender=friend`）的新文本，作为回访判定的唯一输入信号（master plan 行 494-495）。
2. 由 9100 LLM 严格判定（LLM 优先，关键字兜底），输出置信度、回访话术、模型与受控风险标记。
3. 复用既有 `ReturnVisitRun` 持久化后异步处理，不阻塞 Local Agent；崩溃后可恢复重新判定，不丢失已持久化任务。
4. **实现完整真实发送代码路径**：复用底层 `_send_private_message_with_context`（`send_source="return_visit_auto"`，扩展 `return_visit_run_id`）→ 写 `douyin_private_message_sends` + `return_visit_runs`。自动测试以桩替换所有真实网络调用，真实网络调用数为 0；宝塔生产真实验证后置。
5. 提供管理页编辑三场景提示词（PUT 带变更原因 + 审计）与查看只读运行记录；提供内部判定接口（复用既有内部鉴权链）。

### 1.3 冻结结论清单（十三条）

| 编号 | 冻结结论 |
|------|----------|
| C1 | 三类场景固定键：`retain_contact_conversion` / `finance_plan_followup` / `silent_customer_wakeup` |
| C2 | 不做抖音会话时间扫描；沉默客户唤醒仍由销售微信反馈触发 |
| C3 | 仅锚定派单通知之后的新 `sender=friend` 文本 |
| C4 | ReplyCheck 状态与回访触发解耦 |
| C5 | 持久化 `ReturnVisitRun`（含完整标准化回复包）后异步处理；统一入口 `process_return_visit_run(run_id)`；请求路径用 FastAPI `BackgroundTasks`，启动路径在 lifespan `startup` 中启动一次性、有界、单飞后台任务；不引入周期高频 worker；不丢失已持久化任务 |
| C6 | LLM 输出 `confidence` 范围 `0～1`；配置 `confidence_threshold` 范围 `0.50～1.00` 初始 `0.90`；**阈值仅约束 LLM 的 `completed` 分支**，关键词兜底不参与阈值门禁 |
| C7 | LLM 优先；**仅技术故障**（超时/网络异常/未配置/空输出/普通格式错误/置信度越界）时关键词兜底；**模型拒答 `model_refusal` 与提示词注入 `prompt_injection` 为安全阻断**，写 `risk_flags` 进 `blocked`，**不进入关键词兜底**；关键词分**触发词**与**抑制词**（抑制优先阻断）；多场景命中记 `ambiguous` 不发送；单场景触发词命中且场景 `enabled` 直接用 `fallback_message`，`confidence=0.5` 仅审计值；关键词固定代码（9100 判定模块）不入 DB |
| C8 | 消息级永久幂等键 = `sha256(merchant_id + dispatch_notification_id + trigger_message_fp)`（不含 `prompt_key`）；会话级 24h 冷却按 `(merchant_id, account_open_id, conversation_short_id, customer_open_id, prompt_key)` 统计，时间基准为 `DouyinPrivateMessageSend.sent_at`（JOIN 发送流水），**仅 `sent` 计入** |
| C9 | 安全熔断使用抖音 env 总熔断 + `AutoReplyRolloutConfig.real_send_enabled`；**不使用**微信 `is_automation_allowed`；**不使用**账号/客户灰度白名单 |
| C10 | 状态机 11 态；除 `pending_judgement/processing/send_authorized` 外其余 **8 态为不可重试终态**；崩溃恢复分层：`pending_judgement` 重调度、未授权 `processing` 回 `pending_judgement`、`send_authorized` 只核对发送流水（已发送→`sent`，否则→`send_unknown`），**绝不重发**；新消息创建新 run ≠ 旧终态 run 可继续 |
| C11 | 管理 API：`/admin/return-visit-prompts`（PUT 要求 `reason` + `record_admin_audit`）+ `/admin/return-visit-runs`（只读）+ 内部 `/internal/return-visits/decide-and-generate`（复用既有 `require_internal_service_token` / `XgDouyinAiCsClient` / `X-Internal-Service-Token` / `XG_DOUYIN_AI_CS_SERVICE_TOKEN`，不另造令牌）；权限码 `auto_wechat:admin:return_visit_prompts`；不提供重试或立即发送 |
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
- N6：不新建表；提示词为全局配置，复用既有 `ReturnVisitPrompt`。
- N7：不把关键词存入数据库或暴露为前端可编辑项（C7）。
- N8：不经过上层 `ai_auto_reply_send_service`（绑定 `AiAutoReplyRun` 与白名单）。
- N9：不复用 `_frequency_snapshot`（查 `AiAutoReplyRun` 含 blocked/failed，不反映 Phase 9 实发量）。

### 2.2 禁止事项

- F1：禁止重复创建既有表；迁移只能 ALTER 或安全重建既有表。
- F2：禁止使用微信 `is_automation_allowed` 作为回访发送熔断（C9）。
- F3：禁止使用账号/客户灰度白名单（C9）。
- F4：禁止跨商户读取或写入 `ReturnVisitRun`。
- F5：禁止在 `send_unknown`/`sent` 等终态重发；禁止对 `send_authorized` 重发（C10）。
- F6：禁止发送未过违禁词替换的回访话术（底层函数内置）。
- F7：禁止在 Local Agent 线程内同步执行 LLM 判定。
- F8：禁止销售回复原文进入**日志与管理 API**（DB 持久化完整标准化回复包仅供崩溃重判定；日志/管理 API 仅指纹与长度摘要）。
- F9：禁止引入周期高频 worker。
- F10：禁止迁移 seed 写空占位或保留占位默认值；`fallback_message` 必须 NOT NULL 并回填已批准三条文案；SQLite 安全重建按三键写入，PG 先可空→回填→校验零空值→SET NOT NULL。
- F11：禁止幂等键依赖判定前未知的 `prompt_key`。
- F12：禁止启动对账把可恢复的 `pending_judgement`/未授权 `processing` 标记终态（会因永久幂等丢失任务）。
- F13：禁止 SQLite downgrade 保留新增列；必须安全重建真实恢复迁移前结构。
- F14：禁止启动路径使用请求级 FastAPI `BackgroundTasks`（其依赖 HTTP 响应生命周期）。
- F15：禁止另造内部鉴权令牌；必须复用既有 `require_internal_service_token` 链。
- F16：禁止用 run.`created_at` 作为冷却时间基准；必须用 `DouyinPrivateMessageSend.sent_at`。

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
        │  标准化回复包 = normalize(销售回复文本)（去首尾空白、合并连续空白、统一全角半角）
        │  trigger_message_fp = sha256(标准化回复包)
        │  幂等预检：idempotency_key = sha256(merchant + dispatch_notification_id + trigger_message_fp)
        │  会话级 24h 冷却预检（JOIN DouyinPrivateMessageSend.sent_at，仅 sent）
        ▼
持久化 ReturnVisitRun
        │  send_status=pending_judgement
        │  trigger_text = 标准化完整回复包（★ 供崩溃重判定，不入日志/管理 API）
        │  trigger_message_fp / account_open_id / conversation_short_id / customer_open_id /
        │    context_server_message_id / dispatch_notification_id 落库
        │  ★ 持久化即返回 run_id，不阻塞 Local Agent（C5）
        ▼
异步处理：统一入口 process_return_visit_run(run_id)
        │  请求路径：FastAPI BackgroundTasks.add_task(process_return_visit_run, run_id)
        │  启动路径：lifespan startup 一次性有界单飞后台任务（见 §9.1）
        │  claim: pending_judgement → processing（lease_owner + lease_expires_at）
        │
        ▼  调用内部协议 /internal/return-visits/decide-and-generate（XgDouyinAiCsClient + X-Internal-Service-Token）
9100 LLM 判定（LLM 优先，关键字兜底仅技术故障，C7）
        │  入参含 sales_reply_text = run.trigger_text（DB 读取，崩溃可重判定）
        │  输出：prompt_key / confidence(0-1) / suggested_message / judgement_source /
        │        judgement_result / model / risk_flags(固定枚举) / ambiguous
        │  提示词注入预检（兜底前）→ risk_flags=[prompt_injection] → blocked（不进兜底）
        │  模型拒答 model_refusal → risk_flags=[model_refusal] → blocked（不进兜底）
        │  抑制词命中 → not_needed（suppress_hit）
        │  其他 risk_flags 命中 → blocked（风险阻断）
        │  多场景命中 → ambiguous 不发送
        │  仅技术故障（超时/网络/未配置/空输出/普通格式错误/置信度越界）→ 关键词兜底
        ▼
判定结果分流
        │  未命中 → not_needed
        │  LLM completed 但 confidence < 阈值 → confidence_low（阈值仅约束 LLM）
        │  场景 prompt.enabled=false（LLM 或关键词命中均检查）→ prompt_disabled
        │  单场景命中（LLM 过阈值 或 关键词触发词命中）→ 继续
        ▼
门禁检查（C-安全版 11 项，见第 7 节）
        │  env kill switch / DB real_send_enabled / 商户隔离 / 人工接管 /
        │  最新消息与上下文三条件 / 账号每小时限频(基准 sent_at，回落60) /
        │  会话级 24h 冷误(基准 sent_at) / 消息级幂等 / 话术安全+risk_flags
        │  门禁拦截 → blocked（G1-G5/G10）；限频/冷却 → rate_limited（G6/G7）
        ▼
send_status=send_authorized（话术 generated_content 已生成、门禁已过）
        ▼
调用底层 _send_private_message_with_context（send_source="return_visit_auto"，return_visit_run_id=本run）
        │  底层内置：sanitize / 违禁词替换(source=douyin_return_visit) / context 24h 校验 /
        │    account 归属校验 / call_douyin_openapi("/send_msg") / 写 DouyinPrivateMessageSend 流水（sent_at 成功时回填）
        │  ★ 自动测试中 call_douyin_openapi 被桩替换（C12）
        ▼
结果回写 ReturnVisitRun（发送后处理，非门禁）
        │  OpenAPI code=0 → send_status=sent，send_id=upstream msg_id
        │  结果不确定 → send_status=send_unknown（终态禁重发）
        │  明确失败 → send_status=failed（终态），error_message + last_failure_stage
```

### 3.2 关键边界

- 锚点：每个 `ReturnVisitRun` 必须关联派单通知记录与可用 `send_msg context`（master plan 行 496）。
- 恢复输入：`trigger_text` 持久化**标准化完整回复包**，崩溃重调度 `pending_judgement` 时可重新喂给 9100 判定（F8：仅不入日志/管理 API）。
- 发送底层：复用 `_send_private_message_with_context`，**不经过** `ai_auto_reply_send_service`（N8）。

---

## 4. 数据模型增量与状态机（ALTER 既有表）

### 4.1 既有表 `return_visit_prompts`（不重建，ALTER 增量）

既有字段：`id / prompt_key(UNIQUE) / name / scene_type / template_text / scope='global' / enabled / sort_order / created_at / updated_at`。既有 seed（0027/0008，冻结）：三场景固定键。

Phase 9 增量字段：

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| confidence_threshold | FLOAT | NOT NULL DEFAULT 0.90 | 场景置信度阈值 0.50～1.00，**仅约束 LLM** |
| fallback_message | TEXT | NOT NULL（无占位默认值） | LLM 不可用且关键词触发词命中时兜底文案 |

`fallback_message` **已批准三条固定文案**（迁移回填，NOT NULL，F10）：

| prompt_key | fallback_message（已批准，原样回填） |
|------------|----------------------------------------|
| `retain_contact_conversion` | 您好，刚才留存的联系方式似乎无法正常联系。麻烦您重新发送一个常用手机号或微信号，方便我们继续为您服务。 |
| `finance_plan_followup` | 您好，关于您关注的金融方案，我们可以继续为您说明。您更想了解首付、月供还是分期期限？ |
| `silent_customer_wakeup` | 您好，之前的咨询还需要我们继续协助吗？方便时告诉我您目前最关心的问题，我们再为您跟进。 |

### 4.2 既有表 `return_visit_runs`（不重建，ALTER 增量）

既有字段（复用，不新增重复语义字段）：`id / merchant_id / lead_id / staff_id / reply_check_id / prompt_key / trigger_source / trigger_text / judgement_source / judgement_result / generated_content / final_content / send_status / send_id / error_message / created_at / updated_at`。

**复用映射**：
- `trigger_text`（既有）= **标准化完整回复包**（F8：不入日志/管理 API，仅供崩溃重判定）。
- `judgement_source`（既有）= `llm` / `keyword_fallback`。
- `judgement_result`（既有）= 命中 `prompt_key` / `ambiguous` / `no_match` / `below_threshold` / `prompt_disabled` / `suppress_hit`。
- `prompt_key` / `generated_content` / `final_content` / `send_status`（11 态）/ `send_id` / `error_message` 复用。

Phase 9 增量字段（ALTER ADD COLUMN）：

| 分组 | 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|------|
| 触发键 | dispatch_notification_id | INTEGER | NULL | 派单通知锚点 |
| 触发键 | trigger_message_fp | VARCHAR(64) | NULL | 标准化回复包 sha256 指纹 |
| 触发键 | idempotency_key | VARCHAR(128) | UNIQUE | 消息级永久幂等键（不含 prompt_key） |
| 抖音上下文 | account_open_id | VARCHAR(255) | NULL | 抖音账号 open_id（既有体系） |
| 抖音上下文 | conversation_short_id | VARCHAR(255) | NULL | 会话短 ID |
| 抖音上下文 | customer_open_id | VARCHAR(255) | NULL | 客户 open_id |
| 抖音上下文 | context_server_message_id | VARCHAR(255) | NULL | 发送上下文锚定消息 ID（漂移检测） |
| 判定 | confidence | FLOAT | NULL | LLM/关键词置信度 0～1（关键词=0.5 审计值） |
| 判定 | model | VARCHAR(128) | NULL | LLM 模型名（对齐 ComputeTransaction.model） |
| 判定 | risk_flags_json | TEXT | NULL | risk_flags 固定枚举 JSON（命中阻断） |
| 门禁 | gate_results_json | TEXT | NULL | 门禁通过/拦截摘要 |
| 门禁 | last_failure_stage | VARCHAR(100) | NULL | 最近失败阶段码 |
| 门禁 | manual_takeover | BOOLEAN | NOT NULL DEFAULT 0 | 人工接管标记 |
| 租约 | lease_owner | VARCHAR(64) | NULL | 处理 owner（请求/启动任务标识） |
| 租约 | lease_expires_at | DATETIME | NULL | 租约过期 |
| 租约 | attempt_count | INTEGER | NOT NULL DEFAULT 0 | 判定尝试次数 |

删除相比初版的字段（语义并入既有）：`decision_source` / `reason_code` / `llm_raw_status` / `ambiguous_hit` / `last_run_at` / `douyin_account_id`（改 `account_open_id`）。

索引增量：
- UNIQUE(idempotency_key)（SQLite 安全重建 / PG ADD CONSTRAINT）
- INDEX(merchant_id, account_open_id, conversation_short_id, customer_open_id, prompt_key)（会话级冷却 JOIN）
- INDEX(dispatch_notification_id)

**幂等键**（C8/F11，无循环）：
```
trigger_message_fp = sha256(normalize(销售回复文本包))
idempotency_key = sha256(merchant_id + ":" + dispatch_notification_id + ":" + trigger_message_fp)
```

**会话级 24h 冷却**（C8/F16，时间基准 = 发送流水 sent_at）：
```
count = SELECT COUNT(*) FROM return_visit_runs r
  JOIN douyin_private_message_sends s ON s.return_visit_run_id = r.id
  WHERE r.merchant_id=:m AND r.account_open_id=:a
    AND r.conversation_short_id=:c AND r.customer_open_id=:u AND r.prompt_key=:p
    AND r.send_status='sent' AND s.status='sent'
    AND s.sent_at >= NOW() - INTERVAL '24 hours'
if count >= 1: rate_limited / session_cooldown
```
不使用 run.`created_at`；不使用 `last_run_at` 字段。

### 4.3 既有表 `douyin_private_message_sends`（不重建，ALTER 增量）

既有 `auto_reply_run_id INTEGER UNIQUE` + `sent_at`（models.py:389）。Phase 9 增量：

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| return_visit_run_id | INTEGER | UNIQUE | 回访 run ID，防重复发送（镜像 auto_reply_run_id） |

### 4.4 既有底层发送函数扩展（代码改动，非迁移）

`_send_private_message_with_context`（douyin_private_message_send_service.py:94）扩展：
- 新增参数 `return_visit_run_id: int | None = None`。
- `send_source` 接受 `"return_visit_auto"`。
- 违禁词替换 `source` 扩展 `"douyin_return_visit"`。
- 写 `DouyinPrivateMessageSend` 时填 `return_visit_run_id`；`sent_at` 在 OpenAPI code=0 时回填（既有逻辑）。

### 4.5 状态机（`send_status`，11 态，8 终态）

```
pending_judgement ──claim──▶ processing
                                 │
          ┌────────┬────────┬────┴─────┬───────────┬──────────┐
          ▼        ▼        ▼          ▼           ▼          ▼
      not_needed confidence_low prompt_disabled rate_limited blocked  send_authorized
      (未命中/   (LLM低置信)  (场景禁用)    (24h/限频)   (门禁)    (话术生成+门禁过)
       suppress)                                                        │
                                                            ┌───────────┴──────────┐
                                                            ▼                      ▼
                                                         sent                 send_unknown
                                                     (OpenAPI code=0)       (结果不确定)

failed：LLM/发送明确失败
```

- **可恢复（3 态）**：`pending_judgement` / `processing` / `send_authorized`。
- **不可重试终态（8 态）**：`not_needed` / `confidence_low` / `prompt_disabled` / `rate_limited` / `blocked` / `sent` / `send_unknown` / `failed`。
- 终态 run 永不继续；新消息若通过幂等与冷却约束则创建**新 run**（≠ 旧 run 可继续）。

---

## 5. 9100 严格判定协议

### 5.1 协议入口（复用既有内部鉴权链）

冻结内部接口 `/internal/return-visits/decide-and-generate`：
- 9100 路由用既有 `require_internal_service_token`（不另造令牌，F15）。
- 鉴权 token = `XG_DOUYIN_AI_CS_SERVICE_TOKEN`（config.py:268），header = `X-Internal-Service-Token`。
- 9000 侧用既有 `XgDouyinAiCsClient`（xg_douyin_ai_cs_client.py:32，自动带 token header）调用。
- 实现复用 `apps/xg_douyin_ai_cs/services/reply_decision_service.py` 既有 LLM 客户端，新增 `judge_return_visit(request)`。

### 5.2 输入

```
ReturnVisitJudgeRequest:
  tenant_id / merchant_id / lead_id
  prompts: dict[prompt_key, {template_text, fallback_message, confidence_threshold, enabled}]
  sales_reply_text: str          # = run.trigger_text（标准化完整回复包，从 DB 读，非仅内存）
  dispatch_context: dict
```

### 5.3 输出（复用既有字段 + model + risk_flags 固定枚举）

```
ReturnVisitJudgment:
  prompt_key: str | None          # 必须为三键之一，否则归 no_match
  confidence: float               # 0～1，越界视为 LLM 不可用
  should_trigger: bool
  suggested_message: str | None
  judgement_source: str           # llm / keyword_fallback（复用既有字段）
  judgement_result: str           # 命中key/ambiguous/no_match/below_threshold/prompt_disabled/suppress_hit（复用既有字段）
  model: str | None               # LLM 模型名
  risk_flags: list[str]           # 固定枚举，≤8 项，单项 ≤32 字符；命中阻断
  ambiguous: bool
```

**risk_flags 固定枚举**（`{prompt_injection, sensitive_info, off_topic, duplicate, policy_violation, model_refusal}`；未知值归一 `policy_violation` 保守阻断）。

### 5.4 判定顺序（安全阻断优先，LLM 优先，关键词兜底仅技术故障，关键词命中也检查 enabled）

1. **提示词注入安全预检**（最高优先级，LLM 与兜底前）：销售回复含指令性注入 → `risk_flags=[prompt_injection]`，`should_trigger=false`，进 `blocked`（**既不进入 LLM 也不进入关键词兜底**）。
2. **抑制词预检**（C7）：命中抑制词 → `judgement_result=suppress_hit`，`should_trigger=false`，进 `not_needed`。
3. **LLM 优先**（`judgement_source=llm`）：
   - **模型拒答**（`model_refusal`）→ `risk_flags=[model_refusal]`，进 `blocked`（**安全阻断，不进关键词兜底**）。
   - **其他 `risk_flags` 非空** → 返回，门禁 G10 阻断（不在此拦截判定）。
   - **LLM 技术故障**（超时/网络异常/未配置/空输出/普通格式错误/置信度越界）→ 进入步骤 4 关键词兜底。
   - LLM 正常（输出受控结构、confidence ∈ [0,1]、prompt_key 为三键之一、非空输出、非拒答）：
     - 多场景命中 → `ambiguous`，不发送。
     - 场景 `enabled=false` → `prompt_disabled`。
     - 单场景 + `confidence >= confidence_threshold` → 命中，`suggested_message` 基于 template_text 生成。
     - 单场景 + `confidence < 阈值` → `below_threshold`（阈值仅约束 LLM）。
     - 未命中 → `no_match`。
4. **关键词兜底**（`judgement_source=keyword_fallback`，**仅 LLM 技术故障时执行**，C7）：
   - 关键字固定代码常量（9100 判定模块），分触发词与抑制词。
   - **关键词命中后也必须检查 `prompt.enabled`**：`enabled=false` → `prompt_disabled`。
   - 多场景触发词同时命中 → `ambiguous`，不发送。
   - 单场景触发词命中 + `enabled=true` → **直接触发**，`suggested_message=fallback_message`，`confidence=0.5`（审计值，不过阈值门禁），`judgement_result=命中 prompt_key`。
   - 全未命中 → `no_match`。

> **安全阻断不进兜底**：模型拒答（`model_refusal`）与提示词注入（`prompt_injection`）写 `risk_flags` 进 `blocked`，**绝不进入关键词兜底**；只有超时、网络异常、未配置、空输出、普通格式错误、置信度越界等**技术故障**才允许关键词兜底。

### 5.5 判定结果到状态映射

| judgement_result | send_status |
|------------------|-------------|
| 命中 prompt_key（LLM 过阈值 或 关键词触发词 + enabled） | 继续 → 门禁 → send_authorized |
| `below_threshold` | `confidence_low` |
| `prompt_disabled`（LLM 或关键词命中均检查） | `prompt_disabled` |
| `ambiguous` | `not_needed` |
| `no_match` | `not_needed` |
| `suppress_hit` | `not_needed` |
| `risk_flags` 非空 | `blocked`（风险阻断，G10） |

### 5.6 严格性约束

- LLM 输出受控结构；**技术故障**（解析失败/超时/网络异常/未配置/空输出/普通格式错误）→ 关键词兜底；**模型拒答**（`model_refusal`）→ 安全阻断进 `blocked`，**不进关键词兜底**。
- `prompt_key` 必须为三键之一，未知键 → `no_match`。
- `confidence` 越界（<0 或 >1）→ 视为技术故障 → 关键词兜底。
- 提示词注入预检在 LLM 调用与关键词兜底**之前**完成，命中即 `risk_flags=[prompt_injection]` → `blocked`（不进兜底）。
- 9100 日志只记 `lead_id` / `prompt_key` / `confidence` / `judgement_source` / `judgement_result` / `model` / `risk_flags`，不记原文。

---

## 6. 关键词与回访话术

### 6.1 关键词（固定代码，触发词 + 抑制词，抑制优先，C7）

关键字定义在 **9100 判定模块** `apps/xg_douyin_ai_cs/services/return_visit_judge_service.py` 模块级常量，不入 DB（关键词兜底由 9100 `judge_return_visit` 执行）。**9000 仅负责持久化、调用 9100、门禁与发送，不持有判定/关键词逻辑**；9100 不反向依赖 9000 业务服务。基于 master plan 行 492-495：

**抑制词**（最高优先级，命中即 `suppress_hit`）：
`不是手机号不对`、`号码没问题`、`已联系上`、`客户已回复`、`客户回消息了`、`无需回访`、`不用回访`、`已成交`、`已到店`

**触发词**（按场景，否定语义优先）：

| prompt_key | 否定触发词（优先） | 肯定触发词 |
|------------|--------------------|------------|
| `retain_contact_conversion` | `手机号不对`、`号码错了`、`联系方式不对`、`空号` | `留资`、`加微信`、`留电话` |
| `finance_plan_followup` | `金融方案不合适`、`首付太高`、`月供太高`、`利息高` | `金融方案`、`贷款`、`分期`、`首付`、`月供` |
| `silent_customer_wakeup` | `客户长期未回复`、`联系不上`、`失联`、`不回消息`、`找不到人` | （沉默场景以否定语义为主） |

匹配规则：抑制词优先 → 否定触发词优先于肯定 → 多场景触发词同时命中 `ambiguous` 不发送 → 关键词命中也检查 `enabled`。调整走代码评审 + 提交。

### 6.2 回访话术（template_text + fallback_message NOT NULL，管理员编辑）

- **正常话术**：`template_text`（既有）。LLM 命中后基于模板生成 `generated_content`。
- **兜底话术**：`fallback_message`（Phase 9 增量，NOT NULL，已批准三条见 §4.1）。
- **编辑入口**：`/admin/return-visit-prompts`（PUT 必须 `reason` + `record_admin_audit`，见 §8）。
- **长度与安全**：上限 500 字符；提交过违禁词预检（不替换，仅告警，命中记 `forbidden_word_hit_logs` source=`return_visit_prompt_edit`）。

---

## 7. 真实发送门禁（C-安全版 11 项，C9）

完整实现真实发送代码路径（C12），复用底层 `_send_private_message_with_context`（不经上层 `ai_auto_reply_send_service`）。门禁在 `send_authorized` 之前评估；**失败回写是发送后结果处理，不是发送前门禁**。限频与冷却进 `rate_limited`；其余拦截进 `blocked`。

| 序 | 门禁 | 不过处置 | 说明 |
|----|------|----------|------|
| G1 | 抖音 env 总熔断（既有 autoreply kill switch） | blocked / env_kill_switch | 全局熔断 |
| G2 | `AutoReplyRolloutConfig.real_send_enabled`(scope=global) | blocked / real_send_disabled | DB 全局开关（C9） |
| G3 | 商户隔离 `merchant_id` | blocked / cross_merchant | 跨商户不可见 |
| G4 | 人工接管 `evaluate_manual_takeover_gate` | blocked / manual_takeover | 销售已人工接管 |
| G5 | 最新消息与上下文三独立条件（任一即 blocked） | blocked / 见下 | 安全链冻结三条件 |
| G6 | 账号每小时限频（基准 `douyin_private_message_sends.sent_at`） | **rate_limited** / frequency_account_exceeded | 见下，不复用 `_frequency_snapshot` |
| G7 | 会话级 24h 冷却（基准 `sent_at` JOIN，仅 sent） | **rate_limited** / session_cooldown | C8/F16 |
| G8 | 消息级幂等 `idempotency_key` UNIQUE | 跳过（返回既有 run） | 永久幂等 |
| G9 | LLM `confidence >= confidence_threshold`（**仅约束 LLM**；关键词直接放行） | `confidence_low` | 阈值不约束关键词 |
| G10 | 话术安全 + `risk_flags` 风险阻断（固定枚举）+ 违禁词替换（底层内置） | blocked / message_invalid 或 blocked / risk_flags | |
| G11 | `send_authorized → send_unknown` 禁重发 | send_unknown 终态 | C10 |

**G5 最新消息与上下文三独立阻断条件**（冻结，C-安全版）：
- `has_outbound_after_trigger is True` → blocked / `outbound_after_trigger`（派单通知后该会话已有出站消息，防止重复打扰）
- `latest_is_customer_message is not True` → blocked / `latest_not_customer`（最新消息不是客户消息）
- `latest_server_message_id != context_server_message_id` → blocked / `context_drifted`（上下文锚定消息已被新消息顶替）

**G6 账号每小时限频**（不复用 `_frequency_snapshot`，N9；基准 sent_at）：
```
account_sent = SELECT COUNT(*) FROM douyin_private_message_sends
  WHERE account_open_id=:a AND status='sent'
    AND send_source IN ('ai_auto','return_visit_auto')
    AND sent_at >= NOW() - INTERVAL '1 hour'
limit = DouyinAccountAutoreplySetting.max_replies_per_account_per_hour
  -- 复用账号设置；缺失/None/<=0 → 回落 60
if account_sent >= limit: rate_limited / frequency_account_exceeded
```

明确排除（C-安全版不检查）：账号/客户灰度白名单；微信 `is_automation_allowed`；上层 `ai_auto_reply_send_service` 的 `AiAutoReplyRun`/白名单逻辑；`_frequency_snapshot`。

---

## 8. 管理 API 与内部协议（C11）

### 8.1 管理 API（权限 `auto_wechat:admin:return_visit_prompts`，跨商户统一 404）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/admin/return-visit-prompts` | 列出三场景全局提示词 |
| PUT | `/admin/return-visit-prompts/{prompt_key}` | 编辑（template_text / fallback_message / confidence_threshold / enabled）；**请求体必须含 `reason`**；事务内 `record_admin_audit(action="return_visit_prompt_update", target_type="return_visit_prompt", target_id=prompt_key, before=旧值摘要, after=新值摘要, reason=reason)` |
| GET | `/admin/return-visit-runs` | 只读列表（按 send_status / prompt_key / judgement_source 筛选） |
| GET | `/admin/return-visit-runs/{id}` | 只读详情 |
| GET | `/admin/return-visit-runs/stats` | 统计聚合 |

明确不提供（C11）：不提供 `retry` / `send` 写接口。

响应脱敏（F8）：`trigger_text` **不返回**（列表与详情均不回显原文）；`trigger_message_fp` 返回指纹；不返回客户手机号；`customer_open_id` 仅详情可见；`generated_content`/`final_content` 仅详情可见。

### 8.2 内部协议（复用既有内部鉴权链，F15）

| 方法 | 路径 | 鉴权 | 说明 |
|------|------|------|------|
| POST | `/internal/return-visits/decide-and-generate` | `require_internal_service_token` + `X-Internal-Service-Token` = `XG_DOUYIN_AI_CS_SERVICE_TOKEN` | 9000 用 `XgDouyinAiCsClient` 调用；出参含 model/risk_flags；仅 9000 调用，不暴露公网 |

### 8.3 前端设计

复用既有超管后台导航（`auto_wechat:admin:return_visit_prompts`），新增：
1. **回访提示词配置页**：三场景卡片，编辑 `template_text` / `fallback_message` / `confidence_threshold`(0.50～1.00) / `enabled`；PUT 必填 `reason`；违禁词预检告警 + 审计摘要。
2. **回访运行记录页（只读）**：列表（prompt_key / send_status / judgement_source / judgement_result / confidence / model / risk_flags / last_failure_stage / created_at），详情抽屉（generated_content / final_content / trigger_message_fp / risk_flags_json / gate_results_json）。不提供重试/立即发送。

前端约束：`confidence_threshold ∈ [0.50, 1.00]`；`template_text`/`fallback_message` 长度 ≤ 500；`reason` 非空。

---

## 9. 崩溃恢复与幂等（统一入口 + 分层对账，C5/C10）

### 9.1 崩溃恢复（统一入口 + 分层启动对账，无周期 worker）

- **持久化优先**：持久化 `ReturnVisitRun(send_status=pending_judgement, trigger_text=标准化完整回复包)` 后立即返回 `run_id`。
- **统一处理入口** `process_return_visit_run(run_id)`：claim（`pending_judgement → processing`，设 lease）→ 调用 9100 判定（入参 `trigger_text` 从 DB 读）→ 门禁 → 底层发送 → 结果回写。
- **请求路径**：`BackgroundTasks.add_task(process_return_visit_run, run_id)`（FastAPI 请求级，依赖 HTTP 响应生命周期，仅用于在线触发）。
- **启动路径**（F14，不请求级）：在 `@app.on_event("startup")`（main.py:161 既有钩子）中启动**一次性、有界、单飞**后台任务，遍历需要恢复的 run 调用 `process_return_visit_run(run_id)`，处理完毕后退出，不周期轮询（F9）。
- **分层启动对账**（唯一 reclaim 路径，F12）：
  1. `pending_judgement`：**重新调度**（投递给启动后台任务调用 `process_return_visit_run`），不标 failed。
  2. `processing AND lease_expires_at < NOW`（未授权 `send_authorized`）：**安全回 `pending_judgement`**（`attempt_count += 1`），再由启动任务处理。安全因尚未发送。
  3. `send_authorized`：**不重发**，只核对 `douyin_private_message_sends WHERE return_visit_run_id=:id`：
     - 存在 `status='sent'` → `send_status='sent'`，补 `send_id`。
     - 否则 → `send_status='send_unknown'`（终态）。
- **不丢失任务**：`trigger_text` 持久化完整回复包，重判定可重喂 9100；`pending_judgement`/未授权 `processing` 可恢复；永久幂等不阻止状态推进（同 idempotency_key 的 run 继续处理，不创建新 run）。
- **不自动重试终态**：8 终态永不继续。

### 9.2 幂等（C8）

- **消息级永久幂等**：`idempotency_key = sha256(merchant_id + ":" + dispatch_notification_id + ":" + trigger_message_fp)`，UNIQUE。冲突返回既有 run。
- **会话级 24h 冷却**：`(merchant_id, account_open_id, conversation_short_id, customer_open_id, prompt_key)`，仅 `sent` 计入，时间基准 `DouyinPrivateMessageSend.sent_at`（§4.2 JOIN）。
- **判定顺序**：先消息级（永久），再会话级冷却。
- **非 sent 终态不计冷却**：`failed/blocked/not_needed/confidence_low/prompt_disabled/rate_limited/send_unknown` 不计入。

---

## 10. SQLite `0030` / PostgreSQL `0011` 迁移边界（ALTER + 真实回滚 + NOT NULL 无占位）

### 10.1 SQLite `0030_return_visit_phase9.py`

**不重复建表**（F1）。**fallback_message 不用占位默认值建列**（F10）：SQLite 不能直接 ADD NOT NULL 无默认列到非空表，故 `return_visit_prompts` 与 `return_visit_runs`/`douyin_private_message_sends` 均采用**安全重建**（复用 0028/0029 `_backup/_new/_guard`）：

1. `return_visit_prompts` 安全重建：
   - CREATE `_new`（全部旧列 + `confidence_threshold FLOAT NOT NULL DEFAULT 0.90` + `fallback_message TEXT NOT NULL`**无 DEFAULT**）。
   - **迁移前校验**：`SELECT COUNT(*) FROM return_visit_prompts WHERE prompt_key NOT IN ('retain_contact_conversion','finance_plan_followup','silent_customer_wakeup')` 必须为 0；非 0 立即 ROLLBACK 不登记 0030（表中只能存在三个冻结键）。
   - INSERT SELECT：旧列直选；`fallback_message` 用 `CASE prompt_key WHEN 'retain_contact_conversion' THEN '<文案1>' WHEN 'finance_plan_followup' THEN '<文案2>' WHEN 'silent_customer_wakeup' THEN '<文案3>' END`（**无 ELSE 兜底**；前置校验已保证仅三键，CASE 未匹配则 NULL 触发 NOT NULL 约束失败回滚）。
   - 行数 + max(id) + 双向 GROUP BY 守卫（含 fallback_message 非空 CHECK）→ RENAME 旧 `_backup`、`_new` 正式 → DROP `_backup`。CHECK 违反 ROLLBACK 不登记 0030。
2. `return_visit_runs` 安全重建：CREATE `_new`（全部旧列 + §4.2 新列 + `idempotency_key` + UNIQUE + 索引）→ INSERT SELECT 旧数据 → 守卫 → RENAME 替换。
3. `douyin_private_message_sends` 安全重建：CREATE `_new`（全部旧列含 `auto_reply_run_id UNIQUE` + `return_visit_run_id` + UNIQUE）→ INSERT SELECT → 守卫 → RENAME。
4. 守卫：表/列/约束存在性 + seed 行数 = 3 + `fallback_message` 零空值断言。
5. 幂等：迁移内检测表已含新列则跳过；runner 已登记版本整体跳过。

**downgrade（F13，真实恢复）**：安全重建 `_new_pre`（仅迁移前列结构）→ INSERT SELECT 旧列 → 行数/max(id) 守卫 → RENAME 替换 → DROP。回滚三表到 0027/0008 原始结构（移除 confidence_threshold/fallback_message/return_visit_runs 新列/return_visit_run_id）。测试覆盖往返。

### 10.2 PostgreSQL `0011_return_visit_phase9.py`

**不重复建表**（F1）。**fallback_message 先可空→回填→校验零空值→SET NOT NULL**（F10，不保留占位默认）：

1. `return_visit_prompts`：
   - `ALTER TABLE ADD COLUMN confidence_threshold FLOAT NOT NULL DEFAULT 0.90`
   - `ALTER TABLE ADD COLUMN fallback_message TEXT`（**可空，无默认**）
   - UPDATE 三键回填 §4.1 已批准文案（`WHERE prompt_key IN (...)`）。
   - 校验：`SELECT COUNT(*) FROM return_visit_prompts WHERE fallback_message IS NULL OR fallback_message = ''` 必须为 0；非 0 则 RAISE ROLLBACK 不登记 0011。
   - `ALTER TABLE return_visit_prompts ALTER COLUMN fallback_message SET NOT NULL`。
2. `return_visit_runs`：`ADD COLUMN` 全部新列 + `ADD CONSTRAINT uk_return_visit_runs_idempotency_key UNIQUE (idempotency_key)` + 会话冷却索引 + dispatch_notification_id 索引。
3. `douyin_private_message_sends`：`ADD COLUMN return_visit_run_id INTEGER` + `ADD CONSTRAINT uk_..._return_visit_run_id UNIQUE (return_visit_run_id)`。
4. 权限：0008 表级 GRANT 覆盖新列。
5. 幂等：`ADD COLUMN IF NOT EXISTS`（PG 14+）+ `DO $$ ... IF NOT EXISTS ... END $$` 守卫约束。

**downgrade（F13）**：`DROP COLUMN confidence_threshold, fallback_message`（return_visit_prompts）+ `DROP COLUMN` return_visit_runs 全部新列 + `DROP CONSTRAINT` + `DROP COLUMN return_visit_run_id`。真实恢复。

### 10.3 迁移边界（硬约束）

- 仅 ALTER 或安全重建既有 3 表，**不创建新表**（F1）。
- 不修改既有列类型/约束。
- SQLite 与 PostgreSQL 字段定义一致（FLOAT/TEXT/VARCHAR(255)/INTEGER）。
- `fallback_message` NOT NULL 无占位默认值（F10）。
- downgrade 真实恢复迁移前结构，不保留新列（F13）。
- 迁移测试覆盖 upgrade/downgrade 往返 + 零空值断言（见 §11）。

---

## 11. 自动化测试矩阵

### 11.1 真实网络调用为零（C12）

- 所有抖音 OpenAPI HTTP 调用（`call_douyin_openapi`）以桩/monkeypatch 替换，真实网络调用数 = 0。
- 断言：`_send_private_message_with_context` 调用参数（`send_source="return_visit_auto"`、`return_visit_run_id`、final_content）、写 `douyin_private_message_sends`（return_visit_run_id UNIQUE）、不经过上层 `ai_auto_reply_send_service`。

### 11.2 9100 判定协议单元测试（含边界与注入）

| 用例 | 期望 |
|------|------|
| LLM 单场景 + confidence ∈ [0,1] + 过阈值 | judgement_source=llm，judgement_result=命中key，返回 model |
| LLM confidence < 阈值 | below_threshold（仅约束 LLM） |
| LLM 不可用 → 否定触发词命中 + enabled | keyword_fallback，confidence=0.5，fallback_message，**过阈值门禁** |
| LLM 不可用 → 关键词命中但 enabled=false | prompt_disabled（关键词也检查 enabled） |
| 抑制词命中 | suppress_hit → not_needed |
| 多场景触发词命中 | ambiguous，不发送 |
| **未知场景键**（LLM 返回非三键） | 视为 no_match |
| **越界置信度**（<0 或 >1） | 视为技术故障 → 关键词兜底 |
| **空输出**（LLM 返回空） | 视为技术故障 → 关键词兜底 |
| **超时**（LLM 超时） | 视为技术故障 → 关键词兜底 |
| **网络异常 / 未配置 / 普通格式错误** | 视为技术故障 → 关键词兜底 |
| **提示词注入**（销售回复含注入指令） | risk_flags=[prompt_injection] → blocked（**不进兜底**） |
| **模型拒答**（refusal） | risk_flags=[model_refusal] → blocked（**不进兜底**） |
| 提示词注入 + LLM 技术故障叠加 | 注入预检先阻断 → blocked（不进兜底） |
| risk_flags 非空 | 返回，门禁 G10 阻断 |
| risk_flags 未知值 | 归一 policy_violation 保守阻断 |
| risk_flags 数量 >8 或单项 >32 字符 | 视为无效 → 阻断 |

### 11.3 幂等与状态机单元测试

| 用例 | 期望 |
|------|------|
| 同 idempotency_key 第二次插入 | 返回既有 run |
| 幂等键不含 prompt_key | 持久化时可算，无循环 |
| 会话级 24h 内已有 sent（sent_at 基准） | rate_limited / session_cooldown |
| 仅 failed/not_needed run 存在 | 不计冷却，新消息可触发 |
| pending_judgement → processing → send_authorized → sent | 流转正确 |
| send_authorized → send_unknown | 终态禁重发 |
| 8 终态不可继续 | 新消息创建新 run（≠ 旧 run 继续） |

### 11.4 门禁集成测试（C-安全版，G1-G11）

| 用例 | 期望 |
|------|------|
| env kill switch 关闭 | blocked / env_kill_switch |
| DB real_send_enabled=false | blocked / real_send_disabled |
| 人工接管 | blocked / manual_takeover |
| has_outbound_after_trigger=True | blocked / outbound_after_trigger |
| latest_is_customer_message != True | blocked / latest_not_customer |
| latest_server_message_id != context_server_message_id | blocked / context_drifted |
| 账号每小时 sent 计数 >= 上限（回落60） | **rate_limited** / frequency_account_exceeded |
| 会话级 24h 冷却（sent_at 基准，已 sent） | **rate_limited** / session_cooldown |
| 限频统计 send_source IN (ai_auto, return_visit_auto) | blocked/run 不混计 AiAutoReplyRun |
| 消息级幂等冲突 | 跳过 |
| LLM confidence < 阈值 | confidence_low |
| 关键词命中（confidence=0.5） | 过 G9 → send_authorized |
| risk_flags 非空 | blocked / risk_flags |
| 话术为空 | blocked / message_invalid |
| 发送路径调用底层（不经 ai_auto_reply_send_service） | send_source=return_visit_auto |
| OpenAPI code=0 | sent，sent_at 回填 |
| OpenAPI 结果不确定 | send_unknown |
| **不使用** is_automation_allowed / 白名单 / _frequency_snapshot | 不查询 |

### 11.5 崩溃恢复分层测试

| 用例 | 期望 |
|------|------|
| trigger_text 持久化完整回复包 | 重启后可重判定 |
| 启动时 pending_judgement | 启动后台任务重新调度（不 failed） |
| 启动时 processing 过期（未授权） | 回 pending_judgement，attempt+1，重判定 |
| 启动时 send_authorized + 有 sent 流水 | sent（不重发） |
| 启动时 send_authorized + 无流水 | send_unknown（不重发） |
| 启动任务一次性有界单飞 | 处理完毕退出，不周期轮询 |
| 8 终态不被启动对账改动 | 终态保持 |

### 11.6 管理 API + 内部协议测试

| 用例 | 期望 |
|------|------|
| GET /admin/return-visit-prompts 返回三场景 | 200，fallback_message NOT NULL（已批准三条） |
| PUT 缺 reason | 422 |
| PUT 带 reason | 200，record_admin_audit 写入（before/after/reason） |
| PUT confidence_threshold=0.3 | 422 |
| GET /admin/return-visit-runs 列表不返回 trigger_text 原文 | 无 trigger_text 字段 |
| /internal 无 X-Internal-Service-Token | 401/403 |
| /internal 错误 token | 401/403 |
| /internal 正确 token（XgDouyinAiCsClient） | 200，返回 model/risk_flags |
| 跨商户 GET runs/{id} | 404 |
| 权限码校验 | 无权限 403 |

### 11.7 迁移测试

| 用例 | 期望 |
|------|------|
| SQLite 0030 安全重建 + 新列 + UNIQUE + fallback_message NOT NULL 无占位 | 存在，零空值 |
| SQLite 0030 三键回填已批准文案 | 行数=3，文案正确 |
| **SQLite 0030 downgrade 真实恢复** | 新列移除，结构回 0027 |
| SQLite 0030 与 0029 共存 | 迁移链不中断 |
| PG 0011 先可空→回填→零空值校验→SET NOT NULL | NOT NULL，无占位默认 |
| PG 0011 ADD COLUMN/CONSTRAINT | 可重入 |
| **PG 0011 downgrade DROP COLUMN** | 真实恢复 |

### 11.8 端到端闭环（网络桩）

| 用例 | 期望 |
|------|------|
| 派单通知 → 销售回复"手机号不对" → 持久化(trigger_text 完整包) → 判定 → 底层发送桩 → sent | 全链路，真实网络=0 |
| 销售回复"已联系上" | suppress_hit → not_needed |
| 服务重启 trigger_text 可重判定 | pending_judgement 重调度成功 |
| 服务重启 send_authorized 核对流水 | sent 或 send_unknown，不重发 |
| ReplyCheck.check_status=timeout 仍可触发 | C4 解耦 |

---

## 12. 宝塔真实验证后置说明（C12）

- 本阶段所有回访发送在自动测试中以桩替换 `call_douyin_openapi`，真实网络调用数为 0。
- 真实抖音发送代码路径完整实现并复用底层 `_send_private_message_with_context`（master plan 行 502-506），未在宝塔生产环境真实验证。
- 宝塔生产验证后置：账号鉴权 / env 熔断 / `AutoReplyRolloutConfig.real_send_enabled` 开启 / 限频配置（账号每小时上限复用设置缺失回落 60）/ 违禁词服务 / 监控；`send_authorized → 真实 im_send_msg` 观测；`sent`/`send_unknown` 分布。
- 后置不阻塞：Phase 9 验收以"代码与自动测试闭环 DONE"为准，`baota_production_send_not_verified` 作为唯一 concern。
- 宝塔真实发送验证需另开执行包 + 生产检查点。

---

## 13. 风险与最终状态口径

### 13.1 风险

| 风险 | 等级 | 缓解 |
|------|------|------|
| `baota_production_send_not_verified` | 中 | 唯一 concern；发送代码路径已实现，宝塔验证另开 |
| LLM 故障导致关键词兜底覆盖率 | 中 | 触发词基于 master plan 样例；管理页观测 judgement_source 分布 |
| BackgroundTasks 崩溃丢 in-flight | 低 | 统一入口 + 分层启动对账（trigger_text 完整包可重判定；pending 重调度；processing 回 pending；send_authorized 核对流水） |
| Qt 微信 UIA 限制影响回访 | 无 | 锚定 sender=friend 文本读取（与 Phase 8-B 正交） |
| 配置误改回访风暴 | 中 | 24h 冷却（sent_at 基准）+ 账号每小时限频 + DB real_send_enabled + env kill switch + 管理页无立即发送 |

### 13.2 最终状态口径（冻结）

| 项目 | 状态 |
|------|------|
| Phase 9 代码与自动测试闭环 | `DONE` |
| Phase 9 | `DONE_WITH_CONCERNS`（唯一 concern = `baota_production_send_not_verified`） |
| Phase 8-B | `PARTIAL_BLOCKED_DEFERRED`（不恢复） |
| Phase 11 一键过审 | `CANCELLED_BY_CUSTOMER`（不恢复） |
| Task 8（日报真实分发） | `NOT_STARTED` |
| 真实抖音回访发送（宝塔验证） | 后置（另开执行包 + 生产检查点） |

### 13.3 自检（术语 / 状态 / 阈值 / 限频 / 鉴权 / 验收一致性）

- 三场景固定键：`retain_contact_conversion` / `finance_plan_followup` / `silent_customer_wakeup`。
- 状态机 11 态；**8 终态**（not_needed/confidence_low/prompt_disabled/rate_limited/blocked/sent/send_unknown/failed），3 可恢复（pending_judgement/processing/send_authorized）。
- LLM `confidence` 0～1；`confidence_threshold` 0.50～1.00 初始 0.90，**仅约束 LLM**（C6）。
- 会话级冷却 24h，基准 `DouyinPrivateMessageSend.sent_at`（JOIN，F16），仅 sent 计入。
- 账号每小时限频基准 `douyin_private_message_sends.sent_at` + `send_source IN ('ai_auto','return_visit_auto')`，上限复用账号设置缺失回落 60，进 `rate_limited`（G6）。
- G5 三独立阻断：`outbound_after_trigger` / `latest_not_customer` / `context_drifted`。
- 幂等键 = `sha256(merchant + dispatch_notification_id + trigger_message_fp)`，不含 prompt_key（F11）。
- 熔断：抖音 env + `AutoReplyRolloutConfig.real_send_enabled`（C9），不用微信 is_automation_allowed/白名单。
- 关键词：触发词+抑制词，抑制优先，ambiguous 不发送，**关键词命中也检查 enabled**，固定代码（**归属 9100 判定模块** `apps/xg_douyin_ai_cs/services/return_visit_judge_service.py`；9000 不持有判定逻辑，C7）。
- **安全阻断 vs 技术故障**：模型拒答 `model_refusal` + 提示词注入 `prompt_injection` → `risk_flags` → `blocked`，**不进关键词兜底**；仅技术故障（超时/网络/未配置/空输出/普通格式错误/置信度越界）允许关键词兜底。
- 发送：复用底层 `_send_private_message_with_context`，send_source=`return_visit_auto`，不经上层 ai_auto_reply_send_service（C12）；不复用 `_frequency_snapshot`（N9）。
- 复用既有 `judgement_source`/`judgement_result`/`trigger_text`（持久化完整回复包），不新增 decision_source/reason_code。
- 恢复：统一入口 `process_return_visit_run`；请求 BackgroundTasks + 启动 lifespan 一次性有界单飞任务（F14）。
- 内部鉴权：复用 `require_internal_service_token` + `XgDouyinAiCsClient` + `X-Internal-Service-Token` + `XG_DOUYIN_AI_CS_SERVICE_TOKEN`（F15）。
- risk_flags 固定枚举（6 值），≤8 项，单项 ≤32 字符，未知归一 policy_violation。
- 权限码 `auto_wechat:admin:return_visit_prompts`；API `/admin/return-visit-prompts`(PUT reason+审计) + `/admin/return-visit-runs` + `/internal/return-visits/decide-and-generate`（C11）。
- fallback_message NOT NULL 回填已批准三条（F10）。
- 迁移 downgrade 真实恢复，不保留新列（F13）。
- 自动测试真实网络调用为 0（C12）。
- 无 TODO/TBD/未定义字段。

---

## 附录 A：与既有体系的边界

- `ReturnVisitPrompt`（models.py:921）：补 `confidence_threshold` / `fallback_message`(NOT NULL 已批准三条)。
- `ReturnVisitRun`（models.py:941）：`trigger_text` 持久化完整标准化回复包；补触发键/抖音上下文(account_open_id VARCHAR(255))/context_server_message_id/confidence/model/risk_flags_json/门禁/租约；复用 judgement_source/judgement_result/prompt_key/generated_content/final_content/send_status。
- `DouyinPrivateMessageSend`（models.py:361）：补 `return_visit_run_id UNIQUE`；复用 `sent_at`(:389) 作限频/冷却时间基准。
- `DouyinAccountAutoreplySetting`（models.py:509）：复用 `max_replies_per_account_per_hour`（缺失/无效回落 60）。
- `_send_private_message_with_context`(douyin_private_message_send_service.py:94)：扩展 return_visit_run_id + send_source + 违禁词 source。
- `AutoReplyRolloutConfig`(models.py:514)：复用 real_send_enabled。
- `record_admin_audit`(autoreply_admin_rollout_service.py:287)：提示词 PUT 审计带 reason。
- `evaluate_manual_takeover_gate`(conversation_autopilot_state_service)：G4 人工接管。
- `require_internal_service_token` + `XgDouyinAiCsClient`(xg_douyin_ai_cs_client.py:32) + `X-Internal-Service-Token`(:213) + `XG_DOUYIN_AI_CS_SERVICE_TOKEN`(config.py:268)：内部鉴权链（F15）。
- `@app.on_event("startup")`(main.py:161)：启动一次性有界单飞任务挂载点。
- 迁移：SQLite 0030 接续 0029；PG 0011 接续 0010。

## 附录 B：后续执行包拆分建议（仅供参考，不在本设计范围）

1. 迁移：SQLite 0030 / PG 0011（安全重建/先可空回填校验SET NOT NULL + 真实回滚 + 已批准三条文案）。
2. 底层发送扩展：`_send_private_message_with_context` 加 return_visit_run_id + send_source/违禁词 source。
3. 9100 `judge_return_visit` + `/internal/return-visits/decide-and-generate`（复用既有内部鉴权链，model/risk_flags 固定枚举）。
4. 关键词常量（触发词+抑制词+三条件+enabled 检查，**归属 9100 `return_visit_judge_service`，随第 3 项 `judge_return_visit` 实现**）。
5. 9000 回访触发 + 持久化(trigger_text 完整包) + 统一入口 `process_return_visit_run` + 请求 BackgroundTasks + 启动 lifespan 一次性任务 + 分层对账 + 幂等。
6. C-安全版 11 门禁（env + DB real_send_enabled + 人工接管 + G5 三条件 + 限频 sent_at 基准回落60 + 冷却 sent_at JOIN + risk_flags）。
7. 管理 API + 前端（PUT reason + record_admin_audit）。
8. 测试矩阵落地（11.1～11.8，真实网络为 0，含边界/注入/超时/拒答）。
9. 宝塔真实发送验证（另开执行包 + 生产检查点）。
