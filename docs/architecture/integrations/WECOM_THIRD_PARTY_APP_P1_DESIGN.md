# 企业微信第三方应用 P1 设计 v1.0（Design Authority 输出）

```text
TASK                  = P1-WECOM-THIRD-PARTY-APPLICATION-DESIGN-v1.0
TASK_LEVEL            = L3
AUTHORITY             = Design Authority
OWNER                 = M04
TASK_TYPE             = DESIGN_ONLY
CODE_CHANGE           = NOT AUTHORIZED（本文件不产生代码）
DB_CHANGE             = NOT AUTHORIZED（本文件不产生 migration）
IMPLEMENTATION        = NOT AUTHORIZED
PRODUCTION_CHANGE     = NOT AUTHORIZED
STATUS                = P1 READY_PENDING_OWNER_DECISIONS
DATE                  = 2026-08-21
```

> 修订标注：**SPEC_CORRECTION-1（DA 裁决 2026-08-21）**——`wecom_enterprise_authorizations.merchant_id`
> 类型为 `String(128)`（与全仓 30+ 处 merchant_id 一致，生产格式 `m_nc_...`），非 INTEGER。
> 见 `WECOM_THIRD_PARTY_APP_P1_SPEC-v1.0.md` §2.2 修订。

> 本文是 P1 架构设计输出，只做设计、不做实施。所有开放问题一律标记 `[DECISION_REQUIRED]`，
> 不得由 Design Authority 或后续 Implementation 自行替代 Owner 决定。
> 设计基线：`WECOM_THIRD_PARTY_APP_TECHNICAL_DESIGN_V1_CONVERGENCE.md`（APPROVED_PENDING_IMPLEMENTATION）、
> `WECOM_THIRD_PARTY_APP_API_EXPLORATION.md`（能力证据）、`WECOM_THIRD_PARTY_APP_IMPLEMENTATION_PLAN_V1.md`（阶段规划）、
> `wecom_p0/evidence_checklist.md`（P0 实测证据）。
> 未确认的企业微信能力一律按官方证据标注，禁止凭经验补全。

---

## 1. Current State

### 1.1 已冻结的事实

- **P0 = CLOSED_PASS（2026-08-20 真实回调验证）**：
  - 公网 HTTPS 回调已部署 `https://merchant.xiaogaoai.cn/api/integrations/wecom/callback`，外网可达（非 404/502/503）；
  - GET verifyURL = PASS（验签 + AES 解密 + echostr 明文返回）；**实测 echostr 加密 receiveid 是 corpid（wwaa 前缀 18 位），非 suite_id**；
  - 指令回调保存 = PASS；suite_ticket 10 分钟稳定投递 ×3（ticket_hash 前缀脱敏），ACK `success` 返回 200，后台无持续报错；
  - 数据回调保存 = PASS；**指令/数据共用同一物理 URL，Token/EncodingAESKey 共用 = VALIDATED**；
  - `WECOM_CALLBACK_RECEIVE_ID_RULE = FROZEN`（GET 不强制 receiveid==suite_id；POST 指令回调保留 receiveid==suite_id 校验）。
- **已落地 Probe 代码（仅协议层，零业务）**：
  - `app/routers/wecom_callback.py`：GET 验签+解密+明文返回；POST 验签+解密+最小事件识别+安全日志+ACK，不写库；
  - `app/integrations/wecom/crypto.py`：签名校验（SHA1 字典序）、AES-256-CBC（PKCS7）、XXE 拒绝；
  - `app/config.py:340-342`：`WECOM_CALLBACK_TOKEN` / `WECOM_CALLBACK_ENCODING_AES_KEY` / `WECOM_SUITE_ID`（env 注入，缺省 fail-closed）；
  - `tests/test_wecom_callback_probe.py`：19 项协议测试全 PASS；
  - 已部署生效 commit `ec506ef`（含路由前缀对齐 + verifyURL receiveid 两项修复）。
- **设计基线已定稿**：收敛设计 v1.0 = APPROVED_PENDING_IMPLEMENTATION；实施计划 v1.0 = IMPLEMENTATION_PLAN_PENDING_OWNER_APPROVAL。
- **当前 M04 运行事实**：个人微信链路由 19000 Local Agent 承载（派单=搜索联系人/OCR/粘贴发送；反馈=OCR 读气泡+关键词判定）；
  `wechat_tasks` 已具备 P2-M04 claim/lease（`claim_token_hash/lease_expires_at/attempt_count/claimed_by`，models.py:332-337）；
  `sales_staff`（models.py:94-117）持 `wechat_id/wechat_nickname/phone` 个人微信身份字段，无企微身份字段。

