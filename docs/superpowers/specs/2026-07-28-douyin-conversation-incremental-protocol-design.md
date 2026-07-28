# 抖音客服会话增量协议设计

## 1. 元数据

- Task-ID：`DY-CS-CONVERSATION-INCREMENTAL-PROTOCOL-1`
- Design-Revision：`D1`
- Design-Base：`c751deacd7ccf4be12e649f64db3439619031649`
- 风险等级：`MEDIUM`
- 任务类型：只读会话协议、前端增量同步与恢复
- 执行方式：原地执行，不创建 worktree、不新建分支

## 2. 已核实事实

1. 正式工作台通过 9000 的 `integrations` 路由读取 `DouyinWebhookEvent`，前端不直接依赖 9100 mock 会话接口。
2. 会话列表当前按最近 `2000` 条事件聚合，可逐步扩大到 `20000`；消息详情固定读取最近 `200` 条，均没有事件游标。
3. 前端每 8 秒重新加载当前账号会话列表；检测到当前会话摘要变化后，再整批加载当前会话详情。
4. `DouyinWebhookEvent.id` 已作为 `raw_event_id` 返回，现有已读协议也使用事件 ID；消息展示排序为 `(created_at, event_id)`。
5. 工作台读取已经通过 `RequestContext.merchant_id`、`require_owned_account()`、事件 `merchant_id` 和账号/会话条件形成商户隔离；`merchant_id=NULL` 历史事件对普通商户不可见。
6. PostgreSQL 中 `douyin_webhook_events.id` 为 `BIGINT` 自增主键；现有索引未完整覆盖“商户 + 账号/会话 + 事件 ID”增量查询。
7. 前端没有 Vitest/Jest；当前工作台前端合同主要由 Python 静态测试、TypeScript 构建和定向检查覆盖。

## 3. 目标与非目标

### 3.1 目标

1. 使用稳定事件 ID 补拉新消息和分页加载历史消息，不再依靠不断扩大的事件窗口保证完整性。
2. 断网、页面隐藏或请求失败期间产生的消息，在恢复后能够继续补拉且无重复、无缺失。
3. 更新所有有效授权抖音号的未读红点，不只更新当前账号。
4. 保持现有接口、商户隔离、防枚举 404 和已读提交语义向后兼容。
5. 为账号、会话摘要和消息分别保存同步状态、错误和重试动作，并显示最后成功同步时间。

### 3.2 非目标

- 不实施 SSE/WebSocket；游标补拉稳定后，它们只能作为“有变化”的唤醒信号另行设计。
- 不缩短 8 秒基础轮询周期。
- 不修改 webhook 验签、消息发送、自动回复、outbox、违禁词、9100 或生产配置。
- 不新增会话摘要表、游标表或前端依赖。
- 不在执行计划验证前预先增加 PostgreSQL 索引。

## 4. 方案选择

采用现有接口增加可选数字事件游标：

- `DouyinWebhookEvent.id` 是传输水位和去重键。
- `created_at` 只参与展示排序，不作为补拉水位。
- 延迟到达但消息时间较早的 webhook 仍会获得更大的入库事件 ID，因此不会落在补拉水位之前。
- 不采用不透明字符串游标，避免当前没有收益的编码和校验逻辑。
- 不采用 `(created_at, event_id)` 复合补拉游标，避免延迟入库事件因旧时间戳漏拉。

## 5. 接口合同

### 5.1 企业号列表

`GET /integrations/douyin/accounts`

现有账号条目增加：

```json
{
  "account_open_id": "account-1",
  "unread_count": 3,
  "latest_event_id": 130
}
```

- `latest_event_id` 是当前商户、当前有效绑定账号下，非重复私信事件的最大可见事件 ID。
- 没有可见私信事件时返回 `0`。
- 该字段用于首次建立所有授权账号的增量基线；不得包含他商户或 `merchant_id=NULL` 事件。

### 5.2 会话列表

`GET /integrations/douyin/accounts/{account_id}/conversations`

新增可选查询参数：

- `after_event_id`：大于等于 `0` 的十进制整数；传入后启用增量模式。
- `limit`：增量模式默认 `100`，最大 `500`。
- 原有 `event_limit` 仅保留给无游标旧调用；`after_event_id` 与 `event_limit` 同时出现时返回 `422`。

