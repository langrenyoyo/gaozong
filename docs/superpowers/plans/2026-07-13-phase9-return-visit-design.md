# Phase 9 微信到抖音回访设计（冻结）

- 文档日期：2026-07-13
- 文档性质：冻结设计落盘（仅文档，不含代码改动）
- 修订：2026-07-13 修正版（对齐既有 `ReturnVisitPrompt` / `ReturnVisitRun` / `DouyinPrivateMessageSend` 模型契约）
- 验收口径：代码与自动测试闭环 `DONE`；Phase 9 `DONE_WITH_CONCERNS`，唯一 concern 为 `baota_production_send_not_verified`
- 关联阶段：Phase 8-B `PARTIAL_BLOCKED_DEFERRED`（不恢复）；Phase 11 一键过审 `CANCELLED_BY_CUSTOMER`（不恢复）
- 既有契约：
  - `app/models.py:921` `ReturnVisitPrompt`（全局配置，`prompt_key` UNIQUE）
  - `app/models.py:941` `ReturnVisitRun`（运行流水）
  - `app/models.py:361` `DouyinPrivateMessageSend`（抖音私信发送流水，已有 `auto_reply_run_id UNIQUE` 防重模式）
  - `app/models.py:514` `AutoReplyRolloutConfig`（DB 全局真实发送开关 `real_send_enabled`）
  - 迁移 `migrations/versions/0027_xiaogao_phase1_core.sql` / `migrations/postgres/auto_wechat/versions/0008_xiaogao_phase1_core.py`（已建表 + 3 场景 seed）
  - 权威范围：`docs/superpowers/plans/2026-07-10-xiaogao-ai-phase1-master-plan.md` Phase 9（行 473-513）

---

## 1. 背景与目标

### 1.1 业务背景

auto_wechat 现有链路：客户在抖音私信留资 → Webhook 入库 → 分配销售 → 通过主机微信向销售下发派单通知 → 销售在微信回复 → ReplyCheck 检测销售是否回复。

Phase 9 在该链路之后增加"回访"能力（master plan 行 475）：当销售在微信侧产生符合特定场景的新回复时，由 9100 LLM 判定是否命中三类固定场景，生成回访话术，经违禁词替换后**调用抖音私信发送服务**主动回访客户。

### 1.2 目标

1. 锚定派单通知之后销售侧（微信 `sender=friend`）的新文本，作为回访判定的唯一输入信号（master plan 行 494-495：沉默唤醒也由销售微信反馈触发，不扫描抖音会话时间）。
2. 由 9100 LLM 严格判定该文本是否命中三类固定场景之一（LLM 优先，关键字兜底，master plan 行 498-499），输出置信度与回访话术。
3. 复用既有 `ReturnVisitRun` 持久化后异步处理（FastAPI BackgroundTasks），不阻塞 Local Agent 与既有派单/检测链路。
4. **实现完整真实发送代码路径**：生成话术 → 违禁词替换 → 调用抖音 OpenAPI 发送服务 → 写 `douyin_private_message_sends` + `return_visit_runs`（master plan 行 502-506）。本阶段在自动测试中以桩替换所有真实网络调用，真实网络调用数为 0；宝塔生产真实验证后置。
5. 提供管理页用于编辑三场景提示词模板（`/admin/return-visit-prompts`）与查看只读运行记录（`/admin/return-visit-runs`）。

### 1.3 冻结结论清单（十三条）

| 编号 | 冻结结论 |
|------|----------|
| C1 | 三类场景固定键：`retain_contact_conversion`（留资转化）、`finance_plan_followup`（金融方案）、`silent_customer_wakeup`（沉默客户唤醒） |
| C2 | 不做抖音会话时间扫描；沉默客户唤醒仍由销售微信反馈触发（master plan 行 495） |
| C3 | 仅锚定派单通知之后的新 `sender=friend` 文本 |
| C4 | ReplyCheck 状态与回访触发解耦（master plan 行 396-398：回复检测后尝试解析，无模板但有关键字仍可进入回访判断） |
| C5 | 持久化 `ReturnVisitRun` 后异步处理（BackgroundTasks + 启动对账），不阻塞 Local Agent；不引入周期高频 worker |
| C6 | 每场景独立配置阈值 `confidence_threshold`，范围 `0.50～1.00`，初始 `0.90`；LLM 输出 `confidence` 范围 `0～1` |
| C7 | LLM 优先；仅 LLM 故障时使用**固定在代码**的保守关键词（否定语义优先）和 `ReturnVisitPrompt.fallback_message`（管理员可编辑）兜底 |
| C8 | 同一消息永久幂等（`idempotency_key` UNIQUE）；同一会话每场景 24 小时最多一次 |
| C9 | 安全熔断使用抖音 env 总熔断 + `AutoReplyRolloutConfig.real_send_enabled`（DB 全局真实发送开关），**不使用**微信 `is_automation_allowed`，**不使用**账号/客户灰度白名单 |
| C10 | 状态机 11 态：`pending_judgement / processing / not_needed / confidence_low / prompt_disabled / rate_limited / blocked / send_authorized / sent / send_unknown / failed`；`send_authorized` 后结果不确定进入 `send_unknown`，禁止重发 |
| C11 | 管理 API：`/admin/return-visit-prompts`（编辑）+ `/admin/return-visit-runs`（只读）；权限码 `auto_wechat:admin:return_visit_prompts`；不提供重试或立即发送 |
| C12 | 本阶段实现完整真实发送代码路径，自动测试中 OpenAPI 调用全部替换（真实网络调用为 0）；宝塔生产真实验证后置且不阻塞验收 |
| C13 | 验收状态目标：代码与自动测试闭环 `DONE`，Phase 9 `DONE_WITH_CONCERNS`，唯一 concern 为 `baota_production_send_not_verified` |

---

## 2. 非目标与禁止事项

### 2.1 非目标