### 1.2 未决事项（进入 P1 实现的输入）

- 收敛设计 §9 五项编码前业务决策未冻结；实施计划 §12 两项 Owner 决策（OWNER_DECISION_03 / OWNER_DECISION_05）未冻结。
- 6 项 `UNKNOWN_OFFICIAL_CAPABILITIES`（U1~U6）仍需服务商账号实测补证（见 API_EXPLORATION §19）。
- 外部资源 R1~R5（服务商主体/测试企业/公网回调/测试成员/基础接口许可）部分就绪（R3 公网回调已就绪并实测；R1/R2/R4/R5 待 Owner 提供）。
- 19000 退役 = CONDITIONAL，阻塞项 B1~B6 见 API_EXPLORATION §18；M06 剪辑本地执行面独立于本链路。

### 1.3 设计前提

本设计不改变以下已批准收敛决策：集成模式=THIRD_PARTY_APPLICATION；成员身份=merchant_id+auth_corp_id+open_userid；
显式自绑定；派单=Template Card button_interaction；反馈主=卡片回调（F2）、次=H5（P5 延期）、NLP=兜底非主链；
WechatTask RETAIN/ADAPT；单实例 Token 缓存；六张核心表；禁止企微失败自动切个人微信。

---

## 2. Design Goals

| # | 目标 | 验收方向（不在本轮实施） |
|---|---|---|
| G1 | 移除 M04 对 19000 / 个人微信的运行依赖（TARGET） | P6 后 M04_RUNTIME_DEPENDENCY_ON_19000 = 0 |
| G2 | 可靠性优先：回调不保证 100% 投递，须对账兜底；未知外部结果不盲目重发 | 回放/崩溃只产生一次业务反馈 |
| G3 | 多商户 SaaS 授权隔离：auth_corp_id ↔ merchant_id 一一绑定，凭证 merchant scoped | 跨商户正负例全 PASS |
| G4 | 结构化反馈免 OCR / 免 NLP：Template Card 按钮回调为主链 | 反馈采集链路无 OCR、无关键词判定 |
| G5 | 安全 fail-closed：验签/解密/配置缺失/未知 corpid 一律拒绝并审计 | 安全拒绝事件可审计、不泄露细节 |
| G6 | 单实例简化：进程内按 key 缓存 token，不提前引入分布式共享缓存 | 单实例下 token 不重复获取、失效强刷一次 |
| G7 | 不破坏既有业务：WechatTask 职责与 claim/lease 保留，channel 扩展，历史任务默认 legacy | 旧任务与新任务不混淆、无双发 |

---

## 3. Enterprise WeChat authorization lifecycle

### 3.1 授权状态机（wecom_enterprise_authorizations.authorization_status）

```text
        [创建授权入口]
             │
             ▼
         PENDING ──(扫码安装完成, get_permanent_code v2 成功 + get_auth_info 回填 agentid/privilege)──▶ ACTIVE
             │                                                                                        │
             │(auth_code 过期/失败)                                                                   │
             ▼                                                                                        │
        FAILED  ◀──────────────────────────────────────────────────────────────────────────┐         │
                                                                                            │         │
   (change_auth 事件 / 定期对账发现变更)                                                     │         ▼
        ──────────────────────────────────────────────────────────────────────────────▶ CHANGED ──▶（重新 get_auth_info 同步，回到 ACTIVE）
                                                                                            │
   (cancel_auth 事件 / 对账发现授权取消)                                                     ▼
        ──────────────────────────────────────────────────────────────────────────────▶ CANCELLED
                                                                                            │
   (permanent_code 换码失败 / 安全事件)                                                      ▼
        ──────────────────────────────────────────────────────────────────────────────▶ INVALID
```

