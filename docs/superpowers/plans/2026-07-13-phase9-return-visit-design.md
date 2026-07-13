# Phase 9 微信到抖音回访设计（冻结）

- 文档日期：2026-07-13
- 文档性质：冻结设计落盘（仅文档，不含代码改动）
- 验收口径：代码与模拟闭环 `DONE`；Phase 9 `DONE_WITH_CONCERNS`，唯一 concern 为 `baota_production_send_not_verified`
- 关联阶段：Phase 8-B `PARTIAL_BLOCKED_DEFERRED`（不恢复）；Phase 11 一键过审 `CANCELLED_BY_CUSTOMER`（不恢复）
- 关联代码：`app/models.py:103` `ReplyCheck`（check_status: pending/replied/timeout/invalid）；`app/services/daily_report_delivery_service.py:38-46` 投递状态常量；`apps/xg_douyin_ai_cs/services/reply_decision_service.py` LLM 判定

---

## 1. 背景与目标

### 1.1 业务背景

auto_wechat 现有链路：客户在抖音私信留资 → Webhook 入库 → 分配销售 → 通过主机微信向销售下发派单通知 → 销售在微信回复 → ReplyCheck 检测销售是否回复。

Phase 9 在该链路之后增加"回访"能力：当销售在微信侧产生符合特定场景的新回复时，由 9100 的 LLM 判定是否需要通过抖音私信主动回访客户，并生成回访话术。本阶段只做判定与模拟闭环（dry_run），不做真实抖音发送。

### 1.2 目标

1. 锚定派单通知之后销售侧（微信 `sender=friend`）的新文本，作为回访判定的唯一输入信号。
2. 由 9100 LLM 严格判定该文本是否命中三类固定场景之一，并给出置信度与回访话术。
3. 持久化 `ReturnVisitRun` 后异步处理，绝不阻塞 Local Agent 与既有派单/检测链路。
4. 提供管理页用于编辑三场景的提示词（兜底文案 + 关键词 + 置信度阈值）与查看只读运行记录。
5. 完整设计真实发送门禁，但本阶段不执行真实发送；宝塔部署验证后置且不阻塞验收。

### 1.3 冻结结论清单（十三条）

| 编号 | 冻结结论 |
|------|----------|
| C1 | 三类场景固定：留资转化（lead_conversion）、金融方案（finance_plan）、销售反馈触发的沉默唤醒（silent_wake） |
| C2 | 不做抖音会话时间扫描 |
| C3 | 仅锚定派单通知之后的新 `sender=friend` 文本 |
| C4 | ReplyCheck 状态与回访触发解耦 |
| C5 | 持久化 `ReturnVisitRun` 后异步处理，不阻塞 Local Agent |
| C6 | 每场景独立配置置信度 `0.50～1.00`，初始 `0.90` |
| C7 | LLM 优先；仅 LLM 故障时使用保守关键词和可编辑 `fallback_message` |
| C8 | 同一消息永久幂等；同一会话每场景 24 小时最多一次 |
| C9 | 采用 `C-安全版`：不检查账号/客户灰度白名单，但保留总熔断、人工接管、限频、上下文、商户隔离、违禁词、失败回写 |
| C10 | `send_authorized` 后结果不确定时进入 `send_unknown`，禁止重发 |
| C11 | 管理页提供提示词配置与只读运行记录，不提供重试或立即发送 |
| C12 | 本阶段不做真实抖音发送；宝塔部署验证后置且不阻塞 |
| C13 | 验收状态目标：代码与模拟闭环 `DONE`，Phase 9 `DONE_WITH_CONCERNS`，唯一 concern 为 `baota_production_send_not_verified` |

---

## 2. 非目标与禁止事项

### 2.1 非目标

- N1：不扫描抖音会话历史或会话时间序列（C2）。
- N2：不依据 `ReplyCheck.check_status` 触发回访（C4）。回访判定独立于回复检测状态机。
- N3：不在本阶段执行真实抖音私信发送（C12）。
- N4：不在管理页提供"重试""立即发送"等写操作（C11）。
- N5：不做账号级或客户级的灰度白名单判定（C9）。

### 2.2 禁止事项