无游标时保持现有会话列表行为，并给每个摘要增加稳定水位。增量模式只返回游标后发生变化的会话摘要：

```json
{
  "items": [
    {
      "conversation_key": "conv-1",
      "latest_event_id": 123,
      "unread_count": 2
    }
  ],
  "latest_event_id": 130,
  "next_after_event_id": 123,
  "account_unread_count": 5,
  "has_more": true
}
```

- `items` 保持现有完整会话摘要结构，新增 `latest_event_id`。
- 顶层 `latest_event_id` 是本次查询时账号范围内的当前最大可见事件 ID。
- `next_after_event_id` 是本页已扫描的最大事件 ID；本页无可扫描事件时保持请求水位。
- `account_unread_count` 是该账号当前权威未读总数，供未加载完整会话缓存的账号直接更新红点。
- `has_more` 表示当前水位后仍有未扫描的合法候选事件。
- 无变化时返回 `200`、空 `items`、`has_more=false`，不得把正常空增量当作错误。
- 无变化时 `next_after_event_id` 不得小于请求水位；任何响应都不得要求客户端倒退游标。

### 5.3 消息列表

`GET /integrations/douyin/conversation-messages`

路径形式 `/integrations/douyin/conversations/{conversation_key}/messages` 保持同一服务合同。新增可选查询参数：

- `after_event_id`：补拉新消息。
- `before_event_id`：加载更早消息。
- `limit`：游标模式默认 `100`，最大 `200`。
- 两种游标互斥；负数、非整数、同时出现或越界 `limit` 返回 `422`。

响应扩展为：

```json
{
  "items": [],
  "latest_event_id": 130,
  "next_after_event_id": 130,
  "next_before_event_id": 80,
  "has_more": false
}
```

具体语义：

1. 不传游标和 `limit`：保持当前最近 `200` 条、按展示顺序升序返回。
2. 仅传 `limit`：返回最近 `limit` 条，作为受限初始页。
3. `after_event_id`：查询 `id > cursor`，按 ID 升序扫描，最终按 `(created_at, event_id)` 展示排序。
4. `before_event_id`：查询 `id < cursor`，先按 ID 倒序取得最接近游标的一页，截断后按展示顺序返回。
5. `next_after_event_id` 和 `next_before_event_id` 分别给出后续补拉及历史分页水位。
6. `has_more` 只表示本次请求方向是否还有下一页。
7. 合法会话没有新消息或更早消息时返回 `200 + items=[]`。
8. 真正不存在、跨账号或跨商户的会话继续返回防枚举 `404`。

`GET /integrations/douyin/conversation-detail` 不增加游标参数。首次进入继续一次返回消息和画像，其 `messages` 使用上述扩展响应结构；后续增量和历史分页统一调用消息接口，避免重复加载画像。

## 6. 后端查询与安全设计

### 6.1 有界查询

- `after_event_id`：`id > cursor`、`ORDER BY id ASC`、`LIMIT limit + 1`。
- `before_event_id`：`id < cursor`、`ORDER BY id DESC`、`LIMIT limit + 1`，截断后反转。
- 会话列表增量先读取有限事件页，只重新聚合发生变化的会话，不扫描账号完整的 `2000~20000` 事件窗口。
- 游标推进到已扫描的最大事件 ID，即使某事件解析失败或最终未形成消息，也不能永久卡在同一事件。
- 每页使用额外一行判断 `has_more`，额外行不进入本页结果。

实现应复用一个共享事件查询构造逻辑，使会话列表、详情和消息接口的事件类型、重复排除、商户、账号和会话条件保持一致。不得为每个路由复制一套权限过滤。

### 6.2 会话存在性

游标页为空不能证明会话不存在。普通商户请求必须通过不受游标范围影响的归属查询确认：

- 会话存在但页为空：`200`。
- 当前账号/商户范围内从未存在该会话：`404`。
- 游标数字本身不做跨商户事件查找，避免形成事件 ID 存在性侧信道。

### 6.3 每次请求的强制过滤