- 触发源：`create_auth`（应用市场发起）/ `change_auth`（含可见范围变更）/ `cancel_auth` / `reset_permanent_code` / 定期 `get_auth_info` 对账。
- **回调不保证 100% 成功（官方明示）**：状态迁移必须以「事件 + 定期对账」双源驱动，事件优先、对账兜底。
- 授权类事件要求 **1000ms 内响应**：Callback 入口只落库 + ACK，状态迁移交给异步 Worker。
- `cancel_auth` 官方要求"删除该企业所有相关数据"——本设计落地为：状态置 CANCELLED、绑定 SUSPENDED、凭证不可再用（见 4.3 与 5.4）。
- `reset_permanent_code`：用新 auth_code 换最新 permanent_code，原码作废，状态保持 ACTIVE 但触发 credential 轮换。
- `[DECISION_REQUIRED]` U3：cancel_auth 后 permanent_code 是否自动失效，官方未说明。设计默认 fail-closed 置 INVALID，但该策略须 Owner 确认（见 13-D2）。

### 3.2 授权发起链（Phase A/B）

```text
服务商后台配置（suite_id/suite_secret/Token/EncodingAESKey）
  → get_suite_token（suite_access_token, 2h）
  → get_pre_auth_code（pre_auth_code, 20min 一次性）
  → 3rdapp/install 授权 URL（redirect_uri + state）
  → 管理员扫码 + 选可见范围（allow_user/party/tag）
  → 回调 auth_code（10min 一次性）
  → get_permanent_code v2（permanent_code + auth_corp_info；v2 不返回 agentid）
  → get_auth_info v2（回填 agentid + privilege 可见范围）
  → 落库 wecom_enterprise_authorizations = ACTIVE
```

- `state` 防 CSRF：授权 URL 的 state 必须随机、一次性、带过期，回调校验。
- 同一 auth_corp_id 重复授权：幂等处理（已存在 ACTIVE 则返回已有；状态冲突返回确定性错误）。

### 3.3 对账任务（B4 兜底）

- 定期（`[DECISION_REQUIRED]` 频率，建议 1 小时级，见 13-D8）对每个 ACTIVE 授权调 `get_auth_info`，比对 `agentid/privilege` 与库内值；
- 发现差异 → 进 CHANGED 并按 3.1 回 ACTIVE（同步可见范围）；发现授权消失 → CANCELLED。
- 对账任务与 cancel_auth 事件竞争：以"库内状态 + 对账结果"为最终一致源，事件只做加速。

---

## 4. Credential lifecycle model

### 4.1 凭证三层模型

| 层级 | 凭证 | 生命周期 | 持久化 | 敏感度 |
|---|---|---|---|---|
| SERVICE_PROVIDER（服务商级） | suite_id / suite_secret | 长期 | secret 配置（不入表） | 高 |
| SERVICE_PROVIDER | Token / EncodingAESKey | 长期（回调配置） | secret 配置（不入表） | 高 |
| SERVICE_PROVIDER | suite_ticket | 30min 有效 / 10min 推送，只用最新值 | `wecom_suite_runtime.suite_ticket_encrypted`（加密） | 高 |
| SERVICE_PROVIDER | suite_access_token | 2h | 进程内缓存 | 高 |
| MERCHANT（企业级） | auth_corp_id（密文 corpid） | 长期 | `wecom_enterprise_authorizations` | 高 |
| MERCHANT | permanent_code | 永久 | `wecom_enterprise_authorizations.permanent_code_encrypted`（加密） | 高 |
| MERCHANT | agentid | 长期 | `wecom_enterprise_authorizations` | 中 |
| MERCHANT | corp_access_token | 2h | 进程内缓存（merchant 隔离） | 高 |
| MEMBER（成员级） | open_userid | 长期 | `wecom_member_snapshots` / `wecom_member_bindings` | 中 |

### 4.2 Token 缓存模型（G6 单实例）

- 服务商级与 merchant 级 token 均：**进程内按 key 缓存 + 每 key 一把进程内锁 + 提前刷新**；
- 锁内先读缓存（double-check），未命中才调官方接口；同一 key 并发只放行一次获取；
- token 明确失效（官方错误码指示）→ **只强制刷新一次**，仍失败即 fail-closed，不无限重试；
- 刷新失败停止重试并记安全日志（stage/error_code，不含明文）；
- **未来实例 ≥2 时**：另立 Redis/DB 共享缓存升级任务（本期不实现，见 12）；
- suite_ticket 每次收到新值即更新 `wecom_suite_runtime`（加密落库），token 获取始终用库内最新 ticket。

### 4.3 持久化与加密

