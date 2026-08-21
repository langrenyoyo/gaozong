# P1-WECOM-THIRD-PARTY-APPLICATION-SPEC-v1.0

```text
TASK                  = P1-WECOM-THIRD-PARTY-APPLICATION-SPEC-v1.0
AUTHORITY             = Spec Authority
TASK_LEVEL            = L3
OWNER                 = M04
INPUT                 = WECOM_THIRD_PARTY_APP_P1_DESIGN.md v1.0（APPROVED_FOR_SPEC）
                      + P1-WECOM-DESIGN-DECISION-v1.0（APPROVED_FOR_SPEC，DA Frozen Decisions 9 项）
                      + Owner Decision Response v1.0（D1 / D11 / D12 / D13，经启动指令转述）
                      + DA 采纳默认值（D2 / D6 / D7 / D8）
TASK_TYPE             = SPEC_ONLY
CODE_CHANGE           = NOT AUTHORIZED
DB_CHANGE             = NOT AUTHORIZED
MIGRATION             = DESIGN ONLY（不生成迁移文件）
IMPLEMENTATION        = NOT AUTHORIZED
PRODUCTION_CHANGE     = NOT AUTHORIZED
STATUS                = SPEC_READY_FOR_IMPLEMENTATION（等待 DA 审批 Implementation 授权）
DATE                  = 2026-08-21
```

> 本规格将 Design v1.0 与 DA/Owner 裁决逐条落实为冻结实施合同。所有未冻结细节在本规格内冻结；
> 实施不得临场自选设计分支。UNKNOWN 项显式标注，禁止假设未实测能力。
> 前序 GMP / LAS 任务上下文已清空，本规格不继承其实现假设。

### SPEC_CORRECTION-1（DA 裁决 2026-08-21）

- Spec §2.2 `wecom_enterprise_authorizations.merchant_id` 类型由 `INTEGER` **更正为 `VARCHAR(128)`**（NOT NULL 保持）。
- 理由：全仓 `merchant_id` 列均为 `String(128)`（近 30 处，含 SalesStaff / WechatTask / DouyinLead 等）+ `RequestContext.merchant_id` 为 `str`；INTEGER 会迫使服务层做全仓独一份的类型适配。
- 不受影响：D13 唯一约束（`UNIQUE(auth_corp_id)`）、D1、D12 及其余冻结项均不变。
- 执行方式：Implementation 按 `String(128)` 全仓模式实施，零额外适配。
- 本修订仅限 §2.2 一处，不扩大 Spec 其它冻结项。

---

## 0. DA Frozen Design Decisions 9 项（冻结清单）

以下 9 项为 DA 已冻结设计决策（引自 P1-WECOM-DESIGN-DECISION-v1.0，与 Design v1.0 §3~§10 一致），
本规格逐条落实，实施禁止改动：

| # | 冻结决策 | Design 出处 | 本规格落实位置 |
|---|---|---|---|
| FD-1 | 凭证三层模型：SERVICE_PROVIDER / MERCHANT / MEMBER；动态 token 只存进程内缓存，不落库 | §4.1 | §3.1 / §4 |
| FD-2 | 隔离红线：merchant scoped；callback 按 ToUserName 解析 merchant；未知 corpid 拒绝；touser 只用绑定表 open_userid；前端不持凭证；明文 userid/external_userid 不进 9000 | §5.3 | §4 / §6 |
| FD-3 | 三层幂等：Transport（provider_event_key UNIQUE）/ Delivery（状态机 + 行锁）/ Business（只允许 SENT→FEEDBACK_RECEIVED） | §9.1 | §7 |
| FD-4 | Callback Worker 重试：lease + attempt_count + next_attempt_at，复用 P2-M04 claim/lease 模式 | §9.3 | §7.3 |
| FD-5 | 单实例进程内 token 缓存：每 key 一把锁 + double-check + 提前刷新 + 失效强刷一次，不提前引入共享缓存 | §4.2 | §4.2 |
| FD-6 | 授权状态机：PENDING / ACTIVE / CHANGED / CANCELLED / INVALID（DA 口径"五态"；FAILED 为授权发起失败终态，见 §3.2 Spec 注记）；事件 + 对账双源驱动 | §3.1 | §3 |
| FD-7 | callback transport：验签 / 解密 / receiveid 校验 / 事件识别 / 落库 / ACK / 幂等 / 重试；授权类事件 ≤1000ms ACK；指令回调返回 `success` | §8 | §6 |
| FD-8 | fail-closed 全链：验签失败 / 解密失败 / 未知 corpid / 配置缺失 → 拒绝 + 审计 + 不泄露细节 | §10 | §6 / §10 |
| FD-9 | 日志脱敏：只记 stage / result / event_type / error_code / suite_id / ticket_hash 前缀 / auth_corp_id | §10.3 | §10 |

### Owner Decision Response（冻结）

| # | Owner 裁决 | 落实位置 |
|---|---|---|
| D1 | 密钥管理四项（key rotation / 环境隔离 / 泄露处理 / backup 策略）为 Owner 强制要求，写入独立章节 | §8 |
| D2（DA 采纳默认） | cancel_auth 后 permanent_code 失效策略 = fail-closed 置 INVALID（凭证不可再用） | §3.3 |
| D6（DA 采纳默认） | 同一自然人换企业后 open_userid 按每个 auth_corp_id 独立成员身份，不跨企业合并（P2 范围，P1 仅约束不落地） | §9 UNKNOWN |
| D7（DA 采纳默认） | provider_event_key 按官方建议口径（指令类 = InfoType+SuiteId+AuthCorpId+CreateTime；数据类 = FromUserName+CreateTime），以 P0 实测回放为准调整 | §7.1 |
| D8（DA 采纳默认） | 对账频率 = 小时级，设为配置项 `WECOM_AUTH_RECONCILE_INTERVAL_MINUTES`（默认 60） | §3.4 / §4.3 |
| D11 | 验证基于 Owner 受控测试主体；禁止生产真实企业 / 客户企业 / 未授权第三方；资源未到位则标注"待资源到位执行" | §12 |
| D12 | P1 范围冻结（做 / 不做清单） | §1 |
| D13 | merchant_id ↔ auth_corp_id 1:1 唯一约束（含并发兜底语义） | §2.1 / §3.5 |

