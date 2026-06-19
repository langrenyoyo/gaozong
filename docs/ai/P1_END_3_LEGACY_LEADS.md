# P1-END-3 旧 pending / 历史 NULL 线索处理策略

> 文档类型：策略文档（docs-only，不涉及代码改动）
> 编写日期：2026-06-19
> 关联提交：`971707b`（按商户会话隔离抖音线索）、`1a233e3`（补齐线索前端类型字段）
> 关联迁移：`migrations/versions/0011_leads_session_isolation.sql`（已应用至生产/宝塔 SQLite）
> 当前 HEAD：`1a233e3`

---

## 1. 背景

`971707b` 落地「按商户会话隔离抖音线索」后，`douyin_leads` 新线索的写入与查询口径已切换为三字段隔离：

- `merchant_id`：商户隔离键，来自 `RequestContext`（NewCarProject 登录态），**不来自前端 / GMP / 客户端**。
- `account_open_id`：企业号 open_id，取自私信事件 `to_user_id`（接收方），并反查 `douyin_authorized_accounts`（`bind_status=1`）确认归属商户。
- `conversation_short_id`：会话短 ID，取自私信事件 `content.conversation_short_id`。

新写入线索的唯一聚合键为 `(account_open_id, conversation_short_id)`，并强制携带可信 `merchant_id`。

迁移 `0011` 之前的历史线索，可能三字段全部为 `NULL`：

- `merchant_id IS NULL`：迁移加列时默认为 NULL，旧行未被回填。
- `account_open_id IS NULL` / `conversation_short_id IS NULL`：旧 webhook 聚合键是客户 `source_id`（`from_user_id`），未记录企业号与会话维度。

### D3 决策（历史 NULL 线索保留原则）

历史 `merchant_id=NULL` 线索**保留**，但对商户**不可见**，**不自动归属默认商户**。本决策的目的是：

- 避免把历史线索错误塞给某个商户，破坏商户隔离与审计；
- 不丢失历史数据，便于后续追溯；
- 不在迁移阶段承担「猜测归属」的风险。

> 本文档即 P1-END-3 的收尾交付：**以文档化策略收尾，不进入代码实现**。

---

## 2. 历史 NULL 线索定义

一条 `douyin_leads` 记录被判定为「历史 NULL 线索」，当且仅当满足以下**任一**条件：

- `merchant_id IS NULL`
- `account_open_id IS NULL`
- `conversation_short_id IS NULL`

> 注：以「任一为 NULL」为口径偏保守。多数历史线索三字段同时为 NULL；个别仅缺会话维度的记录同样视为历史数据，不进入新口径。

---

## 3. 当前代码行为（截至 HEAD `1a233e3`）

### 3.1 普通商户线索列表 `/leads` —— 不可见

`app/routers/leads.py` `list_leads` 注入 `merchant_id = None if context.super_admin else context.merchant_id`；`app/services/lead_management_service.py` `_lead_query` 在 `merchant_id` 非空时执行 `filter(DouyinLead.merchant_id == merchant_id)`。SQL 语义下 `NULL == '商户A'` 为假，**历史 NULL 线索被过滤掉**。

### 3.2 普通商户统计 `/reports/summary` —— 不计入

`app/services/report_service.py` `get_summary` 的 `_scoped` 辅助函数同样在 `merchant_id` 非空时过滤；`lead_management_service.summary` 同理。历史 NULL 线索**不计入** `total_leads` / `assigned_count` / `retained_contact_count` / `retained_contact_rate`（转化率）/ `high_intent_count`。

### 3.3 普通商户 `GET /leads/{id}` 与 `POST /leads/{id}/assign` —— 不可操作

`app/services/lead_management_service.py` `require_lead_ownership`：`super_admin` 直接放行；非 `super_admin` 时 `not lead.merchant_id or lead.merchant_id != context.merchant_id` 一律返回 **404 `LEAD_NOT_FOUND`**（不泄露存在性）。`assign_lead` 在分配前先做归属校验，故历史 NULL 线索**既不能查看详情也不能分配/重新分配**。

### 3.4 对话跟进 —— 自动不可用

