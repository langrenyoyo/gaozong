# auto_wechat 独立验收版 PRD

版本：V1.0
阶段：功能子系统验收版
适用项目：auto_wechat / 小高AI微信助手
后续上游系统：NewCarProject
当前状态：需求边界基本冻结，待后续补充架构设计、技术方案、代码方案、分阶段开发计划

------

# 1. 项目背景

auto_wechat 是面向客户售卖的功能子系统，核心目标是帮助客户自动处理抖音 / 巨量来源线索，并通过客户本地电脑上的微信完成销售通知、销售回复检测、超时判断和人工处理。

当前第一版不是完整主系统，也不是接入已经完成的主系统，而是一个可独立验收、可客户直接使用的功能子系统。

未来 NewCarProject 作为上游主系统，负责管理员、商户、权限、角色、功能模块、套餐和消耗等统一管理。auto_wechat 作为 NewCarProject 下游的一个子功能模块存在。

------

# 2. 产品定位

## 2.1 当前定位

auto_wechat 当前定位为：

> 独立验收版功能子系统。

当前第一版用于客户验收和测试，需要具备完整的线索处理闭环。

当前第一版支持单客户，但必须预留多客户能力。

## 2.2 未来定位

未来 auto_wechat 作为 NewCarProject 下游的一个子功能模块。

NewCarProject 负责：

1. 创建和管理管理员。
2. 创建和管理商户。
3. 管理商户权限。
4. 管理商户可使用的子功能系统。
5. 管理统一登录。
6. 管理套餐和消耗展示。
7. 管理多子功能入口。

auto_wechat 负责：

1. 接收真实线索事件。
2. 记录原始事件。
3. 识别有效线索。
4. 分配销售。
5. 创建微信通知任务。
6. 通过 Local Agent 操作本地微信。
7. 检测销售回复。
8. 处理超时未回复。
9. 支持人工处理。
10. 支持数据导出。
11. 向上游同步必要状态。

------

# 3. 角色定义

## 3.1 NewCarProject 管理员

由 NewCarProject 侧创建和管理。

职责：

1. 创建商户。
2. 管理商户权限。
3. 控制商户能使用哪些子功能模块。
4. 管理商户账号。
5. 管理套餐和消耗。
6. 控制非商户角色的跳转入口。

## 3.2 商户

商户是 auto_wechat 的主要使用者。

商户可以：

1. 登录 auto_wechat。
2. 查看线索。
3. 管理销售。
4. 导入销售。
5. 配置关键词。
6. 配置工作时间。
7. 配置超时时间。
8. 配置是否自动重分配。
9. 查看微信任务。
10. 查看回复检测。
11. 查看失败记录。
12. 人工处理失败线索。
13. 导出数据。
14. 修改自己的密码。

商户不允许跳转到其他子功能系统。

## 3.3 Local Agent / 小高AI微信助手

运行在客户电脑上的本地执行端。

职责：

1. 连接 auto_wechat 服务端。
2. 接收任务。
3. 操作本机微信。
4. 搜索销售微信昵称。
5. 发送线索信息。
6. 只读检测销售回复。
7. 回写执行结果。
8. 遇到异常时停止操作并回写失败原因。

Local Agent 不负责业务状态决策。

------

# 4. 子功能入口

NewCarProject 前端菜单共 6 个：

1. 抖音AI小高客服
2. AI小高线索
3. 小高AI微信助手
4. AI小高剪辑
5. 小高素材库
6. 小高算力

其中：

> 小高算力不是子功能，而是给商户查看自己的套餐和消耗。

auto_wechat 对应：

> 小高AI微信助手。

------

# 5. 第一版范围

## 5.1 第一版必须支持

第一版必须支持：

1. 商户登录。
2. 商户修改密码。
3. NewCarProject 使用 token + cookie 跳转 auto_wechat。
4. auto_wechat 识别 NewCarProject 传入的登录态和角色信息。
5. webhook 直收真实线索事件。
6. 使用 `callback.misanduo.com/webhook/douyin` 作为正式 webhook 地址。
7. 所有事件进入原始事件表。
8. 有效线索进入有效线索表。
9. 有效线索自动进入销售分配流程。
10. 销售列表管理。
11. 销售 Excel 导入。
12. 关键词配置。
13. 工作时间配置。
14. 超时时间配置。
15. 自动重分配配置。
16. 微信通知任务创建。
17. Local Agent 接收任务。
18. Local Agent 串行操作微信。
19. Local Agent 发送线索给销售。
20. Local Agent 检测销售回复。
21. 超时未回复判断。
22. 超时自动重分配。
23. 失败记录。
24. 人工处理。
25. Excel 数据导出。
26. 业务数据保存 180 天。
27. 截图不保存。
28. 截图不入库。

