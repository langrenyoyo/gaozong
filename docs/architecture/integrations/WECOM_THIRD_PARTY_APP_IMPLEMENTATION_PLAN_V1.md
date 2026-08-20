# 企业微信第三方应用实施计划 v1.0

> 状态：IMPLEMENTATION_PLAN_PENDING_OWNER_APPROVAL
> 决策依据：WECOM_THIRD_PARTY_APP_TECHNICAL_DESIGN_V1_CONVERGENCE.md
> 主架构基线：WECOM_THIRD_PARTY_APP_TECHNICAL_DESIGN_CODEX_INDEPENDENT.md
> 当前阶段：仅规划，不执行代码修改

## 0. 计划边界

本计划严格执行 Decision Delta v1.0：

- 集成模式固定为 THIRD_PARTY_APPLICATION。
- 成员身份固定为 merchant_id + auth_corp_id + open_userid。
- 销售绑定只允许显式绑定或已验证的销售自绑定。
- Template Card 为主派单通道，Callback 为主反馈通道。
- WechatTask 保留并增加 channel；企业微信发送事实进入 wecom_message_deliveries。
- Callback 必须验签、解密、写 Durable Inbox、ACK，再由 Worker 处理业务事务。
- 第一版采用单实例进程内 Token 缓存，不提前实现分布式共享 Token 架构。
- 核心表固定为六张：wecom_suite_runtime、wecom_enterprise_authorizations、wecom_member_snapshots、wecom_member_bindings、wecom_message_deliveries、wecom_callback_events。
- H5 为 Secondary Feedback，延期，不进入 P0-P4 主链。
- P7 关闭 M04 对 19000 的运行依赖必须在 P6 通过后单独执行；P8 物理删除和全项目退役另立任务。

不重新讨论架构选型，不扩展 externalcontact、客户群、朋友圈、会话存档、企微客户 AI 自动聊天、NLP 主反馈链、M06 LAS 重构或全项目重构。

## 1. 阶段依赖与固定边界

    P0 官方能力实证
      -> P1 授权与凭证
      -> P2 成员快照与绑定
      -> P3 Template Card 派单
      -> P4 Callback 与结构化反馈
      -> P6 核心 E2E
      -> P7 关闭 M04 的 19000 runtime 依赖
      -> P8 全项目 Local Agent 依赖审计

P5 H5 是延期阶段，不得在 P0-P4 偷渡实现。

| 模块 | 计划责任 |
|---|---|
| M02 | Lead、既有 Lead 状态和业务事实 Owner |
| M04 | 授权、凭证、成员绑定、派单、回调和反馈编排 |
| M06 | 无 Local Agent 依赖，本计划不修改 |
| M07 | 本计划不修改 |
| PLATFORM/企业微信 | 官方授权、成员、消息和回调能力 |

P3/P4 会改变 M02↔M04 的 Task/Feedback Contract，完成后必须提交 G3/G4 delta。

## 2. P0 官方能力与测试主体实证

### 目标

关闭官方能力证据缺口，冻结真实协议样本，不编写业务实现。

### 涉及模块

M04、PLATFORM 测试工具、外部企业微信服务商后台；不修改 M02、M06、M07。

### DB变化

无。不得创建 migration，不得使用 create_all 代替设计验证。

### API变化

不新增生产 API。只允许脱敏测试脚本，临时接口不得成为正式合同。

### Migration策略

无 migration。输出六张表所需字段、官方事件字段、唯一性和状态证据。

### 测试策略

实测服务商/测试企业授权、授权变更、取消授权、成员可见范围、Template Card 发送、按钮回调、卡片更新、网页授权身份链、callback 稳定事件标识和 ACK 格式；保存脱敏 request/response fixture。

### 风险

官方许可、收费或可见范围不足；回调字段或 ACK 规则差异；网页授权无法支持销售自绑定；测试主体权限不足。

### 验收标准

每个生产阻断项都有官方当前证据、真实请求/响应摘要、失败分类和回滚方式。Owner 批准后才能进入 P1。

## 3. P1 授权与凭证基础

### 目标