---

## 1. Scope

### 做什么（D12 冻结）

1. `wecom_suite_runtime`：suite_ticket 加密落库（只用最新值）。
2. `wecom_enterprise_authorizations`：授权状态机（PENDING / FAILED / ACTIVE / CHANGED / CANCELLED / INVALID）。
3. `WeComCredentialService`：suite_access_token / corp_access_token / permanent_code 生命周期（进程内缓存 + 加密持久化）。
4. authorization lifecycle：create / change / cancel / reset + 定期对账兜底。
5. callback transport 扩展：验签 / 解密 / receiveid 校验 / 事件识别 / 落库 / ACK / 幂等 / 重试（Durable Inbox 雏形）。

### 不做什么（禁止写入本 Spec 之外的能力）

❌ 成员同步（P2） ❌ 派单 / Template Card（P3） ❌ 结构化反馈事务（P4） ❌ H5 反馈（P5）
❌ Personal WeChat 退出 / legacy fallback（P7） ❌ 19000 物理删除（P8） ❌ 多企业主体（D13 一期 1:1）
❌ externalcontact / 客户群 / 朋友圈 / 会话存档 ❌ 企微客户 AI 自动聊天 ❌ NLP 反馈主链
❌ Redis/DB 共享 token 缓存 ❌ 恢复 `wecom_provider_credentials` 表 ❌ 新增 Lead 核心状态
❌ 修改 M02 / M06 / M07 ❌ `wecom_member_snapshots` / `wecom_member_bindings` / `wecom_message_deliveries`（P2/P3）
❌ 影响 P0.5 发布链（7d 观察窗口 / 7h 待执行窗口 / 已冻结 Release Plan）

---

## 2. Data Contract

### 2.1 表：`wecom_suite_runtime`（新增）

| 字段 | PostgreSQL 类型 | 空值/默认 | 语义 |
|---|---|---|---|
| `id` | INTEGER PK autoincrement | — | 主键 |
| `suite_id` | VARCHAR(64) | NOT NULL | 服务商 suite_id |
| `suite_ticket_encrypted` | TEXT | NOT NULL | suite_ticket AES-256-GCM 加密（D1 主密钥） |
| `key_version` | INTEGER | NOT NULL DEFAULT 1 | 加密主密钥版本（D1 rotation） |
| `ticket_hash_prefix` | VARCHAR(8) | NOT NULL | SHA256(ticket) 前 8 位，日志脱敏对照 |
| `received_at` | TIMESTAMPTZ | NOT NULL | 最近一次接收时间 |
| `updated_at` | TIMESTAMPTZ | NOT NULL | 记录更新时间 |

- 约束：`UNIQUE (suite_id)`；单套件单行，**覆盖更新**（只用最新值，不保留 ticket 历史，设计 §4.1）。
- 每次收到新 suite_ticket：更新密文 + key_version + ticket_hash_prefix + received_at，同一事务。

### 2.2 表：`wecom_enterprise_authorizations`（新增）

| 字段 | PostgreSQL 类型 | 空值/默认 | 语义 |
|---|---|---|---|
| `id` | INTEGER PK autoincrement | — | 主键 |
| `merchant_id` | VARCHAR(128) | NOT NULL | 可信商户（RequestContext / 持久化身份注入；String(128) 与全仓一致，SPEC_CORRECTION-1） |
| `auth_corp_id` | VARCHAR(64) | NOT NULL | 密文 corpid（服务商主体下全局稳定，wwaa 前缀 18 位） |
| `authorization_status` | VARCHAR(16) | NOT NULL DEFAULT 'PENDING' | 状态机（见 §3.1） |
| `permanent_code_encrypted` | TEXT | NULL | permanent_code AES-256-GCM 加密（ACTIVE 后有值） |
| `key_version` | INTEGER | NOT NULL DEFAULT 1 | 加密主密钥版本 |
| `agentid` | VARCHAR(64) | NULL | get_auth_info 回填 |
| `privilege` | JSONB | NULL | get_auth_info 可见范围（allow_user / allow_party / allow_tag） |
| `state_hash` | VARCHAR(64) | NULL | 授权发起 state 的 SHA-256（防 CSRF，一次性） |
| `state_expires_at` | TIMESTAMPTZ | NULL | state 过期时间 |
| `last_sync_at` | TIMESTAMPTZ | NULL | 最近一次 get_auth_info 对账/同步时间 |
| `authorized_at` | TIMESTAMPTZ | NULL | 最近一次进入 ACTIVE 时间 |
| `failure_reason` | VARCHAR(64) | NULL | FAILED 原因分类（不存明文细节） |
| `created_at` | TIMESTAMPTZ | NOT NULL | 创建时间 |
| `updated_at` | TIMESTAMPTZ | NOT NULL | 更新时间 |

- 约束：
  ```sql
  ck_wecom_enterprise_authorizations_status
      CHECK (authorization_status IN ('PENDING','FAILED','ACTIVE','CHANGED','CANCELLED','INVALID'))
  uk_wecom_enterprise_authorizations_auth_corp_id
      UNIQUE (auth_corp_id)   -- D13：服务商全局 1:1
  ```
- 索引：`idx_wecom_enterprise_authorizations_merchant (merchant_id)`（按商户查询）。
- **D13 并发兜底语义**：两个商户并发授权同一 auth_corp_id → 唯一约束拒绝第二个 INSERT（IntegrityError）→
  返回确定性错误 `WECOM_AUTH_CORP_ALREADY_BOUND`（409），**绝不覆盖已有绑定**；应用层不得 try-except 后静默跳过。

### 2.3 表：`wecom_callback_events`（新增，Durable Inbox 雏形）

