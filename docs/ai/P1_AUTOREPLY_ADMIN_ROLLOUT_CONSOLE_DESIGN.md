# P1-AUTOREPLY-ADMIN-ROLLOUT-CONSOLE-DESIGN

## 1. 为什么需要管理员控制台

当前抖音 AI 自动回复真实发送候选链路由多层配置共同决定：

- 环境级熔断：`DOUYIN_AUTO_REPLY_ENABLED`、`DOUYIN_AUTO_REPLY_REAL_SEND_ENABLED`、`DOUYIN_AUTO_REPLY_ALLOW_FULL_ROLLOUT`。
- 环境级白名单：`DOUYIN_AUTO_REPLY_ACCOUNT_WHITELIST`、`DOUYIN_AUTO_REPLY_CUSTOMER_WHITELIST`、`DOUYIN_AUTO_REPLY_CONVERSATION_WHITELIST`。
- 账号级配置：`douyin_account_autoreply_settings.enabled`、`send_enabled`、账号级客户 / 会话白名单、频控、RAG 要求。
- 运行时安全门禁：Agent 绑定、RAG 命中、post-LLM gate、人工接管、最新消息、send context、发送去重。

这些配置对甲方管理员不可见、不可审计、不可快速回滚。控制台的目标不是绕过 gate，而是把“能否进入真实发送候选”拆成可理解的状态、可控的灰度范围、可追踪的操作记录和一键回滚入口。

## 2. 当前 env / DB / gate 关系

### 2.1 当前事实

| 层级 | 当前载体 | 当前代码位置 | 作用 |
|---|---|---|---|
| 环境级全局开关 | env | `app/config.py` | 进程启动时读取，真实发送 gate 使用 |
| 环境级白名单 | env | `app/config.py`、`douyin_autoreply_gate_service.py` | 非 full rollout 时限制账号、客户、会话 |
| 账号级开关 | DB | `douyin_account_autoreply_settings` | 控制账号是否启用自动回复和真实发送 |
| Agent 绑定 | DB | `douyin_account_agent_bindings` | 账号必须绑定 active Agent |
| 会话人工接管 | DB | `conversation_autopilot_states` | 会话级阻断真实发送 |
| 运行记录 | DB | `ai_auto_reply_runs` | 记录 dry-run / real-send candidate / sent / blocked |
| 决策日志 | DB | `ai_reply_decision_logs` | 记录 LLM/RAG 决策和 `final_auto_send` |
| 发送记录 | DB | `douyin_private_message_sends` | 记录真实发送结果和去重 |

### 2.2 当前接口

| 接口 | 当前用途 | 是否可复用 |
|---|---|---|
| `GET /douyin-autoreply/settings` | 商户查看本商户企业号自动回复配置 | 可复用为账号列表基础数据 |
| `GET /douyin-autoreply/settings/{account_open_id}` | 商户查看单账号配置 | 可复用 |
| `PUT /douyin-autoreply/settings/{account_open_id}` | 商户修改单账号配置 | 管理员控制台不建议直接复用，应走 admin 包装接口并记录审计 |
| `PUT /douyin-autoreply/settings/{account_open_id}/mode` | 切换托管模式，映射到 `enabled/send_enabled` | 可作为商户侧入口保留 |
| `GET /ai-auto-reply-runs` | 商户查看运行记录 | 可复用查询逻辑，admin 侧需支持跨商户和更完整筛选 |
| `GET /ai-auto-reply-runs/{run_id}` | 商户查看单条运行详情 | 可复用脱敏逻辑 |
| `POST /douyin-autoreply/settings/{account}/conversation-autopilot/pause` | 会话人工接管 | 控制台可跳转或调用现有能力 |

### 2.3 设计结论

下一阶段不建议让前端直接修改 env。应引入 DB 层“管理开关 / 管理白名单”，并保留 env 作为最高优先级熔断：