- N1：不扫描抖音会话历史或会话时间序列（C2，master plan 行 495）。
- N2：不依据 `ReplyCheck.check_status` 触发回访（C4）。
- N3：不在自动测试中发起任何真实抖音 OpenAPI 网络调用（C12）。
- N4：不在管理页提供"重试""立即发送"等写操作（C11）。
- N5：不做账号级或客户级的灰度白名单判定（C9）。
- N6：不新建场景配置表；提示词为全局配置，复用既有 `ReturnVisitPrompt`（`scope='global'`）。
- N7：不把关键词存入数据库或暴露为前端可编辑项；关键词固定在代码常量（C7）。

### 2.2 禁止事项

- F1：禁止重复创建既有表 `return_visit_prompts` / `return_visit_runs`；迁移只能 ALTER 或安全重建既有表。
- F2：禁止使用微信 `is_automation_allowed` 作为回访发送熔断（C9）。
- F3：禁止使用账号/客户灰度白名单（C9）。
- F4：禁止跨商户读取或写入 `ReturnVisitRun`。
- F5：禁止在 `send_unknown` 状态下重发（C10）。
- F6：禁止发送未过违禁词替换的回访话术（master plan 行 196：回访发送在调用 OpenAPI 前替换）。
- F7：禁止在 Local Agent 线程内同步执行 LLM 判定（必须持久化后异步）。
- F8：禁止回写原始销售回复正文到管理页或日志（仅指纹与摘要）。
- F9：禁止引入周期高频 worker（如秒级/分钟级轮询 reclaim）；崩溃恢复只靠 BackgroundTasks + 启动对账。
- F10：禁止自创营销话术写死在代码或迁移 seed；回访话术来自 `ReturnVisitPrompt.template_text`（管理员编辑），LLM 故障兜底用 `fallback_message`（管理员编辑）。

---

## 3. 端到端数据流

### 3.1 主链路（完整发送路径，自动测试替换网络）

```
派单通知下发（auto_wechat → 主机微信 → 销售）
        │  记录 lead_notifications 锚点
        ▼
销售在微信回复（主机微信出现 sender=friend 新文本）
        │  Local Agent 只读检测读取销售新文本 → 回写 9000
        ▼
9000 回访触发预筛
        │  锚点校验：存在已下发派单通知
        │  场景预筛：sender=friend + 派单通知之后（C3）
        │  幂等预检：idempotency_key UNIQUE + 会话级 24h（C8）
        ▼
持久化 ReturnVisitRun（send_status=pending_judgement，trigger_text 存原文摘要、trigger_message_fp 存 sha256 指纹）
        │  ★ 持久化即返回 run_id，不阻塞 Local Agent（C5）
        ▼
FastAPI BackgroundTasks 异步触发判定（send_status=processing）
        │
        ▼  调用 9100 严格判定协议（judge_return_visit）
9100 LLM 判定（LLM 优先，关键字兜底，C7）
        │  输出：prompt_key / confidence(0-1) / should_trigger / suggested_message / decision_source
        │  多场景命中 → ambiguous，不发送（status=not_needed 或 blocked，见 5.5）
        ▼
判定结果分流
        │  未命中 → not_needed
        │  命中但 confidence < 阈值 → confidence_low
        │  场景 prompt disabled → prompt_disabled
        │  命中且 confidence >= 阈值 → 继续
        ▼
门禁检查（C-安全版，C9，见第 7 节）
        │  抖音 env 总熔断 / DB real_send_enabled / 限频 / 上下文 / 商户隔离 / 违禁词 / 失败回写
        │  任一不过 → blocked / rate_limited，failure_stage 记录
        ▼
生成话术：取 ReturnVisitPrompt.template_text（LLM 可基于模板生成 generated_content）
        ▼
违禁词替换（replace_forbidden_words，source=return_visit，master plan 行 196）
        │  → final_content
        ▼
调用抖音发送服务（ai_auto_reply_send_service 既有路径，send_source=return_visit）
        │  ★ 完整真实发送代码路径（C12）；自动测试中此调用被桩替换
        ▼
写 douyin_private_message_sends（return_visit_run_id UNIQUE 防重，镜像 auto_reply_run_id 模式）
        ▼
结果回写 ReturnVisitRun
        │  OpenAPI code=0 → send_status=sent，send_id=upstream msg_id
        │  结果不确定（超时/响应不可解析）→ send_status=send_unknown（禁止重发，C10）
        │  明确失败 → send_status=failed，error_message
```

### 3.2 关键边界

- 锚点：每个 `ReturnVisitRun` 必须关联一个已下发的派单通知记录（`lead_notifications`）与可用 `send_msg context`（master plan 行 496：需要存在可用 send_msg context，否则只记录不能发送）。
- 文本来源：销售回复文本由 Local Agent 只读检测链路回写，Phase 9 不新增微信读取逻辑，不依赖 Qt 文件气泡识别（与 Phase 8-B 的 Qt UIA 限制无关）。
- 异步边界：持久化 `ReturnVisitRun` 的调用立即返回 `run_id`；LLM 判定、门禁、发送在 BackgroundTasks 内完成，失败回写 `error_message` + `last_failure_stage`。
- 真实发送边界：发送代码路径完整实现并接入既有 `ai_auto_reply_send_service`；本阶段所有自动测试以桩替换抖音 OpenAPI HTTP 调用，真实网络调用数为 0（C12）。宝塔生产环境真实验证后置。

---

## 4. 数据模型增量与状态机（ALTER 既有表）

### 4.1 既有表 `return_visit_prompts`（不重建，ALTER 增量）

既有字段（`models.py:921`，迁移 0027/0008 已建）：`id / prompt_key(UNIQUE) / name / scene_type / template_text / scope='global' / enabled / sort_order / created_at / updated_at`。

既有 seed（迁移 0027 行 384-394 / 0008 行 368-381，冻结，不改动）：

| prompt_key | name | scene_type | sort_order |
|------------|------|------------|------------|
| `retain_contact_conversion` | 留资转化回访 | `retain_conversion` | 1 |
| `finance_plan_followup` | 金融方案回访 | `finance_followup` | 2 |
| `silent_customer_wakeup` | 沉默客户唤醒 | `wakeup` | 3 |