- F1：禁止绕过 `is_automation_allowed` 总熔断。
- F2：禁止绕过人工接管（`manual_takeover`）标记。
- F3：禁止跨商户读取或写入 `ReturnVisitRun`。
- F4：禁止在 `send_unknown` 状态下重发。
- F5：禁止发送未过违禁词替换的回访话术。
- F6：禁止在 Local Agent 线程内同步执行 LLM 判定（必须持久化后异步）。
- F7：禁止回写原始销售回复正文到管理页或日志（仅指纹）。
- F8：禁止在本阶段修改既有 `wechat_tasks` / `daily_report_deliveries` / `reply_checks` 表结构与状态机。

---

## 3. 端到端数据流

### 3.1 主链路（dry_run 闭环）

```
派单通知下发（auto_wechat → 主机微信 → 销售）
        │
        ▼  记录 dispatch_notification 锚点
销售在微信回复（主机微信出现 sender=friend 新文本）
        │
        ▼  Local Agent 只读检测读取销售新文本
        │   （复用既有回复检测读取链路，不依赖 Qt 文件气泡识别）
        ▼  回写销售回复文本摘要到 9000
9000 回访触发判定
        │  锚点校验：必须存在已下发的派单通知
        │  场景预筛：sender=friend + 派单通知之后
        ▼
持久化 ReturnVisitRun（status=pending，trigger_message_fp=sha256(原文)）
        │  ★ 持久化即返回，不阻塞 Local Agent（C5）
        ▼
异步 worker 取出 pending run（status=pending → running）
        │
        ▼  调用 9100 严格判定协议
9100 LLM 判定
        │  输入：销售回复文本 + 场景配置（阈值/关键词/兜底文案）
        │  输出：scenario / confidence / should_trigger / suggested_message / decision_source
        │  LLM completed → 置信度 >= 阈值 触发
        │  LLM failed/not_configured → 保守关键词兜底
        ▼
门禁检查（C-安全版 7 项保留 + 5 项，共 12 项，见第 7 节）
        │  任一不过 → status=blocked，failure_stage 记录
        ▼
dry_run 授权（status=send_authorized）
        │  生成 intended_message（拟回访话术，落库不发送）
        ▼
结果不确定 → status=send_unknown（禁止重发，C10）
或 模拟完成 → 保留 send_authorized（真实发送需另开执行包）
```

### 3.2 关键边界

- 锚点唯一性：每个 `ReturnVisitRun` 必须关联一个已下发的派单通知记录，无锚点不入链路。
- 文本来源：销售回复文本由 Local Agent 只读检测链路回写，Phase 9 不新增微信读取逻辑，不依赖 Qt 文件气泡识别（与 Phase 8-B 的 Qt UIA 限制无关）。
- 异步边界：持久化 `ReturnVisitRun` 的调用立即返回 `run_id`；LLM 判定与门禁在 worker 内完成，失败回写 `failure_stage`。

---

## 4. 数据模型增量与状态机

### 4.1 新增表 `return_visit_runs`

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | BIGINT | PK, autoincrement | |
| tenant_id | VARCHAR(128) | NOT NULL | 租户（统一知识库 scope） |
| merchant_id | VARCHAR(128) | NOT NULL | 商户隔离键 |
| douyin_account_id | BIGINT | NOT NULL DEFAULT 0 | 抖音账号 |
| lead_id | BIGINT | FK douyin_leads(id) | 线索 |
| staff_id | BIGINT | FK sales_staff(id) | 销售 |
| reply_check_id | BIGINT | FK reply_checks(id), NULL | 关联但不耦合（C4） |
| dispatch_notification_id | BIGINT | NOT NULL | 派单通知锚点 |
| scenario | VARCHAR(32) | NOT NULL | lead_conversion / finance_plan / silent_wake |
| trigger_message_fp | VARCHAR(64) | NOT NULL | sha256(销售回复原文)，脱敏不存原文 |
| confidence | NUMERIC(4,3) | NULL | LLM/关键词置信度，0.500～1.000 |
| decision_source | VARCHAR(16) | NOT NULL | llm / keyword_fallback |
| llm_raw_status | VARCHAR(16) | NULL | completed / failed / not_configured |
| intended_message | TEXT | NULL | 拟回访话术（dry_run 落库不发送） |
| fallback_message_used | BOOLEAN | NOT NULL DEFAULT FALSE | 是否使用了兜底文案 |
| status | VARCHAR(20) | NOT NULL DEFAULT 'pending' | 见 4.3 状态机 |
| send_attempt_count | INT | NOT NULL DEFAULT 0 | |
| last_failure_stage | VARCHAR(100) | NULL | |
| idempotency_key | VARCHAR(128) | NOT NULL, UNIQUE | 消息级永久幂等键 |
| last_run_at | DATETIME | NULL | 会话级 24h 冷却判据 |
| created_at | DATETIME | NOT NULL | |
| updated_at | DATETIME | NOT NULL | |