```text
env 熔断关闭
  -> 无论 DB 如何配置，都不能真实发送

env 熔断开启
  -> 再看 DB 管理开关
  -> 再看 rollout / whitelist
  -> 再看账号 enabled/send_enabled
  -> 再看 Agent / RAG / post-LLM / 人工接管 / send context
```

## 3. 页面信息架构

页面名称建议：`AI 自动回复安全控制台`。这是管理员端页面，不是商户工作台页面。

### 3.1 总览状态

展示目标：让管理员一眼知道“系统是否允许真实发送”和“当前影响范围有多大”。

字段建议：

| 字段 | 来源 | 说明 |
|---|---|---|
| AI 自动回复状态 | env + DB 管理开关 | 区分“系统熔断中 / 管理端启用 / 管理端暂停” |
| 真实发送状态 | env + DB 管理开关 | env 关闭时显示“系统熔断中”，不允许前端强开 |
| full rollout 状态 | env + DB 管理开关 | 生产开启需二次确认 |
| 当前真实发送范围 | rollout 配置 | `白名单` / `全量` / `已熔断` |
| 已开启发送企业号数量 | `douyin_account_autoreply_settings` | `enabled=true and send_enabled=true` |
| 最近 24h dry-run 数 | `ai_auto_reply_runs` | `mode=dry_run` |
| 最近 24h real-send candidate 数 | `ai_auto_reply_runs` | `mode=real_send_candidate` |
| 最近 24h sent 数 | `ai_auto_reply_runs` | `status=sent` |
| 最近 24h blocked 数 | `ai_auto_reply_runs` | `status=blocked` 或 `send_skipped` |

### 3.2 全局控制

管理员可操作项：

- 暂停 / 启用 AI 自动回复管理开关。
- 暂停 / 启用真实发送管理开关。
- 关闭 / 启用 full rollout。
- 一键暂停真实发送。

交互规则：

1. `DOUYIN_AUTO_REPLY_REAL_SEND_ENABLED=false` 时，真实发送开关展示为“系统熔断中”，按钮置灰。
2. 前端只能修改 DB 管理层开关，不能覆盖 env。
3. full rollout 开启必须弹出二次确认，确认内容包含影响范围、操作原因和回滚入口。
4. 一键暂停真实发送只关闭 DB 管理层真实发送开关，不修改 env 文件。

### 3.3 企业号级控制

列表字段：

| 字段 | 说明 |
|---|---|
| 企业号昵称 | 来自 `douyin_authorized_accounts.account_name` |
| account_open_id | 默认脱敏展示，详情中也不展示完整值给普通管理员 |
| 是否绑定 Agent | 来自 `douyin_account_agent_bindings` + `ai_agents` |
| Agent 名称 | active 绑定的 Agent |
| enabled | 账号自动回复开关 |
| send_enabled | 账号真实发送开关 |
| 企业号白名单状态 | 管理白名单是否包含该账号 |
| 今日 dry-run / sent / blocked | 聚合 `ai_auto_reply_runs` |
| 最后 blocked_reason | 最近一条 blocked / send_skipped 记录 |

管理员操作：

- 开启 / 关闭账号自动回复。
- 开启 / 关闭账号真实发送。
- 加入 / 移出测试企业号白名单。
- 查看该账号 gate 详情。

限制：

- 不能直接设置 `final_auto_send`。
- 不能调用 `send_ai_auto_reply_for_run`。
- 不能修改 Agent 绑定之外的 RAG / LLM 运行结果。

### 3.4 测试范围控制

支持三类白名单：

| 类型 | 用途 | 展示 |
|---|---|---|
| 企业号白名单 | 限定可进入真实发送候选的企业号 | 企业号昵称 + account_open_id 脱敏 |
| 客户白名单 | 限定测试客户 | open_id 脱敏 |
| 会话白名单 | 限定测试会话 | conversation_short_id 脱敏 |

添加白名单必须填写：

