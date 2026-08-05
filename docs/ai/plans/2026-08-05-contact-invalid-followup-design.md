# 空号追问链路——详细技术方案

## 一、总体架构

```
人工客服/销售反馈"空号"
  → 统一有效性分析（否定优先/有效确认优先/正反=unknown）
  → 状态迁移：VALID→INVALID（invalid_version递增）
  → 创建 contact_invalid_followup_task（同一事务）
  → 唤醒主动追问 Worker

Worker 领取任务
  → 专用新鲜度检查（非通用门禁无条件豁免）
  → _send_private_message_with_context（4层串号防护）
  → 固定话术（按 invalid_reason 两模板）
  → send_source=contact_invalid_followup

客户下次发消息
  → 联系方式识别（优先于读取旧状态）
  → 有效新号码 → 恢复 VALID + 取消追问任务
  → 无效 → 块4被动兜底（结构化状态注入 LLM）
```

## 二、块2：联系方式失效状态闭环

### 2.1 统一有效性分析

**新建** `app/services/contact_validity_analyzer.py`

```python
class ContactValidityResult:
    status: Literal["valid", "invalid", "unknown"]
    reason: Literal[
        "empty_number",        # 空号
        "unreachable",         # 打不通
        "wechat_add_failed",   # 微信加不上
        "wrong_number",        # 号码错误
        "customer_denied",     # 客户拒绝
        "other",               # 其他
    ] | None
    matched_text: str | None  # 命中的原文片段

def analyze_contact_validity(text: str) -> ContactValidityResult:
    """确定性分析联系方式有效性。

    规则优先级：
    1. 否定表达优先——"不是空号""号码没问题"→ valid
    2. 有效确认优先于失效关键词——"已经联系上了"→ valid
    3. 同一条消息同时出现正反信息 → unknown
    4. unknown 不修改客户状态
    """
```

**关键词表**（分正反两组）：

| 类型 | 关键词 | 判定 |
|---|---|---|
| 失效正面 | 空号、打不通、加不上、号码错误、微信错误、联系方式错误、号码不存在、号码无效、联系不上 | invalid |
| 否定/恢复 | 不是空号、号码没问题、号码没有问题、不是加不上、已经联系上、已经加上了、联系上了 | valid |
| 同时出现 | 正反都命中 | unknown |

### 2.2 Task2A 抖音工作台接入

**位置**：`app/integrations/douyin_webhook.py::_post_process_im_send_msg`

当前逻辑只做人工接管。新增：人工客服出站消息文本经 `analyze_contact_validity` 分析：

- `invalid` → 写 lead contact_state=INVALID + 创建失效事件 + 创建追问任务
- `valid` → 如果当前是 INVALID 状态，恢复为 VALID + 取消追问任务
- `unknown` → 不修改状态

**事件原生锚定**：event.account_open_id + event.conversation_short_id + im_send_msg_participants(event) 的 customer_open_id

### 2.3 Task2B 微信回写接入

**位置**：`app/services/reply_checker.py::record_manual_reply`

当前 `analyze_reply` 已有有效性判断。新增：用 `analyze_contact_validity` 替换或补充判断逻辑，检测结果写入 lead 状态。

**task_id→lead_id 强锚定**：check.lead_id（已有）

### 2.4 权威失效状态存储

**复用 `customer_profiles` 表**（不新建表），新增字段：

```sql
ALTER TABLE customer_profiles ADD COLUMN contact_invalid_reason VARCHAR(64);
ALTER TABLE customer_profiles ADD COLUMN contact_invalid_at TIMESTAMP;
ALTER TABLE customer_profiles ADD COLUMN contact_invalid_source VARCHAR(32);
ALTER TABLE customer_profiles ADD COLUMN contact_invalid_source_message_id VARCHAR(255);
ALTER TABLE customer_profiles ADD COLUMN contact_invalid_version INTEGER DEFAULT 0;
```

**状态迁移规则**：