Phase 9 增量字段（ALTER ADD COLUMN）：

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| confidence_threshold | FLOAT | NOT NULL DEFAULT 0.90 | 场景置信度阈值，范围 0.50～1.00（C6） |
| fallback_message | TEXT | NULL | LLM 故障且无 template_text 可生成时的兜底文案，管理员可编辑（C7） |

Seed 补充（迁移内 UPDATE 三行）：`confidence_threshold=0.90`；`fallback_message` 初始为场景语义占位（如 `[留资转化回访] 兜底话术，请管理员编辑`），**不写死营销文案**（F10），真实话术由管理员在 `/admin/return-visit-prompts` 编辑。

### 4.2 既有表 `return_visit_runs`（不重建，ALTER 增量）

既有字段（`models.py:941`，迁移 0027 行 127-145 / 0008 已建）：`id / merchant_id / lead_id / staff_id / reply_check_id / prompt_key / trigger_source / trigger_text / judgement_source / judgement_result / generated_content / final_content / send_status / send_id / error_message / created_at / updated_at`。

Phase 9 增量字段（ALTER ADD COLUMN）：

| 分组 | 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|------|
| 触发键 | dispatch_notification_id | INTEGER | NULL | 派单通知锚点（lead_notifications.id） |
| 触发键 | trigger_message_fp | VARCHAR(64) | NULL | 销售回复原文 sha256 指纹（脱敏，不存原文于日志） |
| 触发键 | idempotency_key | VARCHAR(128) | UNIQUE | 消息级永久幂等键（C8） |
| 抖音上下文 | douyin_account_id | INTEGER | NULL | 发送所需抖音账号 |
| 抖音上下文 | conversation_short_id | VARCHAR(255) | NULL | 抖音会话短 ID |
| 抖音上下文 | customer_open_id | VARCHAR(255) | NULL | 客户 open_id |
| 判定 | confidence | FLOAT | NULL | LLM/关键字置信度，范围 0～1（C6） |
| 判定 | decision_source | VARCHAR(16) | NULL | llm / keyword_fallback |
| 判定 | llm_raw_status | VARCHAR(16) | NULL | completed / failed / not_configured |
| 判定 | ambiguous_hit | BOOLEAN | NOT NULL DEFAULT 0 | 多场景命中标记（命中即不发送，C7） |
| 门禁 | gate_results_json | TEXT | NULL | 各门禁通过/拦截摘要 JSON |
| 门禁 | last_failure_stage | VARCHAR(100) | NULL | 最近失败阶段码 |
| 门禁 | manual_takeover | BOOLEAN | NOT NULL DEFAULT 0 | 人工接管标记 |
| 租约 | lease_owner | VARCHAR(64) | NULL | BackgroundTasks owner（用于僵尸对账） |
| 租约 | lease_expires_at | DATETIME | NULL | 租约过期时间 |
| 租约 | attempt_count | INTEGER | NOT NULL DEFAULT 0 | 判定尝试次数 |
| 租约 | last_run_at | DATETIME | NULL | 会话级 24h 冷却判据（C8） |

索引增量：
- UNIQUE(idempotency_key)（SQLite 需安全重建，PG 用 `ALTER TABLE ADD CONSTRAINT`）
- INDEX(dispatch_notification_id)
- INDEX(merchant_id, prompt_key, last_run_at)（会话级冷却查询）

`idempotency_key = sha256(merchant_id + ":" + lead_id + ":" + trigger_message_fp + ":" + prompt_key)`

### 4.3 既有表 `douyin_private_message_sends`（不重建，ALTER 增量）

既有字段（`models.py:361`）：已有 `auto_reply_run_id INTEGER UNIQUE`（自动回复防重模式）。Phase 9 增量：

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| return_visit_run_id | INTEGER | UNIQUE | 回访 run ID，用于防重复发送（镜像 auto_reply_run_id 模式） |

索引：UNIQUE(return_visit_run_id)（SQLite 安全重建 / PG ADD CONSTRAINT）。

### 4.4 状态机（`return_visit_runs.send_status`，复用既有字段，扩充取值）

11 态（C10）：

```
pending_judgement ──BackgroundTasks claim──▶ processing
                                                 │
          ┌──────────┬──────────┬──────────┬─────┴──────┬──────────┐
          ▼          ▼          ▼          ▼            ▼          ▼
      not_needed  confidence_low prompt_disabled rate_limited blocked  send_authorized
      (未命中)    (置信度低)    (场景禁用)     (24h/商户限频)(门禁)   (话术生成+门禁过)
                                                                           │
                                                              ┌────────────┴────────────┐
                                                              ▼                         ▼
                                                           sent                    send_unknown
                                                       (OpenAPI code=0)        (结果不确定，禁重发)

failed：LLM/系统/发送明确失败（终态，启动对账可写入）
```

- 终态（不可重试）：`not_needed` / `sent` / `send_unknown` / `failed`。
- 可由新消息重新触发新 run：`confidence_low` / `prompt_disabled` / `rate_limited` / `blocked`（旧 run 保留，新 run 受幂等与会话冷却约束）。
- `send_status` 既有字段语义扩充为"回访 run 生命周期状态"，`send_id` 仍记录抖音 upstream msg_id（sent 时）。

### 4.5 与 ReplyCheck 的关系（C4 解耦）

- `return_visit_runs.reply_check_id` 可空，仅作软关联，不参与触发判定。
- 回访触发只看：派单通知锚点 + 派单通知之后的 `sender=friend` 新文本 + 关键字/LLM 判定（master plan 行 396-398）。
- `ReplyCheck.check_status`（pending/replied/timeout/invalid）的任何取值都不阻断也不触发回访。

---

## 5. 9100 严格判定协议

### 5.1 协议入口

复用 `apps/xg_douyin_ai_cs/services/reply_decision_service.py` 既有 LLM 客户端（`OpenAICompatibleClient`，`/chat/completions`），新增 Phase 9 专用判定函数 `judge_return_visit(request) -> ReturnVisitJudgment`。

### 5.2 输入