## 5.2 第一版不做

第一版不做：

1. 完整主系统。
2. NewCarProject 完整开发。
3. 多客户正式运营。
4. 多台 Local Agent。
5. 多抖音 / 巨量账号。
6. LLM 大模型判断。
7. 客户自定义 LLM。
8. 截图保存。
9. 操作审计日志。
10. 数据归档。
11. 客户多回调地址。
12. exe 自动更新。
13. 销售停用后的历史线索迁移。
14. 停用客户后的任务补偿处理。
15. 重置密码。
16. 多角色复杂权限系统。

------

# 6. 线索接入

## 6.1 正式接入链路

第一版正式线索链路为：

> 巨量 / 抖音 / GMP Webhook → auto_wechat

第一版验收正式链路为 webhook 直收。

不再以 douyinAPI 主动拉取作为正式主链路。

## 6.2 正式 webhook 地址

继续使用：

> callback.misanduo.com/webhook/douyin

webhook 签名字段和签名算法按正式接口文档执行，不在 PRD 中自行假设。

## 6.3 webhook 返回规则

采纳以下返回规则：

1. 成功接收：HTTP 200
2. 重复事件：HTTP 200
3. 非线索事件：HTTP 200
4. 无效线索：HTTP 200
5. 请求格式错误：HTTP 400
6. 签名失败：HTTP 401
7. 过期请求：HTTP 401
8. 系统异常：HTTP 500

原则：

> 只要请求合法且系统成功接收，即使不是有效线索，也返回 200，避免外部平台无意义重试。

------

# 7. 原始事件与有效线索

## 7.1 原始事件规则

所有 webhook 事件都必须记录。

所有事件进入：

> lead_source_events

包括：

1. 有效线索事件。
2. 无效线索事件。
3. 非线索事件。
4. 重复事件。
5. 解析失败但通过签名校验的事件。

## 7.2 有效线索规则

有效线索进入：

> douyin_leads

有效线索判断规则：

1. `phone` 或 `wechat` 任一存在，才进入有效线索分配。
2. `phone` 和 `wechat` 都为空，不分配销售。
3. 有留下资料的私信一定创建为有效线索。
4. 没有手机号、没有微信号的事件只进入原始事件记录。
5. invalid 进入前端列表。
6. invalid 参与数据导出。
7. invalid 不需要对外回调。

## 7.3 事件与线索关系

1. 所有事件记录到 `lead_source_events`。
2. 有效线索记录到 `douyin_leads`。
3. 无效线索不进入有效分配流程。
4. 重复事件不重复创建线索。
5. 同一用户多次触发时更新原线索。

------

# 8. 唯一键与去重规则

## 8.1 外部线索 ID

优先使用数据源 `id` 作为：

> external_lead_id

## 8.2 id 缺失时的兜底规则

如果数据源 `id` 缺失，使用：

> open_id + account_open_id

作为线索去重依据。

## 8.3 辅助去重字段

以下字段用于辅助去重和事件追踪：

1. `conversation_short_id`：会话级辅助去重字段。
2. `server_message_id`：事件级幂等字段。
3. `event_key`：webhook 事件幂等字段。

## 8.4 重复触发处理

1. 同一 `open_id + account_open_id` 多次触发时，更新原线索。
2. 同一用户不同会话，仍视为同一用户线索更新。
3. 重复事件不重复创建线索。
4. 重复事件需要返回成功。
5. 重复事件需要记录幂等命中结果。

------

# 9. 字段映射

## 9.1 lead_source_events 建议字段

所有原始事件进入 `lead_source_events`。

建议字段：