| 原状态 | 事件 | 新状态 | 版本 |
|---|---|---|---|
| VALID/none | 检测到失效 | INVALID | invalid_version++ |
| INVALID | 检测到新有效联系方式 | VALID | 清除 invalid_* |
| INVALID | 再次检测到失效 | INVALID | invalid_version++（新事件） |

### 2.5 恢复路径

当 webhook 检测到客户发来新有效联系方式（`extract_contacts_from_text` 返回有效手机号/微信号）：

1. `contact_state` 恢复为 `valid`
2. `contact_invalid_reason/at/source/source_message_id` 清空
3. 取消当前 `invalid_version` 下所有 pending/processing 追问任务
4. 原始失效记录保留在审计/事件表中

### 2.6 迁移 0027

```python
# migrations/postgres/auto_wechat/versions/0027_contact_invalid_fields.py
# customer_profiles 加字段：contact_invalid_reason/at/source/source_message_id/version
```

## 三、块4：被动兜底

### 3.1 结构化状态注入

**位置**：`app/services/douyin_conversation_history_service.py::build_reply_conversation_context`

在 `merge_profile_with_memory` 后，增加 `contact_invalid` 状态注入：

```python
"contact_invalid": {
    "state": "INVALID",  # 或 None
    "reason": "unreachable",
    "version": 2,
    "followup_requested_before": True,
    "followup_last_sent_at": "2026-08-05T22:00:00"
}
```

### 3.2 处理顺序（关键）

```
客户消息进入
  → extract_contacts_from_text（联系方式识别，优先于读取旧状态）
  → 如果是有效新号码：
      → contact_state 恢复 VALID
      → 取消追问任务
      → 构建上下文（不含 contact_invalid）
      → 正常确认收到
  → 如果无效/无联系方式：
      → 构建上下文（含 contact_invalid 状态）
      → LLM 根据状态决定回复
```

**位置**：`app/integrations/douyin_webhook.py::process_webhook_event` 的 `upsert_lead_from_webhook` 调用处。

### 3.3 Prompt 追问规则

```
## 联系方式失效被动追问规则
known_customer.info.contact_invalid 标注联系方式失效状态：
- state=INVALID 且 followup_requested_before=false：
  回答客户当前问题后，简短提醒"您之前发的联系方式好像不太对，能重新发一遍吗"
- state=INVALID 且 followup_requested_before=true：
  正常承接客户消息，不重复完整索要话术，等待客户补充
- state=None 或 VALID：
  正常回复，不提联系方式失效

客户本轮提供有效联系方式时：
  不得继续说联系方式无效。
```

## 四、块3：主动追问发送

### 4.1 新表

```sql
CREATE TABLE contact_invalid_followup_tasks (
    id SERIAL PRIMARY KEY,
    merchant_id VARCHAR(128) NOT NULL,
    lead_id INTEGER NOT NULL,
    account_open_id VARCHAR(255) NOT NULL,
    conversation_short_id VARCHAR(255) NOT NULL,
    customer_open_id VARCHAR(255) NOT NULL,

    invalid_version INTEGER NOT NULL,
    trigger_source VARCHAR(32) NOT NULL,  -- douyin_workbench / wechat_reply
    trigger_message_id VARCHAR(255),
    invalid_reason VARCHAR(64) NOT NULL,

    followup_sequence INTEGER NOT NULL DEFAULT 1,  -- 1 or 2
    status VARCHAR(20) NOT NULL DEFAULT 'pending',  -- pending/processing/sent/cancelled/retry_wait/failed/dead
    scheduled_at TIMESTAMP NOT NULL,

    attempt_count INTEGER NOT NULL DEFAULT 0,
    lease_owner VARCHAR(128),
    lease_expires_at TIMESTAMP,

    sent_message_id VARCHAR(255),
    sent_at TIMESTAMP,
    cancelled_at TIMESTAMP,
    cancel_reason VARCHAR(128),
    last_error TEXT,

    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),

    CONSTRAINT uq_contact_invalid_followup UNIQUE (merchant_id, lead_id, invalid_version, followup_sequence)
);

CREATE INDEX idx_cift_status_scheduled ON contact_invalid_followup_tasks(status, scheduled_at);
CREATE INDEX idx_cift_lead ON contact_invalid_followup_tasks(lead_id, invalid_version);
```