前端 `frontend/src/pages/LeadsManagement.tsx` 的 `getConversationJumpParams` 要求 `account_open_id`、`conversation_short_id`、`open_id` 三者同时齐备；任一缺失返回 `null`，`conversationJumpUrl` 为 `null`，「对话跟进」按钮 `disabled`。历史 NULL 线索缺会话维度 → **按钮自动禁用，不会跳转到无法定位的会话**。

### 3.5 新 webhook 事件 —— 不会回写旧线索

`app/integrations/douyin_webhook.py` `process_webhook_event` 的 `im_receive_msg` 分支以 `(account_open_id=to_user_id, conversation_short_id)` 为聚合键调用 `upsert_lead_from_webhook`（内部走 `find_lead_by_session`），**无 `source_id` 回退匹配**。历史 NULL 线索这两个字段为 NULL，无法被新事件命中 → **新事件一定创建新线索，绝不会更新旧 `source_id` 聚合的历史线索**。

### 3.6 super_admin 视角 —— 可见且计入全局统计

`super_admin` 分支 `merchant_id=None`，`_lead_query` / `_scoped` 跳过过滤 → **super_admin 能看到全部线索（含历史 NULL），且这些线索会计入 super_admin 的全局统计**。这是当前「全局视角」的设计结果，不影响任何普通商户口径。

---

## 4. 可见性矩阵

| 通道 / 角色 | 历史 NULL 线索 | 说明 |
|-------------|----------------|------|
| 普通商户 `/leads` 列表 | ❌ 不可见 | `merchant_id` 过滤排除 NULL |
| 普通商户 `/reports/summary` 统计 | ❌ 不计入 | `_scoped` 过滤排除 NULL |
| 普通商户 `GET /leads/{id}` | ❌ 不可操作 | `require_lead_ownership` → 404 |
| 普通商户 `POST /leads/{id}/assign` | ❌ 不可操作 | 分配前归属校验 → 404 |
| 普通商户「对话跟进」按钮 | ❌ 自动禁用 | 缺 `account_open_id`/`conversation_short_id` |
| super_admin 列表 | ✅ 可见 | 不过滤 merchant_id |
| super_admin 统计 | ⚠️ 当前计入 | 全局视角，含历史 NULL |
| super_admin 操作 | ✅ 可操作 | `super_admin` 绕过归属校验 |
| webhook 新事件回写 | ❌ 不会回写 | 按会话聚合，无 `source_id` 回退 |
| 自动派单链路 | ❌ 不会触达 | 派单基于商户过滤后的 `/leads` 结果 |

---

## 5. 生产只读统计 SQL

> ⚠️ 仅在生产（宝塔 SQLite）执行。本地 `data/auto_wechat.db` 为 **stale/空库**（缺 0011 三列、缺 `schema_migrations` 表、0 数据），**不能用于统计**。

```sql
-- (1) 历史 NULL 线索总数（缺任一 scope 字段）
SELECT COUNT(*) FROM douyin_leads
WHERE merchant_id IS NULL OR account_open_id IS NULL OR conversation_short_id IS NULL;

-- (2) merchant_id IS NULL
SELECT COUNT(*) FROM douyin_leads WHERE merchant_id IS NULL;

-- (3) account_open_id IS NULL
SELECT COUNT(*) FROM douyin_leads WHERE account_open_id IS NULL;

-- (4) conversation_short_id IS NULL
SELECT COUNT(*) FROM douyin_leads WHERE conversation_short_id IS NULL;

-- (5) merchant_id IS NULL 的状态分布
SELECT status, COUNT(*)
FROM douyin_leads
WHERE merchant_id IS NULL
GROUP BY status;

-- (6) 历史 NULL 且仍为 pending 的线索数
SELECT COUNT(*) FROM douyin_leads
WHERE (merchant_id IS NULL OR account_open_id IS NULL OR conversation_short_id IS NULL)
  AND status = 'pending';
```

> 预览（可选）：
> ```sql
> SELECT id, source_id, customer_name, status, created_at
> FROM douyin_leads
> WHERE (merchant_id IS NULL OR account_open_id IS NULL OR conversation_short_id IS NULL)
> ORDER BY created_at DESC
> LIMIT 20;
> ```

---

## 6. 处理原则