```
ReturnVisitJudgeRequest:
  tenant_id: str
  merchant_id: str
  douyin_account_id: int
  lead_id: int
  prompts: dict[prompt_key, {template_text, fallback_message, confidence_threshold, enabled}]
  sales_reply_text: str          # 仅传入 9100 内存，不落盘
  dispatch_context: dict          # 派单通知锚点摘要（车型/线索来源等，用于话术生成）
```

### 5.3 输出

```
ReturnVisitJudgment:
  prompt_key: str | None          # 命中场景 key，None 表示未命中/ambiguous
  confidence: float               # 0～1（C6）
  should_trigger: bool
  suggested_message: str | None
  decision_source: str            # llm / keyword_fallback
  llm_raw_status: str             # completed / failed / not_configured
  ambiguous: bool                 # 多场景命中标记（C7）
  reason_code: str                # 受控原因码，不携带原文
```

### 5.4 判定顺序（严格，LLM 优先）

1. **LLM 优先**：调用 LLM，`llm_raw_status`：
   - `completed`：取 LLM 输出 `prompt_key` + `confidence`（0～1）。
     - 多场景同时命中 → `ambiguous=true`，`should_trigger=false`（C7，不发送）。
     - 单场景命中且 `confidence >= prompts[key].confidence_threshold` → 命中，`suggested_message` 用 LLM 基于 `template_text` 生成，`decision_source=llm`。
     - 单场景命中但 `confidence < 阈值` → `should_trigger=false`，`reason_code=llm_below_threshold`。
     - 未命中 → `prompt_key=None`，`reason_code=llm_no_match`。
   - `failed`（LLM 异常/超时/格式错误）：进入步骤 2。
   - `not_configured`（未配置 LLM）：进入步骤 2。
2. **关键字兜底**（仅 LLM `failed` / `not_configured` 时，C7；master plan 行 498-499）：
   - 关键字**固定在代码常量**（`app/services/return_visit_run_service.py` 模块级，不入 DB，不前端可编辑）。
   - **否定语义优先**：先匹配否定关键字（如"手机号不对"），再匹配肯定关键字。
   - 多场景同时命中 → `ambiguous=true`，`should_trigger=false`（C7，不发送）。
   - 单场景命中 → `confidence=0.5`（兜底固定置信度，需 ≥ 阈值 0.50 才触发），`suggested_message=prompts[key].fallback_message`，`decision_source=keyword_fallback`。
   - 全未命中 → `prompt_key=None`，`reason_code=keyword_no_match`。

### 5.5 关键字与判定结果到状态的映射

| 判定结果 | send_status |
|----------|-------------|
| 未命中（llm_no_match / keyword_no_match） | `not_needed` |
| 命中但 confidence < 阈值 | `confidence_low` |
| 场景 prompt.enabled=false | `prompt_disabled` |
| ambiguous（多场景命中） | `not_needed`（reason_code=ambiguous_hit） |
| 命中且过门禁 → 发送 | `send_authorized → sent / send_unknown / failed` |
| 门禁拦截 | `blocked / rate_limited` |

### 5.6 严格性约束

- LLM 输出必须为受控结构（prompt_key 枚举 + confidence 数值 0～1 + should_trigger 布尔 + 话术字符串）；解析失败视为 `failed`。
- `reason_code` 为受控枚举（`llm_below_threshold` / `llm_no_match` / `keyword_no_match` / `ambiguous_hit` / `llm_completed` / `llm_failed` / `llm_not_configured` / `prompt_disabled`），不携带销售回复原文。
- 9100 内部日志只记 `lead_id` / `prompt_key` / `confidence` / `decision_source` / `llm_raw_status` / `reason_code`，不记原文。

---

## 6. 关键字与回访话术

### 6.1 关键字（固定在代码，C7）

关键字**不存数据库、不前端可编辑**，定义在 `app/services/return_visit_run_service.py` 模块级常量。初始集合基于 master plan Phase 9 Step 2 已批准样例（行 492-495）：

| prompt_key | 否定关键字（优先） | 肯定关键字 |
|------------|--------------------|------------|
| `retain_contact_conversion` | `手机号不对`、`号码错了`、`联系方式不对` | `留资`、`电话`、`加微信` |
| `finance_plan_followup` | `金融方案不合适`、`首付太高`、`月供太高` | `金融方案`、`贷款`、`分期`、`首付`、`月供` |
| `silent_customer_wakeup` | `客户长期未回复`、`联系不上`、`失联`、`不回消息` | （沉默场景以否定语义为主） |

匹配规则（C7）：
- 否定语义优先：先扫否定关键字，命中即归类对应场景，不再扫肯定关键字。
- 多场景同时命中（跨 prompt_key）→ `ambiguous=true`，**不发送**（C7），记 `not_needed / ambiguous_hit`。
- 关键字集合为代码常量，调整需走代码评审 + 提交，不在管理页暴露。

### 6.2 回访话术（template_text + fallback_message，管理员编辑）

- **正常话术**：`ReturnVisitPrompt.template_text`（既有字段）。LLM 命中场景后，基于该模板生成 `generated_content`，经违禁词替换得 `final_content` 发送。
- **兜底话术**：`ReturnVisitPrompt.fallback_message`（Phase 9 增量字段）。LLM `failed/not_configured` 且关键字命中时使用。
- **编辑入口**：`/admin/return-visit-prompts`（权限 `auto_wechat:admin:return_visit_prompts`）。
- **不写死营销文案**：迁移 seed 的 `template_text` 沿用既有占位（行 385/389/393），`fallback_message` 初始为场景语义占位，真实话术由管理员编辑（F10）。
- **长度与安全**：`template_text` / `fallback_message` 长度上限 500 字符；提交时过违禁词替换预检（不替换，仅告警，命中记 `forbidden_word_hit_logs` source=`return_visit_prompt_edit`）。

---

## 7. 真实发送门禁（C-安全版，C9）

完整实现真实发送代码路径（C12），自动测试替换网络。采用 C-安全版：不使用账号/客户灰度白名单，熔断使用**抖音 env 总熔断 + DB 全局 real_send_enabled**（不使用微信 `is_automation_allowed`）。