1. 从 `RequestContext.merchant_id` 获取可信商户。
2. 执行 `require_owned_account()`，验证账号存在、`bind_status==1` 和商户归属。
3. 固定 `DouyinWebhookEvent.merchant_id == 当前商户`。
4. 校验账号参与方与 `conversation_key`。
5. 只读取非重复私信事件。
6. `merchant_id=NULL` 历史事件继续对普通商户不可见。

游标只是范围边界，不是权限凭据。传入另一个商户的真实事件 ID，只能改变当前合法数据的起止范围，不能返回或确认该事件。

## 7. 前端状态与数据流

### 7.1 状态

每个授权账号保存：

- `latest_event_id`
- 最近成功同步时间
- 连续失败次数和下次允许重试时间
- 账号级增量错误

每个会话保存：

- `newest_event_id`
- `oldest_event_id`
- `has_more_before`
- 消息增量错误和历史分页错误

这些状态进入现有工作台查询缓存，不写入 localStorage/sessionStorage。

### 7.2 首次加载与周期补拉

1. 企业号列表返回所有有效账号的权威未读数和 `latest_event_id`，建立账号基线。
2. 当前选中账号执行无游标会话列表；当前会话执行详情请求。
3. 保持 8 秒基础周期，由唯一的 `syncAllAccounts()` 对所有有效账号执行会话增量请求。
4. 同时最多同步 3 个账号；单账号失败不阻塞其他账号。
5. 未选中账号只更新账号红点和会话缓存，不请求消息详情。
6. 当前选中会话摘要变化后，使用 `after_event_id=newest_event_id` 补拉消息。
7. `has_more=true` 时连续推进游标；每轮设置有限页预算，达到预算后让出事件循环并排队继续，防止持续流量造成页面长时间占用。

### 7.3 恢复触发

以下事件触发同一个同步入口：

- `document.visibilityState` 重新变为 `visible`
- 窗口 `focus`
- 浏览器 `online`
- 8 秒基础周期

多种触发同时发生时必须合并；已有同步未完成时只记录一次待补同步，不启动并发风暴。

### 7.4 合并、排序与已读

- 以 `String(raw_event_id)` 作为消息映射键合并和去重。
- 合并后按 `(created_at, raw_event_id)` 排序；延迟入库消息可以插入正确展示位置。
- 历史分页完成后保持滚动锚点，不让当前阅读位置跳动。
- 只有当前选中会话成功响应并完成渲染后，才沿用现有成功凭据推进已读水位。
- 未选中账号和后台会话同步不得调用 mark-read。
- 迟到响应必须同时通过请求序号、账号和会话身份检查，不能覆盖当前选择。

## 8. 错误处理与退避

- 失败时不推进游标、不清空缓存、不清零未读数。
- 企业号列表、账号增量、当前会话增量和历史分页分别保存错误与重试动作。
- 连续失败使用 `8s -> 16s -> 32s -> 60s` 上限退避，并加入少量抖动。
- 页面恢复可见、重新聚焦或联网时允许立即重试一次，但仍受全局请求合并保护。
- 任一账号成功后更新该账号成功时间；页面级“最后成功同步时间”只在本轮所有应同步的有效授权账号均成功后更新，不得在部分失败或仅发起请求时更新。
- 日志只记录 stage、账号/会话脱敏摘要、游标、数量、耗时和 failure_stage，不记录消息正文、URL 密钥或凭据。

## 9. PostgreSQL 索引决策门禁

本设计不直接授权迁移。实现查询后，必须在本地专用 PostgreSQL 上构造至少 5 万条带独立 namespace 的事件，其中目标账号至少 500 条，并记录 `EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)` 与清理结果：

1. 目标查询使用 `limit=100`；执行计划不得对 `douyin_webhook_events` 使用 `Seq Scan`，事件扫描节点的 `Rows Removed by Filter` 不得超过 `5000`。
2. 满足上述门禁时，本任务不新增迁移；任一条件不满足即停止当前实现窗口并回传 `REPAIR_REQUIRED`。
3. 后续单独申请 `0017` 索引迁移，候选索引为：
   - `(merchant_id, to_user_id, id)`
   - `(merchant_id, from_user_id, id)`
   - `(merchant_id, conversation_short_id, id)`
4. 迁移任务风险升级为 `HIGH`，需独立规格、升级/降级验证和生产窗口审批。