索引：
- UNIQUE(idempotency_key)
- INDEX(merchant_id, status)
- INDEX(lead_id, scenario, last_run_at) — 会话级冷却查询
- INDEX(dispatch_notification_id)

`idempotency_key = sha256(merchant_id + ":" + lead_id + ":" + trigger_message_fp + ":" + scenario)`

### 4.2 新增表 `return_visit_scenario_configs`

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | BIGINT | PK, autoincrement | |
| merchant_id | VARCHAR(128) | NOT NULL | |
| scenario | VARCHAR(32) | NOT NULL | lead_conversion / finance_plan / silent_wake |
| enabled | BOOLEAN | NOT NULL DEFAULT TRUE | |
| confidence_threshold | NUMERIC(4,3) | NOT NULL DEFAULT 0.900 | 0.500～1.000（C6） |
| fallback_message | TEXT | NOT NULL | 可编辑兜底文案（C7） |
| keywords | JSON / jsonb | NOT NULL DEFAULT '[]' | 保守关键词数组（LLM 故障时用） |
| cooldown_seconds | INT | NOT NULL DEFAULT 86400 | 会话级冷却，默认 24h（C8） |
| created_at | DATETIME | NOT NULL | |
| updated_at | DATETIME | NOT NULL | |

约束：UNIQUE(merchant_id, scenario)

Seed：迁移时为每个已有商户插入三场景默认行（初始 `confidence_threshold=0.900`，三场景冻结 `fallback_message` 与 `keywords` 见第 6 节）。

### 4.3 状态机（`return_visit_runs.status`）

```
pending ──worker claim──▶ running
                            │
            ┌───────────────┼───────────────┐
            ▼               ▼               ▼
        blocked        send_authorized    failed
        (门禁拦截)     (dry_run 授权)     (LLM/系统失败)
                            │
                            ▼
                       send_unknown
                       (结果不确定，禁止重发，C10)

cancelled：仅人工在管理页标记（本阶段管理页不提供写操作，预留状态）
sent：真实发送终态，本阶段不达（C12，预留）
```

状态常量（与既有投递状态机命名风格一致）：
- `STATUS_PENDING = "pending"`
- `STATUS_RUNNING = "running"`
- `STATUS_SEND_AUTHORIZED = "send_authorized"`
- `STATUS_SEND_UNKNOWN = "send_unknown"`（Phase 9 新增）
- `STATUS_SENT = "sent"`（预留，本阶段不达）
- `STATUS_FAILED = "failed"`
- `STATUS_BLOCKED = "blocked"`
- `STATUS_CANCELLED = "cancelled"`（预留）

终态：`send_unknown` / `sent` / `failed`（reclaim_exhausted）/ `cancelled` 不可重试。`blocked` 允许在配置/熔断恢复后由新一轮触发消息重新创建新 run（旧 run 保留）。

### 4.4 与 ReplyCheck 的关系（C4 解耦）

- `return_visit_runs.reply_check_id` 可空，仅作软关联，不参与触发判定。
- 回访触发只看：派单通知锚点 + 派单通知之后的 `sender=friend` 新文本。
- `ReplyCheck.check_status`（pending/replied/timeout/invalid）的任何取值都不阻断也不触发回访。
- 解耦理由：回复检测关心"销售是否在规定时间内回复"，回访关心"销售回复内容是否命中场景"，两者语义不同，避免状态耦合导致回归风险。

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
  scenario_configs: dict[scenario, {threshold, keywords, fallback_message}]
  sales_reply_text: str          # 销售回复原文（仅传入 9100 内存，不落盘）
  dispatch_context: dict          # 派单通知锚点摘要（车型/线索来源等，用于话术生成）