| 字段 | PostgreSQL 类型 | 空值/默认 | 语义 |
|---|---|---|---|
| `id` | INTEGER PK autoincrement | — | 主键 |
| `provider_event_key` | VARCHAR(255) | NOT NULL | 幂等键（D7 口径，见 §7.1） |
| `info_type` | VARCHAR(32) | NOT NULL | 事件类型（含 change_auth 的 ChangeType 复合值） |
| `suite_id` | VARCHAR(64) | NULL | 事件内 SuiteId |
| `auth_corp_id` | VARCHAR(64) | NULL | 指令类事件 AuthCorpId / 数据类 ToUserName |
| `from_user_name` | VARCHAR(128) | NULL | 数据类 FromUserName |
| `event_create_time` | BIGINT | NULL | 事件 TimeStamp（秒） |
| `status` | VARCHAR(20) | NOT NULL DEFAULT 'RECEIVED' | RECEIVED / PROCESSED / FAILED_RETRYABLE / FAILED_PERMANENT / IGNORED |
| `failure_stage` | VARCHAR(100) | NULL | 失败/忽略阶段标识 |
| `attempt_count` | INTEGER | NOT NULL DEFAULT 0 | 处理尝试次数（P2-M04 模式） |
| `lease_expires_at` | TIMESTAMPTZ | NULL | lease 过期时间（DB authoritative） |
| `next_attempt_at` | TIMESTAMPTZ | NULL | 重试时间 |
| `claimed_by` | VARCHAR(100) | NULL | claim 时 worker 身份（hostname+pid） |
| `processed_at` | TIMESTAMPTZ | NULL | 处理完成时间 |
| `created_at` | TIMESTAMPTZ | NOT NULL | 落库时间 |

- 约束：
  ```sql
  uk_wecom_callback_events_provider_event_key
      UNIQUE (provider_event_key)
  ck_wecom_callback_events_status
      CHECK (status IN ('RECEIVED','PROCESSED','FAILED_RETRYABLE','FAILED_PERMANENT','IGNORED'))
  ```
- 索引：`idx_wecom_callback_events_claim (status, next_attempt_at)`（worker 领取扫描）；`idx_wecom_callback_events_auth_corp (auth_corp_id)`。
- **P1 不存原始报文**（"原文最小化"= 零原文；原始报文加密存储属 P4 回放需求，不在 P1）。

### 2.4 迁移范围（仅设计）

- 仅 `auto_wechat` PG 库：一个迁移 `0039_wecom_third_party_app_p1.py`，创建三表 + 约束 + 索引。
- `down_revision` = 实施时唯一 head（当前唯一 head = `0038_gmp_authorization_health`）；若实施时 head 已变化，以实际唯一 head 为准，禁止多 head 分叉。
- 禁止 `create_all`；禁止 SQLite 迁移骨架扩散（不新增 `migrations/versions/*.sql`）。
- 禁止与 P0.5 发布链并行执行迁移；P0.5（7d 观察 / 7h 待执行）未闭环前不进入 0039 实施窗口。

---

## 3. State Machine

### 3.1 授权状态机（`authorization_status`）

```text
      PENDING ──(redirect 携 auth_code → get_permanent_code v2 成功 + get_auth_info 回填)──▶ ACTIVE
         │
         │(auth_code 过期 / 换码失败 / 安全事件)
         ▼
      FAILED（终态，仅审计，不参与对账与凭证分发）

   ACTIVE ──(change_auth 事件 / 对账发现变更)──▶ CHANGED ──(get_auth_info 重新同步)──▶ ACTIVE
   ACTIVE ──(cancel_auth 事件 / 对账发现授权消失)──▶ CANCELLED
   ACTIVE ──(reset_permanent_code 换码失败 / 安全事件)──▶ INVALID
   CANCELLED / INVALID ──(重新授权：redirect 携新 auth_code)──▶ ACTIVE（复用唯一行，凭证轮换）
```

**Spec 注记（五态/六态口径）**：DA 裁决口径为"五态"（PENDING / ACTIVE / CHANGED / CANCELLED / INVALID）。
Design v1.0 §3.1 图示另含 `FAILED`（授权发起失败终态）。本规格冻结：DB CHECK 允许全部 6 个值；
`FAILED` 为授权发起阶段的失败终态（仅审计与人工介入，不参与对账调度、不参与凭证分发、不参与 API 对外状态合同）；
对外状态合同与对账调度仅面向五态。若 DA 意图为"发起失败不建行/直接删除"，须在 Implementation 授权前明示，
否则按本冻结执行。

### 3.2 事件 → 状态迁移（冻结，幂等）

| 事件 | 库内现状 | 动作 | 结果 |
|---|---|---|---|
| `create_auth` | 无行 | 建 PENDING 行（auth_corp_id 已知）| PENDING |
| `create_auth` | PENDING | no-op（等 redirect 完成）| PENDING |
| `create_auth` | ACTIVE / CHANGED / CANCELLED / INVALID / FAILED | no-op（幂等确认）| 不变 |
| redirect 携 auth_code | 无行 / PENDING / CANCELLED / INVALID / FAILED | 校验 state → get_permanent_code v2 → get_auth_info → 落库/更新 | ACTIVE |
| redirect 携 auth_code | ACTIVE | 幂等返回已有，不重复换码 | ACTIVE |
| `change_auth`（update_authorized）| ACTIVE / CHANGED | 置 CHANGED → 触发 get_auth_info 同步 | ACTIVE |
| `change_auth`（reset_permanent_code）| ACTIVE | 用事件新 auth_code 换新 permanent_code（凭证轮换）| ACTIVE（凭证已换）|
| `cancel_auth` | ACTIVE / CHANGED / PENDING | 置 CANCELLED + 凭证 fail-closed | CANCELLED |
| 对账发现授权消失 | ACTIVE | 置 CANCELLED + 凭证 fail-closed | CANCELLED |
| 对账发现 agentid/privilege 变更 | ACTIVE | 置 CHANGED → 同步 → ACTIVE | ACTIVE |
| 换码失败 / 安全事件 | ACTIVE | 置 INVALID（凭证 fail-closed）| INVALID |