| 序 | 门禁 | 不过处置 | 说明 |
|----|------|----------|------|
| G1 | 抖音 env 总熔断（既有 autoreply kill switch） | blocked / env_kill_switch | 抖音侧全局熔断 |
| G2 | DB 全局真实发送开关 `AutoReplyRolloutConfig.real_send_enabled`（scope=global） | blocked / real_send_disabled | 数据库全局真实发送开关（C9） |
| G3 | 商户隔离 `merchant_id` 校验 | blocked / cross_merchant | 跨商户不可见 |
| G4 | 违禁词替换 `replace_forbidden_words`（source=`return_visit`，master plan 行 196） | 替换后仍命中严重词 → blocked / forbidden_word | 调用 OpenAPI 前替换 |
| G5 | 限频（商户级窗口 + 会话级 24h `last_run_at`） | rate_limited | 会话级冷却 |
| G6 | 上下文完整性（派单通知锚点 + send_msg context 可用） | blocked / context_incomplete | master plan 行 496 |
| G7 | 失败回写（`last_failure_stage` + `error_message`） | failed / 对应 stage | 所有失败回写原因 |
| G8 | 消息级幂等 `idempotency_key` UNIQUE | 跳过（返回既有 run） | 同消息同场景永久幂等（C8） |
| G9 | 会话级幂等 24h（`last_run_at` + cooldown） | rate_limited / session_cooldown | 同会话每场景 24h 最多一次（C8） |
| G10 | LLM/关键字 confidence ≥ `confidence_threshold` | confidence_low | 见第 5 节 |
| G11 | 话术安全（`final_content` 非空 + 违禁词替换后非空 + 长度合规） | blocked / message_invalid | |
| G12 | `send_authorized → send_unknown` 禁重发 | send_unknown 终态 | 结果不确定时进入，禁止重发（C10） |

明确排除（C-安全版不检查）：
- 账号级灰度白名单
- 客户级灰度白名单
- 微信 `is_automation_allowed`（回访走抖音发送，不走微信自动化）

---

## 8. 管理 API 与前端设计

### 8.1 管理 API（C11）