1. id
2. customer_id
3. tenant_id
4. source_platform
5. event_key
6. external_event_id
7. external_lead_id
8. server_message_id
9. conversation_short_id
10. open_id
11. account_open_id
12. event_type
13. latest_event
14. latest_scene
15. lead_action
16. is_duplicate
17. signature_valid
18. raw_payload
19. received_at
20. processed_at
21. process_status
22. error_message

## 9.2 douyin_leads 建议字段

有效线索进入 `douyin_leads`。

建议字段：

1. id
2. customer_id
3. tenant_id
4. external_lead_id
5. dedupe_key
6. open_id
7. account_open_id
8. conversation_short_id
9. server_message_id
10. douyin_display_name
11. avatar_url
12. phone
13. wechat
14. lead_channel
15. lead_type
16. latest_event
17. latest_scene
18. first_active_time
19. latest_active_time
20. source_lead_status
21. tags_json
22. last_interaction_record_json
23. assigned_staff_id
24. status
25. raw_payload
26. cleaned_payload
27. created_at
28. updated_at
29. closed_at

## 9.3 字段映射关系

1. 数据源 `id` → `external_lead_id`
2. `open_id` → `open_id`
3. `account_open_id` → `account_open_id`
4. `display_name` → `douyin_display_name`
5. `avatar_url` → `avatar_url`
6. `phone` → `phone`
7. `wechat` → `wechat`
8. `lead_channel` → `lead_channel`
9. `lead_type` → `lead_type`
10. `latest_event` → `latest_event`
11. `latest_scene` → `latest_scene`
12. `conversation_short_id` → `conversation_short_id`
13. `server_message_id` → `server_message_id`
14. `first_active_time` → `first_active_time`
15. `latest_active_time` → `latest_active_time`
16. `lead_status` → `source_lead_status`
17. `tags` → `tags_json`
18. `last_interaction_record` → `last_interaction_record_json`
19. 完整原始数据 → `raw_payload`
20. 清洗后数据 → `cleaned_payload`

------

# 10. 线索状态

## 10.1 内部状态

`douyin_leads.status` 建议包括：

1. received：已接收
2. invalid：无效线索
3. pending_assign：未分配
4. assigned：已分配
5. notified：已通知销售
6. waiting_reply：等待回复
7. replied：已回复
8. timeout：超时未回复
9. reassigned：已重新分配
10. manual_required：需要人工处理
11. failed：失败
12. closed：人工关闭

## 10.2 对外状态

领导确认对外状态只包括：

1. 未分配
2. 已分配
3. 已回复
4. 超时未回复

## 10.3 内外状态映射

1. `pending_assign` → 未分配
2. `reassigned` → 未分配
3. `assigned` → 已分配
4. `replied` → 已回复
5. `timeout` → 超时未回复

以下状态不对外回调：

1. received
2. invalid
3. agent_pulled
4. notified
5. send_failed
6. manual_required
7. failed
8. closed
9. callback_success

`callback_success` 仅作为内部 `callback_logs.status = success`，不作为对外业务状态。

------

# 11. 销售管理

## 11.1 销售字段

销售信息至少包括：

1. 微信昵称
2. 销售姓名
3. 手机号
4. 备注
5. 排序
6. 状态

## 11.2 销售导入

第一版支持 Excel 导入。

导入规则：

1. 微信昵称必填。
2. 销售姓名可空。
3. 手机号可空。
4. 备注可空。
5. 排序自动生成。
6. 重复微信昵称时覆盖。
7. 导入失败返回错误行号和原因。
8. 支持部分成功。
9. 提供模板下载。

## 11.3 销售为空

销售列表为空时，有效线索进入：

> pending_assign

即未分配状态。

------

# 12. 分配规则

## 12.1 自动分配

第一版支持自动分配。

规则：

1. 按客户销售列表顺序轮流分配。
2. 自动排序。
3. 避免同一销售连续接收过多线索。
4. 销售列表为空时进入未分配。
5. 非工作时间按工作时间策略处理。

## 12.2 超时重分配

第一版支持超时重分配。

规则：

1. 超时时间客户可配置。
2. 默认超时时间为 30 分钟。
3. 最多重分配 5 次。
4. 重分配排除原销售。
5. 超过次数后进入人工处理或失败记录。
6. 超时状态对外映射为“超时未回复”。
7. 重新分配后对外映射为“未分配”。

------

# 13. 工作时间

## 13.1 配置方式