- 无行时收到 `change_auth` / `cancel_auth` / `reset_permanent_code` → 事件落库 status=IGNORED（审计），不建授权行。
- 所有迁移在 Worker 事务内对 `wecom_enterprise_authorizations` 行执行 `SELECT ... FOR UPDATE`，串行化同一 auth_corp_id 的并发事件。

### 3.3 cancel_auth 凭证收口（D2 = fail-closed INVALID）

CANCELLED 后冻结（设计 §5.4）：
- 该 auth_corp_id 的 `corp_access_token` 缓存立即失效；
- 后续任何官方调用（发送 / 对账 get_auth_info / 成员 / 消息）一律不再发起（fail-closed）；
- 历史授权事实保留可审计，不删除；
- permanent_code 在库中保留（加密）供审计，但服务不得再解密使用。

### 3.4 对账任务（B4 兜底，D8）

- 频率：`WECOM_AUTH_RECONCILE_INTERVAL_MINUTES`（默认 60，配置项，小时级）。
- 范围：仅 ACTIVE / CHANGED 授权；对 CANCELLED / INVALID / FAILED 不发起任何官方调用。
- 动作：对每个目标授权调 `get_auth_info`；授权消失 → CANCELLED（凭证收口）；agentid / privilege 与库内不一致 → CHANGED → 同步 → ACTIVE；无变化 → 保持。
- 与事件竞争：以"库内状态 + 对账结果"为最终一致源，事件只做加速；对账任务内同一行也走 FOR UPDATE。

### 3.5 授权发起链（Phase A/B）与 state 防 CSRF

```text
POST /authorization/start（登录态，merchant_id 来自 RequestContext）
  → 生成 state（256 bit 随机，一次性，10 分钟过期），state_hash 落授权行（或暂存行）
  → 返回 authorize_url（含 redirect_uri + state）
管理员扫码 + 选可见范围
  → 微信跳转 redirect_uri?auth_code=xxx&state=yyy
GET /authorization/redirect（公网，浏览器跳转，无登录态）
  → 校验 state（存在 / 未过期 / 未消费，匹配当前 merchant）→ 一次性消费
  → get_permanent_code v2（auth_code 10 分钟一次性）
  → get_auth_info v2（回填 agentid + privilege）
  → upsert wecom_enterprise_authorizations = ACTIVE（D13 唯一约束兜底）
  → 返回简单成功页（或 302 至前端工作台）
```

- `create_auth` 事件与 redirect 为双源：先到 create_auth → 建 PENDING 审计行；先到 redirect → 直接 ACTIVE，随后 create_auth 到达 no-op。
- **UNKNOWN（触发源）**：auth_code 载体（redirect_uri 查询参数）与 create_auth 事件是否携带 auth_code，官方未在 P0 实测覆盖——本规格冻结"唯一完成路径 = redirect 携 auth_code 换码；create_auth 事件不做换码"；若 D11 实测发现 create_auth 事件携 auth_code 或 get_permanent_code 可无 auth_code 调用，按实测调整并需 DA 追认。

---

## 4. WeComCredentialService（FD-1 / FD-5）

### 4.1 凭证分层与持久化

| 层级 | 凭证 | 生命周期 | 持久化 |
|---|---|---|---|
| SERVICE_PROVIDER | suite_id / suite_secret | 长期 | 仅 env 配置（不入表 / 不入 Git / 不入日志）|
| SERVICE_PROVIDER | Token / EncodingAESKey | 长期 | 仅 env 配置 |
| SERVICE_PROVIDER | suite_ticket | 30min 有效 / 10min 推送，只用最新值 | `wecom_suite_runtime.suite_ticket_encrypted`（AES-256-GCM）|
| SERVICE_PROVIDER | suite_access_token | 2h | 进程内缓存，不落库 |
| MERCHANT | auth_corp_id / agentid / privilege | 长期 | `wecom_enterprise_authorizations` |
| MERCHANT | permanent_code | 永久 | `wecom_enterprise_authorizations.permanent_code_encrypted`（AES-256-GCM）|
| MERCHANT | corp_access_token | 2h | 进程内缓存（key = `merchant_id:auth_corp_id`），不落库 |
| MEMBER | open_userid | 长期 | P2（`wecom_member_snapshots` / `wecom_member_bindings`），P1 不落地 |

### 4.2 Token 缓存（单实例，FD-5）

- suite 级：缓存 key = `suite`；corp 级：缓存 key = `merchant_id:auth_corp_id`（禁止全局共享 token 池）。
- 每 key 一把进程内锁；锁内 double-check（先读缓存，未命中才调官方接口）；同一 key 并发只放行一次获取。
- 过期：按官方 2h 有效期提前刷新（如提前 60s）。
- 明确失效（官方 token 失效错误码命中白名单）→ **只强制刷新一次**；仍失败 → fail-closed（抛安全错误码），不无限重试。
- 刷新失败停止重试并记安全日志（stage / error_code，不含明文）。
- suite_access_token 获取始终使用 `wecom_suite_runtime` 内最新 ticket（先解密最新密文）。
- **UNKNOWN（U6）**：官方 token 失效错误码白名单（如 42001 / 40014 / 40001 等）须以官方文档 + D11 实测确认；白名单未确认前冻结为"按官方文档已列错误码实现并写测试锁定"，白名单外一律 fail-closed 不重试（漏判不误判）。

### 4.3 配置（新增 env，全部 Owner 部署侧注入）

```text
WECOM_SUITE_SECRET                    服务商 suite_secret（新，高敏感，不入 env example / release identity）
WECOM_CREDENTIAL_MASTER_KEY           凭证加密主密钥（新，D1，见 §8）
WECOM_CREDENTIAL_MASTER_KEY_VERSION   主密钥版本（新，默认 "1"）
WECOM_AUTH_RECONCILE_INTERVAL_MINUTES 对账频率（新，默认 60，D8）
WECOM_CALLBACK_TOKEN                  （既有，保留）
WECOM_CALLBACK_ENCODING_AES_KEY       （既有，保留）
WECOM_SUITE_ID                        （既有，保留）
```