```

### 5.3 输出

```
ReturnVisitJudgment:
  scenario: str | None           # 命中场景，None 表示未命中
  confidence: float              # 0.500～1.000
  should_trigger: bool
  suggested_message: str | None  # LLM 生成的话术（命中时）
  decision_source: str           # llm / keyword_fallback
  llm_raw_status: str            # completed / failed / not_configured
  reason_code: str               # 受控原因码（不携带原文）
```

### 5.4 判定顺序（严格）

1. **LLM 优先**：调用 LLM，`llm_raw_status`：
   - `completed`：取 LLM 输出的 `scenario` + `confidence`。
     - `confidence >= scenario_configs[scenario].confidence_threshold` 且 `should_trigger=true` → 命中，`suggested_message` 用 LLM 输出，`decision_source=llm`。
     - 否则 → 未命中，`scenario=None`，`should_trigger=false`。
   - `failed`（LLM 异常/超时/格式错误）：进入步骤 2。
   - `not_configured`（未配置 LLM）：进入步骤 2。
2. **关键词兜底**（仅 LLM `failed` / `not_configured` 时，C7）：
   - 对每个启用场景，保守关键词匹配（子串命中）。
   - 命中 → `scenario` 取命中场景，`confidence=0.500`（兜底固定置信度），`should_trigger=true`，`suggested_message=scenario_configs[scenario].fallback_message`，`decision_source=keyword_fallback`，`fallback_message_used=true`。
   - 多场景同时命中：按固定优先级 `lead_conversion > finance_plan > silent_wake`。
   - 全未命中 → `scenario=None`，`should_trigger=false`。

### 5.5 严格性约束

- LLM 输出必须为受控结构（scenario 枚举 + confidence 数值 + should_trigger 布尔 + 话术字符串）；解析失败视为 `failed`。
- `reason_code` 为受控枚举（如 `llm_below_threshold` / `keyword_no_match` / `llm_completed` / `llm_failed` / `llm_not_configured`），不携带销售回复原文。
- 9100 内部日志只记 `lead_id` / `scenario` / `confidence` / `decision_source` / `llm_raw_status` / `reason_code`，不记原文。

---

## 6. 关键词与三条固定兜底文案

### 6.1 场景 lead_conversion（留资转化）

- 保守关键词（初始冻结，管理页可编辑）：
  `["留资", "电话", "微信", "联系方式", "已留", "号码"]`
- 兜底文案（初始冻结，管理页可编辑）：
  > 您好，看到您对这款车很感兴趣，我这边帮您整理了详细的报价方案和到店专属礼遇，方便留个联系方式我直接发给您吗？

### 6.2 场景 finance_plan（金融方案）

- 保守关键词（初始冻结）：
  `["金融", "贷款", "分期", "首付", "月供", "利息"]`
- 兜底文案（初始冻结）：
  > 您好，关于购车的金融方案我们这边有多种选择，首付比例和月供都可以按您的实际情况来定，我可以帮您详细算一份方案，您看什么时候方便？

### 6.3 场景 silent_wake（销售反馈触发的沉默唤醒）

- 保守关键词（初始冻结）：
  `["没回", "不回", "联系不上", "沉默", "失联", "找不到"]`
- 兜底文案（初始冻结）：
  > 您好，之前给您介绍的车型信息不知道您是否方便看到，最近店里有一些新的优惠活动想再跟您同步一下，您看什么时间方便聊一聊？

### 6.4 编辑约束

- `fallback_message` 长度上限 500 字符；提交时过违禁词替换预检（不替换，仅告警）。
- `keywords` 数量上限 30，单项长度上限 20。
- `confidence_threshold` 必须落在 `[0.500, 1.000]`。
- 配置变更写入审计日志（操作人 / 字段 / 旧值指纹 / 新值指纹）。

---

## 7. 真实发送十二项门禁

本阶段不执行真实发送（C12），但完整设计门禁，供后续真实发送执行包直接落地。采用 `C-安全版`（C9）：不检查账号/客户灰度白名单，保留以下 12 项。

| 序 | 门禁 | 不过处置 | 说明 |
|----|------|----------|------|
| G1 | 总熔断 `is_automation_allowed` | blocked / emergency_stop | 全局自动化开关 |
| G2 | 人工接管 `manual_takeover` | blocked / manual_takeover | 销售已人工接管 |
| G3 | 商户隔离 `merchant_id` 校验 | blocked / cross_merchant | 跨商户不可见 |
| G4 | 违禁词替换 `forbidden_words` | blocked / forbidden_word（替换后仍命中则拦截） | 发送前替换话术 |
| G5 | 限频（商户级 + 会话级 24h） | blocked / rate_limited | 商户级窗口 + 会话级 cooldown |
| G6 | 上下文完整性 | blocked / context_incomplete | 派单通知锚点 + 销售回复可读 |
| G7 | 失败回写 | failed / failure_stage 记录 | 所有失败回写原因 |
| G8 | 消息级幂等 `idempotency_key` | 跳过（返回既有 run） | 同消息同场景永久幂等（C8） |
| G9 | 会话级幂等 `cooldown_seconds` | blocked / session_cooldown | 同会话每场景 24h 最多一次（C8） |
| G10 | LLM 置信度 `>= confidence_threshold` | 不触发（未命中） | 见第 5 节 |
| G11 | 回访话术安全 | blocked / message_invalid | 非空 + 违禁词替换后非空 + 长度合规 |
| G12 | `send_authorized → send_unknown` 禁重发 | send_unknown 终态 | 结果不确定时进入，禁止重发（C10） |

`C-安全版` 不检查项（明确排除）：
- 账号级灰度白名单
- 客户级灰度白名单

---

## 8. 管理 API 与前端设计

### 8.1 管理 API（只读运行记录 + 配置编辑，C11）

所有接口要求管理员权限（`auto_wechat:admin:*` 权限码族），跨商户统一 404。

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/admin/return-visit/scenarios` | 列出当前商户三场景配置 |
| PUT | `/admin/return-visit/scenarios/{scenario}` | 编辑单场景配置（enabled / confidence_threshold / fallback_message / keywords / cooldown_seconds） |
| GET | `/admin/return-visit/runs` | 只读运行记录列表（分页，按 status/scenario/decision_source 筛选） |
| GET | `/admin/return-visit/runs/{id}` | 只读单条运行记录详情 |
| GET | `/admin/return-visit/stats` | 统计聚合（按场景/状态/决策来源） |