实现授权状态机和唯一 WeComCredentialService。

### 涉及模块

M04 授权、凭证、Callback transport/crypto、PLATFORM secret 配置。

### DB变化

新增 wecom_suite_runtime、wecom_enterprise_authorizations 及授权 state 所需最小字段。

### API变化

POST /api/wecom/authorization/start
GET /api/wecom/authorization/status
GET /api/wecom/callback
POST /api/wecom/callback

商户 API 只从 RequestContext 取 merchant_id，不接受前端传入 merchant_id、auth_corp_id、permanent_code 或 Token。

### Migration策略

使用 Alembic，禁止 create_all；永久码和动态 Token 加密保存；suite_secret、Token、EncodingAESKey 不入表；migration 前执行 schema contract tests，不改生产库。

### 测试策略

验签/AES、state 过期和重复消费、授权状态转换、per-key token 刷新、invalid 单次强刷、secret 日志扫描、merchant isolation、PostgreSQL migration。

### 风险

授权回调不可达；Token 失效重试误发；加密主密钥未冻结；未来多实例误用单实例缓存。

### 验收标准

授权事件可信；取消后 fail-closed；Token 只有唯一服务入口；失效最多强刷一次；通过安全日志和 schema contract 验证。

## 4. P2 成员目录与销售绑定

### 目标

同步授权可见成员，建立 merchant 内 SalesStaff 与成员的显式双向唯一绑定。

### 涉及模块

M04 成员同步/绑定/权限 API；SalesStaff 只作为关联目标；最小管理员前端；企业微信成员 API。

### DB变化

新增 wecom_member_snapshots、wecom_member_bindings；建立 merchant + auth_corp_id + open_userid 边界、双向 active partial unique、历史解绑和 suspension_reason。

### API变化

GET /api/wecom/members
POST /api/wecom/member-bindings
DELETE /api/wecom/member-bindings/{id}

前端使用 surrogate member id，不直接枚举 open_userid。

### Migration策略

Alembic 新增两表和索引；不向 SalesStaff 写入 open_userid；不保存手机号/邮箱；不自动回填个人微信字段；数据库约束兜底并发唯一性。

### 测试策略

管理员绑定、重复、解绑、重绑、自绑定、并发冲突、停用/离职/移出范围、取消授权、跨商户负例、姓名/手机号/邮箱自动匹配拒绝。

### 风险

网页身份证据不足；成员同步延迟；解绑与待发送 delivery 并发；集团多商户共享企业的规则冲突。

### 验收标准

staff/member active 关系各最多一条；跨商户拒绝；无自动匹配；历史不覆盖；无手机号/邮箱落库。

## 5. P3 企业微信 Template Card 派单

### 目标

让 WechatTask 按 rollout policy 选择 wecom，并创建可审计的 wecom_message_deliveries。

### 涉及模块

M04 SalesNotificationService、Channel Adapter、WeComMessageService；M02 只通过既有 Task Contract 触发；企业微信消息 API。

### DB变化

新增 wecom_message_deliveries、WechatTask.channel、delivery claim/lease 和外部结果字段。open_userid、credential、callback payload、external msgid 不写入 WechatTask。

### API变化

不新增前端业务 API；既有派单合同保持；官方 API 只由服务端 Adapter 调用。

### Migration策略

Alembic 新增 delivery 表、字段和索引；历史任务默认 legacy_personal_wechat；新任务由 rollout policy 决定；禁止企业微信失败自动切个人微信；dedupe_key 和 token hash 唯一。

### 测试策略

单/多销售、三条件 rollout 矩阵、未绑定/取消授权/停用阻断、并发 delivery、未知外部结果、token 不可反解、跨商户隔离和防双发。

### 风险

未知发送结果重发；rollout policy 串商户；旧任务与 delivery 状态混淆；Template Card payload 或许可变化。

### 验收标准

W3/W4 通过；一个 generation 至多一条有效 delivery；legacy adapter 可用；无自动回退；每条发送都有 merchant/task/lead/staff/binding 关联。

## 6. P4 Callback Durable Inbox 与结构化反馈

### 目标