- 配置缺失：`WECOM_SUITE_SECRET` / `WECOM_CREDENTIAL_MASTER_KEY` 缺失 → 启动时 capability 校验 fail-closed（见 §5.3），不 500、不泄露原因。

---

## 5. Callback Transport（FD-7 / FD-8）

### 5.1 物理入口（P0 已 VALIDATED，保持不变）

- 单一 URL `/integrations/wecom/callback`（9000 内部路由，nginx 剥离 /api 匹配，外部 `/api/integrations/wecom/callback`）。
- GET = URL 验证：验签 + AES 解密 + 1 秒内返回精确明文；不强制 receiveid==suite_id（FROZEN）。
- POST = 指令/数据回调（Token / EncodingAESKey 共用，VALIDATED）。

### 5.2 POST 处理管线（P1 扩展，冻结）

```text
WeCom POST
  → verify signature（SHA1 字典序，恒定时间比较）
  → AES-256-CBC 解密（PKCS7，XXE 拒绝）
  → 指令类：receiveid == suite_id 校验；数据类：按 ToUserName 解析 merchant
  → 解析事件 envelope（含 ChangeType 复合识别）
  → 计算 provider_event_key（§7.1）
  → INSERT wecom_callback_events（RECEIVED / IGNORED）   ← 幂等去重点
  → ACK "success"（授权类 ≤1000ms，一般 ≤5s）
  ──────────────── 异步 Worker（§7.3）────────────────
  → 指令类事件 → 授权生命周期 Worker（§3.2）
  → 数据类事件（template_card_event）→ 仅标记处理完成（P1 无业务处理，P4 承接）
```

### 5.3 安全拒绝矩阵（fail-closed，冻结）

| 场景 | 落库 | HTTP 响应 | 审计日志 |
|---|---|---|---|
| 配置缺失（Token/AESKey/SuiteID/SUITE_SECRET/MASTER_KEY）| 不落库 | 400 `verification failed` | stage + error_code=config_missing |
| 验签失败 | 不落库 | 400 `verification failed` | signature_invalid |
| 解密失败 / XXE / 非法填充 | 不落库 | 400 `verification failed` | decrypt_failed / xml_entity_rejected |
| 指令类 receiveid != suite_id 或内层 SuiteId 不匹配 | 不落库 | 400 `verification failed` | suite_mismatch |
| 验签+解密成功、未知 InfoType | 落库 IGNORED（unsupported_event）| 200 `success` | result=ignored_unsupported |
| 数据类 ToUserName 未知 corpid | 落库 IGNORED（security_rejected）| 200 `success` | result=security_rejected |
| 指令类已知事件 | 落库 RECEIVED | 200 `success` | result=ok + 脱敏 metadata |

- 验签/解密失败不落库（不可构造可信事件）；安全拒绝"成功 ACK"避免官方无意义重试，同时以 IGNORED + 审计闭环。
- 响应仅 `success` / `verification failed`，不含内部细节。

### 5.4 事件识别集合（P1）

```text
指令类：suite_ticket / create_auth / change_auth（ChangeType: update_authorized / reset_permanent_code）/ cancel_auth
数据类：template_card_event（识别 + 落库 + ACK，不处理）
```

- `suite_ticket` 事件额外动作：解密 → 覆盖更新 `wecom_suite_runtime`（§2.1，同一事务）。
- **UNKNOWN（U2）**：第三方接收消息配置页细节（数据回调字段）未实测——P1 数据类仅"识别+落库+ACK"，不消费字段，降级安全。

---

## 6. API Contract

### 6.1 `POST /api/wecom/authorization/start`

- 鉴权：登录态 + 商户上下文（复用 `get_request_context_required` 模式）；`merchant_id` 只取 `RequestContext`，拒绝请求体传入。
- 权限：不新增权限码（P1 无前端，merchant 隔离即权限边界）；如需独立权限码，由 Owner 在 Implementation 授权时确认。
- 请求体：`{ "redirect_base": "<可选，授权完成后的跳转前缀>" }`（可选）。
- 响应 200：
  ```json
  {
    "authorize_url": "https://open.weixin.qq.com/connect/oauth2/authorize?...",
    "state": "<随机 256bit>",
    "expires_in": 600
  }
  ```
- 错误：登录失效/无商户上下文 → 401/403（沿用现有合同）；能力未启用（SQLite）→ 503 `WECOM_CAPABILITY_DISABLED`。

### 6.2 `GET /api/wecom/authorization/redirect`

- 公网浏览器跳转端点（无登录态），作为 authorize_url 的 redirect_uri。
- 查询参数：`auth_code`（必填，10min 一次性）、`state`（必填）。
- state 校验：存在 / 未过期 / 未消费 → 一次性消费；失败 → 简单错误页 + 审计（fail-closed，不泄露细节）。
- 成功：换 permanent_code → get_auth_info → upsert（D13）→ 返回成功页（或 302 至 `redirect_base`）。
- 禁止：前端传入 merchant_id / auth_corp_id / permanent_code / Token。

### 6.3 `GET /api/wecom/authorization/status`

- 鉴权：登录态 + 商户上下文（merchant 隔离）。
- 响应 200：
  ```json
  {
    "authorization_status": "PENDING|ACTIVE|CHANGED|CANCELLED|INVALID",
    "auth_corp_id_masked": "wwaa****1234",
    "agentid": null,
    "authorized_at": null,
    "last_sync_at": null
  }
  ```
- 冻结：只返回当前商户（RequestContext.merchant_id）匹配 auth_corp_id 的授权行；不返回 permanent_code / token / state / 明文 corpid。

### 6.4 `GET/POST /api/wecom/callback`

- GET：保持 P0 Probe（URL 验证，§5.1）。
- POST：§5.2 管线；响应仅 `success` / `verification failed`。

### 6.5 错误合同（新增业务码）

```text
WECOM_CAPABILITY_DISABLED     503  能力未启用（非 PG / 缺表），固定文案
WECOM_AUTH_CORP_ALREADY_BOUND 409  D13 唯一约束冲突，固定文案（不覆盖已有绑定）
WECOM_AUTH_STATE_INVALID      400  state 校验失败（redirect），固定文案，不泄露细节
WECOM_CREDENTIAL_ERROR        502  凭证获取失败（fail-closed 后），固定安全文案
```