响应脱敏：
- 不返回销售回复原文、不返回客户手机号/open_id、不返回回访话术原文给非必要字段。
- `trigger_message_fp` 仅返回 sha256 指纹（与既有 `_fingerprint` 一致：长度 + sha256[:8]）。
- `intended_message` 在详情接口可见（供审计），但列表接口不返回。

明确不提供（C11）：
- 不提供 `POST /admin/return-visit/runs/{id}/retry`。
- 不提供 `POST /admin/return-visit/runs/{id}/send`。
- 不提供任何触发立即发送或重试的写接口。

### 8.2 前端设计

新增页面（挂在超管后台）：
1. **回访场景配置页**：三场景卡片，每卡可编辑 enabled / confidence_threshold（滑块 0.500～1.000）/ fallback_message（文本框）/ keywords（标签编辑器）/ cooldown_seconds。提交调 PUT，变更显示审计摘要。
2. **回访运行记录页（只读）**：列表（scenario / status / decision_source / confidence / failure_stage / created_at），详情抽屉（含 intended_message、trigger_message_fp 指纹、llm_raw_status、reason_code）。不提供重试/立即发送按钮。
3. **统计概览**：按场景/状态/决策来源的计数与近期趋势（只读）。

前端约束：
- 列表与详情均不渲染销售回复原文、客户联系方式。
- 配置变更前后端二次校验 `confidence_threshold ∈ [0.500, 1.000]`、`fallback_message` 长度、`keywords` 数量与单项长度。

---

## 9. 崩溃恢复和幂等规则

### 9.1 崩溃恢复