**迁移 0028**：新建表。

### 4.2 状态迁移

```
pending → processing（Worker claim）
processing → sent（发送成功）
processing → retry_wait（发送失败，可重试）
processing → failed（发送失败，不可重试）
pending/processing/retry_wait → cancelled（客户恢复/人工接管/新鲜度检查失败）
retry_wait → pending（定时补偿恢复）
pending → dead（超过 max_attempts=2）
```

### 4.3 创建任务（Webhook 事务内）

**触发条件**：状态迁移 VALID→INVALID（非每次检测到 contact_invalid 都创建）

```python
# 只在状态迁移时创建，不在每次 derive_sales_followup_status 返回 contact_invalid 时创建
if old_contact_state != "INVALID" and new_contact_state == "INVALID":
    # 创建第一条追问任务
    create_contact_invalid_followup_task(
        db,
        merchant_id=...,
        lead_id=...,
        invalid_version=invalid_version,
        trigger_source="douyin_workbench",  # 或 "wechat_reply"
        trigger_message_id=event.id,
        invalid_reason=result.reason,
        followup_sequence=1,
        scheduled_at=now,  # 立即
    )
    # 唤醒 Worker
    wake_contact_invalid_worker()
```

**唯一约束**：`(merchant_id, lead_id, invalid_version, followup_sequence)` 防止重复创建。

### 4.4 Worker 异步发送

**复用 outbox 模式**（与 ai_auto_reply outbox 类似）：

```python
def run_contact_invalid_worker():
    """主动追问 Worker：claim → 门禁检查 → 发送 → 回写"""
    while not stop_event.wait(timeout=interval):
        batch = claim_tasks(batch_size=10)
        for task in batch:
            process_task(task)

def process_task(task):
    # 1. 专用新鲜度检查（非通用门禁无条件豁免）
    if not _check_freshness(task):
        cancel_task(task, "freshness_check_failed")
        return

    # 2. 门禁检查（按确认清单）
    #    G3 商户归属：保留
    #    G4 人工接管：保留
    #    G5/E2/E3/E4：用专用检查替代（见 4.5）
    #    频控/24h窗口/账号开关/总开关/紧急停止/格式校验：保留

    # 3. 固定话术生成
    text = _build_followup_text(task.invalid_reason, salutation)

    # 4. 发送
    send_result = _send_private_message_with_context(
        send_source="contact_invalid_followup",
        content=text,
        ...
    )

    # 5. 回写
    if send_result.success:
        task.status = "sent"
        task.sent_at = now
        task.sent_message_id = send_result.message_id
        # 如果 followup_sequence=1，创建 sequence=2（间隔 30 分钟）
        if task.followup_sequence == 1:
            create_task(sequence=2, scheduled_at=now + 30min)
    else:
        task.status = "retry_wait"
        task.next_attempt_at = now + backoff
```

### 4.5 专用新鲜度检查（替代无条件豁免）

```python
def _check_freshness(task) -> bool:
    """专用新鲜度检查——替代通用门禁的无条件豁免。"""

    # 1. 当前 contact_state 是否仍为 INVALID
    if current_contact_state != "INVALID":
        cancel("contact_already_recovered")
        return False

    # 2. invalid_version 是否匹配
    if current_invalid_version != task.invalid_version:
        cancel("invalid_episode_changed")
        return False

    # 3. 客户是否在任务创建后发了新消息
    if has_customer_inbound_after(task.created_at):
        cancel("customer_message_received_use_passive_fallback")
        return False

    # 4. trigger_message_id 之后是否有新的人工出站消息
    #    （trigger 本身的出站消息允许，新的人工出站说明已接管）
    if has_human_outbound_after(task.trigger_message_id):
        cancel("human_handled_after_trigger")
        return False

    return True
```

### 4.6 固定话术