---

## 7. Idempotency / Retry（FD-3 / FD-4）

### 7.1 Transport 层幂等（provider_event_key，D7）

```text
指令类（含 AuthCorpId）：provider_event_key = InfoType + SuiteId + AuthCorpId + CreateTime
指令类（无 AuthCorpId，如 suite_ticket）：provider_event_key = InfoType + SuiteId + CreateTime
数据类：provider_event_key = FromUserName + CreateTime
```

- InfoType 对 change_auth 内嵌 ChangeType 的事件取复合值：`change_auth:update_authorized` / `change_auth:reset_permanent_code`，保证同秒不同 ChangeType 不冲突。
- CreateTime 源 = 事件内 `TimeStamp`（秒）。
- 重复投递：INSERT 冲突（UNIQUE）→ 已存在 → 直接 ACK `success`，**不重新处理**（无论历史状态）。
- 乱序投递：状态机拒绝非法迁移（如 CANCELLED 后收到过期 create_auth 的 no-op 语义），不覆盖已提交事实。
- **D7 逃生口**：若 P0 实测回放发现更稳定字段（如 MsgId / ResponseCode），按实测调整并需 DA 追认。

### 7.2 Delivery / Business 层（P1 解释注记）

DA 冻结决策 FD-3 的 Delivery（wecom_message_deliveries 状态机 + 行锁）与 Business（SENT→FEEDBACK_RECEIVED）层属 P3/P4 落地；
**P1 的"行锁" = callback 事件行的 lease 领取行锁（§7.3）+ 授权行 FOR UPDATE（§3.2）**。`wecom_message_deliveries` 表不在 P1 创建。
三层幂等中的 P1 可落地部分全部落地，其余部分在对应阶段落地（不提前实现）。

### 7.3 Callback Worker（FD-4，P2-M04 模式）

- 轮询 `wecom_callback_events` 中 `status IN (RECEIVED, FAILED_RETRYABLE) AND (next_attempt_at IS NULL OR next_attempt_at <= now())`。
- 领取：`UPDATE ... SET lease_expires_at = :now + 30s, claimed_by = :identity, attempt_count = attempt_count + 1 WHERE id = :id AND (lease_expires_at IS NULL OR lease_expires_at <= :now)`；rowcount=1 才处理（复用 P2-M04 claim 语义，`claim_token_hash` 等价体为 lease 状态本身）。
- 处理成功后：`status=PROCESSED` + `processed_at`；失败按分类：
  - `FAILED_RETRYABLE`（上游网络 / 5xx / 临时错误）：`next_attempt_at = now + backoff`，`attempt_count` 上限 5 次后转 `FAILED_PERMANENT`；
  - `FAILED_PERMANENT`（逻辑冲突 / 不可调和）：记录 + 告警，不无限重试；
  - `IGNORED`（安全拒绝 / 未知事件）：不再领取。
- backoff：`min(60s * 2^attempt_count, 1800s)`。
- Worker 崩溃恢复：从 RECEIVED / FAILED_RETRYABLE（lease 过期）重新领取；靠 provider_event_key UNIQUE + 授权行锁保证一次且仅一次业务反馈。
- 运行形态：单实例 9000 进程内（复用 `app/scheduler/*` 现有 start/stop 模式），新增 `app/scheduler/wecom_scheduler.py`（callback worker 轮询 + 对账循环两线程），仅 capability 启用时启动（§5.3 关联）。

---

## 8. 密钥管理（D1 四项，Owner 强制，独立章节）

> 冻结主密钥来源（OWNER_DECISION_05）：`WECOM_CREDENTIAL_MASTER_KEY` 由 Owner 在部署环境注入，
> 不进 Git / 不进 env example / 不进 release identity / 不进日志 / 不进 API。加密算法 AES-256-GCM（cryptography 已有依赖，不新增）。

### 8.1 Key Rotation（轮换）

- 密文格式（冻结）：`v{version}:{iv_b64}:{tag_b64}:{ciphertext_b64}`；`version` 对应 `WECOM_CREDENTIAL_MASTER_KEY_VERSION`。
- 轮换流程（冻结，数据量小，单次维护事务完成）：
  1. 部署新版本主密钥（`WECOM_CREDENTIAL_MASTER_KEY_VERSION = N+1` + 新 key）；
  2. 进程内以新版本重加密全部密文（`wecom_suite_runtime.suite_ticket_encrypted` + `wecom_enterprise_authorizations.permanent_code_encrypted`，逐行更新 `key_version`）；
  3. 重加密完成后移除旧版本密钥引用（旧 key 仅保留到所有行迁移完成）；
  4. 验证：抽查行 `key_version` 全部为新版本、解密 round-trip 通过。
- 解密兼容：读侧按密文内 version 选 key；version 无对应 key → fail-closed（`WECOM_CREDENTIAL_ERROR`），不降级明文。

### 8.2 环境隔离（Environment Isolation）

- dev / staging / prod 使用**独立**主密钥，互不通用；dev 可用本地生成 key（禁止纳入 Git）；staging / prod 用部署 secret 注入。
- 密文数据可随 DB 备份流转（密文可备份，明文不可）；备份解密能力仅对应环境的 key 持有者具备。
- 主密钥与回调 secret（Token / EncodingAESKey / suite_secret）为不同 secret，分通道注入。

### 8.3 泄露处理（Leak Handling）

- 疑似泄露即 fail-closed：立即轮换主密钥（§8.1 流程）+ 审计日志（仅 stage/error_code，不含明文）；
- 同步轮换服务商侧 suite_secret（官方后台重新生成，回调 Token/EncodingAESKey 若同批泄露一并轮换）；
- 泄露事件记安全审计，并通知 Owner；不自动重放任何消息、不自动恢复任何发送。

### 8.4 Backup 策略