- `permanent_code` / `suite_ticket` 落库前加密；**加密主密钥来源 = OWNER_DECISION_05**（见 13-D1）；
- 日志只记版本、时间、安全错误码；凭证明文、解密结果、ticket 明文一律不进日志；
- `corp_access_token` 缓存键 = `merchant_id:auth_corp_id`，禁止全局共享 token 池（见 5.3）。

---

## 5. Merchant isolation model

### 5.1 绑定规则

- `auth_corp_id`（密文 corpid，服务商主体下全局稳定）↔ `merchant_id` 一一绑定；
- **`[DECISION_REQUIRED]`（OWNER_DECISION_03）**：是否禁止多个 merchant 同时 ACTIVE 复用同一 auth_corp_id——设计推荐**禁止**（唯一约束兜底），见 13-D3；
- 所有查询入口先从可信 `merchant_id`（RequestContext，禁止前端传入）进入，再校验该 merchant 的授权记录。

### 5.2 数据归属

| 数据 | 归属 | 依据 |
|---|---|---|
| permanent_code / corp_access_token / agentid | merchant scoped（每企业一个） | /100776 /90605 /100779 |
| 成员身份（open_userid / 密文 corpid） | merchant scoped | /98728 |
| 部门目录 | merchant scoped | /90196 |
| callback 事件 | 按 ToUserName（密文 corpid）解析 merchant | /90240 |
| message delivery | merchant scoped（企业 token+agentid 发送） | /90236 |

### 5.3 隔离红线

1. A 商户 token 绝不能读取/发送 B 商户数据；
2. 回调统一入口解密 → 按 ToUserName 解析 merchant → 拒绝未知 corpid（fail-closed）；
3. touser 一律用该 merchant 自己绑定表解析出的 open_userid；
4. 前端不得持有任何企微凭证，不得传 merchant_id/auth_corp_id/permanent_code/Token；
5. 明文 userid / external_userid 不进 9000（第三方应用官方禁止获取）。

### 5.4 取消授权的隔离收口

- CANCELLED 后：该 merchant 下所有绑定 SUSPENDED、delivery 不再新建、corp_access_token 缓存失效；
- 已发送/已反馈事实保留（历史可审计），不删除；
- 对账任务在 cancel 后不再对该 auth_corp_id 发起任何官方调用（fail-closed）。

---

## 6. WeCom organization/member sync design

### 6.1 同步来源与口径

- 数据源：企业 access_token 下的部门列表 + 部门成员接口（受应用可见范围限制，范围外不可读）；
- 身份主线：**open_userid**（全局唯一、同服务商跨应用一致）；`userid` 第三方不保证明文（读取接口返回实际填充 open_userid）；
- 可见范围：来自 `get_auth_info` 的 `privilege.allow_user/allow_party/allow_tag`，管理员可修改，`change_auth` 触发变更。

### 6.2 快照表（wecom_member_snapshots）

- 保存：authorization_id / merchant_id / auth_corp_id / open_userid / display_name（第三方无真实姓名，以 userid 代替）/ department_summary / member_status / visible_scope；
- **禁止保存手机号、邮箱**（第三方不可获取，官方默认不返回）；禁止姓名匹配；
- member_status：1 已激活 / 2 禁用 / 4 未激活 / 5 退出（官方语义）；
- open_userid 只在 merchant_id + auth_corp_id 边界内使用。

### 6.3 同步触发

- `change_auth` 事件 → 触发可见范围重拉（增量）；
- 定期快照刷新（`[DECISION_REQUIRED]` 频率，与 3.3 对账同一调度，见 13-D8）；
- 成员移出可见范围 / 停用 / 退出 → 快照标记 + 关联绑定 SUSPENDED（见 7.4）。

### 6.4 未确认项

- `[DECISION_REQUIRED]` U4：同一自然人换企业后 open_userid 是否相同，官方未明说——跨企业语义按"每个 auth_corp_id 独立成员身份"设计，不做跨企业合并（见 13-D6）；
- 第三方部门/成员 name 不返回真实值——同步仅用于"选择成员"，不可用于自动匹配销售（强制显式绑定）。

---

## 7. sales_staff binding design

### 7.1 绑定原则（G4）

- **只允许显式绑定**：管理员显式绑定，或已完成企业微信身份证明的销售自绑定；
- **禁止**姓名、昵称、手机号、邮箱自动匹配（第三方无真实姓名/手机/邮箱，且自动匹配违反安全底线）；
- 绑定实体 = `wecom_member_bindings`（SalesStaff ↔ WeCom Member），不在 sales_staff 加企微身份列（复用 ExternalMerchantBinding 模式，models.py:120 既有先例）。

