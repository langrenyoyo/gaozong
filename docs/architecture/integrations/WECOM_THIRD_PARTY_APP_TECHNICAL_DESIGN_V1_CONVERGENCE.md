# 企业微信第三方应用技术设计 v1.0（架构收敛决策）

> 状态：APPROVED_PENDING_IMPLEMENTATION
> 决策类型：Architecture Convergence
> 主要基线：WECOM_THIRD_PARTY_APP_TECHNICAL_DESIGN_CODEX_INDEPENDENT.md
> 实施约束：单实例部署简化
> 范围：企业微信第三方应用替代 M04 的 19000 Personal WeChat 通知通道
> 本文只记录收敛后的决策，不启动实现。

## 0. 独立性与适用范围

本文依据 Owner 在当前任务中提供的 Decision Delta，以及当前已完成的独立设计基线形成。

本轮不读取、不搜索、不比较以下未关联脏文件：

    docs/architecture/integrations/WECOM_THIRD_PARTY_APP_TECHNICAL_DESIGN.md

本文是后续审批窗口和 VibeCoding 实施窗口的唯一收敛依据。两份历史设计不再作为并行方案；其中 Codex Independent 承担架构主基线，单实例约束、表名收敛和阶段范围以本文为准。

## 1. 最终架构

    Enterprise WeCom
      -> Third Party App Callback
      -> WeCom Callback Router
      -> Signature + AES Verify
      -> wecom_callback_events（Durable Inbox）
      -> Callback Worker
      -> Feedback Transaction Service
         -> Lead Timeline
         -> Lead Status（仅复用已有状态）
         -> Report Data
         -> Delivery Status

业务通知链：

    Lead Assignment
      -> WechatTask（保留，表示“需要通知销售”）
      -> merchant rollout policy
      -> Channel Adapter
         -> wecom（目标主通道）
         -> legacy_personal_wechat（测试期显式 fallback）
      -> WeComMessageDelivery
      -> Template Card
      -> Callback Button Feedback
      -> Lead / Timeline / Report

禁止企业微信失败后自动切换个人微信。未知外部发送结果不得盲目重发，避免双发。

## 2. 不变的业务决策

| 决策 | 最终结果 |
|---|---|
| 集成模式 | THIRD_PARTY_APPLICATION |
| 成员身份 | merchant_id + auth_corp_id + open_userid |
| 销售绑定 | 显式绑定 / 销售自绑定；禁止姓名、昵称、手机号、邮箱自动匹配 |
| 派单 | Template Card / button_interaction |
| 主反馈 | Template Card Callback |
| NLP 自由文本 | 非主链 |
| 外部任务身份 | 256 bit opaque random token；数据库只存 HMAC-SHA256 |
| WechatTask | RETAIN / ADAPT，不改名、不删除 |
| M06 | 无 Local Agent 依赖，不是 19000 退出 blocker |
| 19000 | 通过退出门后另立物理删除任务 |

## 3. 收敛差异

### 3.1 服务商运行凭证

v1.0 单实例不提前实现多实例共享 Token 架构：

- 采用 wecom_suite_runtime，保存 suite_ticket、更新时间和必要运行元数据；
- suite_access_token 和企业 corp_access_token 由后端获取，存进程内按 key 缓存；
- 每个 key 使用进程内锁，提前刷新；
- token 明确失效后只强制刷新一次；
- 刷新失败停止重试并 fail-closed；
- 未来运行实例达到 2 个或以上时，另立 Redis/DB 共享缓存升级任务。

本决定替代“第一阶段必须使用 PostgreSQL 共享 Token 缓存、advisory lock、token_version CAS”的过度实现约束；不替代安全要求。凭证仍不得返回前端、写入日志或 release identity。

### 3.2 最终六张核心表

第一版只设计并实施以下六张表：

1. wecom_suite_runtime：服务商运行状态，保存 suite_ticket 及更新时间。
2. wecom_enterprise_authorizations：merchant 与授权企业事实，保存 merchant_id、auth_corp_id、agent_id、加密永久码、授权状态和可见范围元数据。
3. wecom_member_snapshots：授权可见企业成员目录快照。
4. wecom_member_bindings：SalesStaff 与企业微信成员的显式绑定历史。
5. wecom_message_deliveries：一次企业微信发送及反馈事实。
6. wecom_callback_events：Callback Durable Inbox，负责接收、去重、重试和审计。

不采用 wecom_provider_credentials 表。第一版不新增独立 feedback receipts 表；反馈事实先由 delivery 行锁、唯一约束和状态机承载。

### 3.3 状态收敛

wecom_member_bindings 首版对外状态收敛为：

    ACTIVE
    UNBOUND
    SUSPENDED

数据库内部可保留 suspension_reason（授权取消、销售停用、成员离职、移出可见范围），但不扩展为多套对外业务状态。

wecom_callback_events 首版状态为：

    RECEIVED
    PROCESSING
    PROCESSED
    FAILED_RETRYABLE
    FAILED_PERMANENT
    IGNORED