- 主密钥备份：Owner 离线托管（密码管理器 / 保险库），**不进仓库、不进任何部署产物**；无主密钥则密文不可恢复（fail-closed，明确不可用，不提供绕过）。
- 密文数据：随 DB 常规备份（加密落库内容 + key_version 可还原）；不备份明文。
- 恢复演练：P1 验证矩阵含"主密钥丢失 → 能力 fail-closed 不可用（不崩溃、不泄露、可审计）"项。

---

## 9. UNKNOWN 项（显式声明 + 降级路径）

| # | 内容 | P1 相关性 | 降级路径 / 冻结处理 |
|---|---|---|---|
| U1 | 第三方网页授权构造链接 appid 取值（suite_id / corpid）| 无关（P2 自绑定）| P1 不实现自绑定；不消费 |
| U2 | 第三方接收消息配置页细节 | 部分（数据回调字段）| P1 数据类仅识别+落库+ACK，不消费字段 |
| U3 | cancel_auth 后 permanent_code 是否自动失效 | **相关** | D2 冻结：fail-closed 置 INVALID，凭证不再使用（§3.3） |
| U4 | 换企业后 open_userid 一致性 | 无关（P2）| D6 冻结：按 auth_corp_id 独立成员身份；P1 不落地 |
| U5 | 服务商许可/收费规则 | 无关（P6）| 不消费 |
| U6 | 官方错误码逐条正文 / token 失效错误码白名单 | **相关** | §4.2 冻结：按官方文档已列错误码实现 + 测试锁定，白名单外 fail-closed |
| — | auth_code 载体（redirect_uri 查询参数 vs create_auth 事件）| **相关** | §3.5 冻结：唯一完成路径 = redirect 携 auth_code 换码；实测不符需 DA 追认 |
| — | change_auth 事件是否携带新 auth_code（reset_permanent_code）| **相关** | 冻结：若携带则用于凭证轮换；若不携带则置 CHANGED 待人工；实测为准 |
| — | 对账 get_auth_info 在授权消失时的错误形态 | **相关** | 冻结：按"官方明确授权无效/不存在"错误码 → CANCELLED；模糊错误 → FAILED_RETRYABLE |

---

## 10. Security Boundary（FD-8 / FD-9）

- 回调：验签（恒定时间比较）→ AES 解密 → receiveid / 内层 SuiteId 双校验 → 未知 corpid 拒绝（§5.3）。
- 配置缺失 fail-closed：不 500、不泄露原因。
- XML：拒绝 DOCTYPE / ENTITY（XXE）；非法密文 / 填充拒绝。
- 凭证：suite_secret / Token / EncodingAESKey / permanent_code / suite_access_token / corp_access_token / suite_ticket **绝不进前端、绝不进日志明文、绝不进 release identity / env example**。
- 落库加密：permanent_code / suite_ticket（AES-256-GCM，§8）；动态 token 不落库。
- 日志脱敏（冻结白名单）：只记 `stage / result / event_type / error_code / suite_id / ticket_hash_prefix（SHA256 前 8 位）/ auth_corp_id / attempt_count / lease 时间`；凭证明文、解密结果、ticket 明文、原始报文一律不进日志。
- 响应仅 `success` / `verification failed` / 固定安全文案，不含内部细节。
- 明文 userid / external_userid 不进 9000（第三方应用官方禁止获取）。

---

## 11. Module Impact

### 文件范围

| 文件 | 动作 |
|---|---|
| `app/models.py` | 改：新增三表（§2.1~§2.3）|
| `migrations/postgres/auto_wechat/versions/0039_wecom_third_party_app_p1.py` | 新增（仅设计，实施时生成）|
| `app/integrations/wecom/crypto.py` | 保持（回调协议层）|
| `app/integrations/wecom/credential_crypto.py` | 新增：AES-256-GCM 主密钥加密 / 解密 / 版本封装 / 轮换（D1）|
| `app/integrations/wecom/api_client.py` | 新增：官方 API 客户端（requests，复用 douyin_openapi_client 先例）|
| `app/services/wecom_credential_service.py` | 新增：WeComCredentialService（§4）|
| `app/services/wecom_authorization_service.py` | 新增：授权生命周期 + 状态机 + 对账（§3）|
| `app/services/wecom_callback_service.py` | 新增：事件落库 + 幂等 + worker 领取（§5/§7）|
| `app/routers/wecom_callback.py` | 改：POST 扩展 durable inbox（§5.2）|
| `app/routers/wecom_authorization.py` | 新增：start / redirect / status（§6.1~§6.3）|
| `app/scheduler/wecom_scheduler.py` | 新增：callback worker + 对账循环（§7.3）|
| `app/config.py` | 改：新增 4 个 env（§4.3）|
| `app/main.py` | 改：router 挂载 + startup 能力校验 + scheduler 挂接 |
| `tests/test_wecom_callback_probe.py` | 改：保持 19 项 PASS + 新增 transport 用例 |
| `tests/test_wecom_credential_crypto.py` / `tests/test_wecom_authorization_lifecycle.py` / `tests/test_wecom_callback_transport.py` | 新增 |

### 模块范围

- M04（授权 / 凭证 / callback transport / worker / 对账）；PLATFORM（官方 API 客户端）。
- M02 / M06 / M07 声明无影响（本规格不触碰其代码与合同）。

### 数据库范围

- 仅 `auto_wechat` PG：三新表 + 约束 + 索引（一个迁移 0039，§2.4）。
- 无 SQLite 迁移骨架；SQLite 开发态显式能力降级（§5.3 关联启动校验）。

---

## 12. Verification Matrix（D11 约束）

> 验证主体：仅使用 Owner 受控测试主体（suite_id / suite_secret 由 Owner 在服务商后台创建并提供来源说明；
> 测试 corp_id 与测试管理员由 Owner 提供；测试回调环境 = 既有公网回调 `merchant.xiaogaoai.cn/api/integrations/wecom/callback`，P0 已实测）。
> **禁止**：生产真实企业、客户企业、未授权第三方。
> 依赖真实企微资源的验证项标注 **「待资源到位执行」**，不阻塞本 Spec 定稿与 Implementation 授权。