所有接口要求权限码 `auto_wechat:admin:return_visit_prompts`（master plan 行 134），跨商户统一 404。

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/admin/return-visit-prompts` | 列出三场景全局提示词（含 template_text / fallback_message / confidence_threshold / enabled） |
| PUT | `/admin/return-visit-prompts/{prompt_key}` | 编辑单场景（template_text / fallback_message / confidence_threshold / enabled）；不提供重试/立即发送 |
| GET | `/admin/return-visit-runs` | 只读运行记录列表（分页，按 send_status / prompt_key / decision_source 筛选） |
| GET | `/admin/return-visit-runs/{id}` | 只读单条运行记录详情 |
| GET | `/admin/return-visit-runs/stats` | 统计聚合（按场景/状态/决策来源） |

明确不提供（C11）：
- 不提供 `POST /admin/return-visit-runs/{id}/retry`。
- 不提供 `POST /admin/return-visit-runs/{id}/send`。
- 不提供任何触发立即发送或重试的写接口。

响应脱敏：
- 不返回销售回复原文（`trigger_text` 在 API 响应中只返回长度摘要，不返回原文；`trigger_message_fp` 返回 sha256 指纹）。
- 不返回客户手机号；`customer_open_id` 仅在详情接口返回（供审计）。
- `generated_content` / `final_content` 在详情接口可见（供审计），列表接口不返回。

### 8.2 前端设计

复用既有超管后台导航（`auto_wechat:admin:return_visit_prompts` 权限码已在 NewCar 权限映射中登记），新增：
1. **回访提示词配置页**：三场景卡片，每卡可编辑 `template_text` / `fallback_message`（文本框）/ `confidence_threshold`（滑块 0.50～1.00）/ `enabled`。提交调 PUT，变更显示违禁词预检告警。
2. **回访运行记录页（只读）**：列表（prompt_key / send_status / decision_source / confidence / last_failure_stage / created_at），详情抽屉（含 generated_content / final_content / trigger_message_fp 指纹 / llm_raw_status / reason_code / gate_results_json）。不提供重试/立即发送按钮。

前端约束：
- 列表与详情均不渲染销售回复原文、客户手机号。
- 配置变更前后端二次校验 `confidence_threshold ∈ [0.50, 1.00]`、`template_text` / `fallback_message` 长度 ≤ 500。

---

## 9. 崩溃恢复和幂等规则

### 9.1 崩溃恢复（BackgroundTasks + 启动对账，C5，无周期高频 worker）

- **持久化优先**：触发判定在持久化 `ReturnVisitRun(send_status=pending_judgement)` 后立即返回 `run_id`，不等待 LLM。Local Agent 不阻塞。
- **BackgroundTasks 触发**：FastAPI BackgroundTasks 内执行 claim（`UPDATE ... SET send_status='processing', lease_owner=:owner, lease_expires_at=:exp WHERE id=:id AND send_status='pending_judgement'`，`affected_rows=1` 才继续）→ 判定 → 门禁 → 发送。
- **启动对账（唯一 reclaim 路径）**：服务启动时执行一次 `UPDATE return_visit_runs SET send_status='failed', last_failure_stage='lease_stale_on_boot' WHERE send_status='processing' AND lease_expires_at < NOW()`，把上次崩溃遗留的僵尸 run 标记 failed。**不引入周期高频 worker**（F9）。
- **不自动重试**：`processing` 崩溃后不自动重新入队；由新消息触发新 run（受幂等与会话冷却约束）。
- `attempt_count` 仅记录判定尝试次数，不作为重试依据。

### 9.2 幂等规则（C8）

- **消息级永久幂等**：`idempotency_key = sha256(merchant_id + ":" + lead_id + ":" + trigger_message_fp + ":" + prompt_key)`，UNIQUE 约束。INSERT 冲突直接返回既有 run，不重复判定、不重复发送。
- **会话级 24h 幂等**：同一 `(lead_id, prompt_key)` 组合，若存在 `last_run_at >= NOW() - 86400` 的非 `failed/blocked/not_needed` run，则新触发 `rate_limited / session_cooldown`。
- **判定顺序**：先查消息级 `idempotency_key`（永久），再查会话级冷却（24h）。两者都过才创建新 run。
- **失败 run 不计入冷却**：`failed` / `blocked` / `not_needed` / `confidence_low` / `prompt_disabled` 的 run 不更新会话级冷却窗口，允许配置/熔断恢复后由新消息重新触发。

---

## 10. SQLite `0030` / PostgreSQL `0011` 迁移边界（ALTER 既有表）

### 10.1 SQLite `0030_return_visit_phase9.py`

**不重复建表**（F1）。所有改动为 ALTER 或安全重建既有表：

1. `return_visit_prompts` 增量（直接 ALTER ADD COLUMN，SQLite 支持）：
   - `ALTER TABLE return_visit_prompts ADD COLUMN confidence_threshold FLOAT NOT NULL DEFAULT 0.90`
   - `ALTER TABLE return_visit_prompts ADD COLUMN fallback_message TEXT`
   - UPDATE 三场景 seed：`fallback_message` = 场景语义占位（不写死营销文案，F10）。
2. `return_visit_runs` 增量（多数字段直接 ALTER ADD COLUMN；`idempotency_key UNIQUE` 需安全重建）：
   - 直接 ADD COLUMN：`dispatch_notification_id / trigger_message_fp / douyin_account_id / conversation_short_id / customer_open_id / confidence / decision_source / llm_raw_status / ambiguous_hit / gate_results_json / last_failure_stage / manual_takeover / lease_owner / lease_expires_at / attempt_count / last_run_at`。
   - `idempotency_key` UNIQUE + 索引：SQLite 无法直接 ADD UNIQUE CONSTRAINT，采用**安全重建模式**（复用 0028/0029 `_backup/_new/_guard` 事务内重建）：CREATE `_new`（含全部旧列 + 新列 + idempotency_key + UNIQUE + 索引）→ INSERT SELECT 旧数据（idempotency_key 由迁移内按公式回填或留空，运行时新建 run 时计算）→ 行数 + max(id) + 双向 GROUP BY 守卫 → RENAME 旧为 `_backup`、`_new` 为正式 → DROP `_backup`。CHECK 违反触发 ROLLBACK 不登记 0030。
3. `douyin_private_message_sends` 增量（`return_visit_run_id UNIQUE`）：
   - 安全重建模式同上（既有 `auto_reply_run_id UNIQUE` 已存在，新增 `return_visit_run_id` 列 + UNIQUE 约束），或若 SQLite 版本支持 `ALTER TABLE ADD COLUMN` + 后置 CREATE UNIQUE INDEX（空列场景可直接建索引）。迁移内选择安全重建以保持与既有模式一致。
4. 守卫：复用 0028/0029 多重集守卫（表存在性 + 列存在性 + seed 行数 = 3 + CHECK），失败整体 ROLLBACK 不登记 0030。
5. 幂等：所有 ALTER 用 try/except 包裹检测列已存在则跳过；seed UPDATE 用 `WHERE fallback_message IS NULL` 或版本守卫。runner 已登记版本时整体跳过。

### 10.2 PostgreSQL `0011_return_visit_phase9.py`

**不重复建表**（F1）。PG 支持 `ALTER TABLE ADD COLUMN` + `ADD CONSTRAINT`：

1. `return_visit_prompts`：
   - `ALTER TABLE return_visit_prompts ADD COLUMN confidence_threshold FLOAT NOT NULL DEFAULT 0.90`
   - `ALTER TABLE return_visit_prompts ADD COLUMN fallback_message TEXT`
   - UPDATE 三场景 seed（同 10.1）。
2. `return_visit_runs`：
   - `ALTER TABLE ... ADD COLUMN` 全部新列。
   - `ALTER TABLE return_visit_runs ADD CONSTRAINT uk_return_visit_runs_idempotency_key UNIQUE (idempotency_key)`
   - `CREATE INDEX IF NOT EXISTS idx_return_visit_runs_dispatch ON return_visit_runs(dispatch_notification_id)`
   - `CREATE INDEX IF NOT EXISTS idx_return_visit_runs_session_cooldown ON return_visit_runs(merchant_id, prompt_key, last_run_at)`
3. `douyin_private_message_sends`：
   - `ALTER TABLE douyin_private_message_sends ADD COLUMN return_visit_run_id INTEGER`
   - `ALTER TABLE douyin_private_message_sends ADD CONSTRAINT uk_douyin_private_message_sends_return_visit_run_id UNIQUE (return_visit_run_id)`
4. 权限：`GRANT SELECT, INSERT, UPDATE, DELETE` 已在 0008 对既有表授予，0011 增量列无需额外授权（表级权限覆盖列）。
5. 幂等：所有 ALTER 用 `IF NOT EXISTS` 检测（PG 14+ 支持 `ADD COLUMN IF NOT EXISTS`）；约束用 `DO $$ BEGIN ... IF NOT EXISTS ... END $$` 守卫。

### 10.3 迁移边界（硬约束）

- 仅 ALTER 或安全重建既有 3 表 + seed UPDATE，**不创建新表**（F1）。
- 不修改既有列类型/约束（`send_status` 字段保留，仅扩充取值语义）。
- 字段定义在 SQLite 与 PostgreSQL 之间保持一致（FLOAT/TEXT/INTEGER 类型一致；无 JSONB 需求，`gate_results_json` 用 TEXT 存 JSON 字符串）。
- 回滚（downgrade）：
  - SQLite：安全重建去掉新列（或保留新列仅清空 seed，因 SQLite DROP COLUMN 兼容性差，downgrade 以"新增列保留空值 + 回滚 seed"为最小方案，注明 ceiling）。
  - PG：`ALTER TABLE ... DROP COLUMN ...` + `DROP CONSTRAINT ...` + 回滚 seed。
- 迁移测试：ALTER + 新列存在 + UNIQUE 约束生效 + seed 行数 = 3 + 与 0029/0010 共存 + 回滚（见第 11 节）。

---

## 11. 自动化测试矩阵

### 11.1 真实网络调用为零（C12 硬约束）

- 所有抖音 OpenAPI HTTP 调用（`ai_auto_reply_send_service` 内的发送请求）在测试中以桩/monkeypatch 替换，真实网络调用数 = 0。
- 测试断言：发送服务被调用次数、调用参数（send_source=`return_visit`、conversation/customer open_id、final_content 违禁词替换后）、写 `douyin_private_message_sends` 行（return_visit_run_id UNIQUE）。
- 禁止任何测试命中真实 `open.douyin.com` 或生产回调。

### 11.2 9100 判定协议单元测试

| 用例 | 期望 |
|------|------|
| LLM completed + 单场景 + confidence >= 阈值 | decision_source=llm，suggested_message 基于 template_text |
| LLM completed + confidence < 阈值 | should_trigger=false，reason_code=llm_below_threshold |
| LLM failed → 否定关键字命中 retain_contact_conversion | decision_source=keyword_fallback，confidence=0.5，suggested_message=fallback_message |
| LLM not_configured → 关键字全未命中 | should_trigger=false，reason_code=keyword_no_match |
| LLM 输出格式错误 | 视为 failed → 关键字兜底 |
| 多场景同时命中（ambiguous） | ambiguous=true，should_trigger=false |
| 否定关键字优先于肯定关键字 | 归类否定场景 |

### 11.3 幂等与状态机单元测试

| 用例 | 期望 |
|------|------|
| 同 idempotency_key 第二次插入 | 返回既有 run，不重复判定 |
| 会话级 24h 内同 (lead, prompt_key) 再次触发 | rate_limited / session_cooldown |
| failed/not_needed run 不更新会话冷却 | 配置恢复后新消息可重新触发 |
| pending_judgement → processing → send_authorized → sent | 状态正确流转 |
| send_authorized → send_unknown | 终态，禁止重发 |
| ambiguous → not_needed | 不发送 |
| prompt disabled → prompt_disabled | 不发送 |
| 启动对账：processing 僵尸 run | 标记 failed / lease_stale_on_boot |

### 11.4 门禁集成测试（C-安全版，G1-G12）

| 用例 | 期望 |
|------|------|
| 抖音 env kill switch 关闭 | blocked / env_kill_switch |
| DB real_send_enabled=false | blocked / real_send_disabled |
| 跨商户读取 | 404 |
| 违禁词替换后仍命中严重词 | blocked / forbidden_word |
| 会话级冷却 | rate_limited / session_cooldown |
| 上下文缺失（无 send_msg context） | blocked / context_incomplete |
| 消息级幂等冲突 | 跳过 |
| 回访话术为空 | blocked / message_invalid |
| 真实发送路径被调用（网络桩） | send_source=return_visit，写 douyin_private_message_sends |
| OpenAPI code=0 | send_status=sent，send_id 记录 |
| OpenAPI 结果不确定 | send_status=send_unknown（禁重发） |
| **不使用**微信 is_automation_allowed | 回访发送不查询微信自动化状态 |
| **不使用**账号/客户白名单 | 回访发送不查询白名单 |

### 11.5 管理 API 测试

| 用例 | 期望 |
|------|------|
| GET /admin/return-visit-prompts 返回三场景 | 200，含 template_text/fallback_message/confidence_threshold |
| PUT /admin/return-visit-prompts/{key} | 200，违禁词预检告警 |
| PUT confidence_threshold=0.3 | 422（越界，范围 0.50-1.00） |
| PUT fallback_message 超 500 字 | 422 |
| GET /admin/return-visit-runs 列表不返回原文 | 无 trigger_text 原文 |
| GET /admin/return-visit-runs/{id} 详情含 final_content | 200 |
| 不提供 retry / send 接口 | 路由不存在（404/405） |
| 跨商户 GET runs/{id} | 404 |
| 权限码 auto_wechat:admin:return_visit_prompts 校验 | 无权限 403 |

### 11.6 迁移测试

| 用例 | 期望 |
|------|------|
| SQLite 0030 ALTER + 新列存在 + UNIQUE | 迁移后列与约束存在 |
| SQLite 0030 安全重建 idempotency_key UNIQUE | 数据保留，行数/max(id) 守卫通过 |
| SQLite 0030 seed UPDATE 三场景 fallback_message | 行数 = 3 |
| SQLite 0030 与 0029 共存 | 迁移链不中断 |
| PG 0011 ALTER + ADD CONSTRAINT | 约束存在，可重入 |
| PG 0011 回滚 | 新列/约束删除，seed 回滚 |

### 11.7 端到端闭环测试（网络桩）

| 用例 | 期望 |
|------|------|
| 派单通知 → 销售回复"手机号不对" → 持久化 → 异步判定 → send_authorized → 发送桩 → sent | 全链路通过，真实网络=0 |
| 三场景分别命中（关键字样例） | 各场景 prompt_key 正确 |
| 销售回复未命中 | not_needed |
| ReplyCheck.check_status=timeout 时仍可触发回访 | 解耦验证（C4） |
| 服务重启后 processing 僵尸 run | failed / lease_stale_on_boot |

---

## 12. 宝塔真实验证后置说明（C12）

- 本阶段所有回访发送在自动测试中以桩替换抖音 OpenAPI 调用，真实网络调用数为 0。
- **真实抖音发送代码路径完整实现并接入既有 `ai_auto_reply_send_service`**（master plan 行 502-506），只是未在宝塔生产环境真实验证。
- 宝塔生产验证后置内容：
  - 宝塔环境部署（账号鉴权 / env 熔断 / `AutoReplyRolloutConfig.real_send_enabled` 开启 / 限频配置 / 违禁词服务 / 监控）。
  - `send_authorized → 真实抖音 im_send_msg` 的生产观测与告警。
  - `send_unknown` 与 `sent` 的生产分布观测。
- 后置不阻塞：Phase 9 验收以"代码与自动测试闭环 DONE"为准，`baota_production_send_not_verified` 作为唯一 concern 记录，不在本阶段消除。
- 宝塔真实发送验证需另开执行包 + 走生产检查点，不得复用本设计文档直接开启真实发送。

---

## 13. 风险与最终状态口径

### 13.1 风险

| 风险 | 等级 | 缓解 |
|------|------|------|
| `baota_production_send_not_verified` | 中 | 唯一 concern；真实发送代码路径已实现，宝塔验证另开执行包 |
| LLM 故障导致关键字兜底覆盖率不足 | 中 | 关键字基于 master plan 已批准样例；管理页可观测 decision_source 分布 |
| BackgroundTasks 进程内崩溃丢失 in-flight run | 低 | 启动对账回收僵尸 run；持久化保证不丢已落盘 run |
| Qt 微信 UIA 文件气泡限制影响回访 | 无 | Phase 9 锚定 sender=friend 文本读取，不依赖文件气泡识别（与 Phase 8-B 限制正交） |
| 配置误改导致回访风暴 | 中 | 会话级 24h 冷却 + 商户级限频 + DB real_send_enabled + env kill switch + 管理页无立即发送 |

### 13.2 最终状态口径（冻结）

| 项目 | 状态 |
|------|------|
| Phase 9 代码与自动测试闭环 | `DONE` |
| Phase 9 | `DONE_WITH_CONCERNS`（唯一 concern = `baota_production_send_not_verified`） |
| Phase 8-B | `PARTIAL_BLOCKED_DEFERRED`（不恢复，Qt UIA 子控件树空，转 verify_pending 人工审计受控方案） |
| Phase 11 一键过审 | `CANCELLED_BY_CUSTOMER`（不恢复，仅同步路线图不删历史） |
| Task 8（日报真实分发） | `NOT_STARTED` |
| 真实抖音回访发送（宝塔验证） | 后置（另开执行包 + 生产检查点） |

### 13.3 自检（术语 / 状态 / 阈值 / 限频 / 验收一致性）

- 三场景固定键：`retain_contact_conversion` / `finance_plan_followup` / `silent_customer_wakeup`（与 0027/0008 seed、master plan 一致），全文一致。
- 状态机 11 态：`pending_judgement / processing / not_needed / confidence_low / prompt_disabled / rate_limited / blocked / send_authorized / sent / send_unknown / failed`（C10），全文一致。
- LLM 输出 `confidence` 范围 `0～1`；配置 `confidence_threshold` 范围 `0.50～1.00`，初始 `0.90`（C6），全文一致。
- 会话级冷却：`24h = 86400s`（C8），全文一致。
- `decision_source`：`llm` / `keyword_fallback`（C7）。
- `llm_raw_status`：`completed` / `failed` / `not_configured`，与既有 9100 reply_decision_service 一致。
- 熔断：抖音 env kill switch + `AutoReplyRolloutConfig.real_send_enabled`（C9），**不使用**微信 `is_automation_allowed`、**不使用**账号/客户白名单，全文一致。
- 关键字固定代码、否定语义优先、多场景命中 ambiguous 不发送（C7），全文一致。
- 权限码 `auto_wechat:admin:return_visit_prompts`（C11），与 master plan 行 134 + NewCar 权限映射一致。
- API 路径：`/admin/return-visit-prompts` + `/admin/return-visit-runs`（C11）。
- 模型契约：复用既有 `ReturnVisitPrompt` / `ReturnVisitRun` / `DouyinPrivateMessageSend`，迁移仅 ALTER/安全重建，**不新建表**（F1）。
- 真实发送代码路径完整实现，自动测试 OpenAPI 调用全部替换，真实网络调用为 0（C12）。
- 验收：代码与自动测试闭环 `DONE`，Phase 9 `DONE_WITH_CONCERNS`，唯一 concern `baota_production_send_not_verified`（C13）。
- 无 `TODO` / `TBD` / 未定义字段。

---

## 附录 A：与既有体系的边界

- `ReturnVisitPrompt`（`app/models.py:921`，迁移 0027/0008 已建）：Phase 9 增量补 `confidence_threshold` / `fallback_message`，不重建表。
- `ReturnVisitRun`（`app/models.py:941`，迁移 0027/0008 已建）：Phase 9 增量补触发键/抖音上下文/判定/门禁/租约字段，`send_status` 扩充 11 态取值，不重建表。
- `DouyinPrivateMessageSend`（`app/models.py:361`）：Phase 9 增量补 `return_visit_run_id UNIQUE`（镜像既有 `auto_reply_run_id` 防重模式）。
- `AutoReplyRolloutConfig`（`app/models.py:514`）：复用 `real_send_enabled`（scope=global）作为 DB 全局真实发送开关（C9），不新增字段。
- 9100 LLM（`apps/xg_douyin_ai_cs/services/reply_decision_service.py`）：复用 `OpenAICompatibleClient` 与 `/chat/completions`，新增 `judge_return_visit` 不改动既有 `build_reply_suggestion`。
- 违禁词替换（`replace_forbidden_words`）：回访发送调用 OpenAPI 前替换，source=`return_visit`（master plan 行 196）。
- 抖音发送（`ai_auto_reply_send_service`）：复用既有路径，send_source=`return_visit`。
- 迁移：SQLite 0030 接续 0029；PostgreSQL 0011 接续 0010。

## 附录 B：后续执行包拆分建议（仅供参考，不在本设计范围）

1. 迁移：SQLite 0030 / PG 0011（ALTER + 安全重建 + seed UPDATE）。
2. 9100 `judge_return_visit` 判定协议 + 代码常量关键字（否定优先 + ambiguous 不发送）。
3. 9000 回访触发 + `ReturnVisitRun` 持久化 + BackgroundTasks 异步判定 + 幂等 + 启动对账。
4. C-安全版 12 项门禁（抖音 env + DB real_send_enabled，不用微信熔断/白名单）。
5. 真实发送路径接入 `ai_auto_reply_send_service` + 写 `douyin_private_message_sends`（return_visit_run_id UNIQUE）。
6. 管理 API + 前端（`/admin/return-visit-prompts` + `/admin/return-visit-runs`，权限 `auto_wechat:admin:return_visit_prompts`）。
7. 测试矩阵落地（11.1～11.7，真实网络调用为 0）。
8. 宝塔真实发送验证（另开执行包 + 生产检查点）。