- 类型：`account` / `customer` / `conversation`
- 值：完整原始 ID，后端存储，前端列表脱敏
- 原因：必填
- 关联商户：可选；生产建议必填
- 过期时间：建议支持，默认不过期但高亮提示

删除白名单也必须记录操作人、时间、原因、删除前值的脱敏摘要。

### 3.5 审计与回滚

展示最近自动回复 run：

| 字段 | 来源 |
|---|---|
| mode | `ai_auto_reply_runs.mode` |
| status | `ai_auto_reply_runs.status` |
| final_auto_send | `ai_reply_decision_logs.final_auto_send` |
| send_gate_passed | `gate_results.real_send.send_gate_passed` |
| blocked_reason | `ai_auto_reply_runs.block_reason` 或 `gate_results.real_send.blocked_reason` |
| fallback_reason | `gate_results.post_llm.fallback_reason` |
| rag_sources_count | `gate_results.post_llm.rag_sources_count` |
| account_send_enabled | `gate_results.real_send.settings.send_enabled` |
| rollout / whitelist 命中 | `gate_results.real_send.global.*_whitelist_hit` |
| created_at | `ai_auto_reply_runs.created_at` |

回滚入口：

1. 一键暂停真实发送：关闭 DB 管理层真实发送开关。
2. 关闭某个企业号 `send_enabled`。
3. 移除企业号 / 客户 / 会话白名单。
4. 切换会话人工接管：优先跳转到现有会话托管能力。

## 4. 管理员可操作项

管理员端只允许配置“范围”和“开关”：

- 管理层 AI 自动回复启用 / 暂停。
- 管理层真实发送启用 / 暂停。
- 管理层 full rollout 启用 / 关闭。
- 企业号 `enabled`。
- 企业号 `send_enabled`。
- 企业号 / 客户 / 会话白名单。
- 会话人工接管入口。

## 5. 管理员不可操作项

必须明确禁止：

- 不能直接设置 `final_auto_send`。
- 不能直接调用 `send_ai_auto_reply_for_run`。
- 不能设置 `force_send`、`bypass`、`ignore_gate`。
- 不能覆盖 env 熔断。
- 不能修改 LLM 原始输出。
- 不能修改 RAG 命中结果。
- 不能让前端传入可信 `merchant_id` 覆盖后端上下文。
- 不能暴露 env 中的密钥、token、cookie、上游凭据。

## 6. 后端接口设计

本轮只设计，不实现。接口路径建议保留 `/admin/autoreply/*`，与已有 `/admin/compute/*` 超管接口风格一致。

### 6.1 权限规则

第一版建议仅允许 `RequestContext.super_admin=true`。后续如 NewCarProject 提供细粒度权限，再引入：

```text
auto_wechat:admin:autoreply_rollout
```

所有接口必须忽略前端传入的可信身份字段；跨商户查询只允许超管显式筛选。

### 6.2 GET /admin/autoreply/rollout/summary

用途：总览状态。

响应建议：

```json
{
  "success": true,
  "data": {
    "env_fuse": {
      "auto_reply_enabled": true,
      "real_send_enabled": false,
      "allow_full_rollout": false
    },
    "admin_control": {
      "global_enabled": false,
      "real_send_enabled": false,
      "allow_full_rollout": false
    },
    "effective": {
      "global_enabled": false,
      "real_send_enabled": false,
      "allow_full_rollout": false,
      "range": "fused"
    },
    "whitelist_counts": {
      "account": 0,
      "customer": 0,
      "conversation": 0
    },
    "account_counts": {
      "enabled": 0,
      "send_enabled": 0
    },
    "last_24h": {
      "dry_run": 0,
      "real_send_candidate": 0,
      "sent": 0,
      "blocked": 0
    }
  },
  "message": "success"
}
```

说明：`effective.real_send_enabled` 必须是 env 与 DB 管理开关共同计算后的结果。