历史 NULL 线索的处理必须遵守以下原则，**任何自动化清理/归属动作均需先经人工评审**：

1. **不硬删除**：历史数据保留，便于审计与追溯；优先软保留/软归档。
2. **不自动回填**：不自动给 `merchant_id IS NULL` 的线索写商户。
3. **不归属默认商户**：不引入「默认商户」兜底把历史线索塞进去。
4. **不用 `source_id` 猜 `merchant_id`**：`source_id` 是客户 open_id（`from_user_id`），与企业号→商户的归属链路无关，不能用来推断商户。
5. **不用客户 open_id 反推企业号 open_id**：私信事件里客户 open_id 与企业号 open_id 是对端关系，旧数据缺失的企业号维度无法从客户维度可靠反推。
6. **如需回填，必须有人工确认的历史映射依据**：例如「当时哪个企业号绑定了哪个商户」的可信对照表；否则一律不回填。
7. **当前推荐：软保留 + 文档说明**：即本文档方案 A，零代码、零迁移、零数据变更。

---

## 7. 后续可选方案（按风险由低到高）

### 方案 A —— 文档说明（当前采用）

`merchant_id IS NULL` 本身即 D3 定义的「历史未归属」隐式标记，代码已基于此隔离普通商户。仅以本文档固化语义与原则。**风险：零。**

### 方案 B —— super_admin 派生 `legacy_unassigned` 标记 / 独立只读 tab（可选）

若产品要求 super_admin 也能区分「历史未归属」与「活跃商户线索」：
- 在 super_admin 查询分支对 `merchant_id IS NULL` 的记录派生 `legacy_unassigned=true`；
- 或提供独立只读 tab 展示，并默认从 super_admin 活跃统计中排除。
- 不新增字段，靠 `merchant_id IS NULL` 派生。**风险：低**（仅 super_admin 路径，不动商户隔离）。

### 方案 C —— 软归档脚本（可选，需迁移/状态机评估）

若需把旧 `pending` 从活跃 pending 计数中彻底摘出：
- 新增独立字段（如 `archived_at` / `origin`）或新状态值，用一次性脚本把 `merchant_id IS NULL AND status='pending'` 的线索软归档（**不删除**）。
- 当前 `DouyinLead.status` 枚举为 `pending/assigned/replied/timeout/closed`，无 legacy 位；建议新增独立字段而非复用 `status`，以避免状态机兼容风险。**风险：中**（涉及迁移 + 状态机 + 测试）。

### 方案 D —— 人工映射回填（高风险，不推荐）

把历史线索回填 `merchant_id`/`account_open_id`/`conversation_short_id` 使其归属商户。**仅在存在明确、人工确认的历史映射依据时才可考虑**；历史线索普遍缺 `account_open_id`，映射依据通常不存在 → **默认不推荐**。**风险：高**（误归属会破坏商户隔离与审计）。

---

## 8. 验收结论

P1-END-3 **当前不进入代码实现**，以本文档化策略收尾。结论依据：

1. 普通 `/leads` 列表已按 `merchant_id` 过滤，历史 NULL 线索对商户**不可见**。
2. 普通 `/reports/summary` 已按 `merchant_id` 过滤，历史 NULL 线索**不计入**统计与转化率。
3. 普通商户 `get/assign` 受 `require_lead_ownership` 保护，历史 NULL 线索**不可操作**（统一 404，不泄露存在性）。
4. 前端「对话跟进」因缺 `account_open_id`/`conversation_short_id` 而**自动禁用**。
5. 新 webhook 按 `(account_open_id, conversation_short_id)` 聚合，**不会回写旧 `source_id` 聚合线索**。

综上：**旧 NULL 线索不影响普通商户的线索列表、统计、对话跟进和新 webhook 入线索**。唯一可感知点为 super_admin 全局视角的统计仍含历史 NULL（见第 3.6 / 4 节），属当前设计，不影响普通商户口径；是否需要方案 B 进一步区分，待产品确认后再评估。

下一步建议：先由运维在生产执行第 5 节 SQL 取得真实数量；即使数量较大，只要普通商户口径正确，也不构成必须清理的理由——**软保留 + 文档说明即可**。