### 7.2 唯一性约束（双向 active 唯一）

- 同一 merchant 下：一个 active SalesStaff ≤ 1 个 active 成员；
- 同一 merchant + auth_corp 下：一个 active open_userid ≤ 1 个 active SalesStaff；
- 数据库唯一约束兜底并发（active partial unique），重复提交返回已有绑定，冲突返回确定性错误。

### 7.3 对外状态

```text
ACTIVE     绑定生效，可派单
UNBOUND    未绑定
SUSPENDED  临时不可派单（suspension_reason：授权取消 / 销售停用 / 成员离职 / 移出可见范围）
```

- 解绑保留历史（binding 历史行 + 已发送 delivery 不删除）；解绑 = 新行 UNBOUND/SUSPENDED，不改写旧行；
- 前端使用 surrogate member id，不直接枚举 open_userid。

### 7.4 生命周期联动

| 事件 | 绑定动作 |
|---|---|
| 成员移出可见范围 | SUSPENDED（reason=scope_removed） |
| 成员停用/退出（status 2/5） | SUSPENDED（reason=member_inactive） |
| 销售停用（sales_staff.status=inactive） | SUSPENDED（reason=staff_inactive） |
| 授权取消（CANCELLED） | 全部 SUSPENDED（reason=auth_cancelled） |
| 授权恢复 / 成员回范围 | 按显式操作恢复 ACTIVE（不自动恢复） |

### 7.5 销售自绑定（依赖 U1）

- 路径：H5/网页 OAuth `getuserinfo3rd` 取成员身份 → 与待绑定 SalesStaff 匹配 → 写入 binding；
- **`[DECISION_REQUIRED]` U1**：第三方网页授权构造链接 appid 取值（suite_id 或 corpid）官方门禁内未确认；若不可行，**降级为管理员显式绑定**（不阻断 P1，见 13-D5）。

---

## 8. Callback architecture

### 8.1 物理入口（已 VALIDATED）

- 单一物理 URL：`/integrations/wecom/callback`（9000 内部路由不带 /api 前缀，nginx 剥离 /api 后匹配，项目惯例）；
- 指令回调与数据回调共用同一 URL + Token/EncodingAESKey（P0 实测 VALIDATED）；
- GET = 后台 URL 验证：验签 + AES 解密 + 1 秒内返回精确明文（无引号/BOM/换行）；**不强制 receiveid==suite_id（FROZEN，实测 echostr receiveid=corpid）**；
- POST = 指令/数据回调：验签 → AES 解密 → receiveid==suite_id 校验（指令语义）→ 事件识别 → 落库 → ACK。

### 8.2 POST 处理管线（P4 目标，P1 只到事件识别+落库雏形）

```text
WeCom POST
  → verify signature（SHA1 字典序, 恒定时间比较）
  → AES-256-CBC 解密（PKCS7, XXE 拒绝）
  → receiveid 校验（命令类 == suite_id；数据类按 ToUserName 路由）
  → 计算 provider_event_key（见 9.1）
  → INSERT wecom_callback_events（RECEIVED）   ← 幂等去重点
  → ACK "success"（授权类 ≤1000ms，一般 ≤5s）
  ───────────────── 异步 Worker ─────────────────
  → 事件分类
       ├─ 指令类（suite_ticket / create_auth / change_auth / cancel_auth / reset_permanent_code）→ 授权生命周期 Worker（3.1）
       └─ 数据类（template_card_event）→ 反馈事务 Worker（8.3）
```

- **Router 不直接更新 Lead / Timeline / Report**；业务更新只发生在 Worker 的事务内；
- 验签/解密失败、未知 corpid、安全拒绝 → fail-closed + 审计（IGNORED + failure_stage=security_rejected）；
- ACK 语义：指令回调返回字符串 `success`；5s 超时官方重试 3 次——必须幂等落地（见 9）。

### 8.3 反馈事务 Worker（F2 主链）