完成 Callback 接收、去重、重试、审计和结构化按钮反馈事务闭环。

### 涉及模块

M04 Callback Router、Crypto、Dispatcher、Worker、Feedback Transaction Service；M02 Lead/Timeline/Report 服务；企业微信回调和卡片更新 API。

### DB变化

新增 wecom_callback_events；delivery 增加 feedback_action、feedback_at、状态和卡片更新结果；callback 增加 lease、attempt_count、next_attempt_at。

### API变化

GET callback 只做官方 URL 验证；POST callback 只验签、解密、Inbox 落库、快速 ACK；Router 不直接更新 Lead/Timeline/Report。

### Migration策略

Alembic 新增 callback 表和索引；provider_event_key 唯一；原文最小化或加密；delivery 只允许 SENT -> FEEDBACK_RECEIVED；兼容旧 WechatTask/LeadNotification。

### 测试策略

重复/并发/乱序 callback、验签/解密失败、未知 event/token、ACK 重试、Worker 崩溃恢复、同 action 幂等、不同 action 冲突、card update 失败、Lead/Timeline/Report 一次且仅一次。

### 风险

ACK 时序不符官方协议；事件标识不稳定；card update 失败被误报；M02 状态映射不一致。

### 验收标准

W5/W6 通过；回放和崩溃只产生一次业务反馈；card update 失败不回滚；未知 task、merchant mismatch、安全拒绝 fail-closed。

## 7. P5 H5 Secondary Feedback（延期）

H5 只用于详情、备注、复杂反馈和二次确认。P0-P4 不实现 H5，不新增 DB/API/migration。未来投产前必须单独完成网页身份、session、merchant boundary、lead access、重放和越权测试。H5 延期不阻断主链和 P7，但不等于取消。

## 8. P6 核心 E2E 与多租户验证

### 目标

在测试企业和至少两个隔离 merchant 上验证授权到反馈的完整链路，决定是否可以关闭 M04 的 19000 runtime 依赖。

### 涉及模块

M02、M04、PLATFORM、企业微信测试环境；M06/M07 只做无回归确认。

### DB变化

无新增表。发现 schema 缺口即暂停并另立审批。

### API变化

无新 API；执行既有授权、成员、绑定、派单、回调合同回归。

### Migration策略

不执行新 migration；核对 migration head、运行 revision、schema contract 三方一致。

### 测试策略

W1-W6、W8-W10；双 merchant 正负交叉请求；callback replay/并发/worker restart；无 19000 条件下 M04 核心链。

### 风险

测试企业与生产许可差异；只看 HTTP 200；只测单商户；误把 H5 未完成当主链完成。

### 验收标准

W1-W6、W8-W10 全部 PASS；平台 verification 与业务 acceptance 分开；所有负例有证据；Owner 与 Verification Authority 签字后进入 P7。

## 9. P7 关闭 M04 19000 runtime 依赖

### 目标

关闭 M04 对个人微信和 19000 的运行依赖，不删除代码。

### 前置条件

P6 W1-W6、W8-W10 PASS；rollout merchant、fallback 时限和关闭条件已确认；未知外部结果已处理；rollback 已演练。

### 涉及模块

M04 rollout policy、legacy adapter runtime gate、运行文档；不改 M02/M06，不删除 19000/OCR/UIA。

### DB/API/Migration

无。不得临时新增 rollout 字段或 API；需要 schema 时另立任务。

### 测试策略

无 19000 时 M04 核心链、legacy 关闭后的 fail-closed、限时 rollback、已发送 delivery 不重发、取消授权/解绑阻断。

### 风险

隐藏 Local Agent 调用点、错误双发、rollback 长期打开。

### 验收标准

M04_RUNTIME_DEPENDENCY_ON_19000 = 0，并具备运行日志、配置检查、调用点审计和核心 E2E 证据。

## 10. P8 Local Agent 依赖审计与退役准备

### 目标

审计 M01-M07 的 Local Agent runtime/code/config/docs 依赖，形成独立物理退役任务输入。

### 涉及模块

M01-M07、G1/G2/G3/G4；M06 固定为无 Local Agent 依赖。