```python
def _build_followup_text(invalid_reason: str, salutation: str) -> str:
    name = salutation or "老板"
    if invalid_reason in ("empty_number", "wrong_number"):
        return f"{name}，您之前发的联系方式好像不太对，麻烦重新发一遍。"
    if invalid_reason in ("unreachable", "wechat_add_failed"):
        return f"{name}，之前的联系方式暂时联系不上，麻烦重新发一遍。"
    return f"{name}，您之前发的联系方式好像不太对，麻烦重新发一遍。"
```

### 4.7 追问次数控制

- 同一 `invalid_version` 最多创建 2 条任务（followup_sequence=1, 2）
- sequence=2 在 sequence=1 发送成功后创建，间隔 30 分钟
- 超过 2 次不再创建——等客户主动回复时走块4被动兜底

### 4.8 取消逻辑

以下情况取消当前 `invalid_version` 下所有未发送任务：

| 触发 | 原因 |
|---|---|
| 客户发来新有效联系方式 | contact_already_recovered |
| 客户在任务创建后发新消息 | customer_message_received_use_passive_fallback |
| 新人工出站消息（trigger 之后） | human_handled_after_trigger |
| G4 人工接管 | manual_takeover_blocked |
| 超过 24h 窗口 | platform_24h_limit |

### 4.9 定时补偿调度

低频调度器（每 60 秒一轮）：
1. 恢复 `processing` 且租约过期的任务 → `retry_wait`
2. `retry_wait` 且 `next_attempt_at <= now` 的任务 → `pending`
3. `pending` 且 `scheduled_at <= now` 的任务 → 被 Worker claim

## 五、改动文件清单

### 块2（阶段A）

| 文件 | 改动 |
|---|---|
| `migrations/.../0027_contact_invalid_fields.py` | 新建迁移 |
| `app/models.py` | CustomerProfile 加字段 + ContactInvalidFollowupTask model |
| `app/services/contact_validity_analyzer.py` | 新建：统一有效性分析 |
| `app/integrations/douyin_webhook.py` | Task2A 接入 |
| `app/services/reply_checker.py` | Task2B 接入 |
| `app/services/customer_profile_service.py` | 状态迁移 + 恢复路径 |

### 块4（阶段B）

| 文件 | 改动 |
|---|---|
| `app/services/douyin_conversation_history_service.py` | 结构化状态注入 |
| `app/integrations/douyin_webhook.py` | 处理顺序（先识别再读旧状态） |
| `apps/.../reply_decision_service.py` | Prompt 追问规则 |

### 块3（阶段C）

| 文件 | 改动 |
|---|---|
| `migrations/.../0028_contact_invalid_followup_tasks.py` | 新建迁移 |
| `app/models.py` | ContactInvalidFollowupTask model |
| `app/services/contact_invalid_followup_service.py` | 新建：Worker + 门禁 + 话术 + 调度 |
| `app/integrations/douyin_webhook.py` | 创建任务（状态迁移时） |
| `app/main.py` | 注册 Worker 调度 |

## 六、安全边界

- Hard 守卫（防欺诈/防骚扰/资料承诺）：**全部保留**
- G3 商户归属：**保留**
- G4 人工接管：**保留**（不豁免）
- 24h 窗口：**保留**（平台硬限制）
- 频控：**保留**
- 账号开关/总开关/紧急停止：**保留**
- 格式校验：**保留**
- 固定话术不依赖 LLM：**是**
- send_source=contact_invalid_followup：**是**
- 追问计数按 invalid_version：**是**
- 新有效联系方式恢复 + 取消任务：**是**
- 专用新鲜度检查替代无条件豁免：**是**

## 七、实施顺序

1. **阶段A（块2）**：统一有效性分析 + 状态闭环 + 迁移 0027 + Task2A/2B 接入
2. **阶段B（块4）**：结构化状态注入 + 处理顺序 + Prompt 规则
3. **阶段C（块3）**：新表 + 迁移 0028 + Worker + 门禁 + 话术 + 调度