```text
template_card_event（EventKey=反馈类型, TaskId=opaque token, FromUserName=open_userid）
  → 解析 delivery（由 TaskId 恢复, 不信任 body 内 merchant_id）
  → SELECT delivery FOR UPDATE（3.2 节行锁）
  → 状态校验（只接受 SENT → FEEDBACK_RECEIVED, 见 9.2）
  → Feedback Transaction（Lead Timeline / Lead Status / Report Data / Delivery Status）
  → update_template_card（置灰/更新, 独立重试, 失败不回滚已提交业务）
```

### 8.4 H5 Secondary Feedback（P5 延期）

- 仅用于详情、备注、复杂反馈、二次确认；第一版主链只实现卡片按钮反馈；
- H5 投产前仍须完成网页身份授权、merchant boundary、lead access 证据（U1 关联）；
- 延期不等于取消，不把 NLP 自由文本提升为主链。

---

## 9. Idempotency / retry design

### 9.1 三层幂等

| 层 | 机制 | 依据 |
|---|---|---|
| Transport | `wecom_callback_events.provider_event_key` UNIQUE | 官方回调无消息 ID/幂等 key、重试 3 次可能重复投递且乱序，幂等键由服务商自设计 |
| Delivery | 一个 delivery 只接受一次首个业务反馈 | delivery 状态机 + 行锁 |
| Business | 行锁只允许 `SENT → FEEDBACK_RECEIVED`；已反馈不被新动作覆盖 | 事务内校验 |

- **provider_event_key 设计**：指令类 = `InfoType + SuiteId + AuthCorpId + CreateTime`；数据类 = `FromUserName + CreateTime`（官方建议口径）；
  `[DECISION_REQUIRED]` 若实测发现更稳定字段（如 MsgId / ResponseCode），以 P0 实测回放为准调整（见 13-D7）；
- 重复投递：INSERT 冲突 → 已存在则直接 ACK `success`（不重复处理）；
- 乱序投递：状态机拒绝非法迁移，不覆盖已提交事实。

### 9.2 Delivery 状态机（wecom_message_deliveries）

```text
PENDING → SENDING → SENT → FEEDBACK_RECEIVED（终态）
                    └─→ FAILED（发送失败, 按错误码分类）
```

- 外部任务身份：`task_id` = opaque token（256 bit 随机，格式 `wecom:{delivery_id}:{nonce}`，≤128 字节）；**数据库只存 delivery_token_hash（HMAC-SHA256）**；
- 外部 token 不得包含 lead_id / merchant_id / sales_staff_id / delivery_id；
- `enable_duplicate_check` + `duplicate_check_interval`（官方默认 1800s）防同样内容重复下发（官方侧二次防线）；
- 未知外部结果（发送 API 超时/无明确 msgid）：不盲目重发，进入人工/对账路径（防双发）。

### 9.3 Callback Worker 重试

- `lease` + `attempt_count` + `next_attempt_at`（复用 P2-M04 claim/lease 既有模式，models.py:332-337 先例）；
- 失败分类：`FAILED_RETRYABLE`（重试，backoff）/ `FAILED_PERMANENT`（记录 + 告警，不无限重试）/ `IGNORED`（安全拒绝/未知事件）；
- Worker 崩溃恢复：从 RECEIVED/FAILED_RETRYABLE 重新领取，靠 provider_event_key UNIQUE + delivery 行锁保证一次且仅一次业务反馈；
- 卡片更新失败不回滚已提交业务；卡片置灰失败可独立重试（72h 内 response_code 一次性）。

---

## 10. Security boundary

### 10.1 凭证安全

- suite_secret / Token / EncodingAESKey / permanent_code / corp_access_token / suite_ticket：**绝不进前端、绝不进日志明文、绝不进 release identity / env example**；
- 落库加密：permanent_code、suite_ticket（主密钥来源 = OWNER_DECISION_05）；
- 动态 token（suite_access_token / corp_access_token）：只存进程内缓存，不落库。

### 10.2 回调与消息安全

- 回调：验签（恒定时间比较）→ AES 解密 → receiveid/内层 suite_id 双校验 → 未知 corpid 拒绝；
- 配置缺失（Token/AESKey/SuiteID）→ fail-closed（不 500、不泄露原因）；
- XML 解析拒绝 XXE；AES 非法密文/填充拒绝；
- 发送：touser 只取绑定表 open_userid；`81013/invaliduser/unlicenseduser` 回写"该销售不可达"，不盲目重试。

### 10.3 数据最小化与日志