### DB/API/Migration

无。不得删除代码或历史数据。

### 测试策略

无 Local Agent 环境启动、关键链回归、配置/脚本/文档扫描、19000 关闭异常路径。

### 风险

隐藏脚本依赖、误删 Legacy、范围扩展到 OCR/鼠标自动化或历史数据。

### 验收标准

LOCAL_AGENT_RUNTIME_DEPENDENCY = 0，并形成单独退役任务草案；物理删除另行审批。

## 11. 全局回滚与禁止事项

回滚：

1. rollout 按 merchant，默认关闭；
2. P1-P4 migration 向前兼容，关闭开关不删除历史；
3. 只允许明确批准的 legacy fallback，禁止单任务双发；
4. 已发送/已反馈事实不因回滚重发或回退；
5. cancel_auth 永远优先；
6. P7 rollback 限时且需 Owner 审批；
7. P8 不执行物理删除。

禁止：

- 重新讨论架构选型；
- 增加企业微信能力范围；
- 新增 Lead 核心状态；
- 提前实现 H5/NLP 主链；
- 恢复 wecom_provider_credentials；
- 提前实现 Redis/DB 共享 Token；
- 修改 M06；
- 提前删除 19000；
- 自行决定 Owner Decisions Required；
- 在规划阶段执行 migration、代码、部署、提交或推送。

## 12. Owner 审批清单

Owner 需要审批：

1. 阶段顺序和 P0-P6 范围；
2. 单实例 Token 缓存；
3. 六张核心表和状态收敛；
4. P5 H5 延期；
5. P7/P8 分离；
6. 五项编码前业务决策；
7. 每阶段进入下一阶段的验收门。

## 13. 当前状态

    PLAN = WECOM IMPLEMENTATION PLAN v1.0
    STATUS = IMPLEMENTATION_PLAN_PENDING_OWNER_APPROVAL
    CODE_CHANGE = 0
    DB_CHANGE = 0
    PRODUCTION_CHANGE = 0
    MIGRATION_EXECUTED = NO
    TESTS_EXECUTED = NO
    COMMIT = NO
    PUSH = NO
    DEPLOYMENT = NO
    RESULT = PLAN_READY_FOR_OWNER_REVIEW

## 14. WECOM P1 Readiness（WECOM-P0-CLOSEOUT-AND-P1-READINESS-1 更新）

> 依据 2026-08-20 P0 真实回调验证（P0 = PASS）。

```text
P0                                = PASS
EXTERNAL_CALLBACK_BLOCKER        = REMOVED（公网回调 URL 已部署并真实验证：merchant.xiaogaoai.cn）
SUITE_TICKET                     = VERIFIED（真实 suite_ticket 10 分钟稳定投递，验签/解密/识别/ACK 全 PASS）
CALLBACK_CRYPTO                  = VERIFIED（signature + AES-256-CBC 真实企业微信请求验证）
SAME_CALLBACK_URL                = VERIFIED（指令/数据回调共用同一物理 URL，Token/EncodingAESKey 共用）
WECOM_CALLBACK_RECEIVE_ID_RULE   = FROZEN（见 Technical Design V1_CONVERGENCE §12A）

P1_IMPLEMENTATION                = NOT_YET_AUTHORIZED
P1 范围 = 授权与凭证基础（wecom_suite_runtime / wecom_enterprise_authorizations / 授权状态机
        / WeComCredentialService / 回调 transport+crypto 扩展）；仍属 P1，非本收口任务实现。
```

### 进入 P1 前仍需 Owner 冻结的决策

```text
OWNER_DECISION_03
= auth_corp_id 与 merchant ACTIVE 关系
  （是否禁止多个 merchant ACTIVE 复用同一 auth_corp_id —— 设计基线推荐：禁止）

OWNER_DECISION_05
= permanent_code credential encryption master key source
  （凭证加密主密钥的项目级来源 —— 不得由 VibeCoding/Executor 自动决定）
```

以上两项不得替 Owner 自动决定；P1 实施授权与决策冻结由 Owner 另行下达。