安全拒绝事件仍必须审计；实现时可用 IGNORED 加 failure_stage=security_rejected，不新增业务状态。

## 4. 最终数据模型约束

### 4.1 wecom_suite_runtime

| 项目 | 决策 |
|---|---|
| 责任 | 服务商运行状态与 suite_ticket |
| 租户范围 | 服务商级，不接受 merchant_id 查询 |
| 字段 | suite_id、suite_ticket_encrypted、ticket_updated_at、last_refresh_at、status、created_at、updated_at |
| 唯一性 | suite_id |
| 敏感字段 | suite_ticket_encrypted |
| 日志 | 只记录版本、时间和安全错误码 |

suite_secret、Token、EncodingAESKey 继续只从后端 secret 配置读取，不入业务表。

### 4.2 wecom_enterprise_authorizations

必须包含：

    merchant_id
    auth_corp_id
    agent_id
    permanent_code_encrypted
    authorization_status
    visible_scope_metadata

状态：

    PENDING / ACTIVE / CHANGED / CANCELLED / INVALID

第一版禁止多个 merchant 同时 ACTIVE 复用同一 auth_corp_id。所有查询先从可信 merchant_id 进入，再校验授权。

### 4.3 wecom_member_snapshots

保存：

    authorization_id
    merchant_id
    auth_corp_id
    open_userid
    display_name
    department_summary
    member_status
    visible_scope

禁止保存手机号、邮箱；禁止姓名匹配。open_userid 只能在 merchant_id + auth_corp_id 边界内使用。

### 4.4 wecom_member_bindings

关系：

    SalesStaff <-> WeCom Member

规则：

- 只允许管理员显式绑定或已完成企业微信身份证明的销售自绑定；
- 同一 merchant 下，一个 active SalesStaff 最多一个 active 成员；
- 同一 merchant/auth_corp 下，一个 active open_userid 最多一个 active SalesStaff；
- 重复提交返回已有绑定，冲突返回确定性错误；
- 解绑保留历史，已发送 delivery 不删除；
- 销售停用、成员离职、授权取消时进入 SUSPENDED 并记录原因。

### 4.5 wecom_message_deliveries

保存：

    wechat_task_id
    merchant_id
    authorization_id
    member_binding_id
    lead_id
    sales_staff_id
    delivery_token_hash
    status
    external_msgid
    feedback_action
    feedback_at

状态：

    PENDING / SENDING / SENT / FAILED / FEEDBACK_RECEIVED

外部 token 不得包含 lead_id、merchant_id、sales_staff_id 或 delivery_id。

### 4.6 wecom_callback_events

责任：

    receive
    dedupe
    retry
    audit

必须具备：

- provider_event_key 唯一约束；
- callback 原文最小化保存或加密保存；
- RECEIVED -> PROCESSING -> PROCESSED 处理状态；
- lease、attempt_count、next_attempt_at；
- 失败阶段和安全错误码；
- callback worker 通过 opaque token 恢复 delivery，不信任事件 body 中的 merchant_id。

## 5. Callback 与幂等最终决策

链路固定为：

    WeCom Callback
      -> Verify Signature
      -> AES Decode
      -> INSERT wecom_callback_events
      -> ACK WeCom
      -> Callback Worker
      -> SELECT delivery FOR UPDATE
      -> Feedback Transaction
      -> Lead / Timeline / Report
      -> update_template_card（独立重试）

三层幂等：

1. Transport：provider_event_key UNIQUE。
2. Delivery：一个 delivery 只接受一次首个业务反馈。
3. Business：行锁只允许 SENT -> FEEDBACK_RECEIVED；已反馈不被新动作覆盖。

卡片置灰或更新失败不回滚已提交业务。回调路由器不得直接更新 Lead、Timeline 或 Report。

## 6. WechatTask 与通道迁移

保留 WechatTask 原有业务职责和 claim/lease 能力。增加 channel：

    legacy_personal_wechat
    wecom

企业微信凭证、open_userid、callback payload、external msgid 不写入 WechatTask；这些字段只属于授权、绑定、delivery 或 callback 表。

服务端 rollout policy：

    if wecom_enabled
       and authorization_active
       and member_binding_active:
        channel = wecom
    elif explicit_legacy_fallback:
        channel = legacy_personal_wechat
    else:
        BLOCKED

前端不得任意选择 channel。企业微信失败不得自动回退个人微信。

## 7. H5 范围收敛

H5 保留为 Secondary Feedback，用于详情、备注、复杂动作和需要二次确认的反馈。

第一版主链只实现：

    Template Card Button Feedback

H5 延期不影响核心派单和卡片反馈验收，也不阻断 M04 退出 19000；但 H5 投产前仍必须完成网页身份授权、merchant boundary 和 lead access 证据。延期不等于删除，也不把 NLP 自由文本提升为主链。

## 8. P0-P6 实施范围冻结

### Included