- **持久化优先**：触发判定在持久化 `ReturnVisitRun(status=pending)` 后立即返回 `run_id`，不等待 LLM。Local Agent 不阻塞（C5）。
- **worker claim**：异步 worker 以 `UPDATE return_visit_runs SET status='running', updated_at=NOW() WHERE id=:id AND status='pending'` 原子领取，`affected_rows=1` 才继续。
- **超时 reclaim**：`running` 超过阈值（默认 300s，可配置）的 run 由周期巡检 reclaim：`running → pending`，`send_attempt_count += 1`。
- **reclaim 上限**：`send_attempt_count` 超过上限（默认 3）→ `failed`，`last_failure_stage='reclaim_exhausted'`。
- **LLM 幂等**：LLM 调用幂等由 `idempotency_key` 保证；同一 run 被 reclaim 后再次判定，若已写过 `send_authorized` 则不重复授权。

### 9.2 幂等规则（C8）

- **消息级永久幂等**：`idempotency_key = sha256(merchant_id + ":" + lead_id + ":" + trigger_message_fp + ":" + scenario)`，UNIQUE 约束。INSERT 冲突直接返回既有 run，不重复判定、不重复授权。
- **会话级 24h 幂等**：同一 `(lead_id, scenario)` 组合，若存在 `last_run_at >= NOW() - cooldown_seconds` 的非失败 run，则新触发 `blocked / session_cooldown`。
- **判定顺序**：先查消息级 `idempotency_key`（永久），再查会话级冷却（24h）。两者都过才创建新 run。
- **失败 run 不计入冷却**：`failed` / `blocked` 的 run 不更新会话级冷却窗口，允许配置/熔断恢复后由新消息重新触发。

---

## 10. SQLite `0030` / PostgreSQL `0011` 迁移边界

### 10.1 SQLite `0030_return_visit.py`

- `CREATE TABLE IF NOT EXISTS return_visit_runs`（字段见 4.1，含 `idempotency_key UNIQUE` + 三个索引）。
- `CREATE TABLE IF NOT EXISTS return_visit_scenario_configs`（字段见 4.2，含 `UNIQUE(merchant_id, scenario)`）。
- Seed：对每个已有 `merchant_id`（从 `sales_staff` / 商户表去重），`INSERT OR IGNORE` 三场景默认行（`confidence_threshold=0.900`，冻结 `fallback_message` 与 `keywords` 见第 6 节，`cooldown_seconds=86400`）。
- 守卫：复用 0028/0029 多重集守卫模式（表存在性 + seed 行数 = 商户数 × 3 + CHECK），失败整体 ROLLBACK 不登记 0030。
- 幂等：所有 DDL 用 `IF NOT EXISTS`；seed 用 `INSERT OR IGNORE`。runner 已登记版本时整体跳过。

### 10.2 PostgreSQL `0011_return_visit.py`

- `CREATE TABLE IF NOT EXISTS return_visit_runs`（PG 语法，`keywords` 用 `JSONB`，`idempotency_key VARCHAR(128) NOT NULL UNIQUE`）。
- `CREATE TABLE IF NOT EXISTS return_visit_scenario_configs`（`keywords JSONB NOT NULL DEFAULT '[]'`，`UNIQUE(merchant_id, scenario)`）。
- Seed：`INSERT ... ON CONFLICT (merchant_id, scenario) DO NOTHING`，三场景默认值同 10.1。
- 权限：`GRANT SELECT, INSERT, UPDATE, DELETE ON return_visit_runs, return_visit_scenario_configs TO <app_role>;`
- 幂等：`IF NOT EXISTS` + `ON CONFLICT DO NOTHING`。

### 10.3 迁移边界（硬约束）

- 仅新增上述 2 表 + seed。
- 不修改 `wechat_tasks` / `daily_report_deliveries` / `reply_checks` / `douyin_leads` / `sales_staff` 任何字段与状态机（F8）。
- 字段定义在 SQLite 与 PostgreSQL 之间保持一致（仅 `keywords` 类型差异：SQLite TEXT(JSON) / PG JSONB）。
- 回滚：`DROP TABLE IF EXISTS return_visit_runs; DROP TABLE IF EXISTS return_visit_scenario_configs;`（seed 随表删除）。
- 迁移测试：建表 + seed 行数 + UNIQUE 冲突 + 回滚 + 与 0029/0010 共存（见第 11 节）。

---

## 11. 自动化测试矩阵

### 11.1 9100 判定协议单元测试