第一版支持客户统一配置工作时间。

暂不支持每个销售单独配置工作时间。

## 13.2 非工作时间处理

非工作时间收到有效线索时，建议处理为：

> 先入库，进入未分配 / 延迟分配状态，等到工作时间后继续自动分配。

具体实现可在技术方案中细化。

------

# 14. 微信通知任务

## 14.1 任务创建

有效线索分配给销售后，系统创建微信通知任务。

## 14.2 默认通知内容

默认模板：

【新线索分配】

客户：{客户名称}

来源：{线索来源}

内容：{线索类型 / 事件}

联系方式：{手机号或微信号}

备注：{备注}

请尽快跟进客户，并在处理完成后回复确认消息。

## 14.3 任务执行

Local Agent 拉取任务后执行。

执行结果包括：

1. 成功发送。
2. 联系人未找到。
3. 微信不可用。
4. 搜索框异常。
5. 焦点丢失。
6. Agent 忙碌。
7. 执行失败。

失败需要记录，但截图不保存。

------

# 15. Local Agent / 小高AI微信助手

## 15.1 基本规则

1. 每个客户第一版只考虑一台电脑运行 Local Agent。
2. 不支持客户多台 Local Agent。
3. 不支持多个账号。
4. 同一电脑、同一微信窗口、同一 agent_client_id，同一时间只允许执行一个任务。
5. 发送任务和检测任务必须互斥。
6. poll-and-execute 与 poll-and-detect 必须互斥。
7. 忙碌时返回 agent_busy。
8. 微信异常时停止操作并回写失败原因。

## 15.2 安全规则

Local Agent 禁止：

1. 未确认联系人时发送。
2. 微信窗口不可用时继续操作。
3. 搜索框焦点未确认时粘贴。
4. 并发操作微信。
5. 无任务状态回写。
6. 无日志执行高风险操作。

## 15.3 exe 名称

统一名称：

> 小高AI微信助手

------

# 16. 回复检测

## 16.1 第一版检测方式

第一版不接入大模型。

回复检测采用：

1. 关键词判断。
2. 规则判断。

## 16.2 有效回复

客户可以配置关键词。

示例：

1. 收到
2. 已添加
3. 已添加微信
4. 已联系
5. 正在跟进
6. 已跟进

## 16.3 注意事项

关键词配置时需要提示客户：

1. 不要与线索模板内容重复。
2. 不要设置过短关键词。
3. 不要设置过宽泛关键词。
4. 应配置明确表达已处理意图的关键词。

------

# 17. 人工处理

## 17.1 适用范围

第一版人工处理主要面向失败状态。

暂时只记录失败，不做复杂人工流程。

## 17.2 人工处理动作

允许：

1. 人工重新分配。
2. 人工补录销售回复。
3. 人工关闭线索。

人工处理后：

1. 重新分配后进入未分配或分配流程。
2. 补录销售回复后可进入已回复。
3. 人工关闭线索后进入 `closed`。
4. `closed` 不对外回调。

------

# 18. 回调与状态同步

## 18.1 回调状态

对外状态只包含：

1. 未分配
2. 已分配
3. 已回复
4. 超时未回复

## 18.2 不回调状态

以下状态不对外回调：

1. invalid
2. received
3. agent_pulled
4. notified
5. send_failed
6. manual_required
7. failed
8. closed
9. callback_success

## 18.3 回调失败

如果需要做状态同步或回调：

1. 最大重试 5 次。
2. 失败后保存错误信息。
3. 失败后在后台页面由开发人员复核处理。
4. 支持查看失败原因。
5. 支持手动处理。
6. 具体接口格式等待接口文档确认。

------

# 19. 登录与权限

## 19.1 登录方式

NewCarProject 跳转 auto_wechat 使用：

> token + cookie

auto_wechat 需要支持识别 token 和 cookie。

## 19.2 角色跳转

规则：

1. 商户进入 auto_wechat。
2. 商户不允许跳转到其他子功能。
3. roles 不是商户的用户，由 NewCarProject 跳转到多子功能菜单。
4. auto_wechat 只负责自己的子系统使用权限。

## 19.3 密码

第一版支持：

1. 修改密码。

第一版不支持：

1. 重置密码。

修改密码的具体规则在技术方案中细化。

------