### 单元测试（无外部依赖）

| 编号 | 场景 | 验收 |
|---|---|---|
| W-P1-01 | provider_event_key 构造（指令/数据/无 AuthCorpId/复合 ChangeType）| 全部符合 §7.1 |
| W-P1-02 | provider_event_key 冲突 → UNIQUE 拒绝 → ACK success 不重复处理 | 幂等 |
| W-P1-03 | 授权状态机迁移矩阵（§3.2 全表）| 非法迁移拒绝 |
| W-P1-04 | credential 缓存：锁 / double-check / 提前刷新 / 失效强刷一次 | 同 key 并发仅一次获取 |
| W-P1-05 | 错误码白名单：白名单外 fail-closed 不重试 | 漏判不误判 |
| W-P1-06 | AES-256-GCM 加密 / 解密 round-trip / 版本选择 / 轮换重加密 | round-trip + 全部行新版本 |
| W-P1-07 | 日志脱敏：无凭证明文 / 无 ticket 明文 / 无原始报文 | 扫描断言 |
| W-P1-08 | 回调安全拒绝矩阵（§5.3 全行）| 响应与落库符合 |
| W-P1-09 | state：生成 / 校验 / 一次性消费 / 过期拒绝 | 防 CSRF |

### 集成测试（PG）

| 编号 | 场景 | 验收 |
|---|---|---|
| W-P1-10 | migration 0039：唯一 head 无分叉、三表约束索引正确、downgrade 可逆 | 无 create_all |
| W-P1-11 | D13：并发同 auth_corp_id 授权 → 第二个 409 确定性错误，不覆盖 | 唯一约束兜底 |
| W-P1-12 | cancel_auth → CANCELLED + 凭证缓存失效 + 后续官方调用不再发起 | fail-closed |
| W-P1-13 | 对账：差异→CHANGED→ACTIVE；授权消失→CANCELLED | 双源收敛 |
| W-P1-14 | worker lease 领取 / 崩溃恢复 / backoff / 上限转 FAILED_PERMANENT | P2-M04 模式 |
| W-P1-15 | SQLite 开发态：能力禁用 + ERROR 启动日志 + API 503 | 显式降级非静默 |

### E2E / 真实回调（依赖 D11 测试主体，标注「待资源到位执行」）

| 编号 | 场景 | 验收 |
|---|---|---|
| W-P1-16 | 真实 suite_ticket 10min 投递 → 加密落库 + token 获取用最新 ticket | PASS（资源到位后）|
| W-P1-17 | 测试企业扫码授权 → redirect 换码 → ACTIVE；create_auth 幂等 | PASS（资源到位后）|
| W-P1-18 | 测试企业变更可见范围 → change_auth → CHANGED → ACTIVE | PASS（资源到位后）|
| W-P1-19 | 测试企业取消授权 → cancel_auth → CANCELLED 凭证收口 | PASS（资源到位后）|
| W-P1-20 | 主密钥丢失 → 能力 fail-closed 不可用（不崩溃 / 可审计）| PASS |

### 回归

- 既有 `tests/test_wecom_callback_probe.py` 19 项必须保持 PASS；
- M02 / M06 / M07 与既有测试套件无回归（本规格不触碰）。

---

## 13. Rollback

### 代码回退

- 回退顺序：先回退应用代码（router / services / scheduler / config / models），再评估数据库降级。
- 新增三表为 additive：旧应用对三表无感知，可先回退应用、保留新表。

### 数据回退

- drop 三表（降级 migration 或手动 drop）仅允许在新应用完全退出后执行，且必须另行审批（丢失授权记录与 ticket）。
- 已发生 cancel_auth / 授权变更事实保留审计，不因回退重放或回退。

### 配置回退

- 删除 `WECOM_SUITE_SECRET` / `WECOM_CREDENTIAL_MASTER_KEY` env → 能力 fail-closed 禁用（不 500、不泄露），callback 回落 P0 Probe 行为；
- `WECOM_AUTH_RECONCILE_INTERVAL_MINUTES` 恢复默认 60。

### 与 P0.5 发布链的隔离

- 本规格零触碰 P0.5（GMP / LAS）已冻结 Release Plan、观察窗口、待执行窗口；
- 0039 迁移实施只能在 P0.5 发布链闭环且唯一 head 确认后进入独立窗口。

---

## 14. Risk Checklist

- **权限**：merchant_id 唯一可信来源 = RequestContext / 持久化身份；redirect 以一次性 state 绑定商户；前端不持任何企微凭证；无新增权限码（已声明，Owner 如需独立权限码在 Implementation 授权时确认）。
- **隔离**：token 缓存 key = `merchant_id:auth_corp_id`，禁止共享池；未知 corpid fail-closed；CANCELLED 后零官方调用；D13 唯一约束防跨商户抢占。
- **幂等**：provider_event_key UNIQUE + 事件行 lease 行锁 + 授权行 FOR UPDATE + 状态机幂等转换；重复投递 ACK success 不重复处理。
- **副作用**：cancel_auth 凭证 fail-closed 不重放不重发；对账只读官方接口且对非 ACTIVE/CHANGED 不发起；加密明文不进日志；刷新失败不无限重试。
- **UNKNOWN 不假设**：U1~U6 及触发源 / reset 事件字段均显式声明 + 降级路径（§9）；实测不符需 DA 追认。
- **已声明可接受风险**：数据类事件 P1 不消费（P4 承接）；五态/六态口径注记（§3.1）；无前端入口（P1 管理 API 由后续阶段承接 UI）。

---

```text
SPEC_STATUS = READY_FOR_IMPLEMENTATION（等待 DA 审批 Implementation 授权）
FINAL_STATUS = DESIGN_ONLY
CODE_CHANGE = 0 / DB_CHANGE = 0 / MIGRATION = DESIGN ONLY / DEPLOYMENT = 0 / COMMIT = 0
DOCUMENT_IMPACT = NEW SPEC RECORD ONLY（G1/G2/G3/G4_DELTA = NO）
```

等待 Decision Authority 审批后进入 Implementation。