| 用例 | 期望 |
|------|------|
| LLM completed + confidence >= 阈值 + should_trigger=true | decision_source=llm，suggested_message=LLM 输出 |
| LLM completed + confidence < 阈值 | should_trigger=false，scenario=None |
| LLM failed → 关键词命中 lead_conversion | decision_source=keyword_fallback，confidence=0.500，suggested_message=fallback |
| LLM not_configured → 关键词全未命中 | should_trigger=false |
| LLM 输出格式错误（解析失败） | 视为 failed → 关键词兜底 |
| 多场景关键词同时命中 | 按 lead_conversion > finance_plan > silent_wake 优先级 |

### 11.2 幂等与状态机单元测试

| 用例 | 期望 |
|------|------|
| 同 idempotency_key 第二次插入 | 返回既有 run，不重复判定 |
| 会话级 24h 内同 (lead, scenario) 再次触发 | blocked / session_cooldown |
| failed run 不更新会话冷却 | 配置恢复后新消息可重新触发 |
| pending → running → send_authorized（dry_run） | 状态正确流转 |
| send_authorized → send_unknown | 终态，禁止重发 |
| blocked 终态可由新消息创建新 run | 旧 run 保留 |

### 11.3 门禁集成测试（C-安全版 12 项）

| 用例 | 期望 |
|------|------|
| 总熔断关闭 | blocked / emergency_stop |
| 人工接管标记 | blocked / manual_takeover |
| 跨商户读取 | 404 |
| 违禁词命中（替换后仍命中） | blocked / forbidden_word |
| 限频（商户级窗口超额） | blocked / rate_limited |
| 上下文缺失（无派单通知锚点） | blocked / context_incomplete |
| 消息级幂等冲突 | 跳过 |
| 会话级冷却 | blocked / session_cooldown |
| 回访话术为空 | blocked / message_invalid |
| reclaim 超过上限 | failed / reclaim_exhausted |

### 11.4 管理 API 测试

| 用例 | 期望 |
|------|------|
| GET scenarios 返回三场景 | 200，含默认配置 |
| PUT scenario 修改 confidence_threshold | 200，审计日志生成 |
| PUT confidence_threshold=0.3 | 422（越界） |
| PUT fallback_message 超 500 字 | 422 |
| GET runs 列表不返回原文 | 无 sales_reply_text 字段 |
| GET runs 详情含 intended_message | 200 |
| 不提供 retry / send 接口 | 路由不存在（404/405） |
| 跨商户 GET runs/{id} | 404 |

### 11.5 迁移测试

| 用例 | 期望 |
|------|------|
| SQLite 0030 建表 + seed | 行数 = 商户数 × 3 |
| SQLite 0030 UNIQUE(idempotency_key) 冲突 | 约束生效 |
| SQLite 0030 与 0029 共存 | 迁移链不中断 |
| SQLite 0030 回滚 | 两表删除 |
| PG 0011 建表 + seed（ON CONFLICT） | 行数正确，可重入 |
| PG 0011 keywords JSONB | 类型正确 |

### 11.6 端到端 dry_run 闭环测试

| 用例 | 期望 |
|------|------|
| 派单通知 → 销售回复（留资关键词）→ 持久化 → 异步判定 → send_authorized | 全链路 dry_run 通过，不真实发送 |
| 三场景分别命中 | 各场景 intended_message 正确 |
| 销售回复未命中任何场景 | should_trigger=false，不创建 run |
| ReplyCheck.check_status=timeout 时仍可触发回访 | 解耦验证（C4） |

---

## 12. 宝塔真实验证后置说明

- 本阶段所有回访"发送"均为 dry_run（`status=send_authorized` 落库 `intended_message`，不调用抖音私信发送接口）。C12。
- 真实抖音发送需另开执行包，包含：
  - `send_authorized → 真实抖音 im_send_msg` 调用链。
  - 宝塔生产环境部署验证（账号鉴权 / 限频配置 / 违禁词服务 / 监控）。
  - `send_unknown` 与 `sent` 的生产观测与告警。
- 后置不阻塞：Phase 9 验收以"代码与模拟闭环 DONE"为准，`baota_production_send_not_verified` 作为唯一 concern 记录，不在本阶段消除。
- 真实发送执行包必须重新走检查点（非检查点 A/B，新增回访检查点），不得复用本设计文档直接上线。

---

## 13. 风险与最终状态口径

### 13.1 风险