- P0 服务商账号、测试企业和官方许可/回调实证；
- P1 授权与凭证基础；
- P2 成员快照与显式绑定；
- P3 企业微信 Template Card 派单；
- P4 Callback Durable Inbox 与结构化反馈；
- P6 核心 E2E 和多租户验证。

### Deferred

- P5 H5；
- P8 19000 物理删除。

P7“关闭 M04 Personal WeChat runtime”必须在 P6 通过后单独执行；它不是本轮 P0-P6 的隐式副产物。P8 仍需全项目 Local Agent 依赖审计和独立退役任务。

## 9. Owner Decisions Required Before Coding

以下决策在实现前必须冻结：

1. Template Card 第一版按钮：contacted、no_answer、invalid_contact。
2. interested、invalid_lead、deal 分别写 Timeline、修改 Lead 状态、进入日报统计的映射。
3. 是否禁止多个 merchant ACTIVE 共用同一 auth_corp_id（推荐禁止）。
4. legacy fallback 的测试商户、时间窗口和关闭条件。
5. Credential Encryption Key 的项目级来源。

VibeCoding 窗口不得自行替代 Owner 决定。

## 10. P0 实施准备清单

P0 只做证据准备，不写业务实现：

- 服务商账号、测试企业和授权范围；
- suite_ticket 推送与签名/AES 配置；
- Template Card 发送、按钮回调和卡片更新真实样本；
- 第三方应用网页授权 appid 与成员身份换取链；
- 取消授权、授权变更、成员移出范围样本；
- 官方许可、接口收费和可见范围证据；
- callback 稳定事件标识与 ACK 格式；
- 脱敏 fixture、回放脚本和证据清单。

P0 验收标准：每个生产阻断项都有官方当前证据、真实请求/响应摘要、失败分类和回滚方式。P0 不创建 migration，不修改生产配置。

## 11. 禁止扩展

本版本禁止：

- externalcontact、客户群、朋友圈、会话存档；
- 企微客户 AI 自动聊天；
- NLP 反馈主链；
- 19000/OCR/鼠标自动化物理删除；
- M06 LAS 重构；
- 全项目 Repository、MVC 或 models 大拆分；
- 新增 Lead 核心状态；
- 自动姓名/手机号/邮箱匹配；
- 企业微信失败自动个人微信重发；
- 在 P0-P6 期间实现 H5 或物理退役。

## 12. 最终批准声明

    STATUS = APPROVED_PENDING_IMPLEMENTATION
    PRIMARY_DESIGN_BASELINE = Codex Independent Design
    IMPLEMENTATION_CONSTRAINT = Single Instance Simplification
    PRIORITY = Reliability First
    TARGET = Remove M04 runtime dependency on 19000
    CODE_CHANGE = 0
    DB_CHANGE = 0
    PRODUCTION_CHANGE = 0
    P0_STATUS = PREPARATION_ONLY
    COMMIT = NO
    PUSH = NO
    DEPLOYMENT = NO

本文件是架构收敛记录，不是 P0 实施授权。进入 P0 实施时必须另行创建实施计划、列出 migration/API/worker 变更并执行对应审批与验证门。

## 12A. P0 实测协议事实（WECOM_CALLBACK_RECEIVE_ID_RULE）

> SOURCE = 2026-08-20 P0 real WeCom verification（merchant.xiaogaoai.cn）
> 状态：FROZEN —— 来自真实企业微信环境，后续"统一实现"不得重新覆盖。

### GET_VERIFY_URL

- signature verification = REQUIRED
- AES decrypt = REQUIRED
- **不强制 receiveid == WECOM_SUITE_ID**
- P0 真实环境证明：verifyURL 的 echostr 加密 receiveid 可为 corpid（实测 wwaa 前缀 18 位），
  而非 suite_id；以 receiveid == suite_id 作为 GET 合法性判断会误拒真实验证
- 来源真实性由 signature + AES verification 保证（只有持有 Token 的企微后台能通过验签）
- 不允许未来仅为了代码统一重新加入 receiveid == suite_id equality check

### POST_COMMAND_CALLBACK

- signature verification = REQUIRED
- AES decrypt = REQUIRED
- 保留第三方 suite identity / suite_id 校验（suite_ticket 等指令事件按 suite identity 路由）
- P0 实测：suite_ticket 推送的 receiveid == suite_id，该校验真实有效

### DATA_CALLBACK

- P0 已证明 command/data 可共用同一物理 URL：
  `https://merchant.xiaogaoai.cn/api/integrations/wecom/callback`
- 当前 Token / EncodingAESKey 可共用
- SAME_PHYSICAL_CALLBACK_URL = VALIDATED

安全边界：本文件不记录真实 Token / EncodingAESKey / SuiteTicket / 解密 payload。

## 13. 文档影响

本轮只新增架构收敛文档，不改变当前运行代码、模块 Owner、G1/G2/G3/G4 拓扑事实：

    G1_DELTA = NO
    G2_DELTA = NO
    G3_DELTA = NO
    G4_DELTA = NO
    DOCUMENT_IMPACT = NEW DECISION RECORD ONLY