不得在没有执行计划证据时预先增加三个生产索引。

## 10. 验收矩阵

### 10.1 后端协议与隔离

| ID | 验收要求 |
|---|---|
| A1 | 无游标会话列表、详情和消息响应保持旧行为兼容 |
| A2 | `after_event_id` 多页补拉无重复、无缺失，水位严格前进 |
| A3 | `before_event_id` 可完整加载超过 200 条历史 |
| A4 | 延迟入库且 `created_at` 更早的事件仍被补拉并按展示顺序插入 |
| A5 | 相同时间戳按事件 ID 稳定排序 |
| A6 | 游标互斥、负数、非整数和超限 `limit` 返回 `422` |
| A7 | 合法会话空增量返回 `200`，不存在或越权会话返回防枚举 `404` |
| A8 | 他商户事件 ID、跨账号会话和 `merchant_id=NULL` 事件不可见 |
| A9 | 重复事件不返回，不可解析事件不会卡死游标 |
| A10 | 企业号 `latest_event_id` 和 `account_unread_count` 只来自当前商户有效绑定账号 |
| A11 | 查询含事件 ID 边界及有限 `LIMIT`，增量路径不使用扩大 `event_limit` |
| A12 | 专用 PostgreSQL 执行计划有记录；需要新索引时按门禁停止 |

### 10.2 前端同步

| ID | 验收要求 |
|---|---|
| F1 | 重复增量响应不会生成重复消息或倒退游标 |
| F2 | 断网期间产生的消息在 `online` 后完整补齐 |
| F3 | 可见、聚焦、联网和周期触发被合并，不产生并发请求风暴 |
| F4 | 其他授权账号的新消息更新账号红点 |
| F5 | 后台同步不标记已读，当前会话渲染成功后才推进已读水位 |
| F6 | 请求失败不推进游标、不清缓存、不清零红点 |
| F7 | 迟到响应不能覆盖已切换的账号或会话 |
| F8 | 历史分页保持滚动锚点 |
| F9 | 最后成功同步时间只在成功后更新 |
| F10 | 源码和网络合同中没有 SSE/WebSocket，8 秒周期未缩短 |

## 11. 测试策略

1. 扩展工作台会话、账号列表、商户隔离和已读协议现有 pytest，覆盖 A1-A12。
2. 增加超过 200 条历史、断点后多页补拉、延迟入库、相同时间戳、坏事件推进和分页期间插入新事件测试。
3. 保留普通商户账号归属、跨商户 403、会话防枚举 404、NULL 归属不可见和后台不同步已读的合同。
4. 前端不新增测试依赖。将纯合并、水位和退避逻辑放入独立 TypeScript 辅助模块，使用已安装的 TypeScript 编译器配合无依赖 Node 检查脚本运行行为断言。
5. 沿用 Python 静态合同验证路由参数、恢复事件监听、唯一同步入口、无 SSE/WebSocket 和现有已读成功凭据。
6. 运行前端构建、编码检查及触及文件的定向 lint；不得用全量自动修复制造无关改动。
7. 运行工作台会话、账号、租户隔离、已读、webhook 事件读取和相邻自动回复只读回归；不得真实调用抖音、9100、LLM 或发送接口。
8. PostgreSQL 专项只连接明确白名单的本地专用测试库；禁止 `create_all`、staging 和 production。

## 12. 实施与治理边界

实现计划应拆为三个独立阶段：

1. 后端协议、查询和 PostgreSQL 执行计划门禁。
2. 前端状态、增量合并、恢复触发和无依赖行为检查。
3. 候选独立测试、推送后单独进行活动文档闭环与外部 TODO 同步。

实现候选禁止包含：

- webhook 签名头或验签改动
- 已读状态模型或 mark-read 语义改动
- 人工发送、自动回复、outbox、违禁词或 9100 改动
- 未经单独批准的迁移或索引
- 新前端依赖、SSE/WebSocket 或更短轮询周期
- 其他 ORM/schema 一致性返修
- 部署、生产连接、真实发送或生产迁移

每个阶段结束后执行文档影响检查；业务候选独立测试并推送前，不更新活动文档或外部 TODO 的完成状态。