| 风险 | 等级 | 缓解 |
|------|------|------|
| `baota_production_send_not_verified` | 中 | 唯一 concern；真实发送另开执行包 + 宝塔验证 |
| LLM 故障导致关键词兜底覆盖率不足 | 中 | 关键词可编辑；管理页可观测 decision_source 分布 |
| 9100 LLM 延迟影响 worker 吞吐 | 低 | 持久化后异步，不阻塞 Local Agent；reclaim 机制兜底 |
| Qt 微信 UIA 文件气泡限制影响回访 | 无 | Phase 9 锚定 sender=friend 文本读取，不依赖文件气泡识别（与 Phase 8-B 限制正交） |
| 配置误改导致回访风暴 | 中 | 会话级 24h 冷却 + 商户级限频 + 总熔断 + 管理页无立即发送 |

### 13.2 最终状态口径（冻结）

| 项目 | 状态 |
|------|------|
| Phase 9 代码与模拟闭环 | `DONE` |
| Phase 9 | `DONE_WITH_CONCERNS`（唯一 concern = `baota_production_send_not_verified`） |
| Phase 8-B | `PARTIAL_BLOCKED_DEFERRED`（不恢复，Qt UIA 子控件树空，转 verify_pending 人工审计受控方案） |
| Phase 11 一键过审 | `CANCELLED_BY_CUSTOMER`（不恢复，仅同步路线图不删历史） |
| Task 8（日报真实分发） | `NOT_STARTED` |
| 真实抖音回访发送 | 禁止（另开执行包 + 回访检查点） |
| 后台轮询 / `verify_pending → sent` | 继续禁止 |

### 13.3 自检（术语 / 状态 / 阈值 / 限频 / 验收一致性）

- 三场景枚举：`lead_conversion` / `finance_plan` / `silent_wake`，全文一致。
- 状态枚举：`pending` / `running` / `send_authorized` / `send_unknown` / `sent` / `failed` / `blocked` / `cancelled`，全文一致，`send_unknown` 为 Phase 9 新增。
- 置信度范围：`0.500～1.000`，初始阈值 `0.900`，全文一致（C6）。
- 会话级冷却：`24h = 86400s`，全文一致（C8）。
- `decision_source`：`llm` / `keyword_fallback`，全文一致（C7）。
- `llm_raw_status`：`completed` / `failed` / `not_configured`，与既有 9100 reply_decision_service 一致。
- C-安全版保留门禁 12 项，不检查项 2 项（账号/客户灰度白名单），全文一致（C9）。
- 验收：代码与模拟闭环 `DONE`，Phase 9 `DONE_WITH_CONCERNS`，唯一 concern `baota_production_send_not_verified`（C13）。
- 无 `TODO` / `TBD` / 未定义字段。

---

## 附录 A：与既有体系的边界

- `ReplyCheck`（`app/models.py:103`）：仅软关联，状态机解耦（C4）。
- 投递状态常量（`app/services/daily_report_delivery_service.py:38-46`）：Phase 9 `send_unknown` 为新增状态，不修改既有 9 态。
- 9100 LLM（`apps/xg_douyin_ai_cs/services/reply_decision_service.py`）：复用 `OpenAICompatibleClient` 与 `/chat/completions`，新增 `judge_return_visit` 不改动既有 `build_reply_suggestion`。
- 安全门禁：复用 `is_automation_allowed`（`app/services/automation_control.py`）、`mark_manual_takeover`（`app/services/conversation_autopilot_state_service.py`）、`forbidden_words`（权限码 `auto_wechat:admin:forbidden_words`）。
- 迁移：SQLite 0030 接续 0029；PostgreSQL 0011 接续 0010。

## 附录 B：后续执行包拆分建议（仅供参考，不在本设计范围）

1. 数据模型 + 迁移（SQLite 0030 / PG 0011）。
2. 9100 `judge_return_visit` 判定协议 + 关键词兜底。
3. 9000 回访触发 + `ReturnVisitRun` 持久化 + 异步 worker + 幂等。
4. C-安全版 12 项门禁。
5. 管理 API + 前端（配置页 + 只读运行记录页）。
6. 测试矩阵落地（11.1～11.6）。
7. 真实发送 + 宝塔验证（另开执行包 + 回访检查点）。