- 快照不存手机号/邮箱；明文 userid/external_userid 不进 9000；
- 日志只记 stage / result / event_type / error_code / suite_id / ticket_hash 前缀 / auth_corp_id（均为脱敏 metadata）；
- 响应仅 `success` / `verification failed`，不含内部细节。

### 10.4 限频与许可（官方约束，设计内承接）

- 每应用对同一成员 ≤ 30 次/分、1000 次/时，超出丢弃——派单侧需排队/限频；
- 未许可成员 = unlicenseduser、全无权限 = 81013——设计为可诊断失败分类并回写，不当作瞬时错误重试；
- `[DECISION_REQUIRED]` 服务商许可/收费规则（U5）未确认——影响 P6 放量与成本评估（见 13-D4）。

---

## 11. Migration strategy from Personal WeChat

### 11.1 WechatTask RETAIN / ADAPT（不改名、不删除）

- 新增 `channel` 列：`legacy_personal_wechat` / `wecom`；
- 历史任务默认 `legacy_personal_wechat`；19000 poll 必须过滤 `channel=personal_wechat`（防企微任务被个人微信执行）；
- 企微凭证、open_userid、callback payload、external msgid **不写入 WechatTask**，只属于授权/绑定/delivery/callback 表；
- WechatTask 原有业务职责与 claim/lease 能力保留（P2-M04 资产复用）。

### 11.2 服务端 rollout policy（不允许前端选 channel）

```text
if wecom_enabled and authorization_active and member_binding_active:
    channel = wecom
elif explicit_legacy_fallback:
    channel = legacy_personal_wechat   # 仅测试期显式开关，不自动
else:
    BLOCKED                            # 不发送，回写原因
```

- **禁止企业微信失败后自动切换个人微信**（防双发）；
- `[DECISION_REQUIRED]` legacy fallback 的测试商户、时间窗口、关闭条件（OWNER 决定，见 13-D9）。

### 11.3 双轨验证 → 退出门

```text
P0 官方能力实证（已完成 PASS）
  → P1 授权与凭证基础（本设计，待 Owner 决策）
  → P2 成员快照与绑定
  → P3 Template Card 派单（channel=wecom）
  → P4 Callback Durable Inbox 与结构化反馈
  → P6 核心 E2E + 多租户验证（W1-W6, W8-W10 PASS）
  → P7 关闭 M04 对 19000 的 runtime 依赖（单独执行, 不删除代码）
  → P8 全项目 Local Agent 依赖审计 + 独立退役任务
```

- P5 H5 延期，不得在 P0-P4 偷渡实现；
- P7 不是 P0-P6 的隐式副产物，必须单独执行并经 Owner + Verification Authority 签字；
- P8 物理删除 19000 另立任务（当前 19000 还承载 AI 剪辑本地执行面，属 M06 独立处置）。

### 11.4 回滚

- rollout 按 merchant，默认关闭；P1-P4 migration 向前兼容，关闭开关不删除历史；
- 只允许明确批准的 legacy fallback，禁止单任务双发；
- 已发送/已反馈事实不因回滚重发或回退；cancel_auth 永远优先；P7 rollback 限时且需 Owner 审批。

---

## 12. Explicitly NOT DO（本版本禁止）

- ❌ 不写代码、不生成 migration、不进入 Execution、不提交不推送（本设计阶段）；
- ❌ externalcontact、客户群、朋友圈、会话存档；
- ❌ 企微客户 AI 自动聊天；
- ❌ NLP 反馈主链（自由文本仅兜底，不提升为主链）；
- ❌ 19000 / OCR / 鼠标自动化物理删除；
- ❌ M06 LAS 重构（无 Local Agent 依赖，非 blocker，但不在本任务范围）；
- ❌ 全项目 Repository / MVC / models 大拆分；
- ❌ 新增 Lead 核心状态；
- ❌ 自动姓名/手机号/邮箱匹配销售；
- ❌ 企业微信失败自动个人微信重发（无自动回退）；
- ❌ 在 P0-P6 期间实现 H5 或物理退役 19000；
- ❌ 恢复 `wecom_provider_credentials` 表（不采用）；
- ❌ 提前实现 Redis/DB 共享 Token 缓存（单实例收敛，未来 ≥2 实例另立任务）；
- ❌ 假设未确认的企业微信能力（U1~U6 未实测前不进入实现假设）；
- ❌ 以 `create_all` 代替 Alembic 迁移；开发阶段禁止直连生产数据库。