# 20. 前端页面范围

第一版建议页面包括：

1. 登录页
2. 首页概览
3. 线索列表
4. 线索详情
5. 销售管理
6. 销售导入
7. 关键词配置
8. 工作时间配置
9. 超时 / 重分配配置
10. Local Agent 状态
11. 微信任务列表
12. 回复检测列表
13. 超时列表
14. 回调失败列表
15. 人工处理页
16. 数据导出页

页面范围可在后续前端设计中根据工期裁剪，但不得影响验收主链路。

------

# 21. 数据导出

## 21.1 导出格式

第一版导出格式：

> Excel

## 21.2 导出筛选

支持按时间范围导出。

## 21.3 导出内容

第一版需要导出：

1. 线索列表
2. 分配记录
3. 微信通知任务
4. 回复检测结果
5. 超时记录
6. 回调失败记录
7. 人工处理记录

## 21.4 脱敏要求

第一版导出不脱敏。

------

# 22. 数据保存与清理

## 22.1 业务数据

业务数据保存：

> 180 天

包括：

1. 原始事件。
2. 有效线索。
3. 分配记录。
4. 微信任务。
5. 回复检测。
6. 超时记录。
7. 回调失败记录。
8. 人工处理记录。

## 22.2 截图

第一版：

1. 截图不保存。
2. 截图不入库。

## 22.3 数据归档

第一版不做数据归档。

客户如需历史数据，由客户自行下载。

------

# 23. 高并发与性能口径

## 23.1 服务端口径

第一版服务端按以下口径预留：

1. 服务端 API 和数据库层面预留 200 QPS。
2. 单客户峰值按 2000 条线索 / 天考虑。
3. 查询接口需要分页。
4. 导出接口需要按时间范围。
5. webhook 接收需要幂等。
6. 状态更新需要幂等。
7. 任务回写需要幂等。

## 23.2 Local Agent 口径

Local Agent 不承诺 200 QPS。

Local Agent 必须串行执行微信任务。

------

# 24. 状态冻结摘要

## 24.1 线索内部状态

1. received
2. invalid
3. pending_assign
4. assigned
5. notified
6. waiting_reply
7. replied
8. timeout
9. reassigned
10. manual_required
11. failed
12. closed

## 24.2 对外状态

1. 未分配
2. 已分配
3. 已回复
4. 超时未回复

## 24.3 回调日志内部状态

1. pending
2. sending
3. success
4. failed
5. retrying
6. manual_required

------

# 25. 验收主链路

第一版验收主链路如下：

1. 外部平台推送 webhook 到 `callback.misanduo.com/webhook/douyin`。
2. auto_wechat 校验 webhook。
3. auto_wechat 记录原始事件。
4. auto_wechat 判断是否为有效线索。
5. 有效线索进入 `douyin_leads`。
6. 无效线索只进入原始事件记录。
7. 有效线索进入未分配状态。
8. 系统按销售列表自动分配。
9. 系统创建微信通知任务。
10. Local Agent 拉取任务。
11. Local Agent 操作本机微信通知销售。
12. 系统进入等待销售回复。
13. Local Agent 检测销售回复。
14. 命中有效关键词后进入已回复。
15. 超过配置时间未回复则进入超时未回复。
16. 超时后按规则自动重分配。
17. 失败任务进入人工处理。
18. 商户可在前端查看线索、任务、回复、超时、失败。
19. 商户可导出 Excel 数据。

------

# 26. 当前仍需外部资料补充

以下不是 PRD 方向问题，但开发前需要拿到资料：

1. webhook 正式接口文档。
2. webhook 签名字段和算法。
3. webhook 请求体完整样例。
4. NewCarProject token / cookie 传参规则。
5. NewCarProject roles 字段结构。
6. NewCarProject 商户 ID 字段。
7. 状态同步接口格式。
8. 服务器部署和域名配置说明。

------

# 27. 后续文档计划

本 PRD 冻结后，后续再分别编写：

1. CLAUDE.md 更新方案。
2. docs/ai 相关规则文档更新方案。
3. 架构设计文档。
4. 技术方案文档。
5. 数据模型设计文档。
6. 接口契约文档。
7. 代码方案文档。
8. 分阶段开发计划。
9. 测试验收计划。
10. VibeCoding 执行指令。