### 6.3 POST /admin/autoreply/rollout/global

用途：修改管理层全局开关。

请求：

```json
{
  "global_enabled": true,
  "real_send_enabled": false,
  "allow_full_rollout": false,
  "reason": "测试账号灰度"
}
```

规则：

1. 不能修改 env。
2. env 真实发送熔断关闭时，即使保存 `real_send_enabled=true`，响应中的 `effective.real_send_enabled` 仍为 false。
3. 开启 full rollout 需要 `confirm_full_rollout=true` 和非空原因。
4. 记录 audit log。

### 6.4 GET /admin/autoreply/rollout/accounts

用途：企业号级控制列表。

查询参数建议：

- `merchant_id`
- `keyword`
- `enabled`
- `send_enabled`
- `whitelist_enabled`
- `page`
- `page_size`

响应项建议：

```json
{
  "account_name": "测试企业号",
  "account_open_id_masked": "acc_***_abcd",
  "has_bound_agent": true,
  "agent_name": "测试智能体",
  "enabled": true,
  "send_enabled": false,
  "account_whitelist_hit": true,
  "today": {
    "dry_run": 10,
    "sent": 0,
    "blocked": 3
  },
  "last_blocked_reason": "account_send_disabled"
}
```

### 6.5 POST /admin/autoreply/rollout/accounts/{account_open_id}

用途：修改账号级开关和账号白名单。

请求：

```json
{
  "enabled": true,
  "send_enabled": false,
  "whitelist_enabled": true,
  "reason": "加入测试企业号灰度"
}
```

规则：

1. 校验企业号存在。
2. 如指定 `merchant_id`，校验归属；否则按账号记录归属。
3. 修改 `enabled/send_enabled` 时复用 `upsert_account_autoreply_settings()`。
4. 修改白名单时写入管理白名单表。
5. 记录 audit log。
6. 不触发 dry-run、9100、发送服务。

### 6.6 GET /admin/autoreply/rollout/whitelist

用途：查询管理白名单。

查询参数：

- `type=account|customer|conversation`
- `merchant_id`
- `keyword`
- `enabled`
- `page`
- `page_size`

响应项：

```json
{
  "id": 1,
  "type": "customer",
  "value_masked": "cus_***_abcd",
  "merchant_id": "merchant-1",
  "reason": "测试客户",
  "enabled": true,
  "created_by": "admin-1",
  "created_at": "2026-07-04T12:00:00"
}
```

### 6.7 POST /admin/autoreply/rollout/whitelist

用途：添加白名单。

请求：

```json
{
  "type": "conversation",
  "value": "conversation_short_id",
  "merchant_id": "merchant-1",
  "reason": "测试会话演练",
  "expires_at": null
}
```

规则：

1. `reason` 必填。
2. 值原文只进入后端存储，不在列表中明文返回。
3. 同类型同值应幂等，重复添加返回已有记录或更新为 enabled。
4. 记录 audit log。

### 6.8 DELETE /admin/autoreply/rollout/whitelist/{id}

用途：移除白名单。

请求体建议：

```json
{
  "reason": "演练结束"
}
```

规则：

1. 推荐软删除或 `enabled=false`，保留历史审计。
2. 记录删除前 value 的 hash / 脱敏摘要。
3. 记录 audit log。

### 6.9 GET /admin/autoreply/runs

用途：管理员查看 dry-run / sent / blocked 记录。

建议复用 `list_ai_auto_reply_runs()` 的构造逻辑，但支持超管跨商户筛选。默认仍脱敏：

- 不返回完整客户消息。
- 不返回完整回复文本。
- 不返回上游 raw response。
- 不返回凭据。

## 7. 审计日志设计

建议新增独立审计表，后续实现时单独 migration：

```text
admin_autoreply_audit_logs
```

字段建议：