---

## 13. Decision Points requiring approval

> 以下决策必须在 P1 实现开始前由 Owner 冻结；Design Authority / Implementation 不得自行替代。

| # | 决策 | 关联 | 设计推荐 | 状态 |
|---|---|---|---|---|
| D1 | permanent_code / suite_ticket 加密主密钥的项目级来源（OWNER_DECISION_05） | 4.3 / 10.1 | 独立 secret 配置，不入 env example / release identity；来源由 Owner 指定 | **`[DECISION_REQUIRED]`** |
| D2 | cancel_auth 后 permanent_code 失效策略（U3） | 3.1 / 5.4 | fail-closed 置 INVALID（即使官方未明示自动失效） | **`[DECISION_REQUIRED]`** |
| D3 | 是否禁止多个 merchant ACTIVE 复用同一 auth_corp_id（OWNER_DECISION_03） | 5.1 | **禁止**（唯一约束兜底） | **`[DECISION_REQUIRED]`** |
| D4 | 服务商基础接口许可/收费规则（U5）对 P6 放量与成本的影响 | 10.4 | 以商务/官方确认结果为准 | **`[DECISION_REQUIRED]`** |
| D5 | 销售自绑定可行性（U1 第三方 OAuth appid 取值） | 7.5 | 不可行则降级管理员显式绑定，不阻断 P1 | **`[DECISION_REQUIRED]`** |
| D6 | 同一自然人换企业后 open_userid 语义（U4） | 6.4 | 按每个 auth_corp_id 独立成员身份，不跨企业合并 | **`[DECISION_REQUIRED]`** |
| D7 | callback provider_event_key 稳定字段确认（E7） | 9.1 | 默认 InfoType+SuiteId+AuthCorpId+CreateTime / FromUserName+CreateTime；以 P0 实测回放为准 | **`[DECISION_REQUIRED]`** |
| D8 | 对账/快照刷新频率（B4 兜底调度） | 3.3 / 6.3 | 建议小时级（具体值 Owner 确认） | **`[DECISION_REQUIRED]`** |
| D9 | legacy fallback 的测试商户、时间窗口、关闭条件 | 11.2 | 测试期显式开关，默认关闭；关闭条件=W1-W6 PASS | **`[DECISION_REQUIRED]`** |
| D10 | Template Card 第一版按钮集合与动作映射 | 收敛 §9 | contacted / no_answer / invalid_contact；interested/invalid_lead/deal 到 Timeline/Lead 状态/日报的映射 | **`[DECISION_REQUIRED]`** |
| D11 | 服务商主体归属（B1）与测试企业（R2）提供方 | P0 清单 | Owner 提供 | **`[DECISION_REQUIRED]`** |
| D12 | P1 阶段范围确认（授权与凭证基础 = wecom_suite_runtime + wecom_enterprise_authorizations + 授权状态机 + WeComCredentialService + 回调 transport 扩展） | 实施计划 §3 | 按实施计划 P1 范围执行，P2+ 另立阶段 | **`[DECISION_REQUIRED]`** |

---

## 14. 当前状态声明

```text
TASK                = P1-WECOM-THIRD-PARTY-APPLICATION-DESIGN-v1.0
STATUS              = DESIGN_READY_PENDING_OWNER_DECISIONS
DESIGN_BASELINE     = WECOM_THIRD_PARTY_APP_TECHNICAL_DESIGN_V1_CONVERGENCE.md（APPROVED_PENDING_IMPLEMENTATION）
P0_STATUS           = CLOSED_PASS（2026-08-20 真实回调验证）
CODE_CHANGE         = 0
DB_CHANGE           = 0
PRODUCTION_CHANGE   = 0
MIGRATION           = NONE（本设计不生成 migration）
DECISION_REQUIRED   = 12 项（见 §13 D1-D12）
COMMIT              = NO
PUSH                = NO
DEPLOYMENT          = NO
DOCUMENT_IMPACT     = NEW DESIGN RECORD ONLY（G1/G2/G3/G4_DELTA = NO，不改代码/owner/CHAIN 事实）
```

> 本文是 P1 架构设计记录，不是实施授权。D1~D12 冻结并由 Owner 批准后，方可进入 P1 实施窗口
> （届时另行创建实施计划并列出 migration/API/worker 变更与验证门）。