| 字段 | 说明 |
|---|---|
| id | 主键 |
| operator_id | 操作人 |
| operator_source | NewCar / mock / internal |
| action | `global_update` / `account_update` / `whitelist_add` / `whitelist_remove` / `pause_real_send` |
| target_type | `global` / `account` / `customer` / `conversation` |
| target_hash | 目标值 hash |
| target_masked | 脱敏展示值 |
| merchant_id | 关联商户 |
| before_json | 修改前摘要，不存凭据 |
| after_json | 修改后摘要，不存凭据 |
| reason | 操作原因 |
| request_id | 请求追踪 |
| created_at | 操作时间 |

审计日志不能记录：

- env 密钥。
- Douyin token / secret。
- NewCar token / cookie。
- Milvus 用户名 / 密码。
- 完整客户消息。
- 完整 open_id，如业务要求可存 hash 和脱敏摘要。

## 8. 回滚方案

从快到稳建议：

1. 关闭 DB 管理层 `real_send_enabled`：最快，适合控制台一键暂停。
2. 关闭账号 `send_enabled`：精确回滚单个企业号。
3. 移除企业号 / 客户 / 会话白名单：收窄测试范围。
4. 关闭 DB 管理层 `global_enabled`：暂停自动回复管理层能力。
5. 关闭 full rollout：从全量退回白名单模式。
6. 会话切人工接管：处理单个高风险会话。
7. 关闭 env `DOUYIN_AUTO_REPLY_REAL_SEND_ENABLED`：最高级熔断，需部署环境操作。
8. 关闭 env `DOUYIN_AUTO_REPLY_ENABLED`：全链路最高级暂停。

控制台应把前 6 项做成页面操作；第 7 和第 8 项只展示状态和操作指引，不让前端修改 env。

## 9. 测试环境真实演练前置条件

进入真实测试账号演练前必须满足：

1. env `DOUYIN_AUTO_REPLY_ENABLED=true`。
2. env `DOUYIN_AUTO_REPLY_REAL_SEND_ENABLED=true`，并确认回滚人员能立即关闭。
3. DB 管理层 `global_enabled=true`。
4. DB 管理层 `real_send_enabled=true`。
5. `full rollout=false`。
6. 只加入测试企业号、测试客户或测试会话白名单。
7. 目标账号 `enabled=true` 且 `send_enabled=true`。
8. 账号绑定 active Agent。
9. Agent 已配置知识范围，RAG 能命中。
10. fake sender 正向路径已通过；真实发送前再做一次 dry-run 观察。
11. 控制台能看到 run、blocked_reason、send_gate_passed 和 whitelist 命中状态。

## 10. 后续实现拆分建议

### 任务 1：DB 管理层配置与审计模型

新增：

- 管理层全局配置表。
- 管理白名单表。
- 管理操作审计表。

不接前端，不改真实发送 gate，只补 service 和测试。

### 任务 2：real-send gate 接入 DB 管理层

在 `evaluate_real_send_gates()` 中增加 DB 管理层 gate：

```text
env fuse -> admin global -> admin rollout/whitelist -> account settings -> runtime gates
```

要求保持 env 优先级最高。新增 blocked_reason 例如：

- `admin_global_disabled`
- `admin_real_send_disabled`
- `admin_rollout_whitelist_missed`

### 任务 3：admin rollout API

新增 `/admin/autoreply/rollout/*`，仅 super_admin 可访问，所有写操作记录 audit log。

### 任务 4：管理员控制台前端

新增页面 `AI 自动回复安全控制台`，只接 admin API，不直接操作发送服务。

### 任务 5：真实测试账号演练

只用测试企业号 / 测试客户 / 测试会话，演练前确认一键暂停和 env 熔断路径。

## 11. 本轮未实现内容

- 未新增后端接口。
- 未新增数据库表。
- 未修改真实发送 gate。
- 未修改前端页面。
- 未触发真实发送。
- 未调用真实 LLM。
- 未连接真实 Milvus。
- 未修改 NewCar、live-check、Local Agent、19000。

## 12. 本轮接口审计结论

1. 现有商户侧设置接口可作为账号配置能力基础，但不适合直接承担管理员审计职责。
2. 现有运行记录接口和查询服务可以复用，但 admin 侧需要跨商户筛选和更完整的 rollout 字段展示。
3. 当前 env 白名单无法通过前端安全修改，生产控制台应引入 DB 管理层白名单。
4. env 仍应保留为最高级熔断，不应被前端覆盖。
5. 后端 gate 继续保持最终权威，控制台只是配置入口和审计入口。

## 13. P1-AUTOREPLY-ADMIN-ROLLOUT-MODEL-1

本轮新增 DB 管理层配置与审计模型，不接入真实发送 gate，不新增 admin API，不做前端页面。

### 13.1 新增表

| 表 | 作用 | 默认安全策略 |
|---|---|---|
| `autoreply_rollout_configs` | 保存管理员 DB 层自动回复灰度意图 | `auto_reply_enabled=false`、`real_send_enabled=false`、`allow_full_rollout=false` |
| `autoreply_whitelist_entries` | 保存企业号 / 客户 / 会话白名单 | 默认空白名单，新增记录默认 `enabled=true` |
| `autoreply_admin_audit_logs` | 保存管理员操作审计 | 只记录配置摘要，不记录密钥、完整客户消息或 prompt |

### 13.2 默认值

未找到 DB 配置时，服务层返回安全默认值：

```text
auto_reply_enabled=false
real_send_enabled=false
allow_full_rollout=false
```

这只是 DB 管理层意图，不计算 env 熔断。后续 gate 接入时必须同时满足 env 和 DB 配置。

### 13.3 审计字段

审计日志记录：

- `action`
- `merchant_id`
- `account_open_id`
- `target_type`
- `target_id`
- `before_json`
- `after_json`
- `reason`
- `operator_id`
- `operator_name`
- `created_at`

`before_json` / `after_json` 写入前会剔除 `token`、`secret`、`password`、`cookie`、`authorization` 等敏感键。

### 13.4 白名单幂等策略

白名单以 `entry_type + merchant_id + account_open_id + value` 作为幂等范围。

- active 记录重复添加：返回已有记录，不重复写审计。
- disabled 记录再次添加：重新启用，并写入审计。
- 移除白名单：软禁用，写入 `disabled_by` / `disabled_at`，不物理删除。

### 13.5 env 熔断与 DB 配置关系

本轮没有让 DB 配置覆盖 env。后续 gate 接入时应保持：

```text
env 熔断
  -> DB 管理层配置
  -> DB 管理层 rollout / whitelist
  -> 账号 enabled/send_enabled
  -> Agent / RAG / post-LLM / 人工接管 / send context
```

env 级开关仍是最高优先级。即使 DB 中 `real_send_enabled=true`，只要 env 真实发送熔断关闭，仍不得真实发送。

### 13.6 本轮未接入真实 gate

本轮未修改：

- `evaluate_real_send_gates`
- `send_ai_auto_reply_for_run`
- 9000 对外 schema
- 管理端 API
- 前端页面
- NewCar、live-check、Local Agent、19000

### 13.7 测试结果

本轮新增测试文件：

```text
tests/test_autoreply_admin_rollout_service.py
```

覆盖：

- 默认配置安全。
- 更新 DB 配置会写审计。
- account 白名单重复添加幂等。
- customer / conversation 白名单添加。
- disable 后不再 active。
- audit log 不记录 secret/token/password。
- 服务层不触发 sender，也不调用既有 gate。

### 13.8 下一步任务

建议下一任务再接入真实发送 gate：

```text
P1-AUTOREPLY-ADMIN-ROLLOUT-GATE-INTEGRATION-1
```

该任务再把 env fuse、DB 管理层配置、DB 白名单与现有账号级 gate 串联，并补充 blocked_reason。
