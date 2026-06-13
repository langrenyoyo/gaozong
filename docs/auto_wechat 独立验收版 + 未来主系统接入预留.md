# auto_wechat 独立验收版 + 未来主系统接入预留

## 0. 项目新定位

auto_wechat 当前阶段不再按“接入已有主系统”推进，而是先作为一个可独立验收、可客户直接使用的功能子系统进行开发和交付。

未来主系统会作为 auto_wechat 的上游系统，负责客户管理、统一登录、权限管理、功能开通、套餐额度等能力。auto_wechat 作为主系统下的一个可售卖子功能系统存在。

当前阶段的核心定位为：

> auto_wechat 是独立验收版功能子系统。
> 当前支持单客户验收，但数据库、接口、权限、配置和任务模型必须预留多客户能力。
> 未来 auto_wechat 接入上游主系统，由主系统统一管理客户、用户、权限和功能开通。

------

# 1. 当前验收版边界

## 1.1 当前第一版做什么

当前第一版是 auto_wechat 功能子系统验收版。

当前需要支持：

1. 客户直接使用 React 前端。
2. 客户登录后可以管理自己的 auto_wechat 子功能系统。
3. 客户可以维护销售列表。
4. 客户可以维护销售微信昵称。
5. 客户可以维护关键词。
6. 客户可以维护工作时间。
7. 客户可以维护超时时间。
8. 客户可以配置是否自动重分配。
9. 系统默认启用 LLM 兜底判断，不开放给客户关闭。
10. 系统从线索源主动拉取巨量广告线索。
11. 系统对线索进行清洗、过滤、去重。
12. 系统自动分配线索给销售。
13. 系统创建微信通知任务。
14. 客户电脑运行 Local Agent / exe。
15. Local Agent / exe 操作本机微信发送线索给销售。
16. Local Agent / exe 检测销售是否有效回复。
17. 系统支持超时重分配。
18. 系统支持状态回调。
19. 系统支持失败任务、人工处理、日志追溯。
20. 数据默认保存半年，并采用分批清理策略避免清理雪崩。

## 1.2 当前第一版不做什么

当前第一版不做完整主系统。

第一版暂不做：

1. 完整客户 SaaS 主系统。
2. 多子功能系统统一管理后台。
3. 完整套餐计费系统。
4. 完整额度扣费系统。
5. 多客户大规模并发生产级压测。
6. 多台 Local Agent 复杂调度。
7. 复杂组织架构和多角色权限。
8. 主系统与 auto_wechat 的完整 SSO 联调。
9. 分库分表。
10. Kafka / RabbitMQ 等复杂消息队列，除非后续压测证明必须引入。
11. exe 自动更新系统。
12. 大规模批量微信自动化。

## 1.3 当前客户范围

当前验收版支持单客户。

但从第一版开始，所有核心表、接口和配置必须预留：

1. customer_id
2. tenant_id
3. created_by
4. updated_by

这样后续主系统上线后，可以平滑扩展到多客户，不需要大规模重构数据库。

------

# 2. 未来主系统接入预留

## 2.1 未来主系统职责

未来主系统作为 auto_wechat 的上游系统，主要负责：

1. 管理客户。
2. 管理客户账号。
3. 管理客户登录。
4. 管理客户使用哪些子功能系统。
5. 管理 auto_wechat 是否对客户开通。
6. 管理客户功能权限。
7. 预留套餐、计费、额度能力。
8. 管理多个功能子系统。
9. 统一登录。
10. 统一权限。
11. 统一客户启停用。
12. 统一审计。

## 2.2 auto_wechat 与主系统关系

auto_wechat 是未来主系统下的一个子功能系统。

主系统不直接替代 auto_wechat 的业务能力。auto_wechat 仍然负责：

1. 线索拉取。
2. 线索清洗。
3. 线索去重。
4. 销售管理。
5. 销售分配。
6. 微信任务创建。
7. Local Agent 管理。
8. 微信发送。
9. 回复检测。
10. 超时处理。
11. 重新分配。
12. 回调数据源。
13. 日志追溯。
14. 客户侧功能页面。

## 2.3 主系统与 auto_wechat 数据库关系

当前确认：

1. 主系统和 auto_wechat 不共用数据库。
2. auto_wechat 需要预留对接主系统 users 表和权限能力。
3. 主系统未来拥有 auto_wechat 的管理权限。
4. 主系统不直接执行业务任务。
5. auto_wechat 作为主系统下游子功能系统独立运行。

因此 auto_wechat 当前需要预留：

1. customer_id 映射。
2. tenant_id 映射。
3. external_user_id 映射。
4. external_customer_id 映射。
5. feature_code。
6. feature_enabled。
7. token 校验扩展点。
8. 权限同步扩展点。
9. 客户停用后的系统禁用能力。

## 2.4 主系统未来接入方式预留

由于主系统当前未开发，auto_wechat 第一版先做轻量本地登录与客户配置能力。

未来主系统上线后，可以采用以下方式接入：

1. 主系统统一登录。
2. 主系统签发 token。
3. auto_wechat 校验主系统 token。
4. auto_wechat 根据 token 获取 customer_id / user_id / feature 权限。
5. auto_wechat 判断客户是否开通 auto_wechat 功能。
6. auto_wechat 根据 customer_id 隔离数据。
7. 主系统停用客户后，auto_wechat 禁止该客户继续拉取线索、创建任务、Local Agent 拉任务。

------

# 3. 当前子系统业务职责

## 3.1 auto_wechat 后端负责

当前 auto_wechat 后端临时承担完整业务闭环，包括：

1. 客户配置。
2. 销售管理。
3. 关键词配置。
4. 工作时间配置。
5. 超时时间配置。
6. 是否自动重分配配置。
7. 线索主动拉取。
8. 线索清洗。
9. 线索过滤。
10. 线索去重。
11. 线索入库。
12. 销售自动分配。
13. 微信通知任务创建。
14. Local Agent 任务下发。
15. Local Agent 执行结果接收。
16. 回复检测任务创建。
17. 回复检测结果接收。
18. 线索状态更新。
19. 通知任务状态更新。
20. 回复检测状态更新。
21. 超时判断。
22. 超时重分配。
23. 数据源状态回调。
24. 回调失败重试。
25. 人工处理。
26. 日志追溯。
27. 数据清理。
28. React 前端接口。

## 3.2 React 客户前端负责

当前 React 前端面向客户直接使用。

第一版建议至少提供：

1. 登录页。
2. 首页概览。
3. 线索列表。
4. 线索详情。
5. 销售管理。
6. 关键词配置。
7. 工作时间配置。
8. 超时配置。
9. Local Agent 状态页。
10. 微信任务列表。
11. 回复检测列表。
12. 超时列表。
13. 失败任务列表。
14. 人工处理入口。
15. 任务重试入口。
16. 日志查看入口。

## 3.3 Local Agent / exe 负责

客户电脑运行 Local Agent / exe。

Local Agent / exe 负责：

1. 连接 auto_wechat 服务端。
2. 上报心跳。
3. 拉取任务。
4. 检查本机微信状态。
5. 操作本机微信。
6. 搜索销售微信昵称。
7. 确认联系人。
8. 粘贴线索信息。
9. 发送线索信息。
10. 检测销售回复。
11. 只读读取微信消息。
12. 回写执行事实。
13. 回写失败原因。
14. 回写截图和日志摘要。
15. 遇到高风险场景停止操作并进入人工处理。

Local Agent / exe 不负责：

1. 不决定最终线索状态。
2. 不决定销售分配规则。
3. 不直接改业务数据。
4. 不直接回调外部数据源。
5. 不绕过 auto_wechat 后端独立闭环。
6. 不在联系人未确认时发送。
7. 不在微信状态异常时继续操作。
8. 不并发操作同一个微信窗口。

------

# 4. 数据源与线索拉取

## 4.1 线索来源

当前确认：

1. 线索原始来源是巨量广告 webhook。
2. auto_wechat 当前采用主动拉取方式获取线索。
3. 当前不直接开发完整 webhook 接收链路。
4. 拉取间隔暂定 30 秒。
5. 允许错峰拉取。
6. 当前验收版先支持单客户。
7. 半年内预计 6 到 10 个客户。
8. 每个客户目前考虑一台电脑运行 Local Agent。
9. 每个客户约 20 个销售微信。

## 4.2 线索示例字段

数据源示例包含：

1. id
2. open_id
3. display_name
4. avatar_url
5. phone
6. wechat
7. account_open_id
8. latest_event
9. conversation_short_id
10. server_message_id
11. latest_scene
12. first_active_time
13. latest_active_time
14. lead_status
15. assignee
16. remark
17. lead_channel
18. lead_type
19. tags
20. last_interaction_record

## 4.3 唯一键与去重

虽然目前确认数据源不会重复返回同一线索，但 auto_wechat 仍必须做幂等和去重。

建议唯一键优先级：

1. source_platform + external_lead_id
2. source_platform + open_id + account_open_id
3. source_platform + conversation_short_id
4. source_platform + server_message_id

如果 phone 存在，可以作为辅助去重字段，但不建议只用 phone 作为唯一键，因为 phone 可能为空。

## 4.4 拉取成功后的状态

当前确认：

> 拉取成功并且 Local Agent 已接收任务后，才回写数据源为已处理。

建议内部状态拆分为：

1. source_seen：在线索源发现。
2. pulled：auto_wechat 已拉取。
3. stored：auto_wechat 已入库。
4. task_created：已创建微信通知任务。
5. agent_pulled：Local Agent 已接收任务。
6. sent：已发送给销售。
7. replied：销售有效回复。
8. timeout：销售回复超时。
9. reassigned：已重新分配。
10. manual_required：需要人工处理。
11. failed：处理失败。

对外回调时不要只回“已处理”，而是回明确业务状态。

------

# 5. 线索清洗、过滤与去重

## 5.1 清洗要求

当前确认需要清洗数据。

清洗内容包括：

1. 标准化来源字段。
2. 标准化客户昵称。
3. 标准化手机号。
4. 标准化微信号。
5. 标准化时间字段。
6. 保存 raw_payload。
7. 生成 cleaned_payload。
8. 生成 dedupe_key。

## 5.2 过滤要求

当前确认需要过滤无效线索，避免无效线索进入销售分配。

建议过滤规则包括：

1. 缺少关键身份字段。
2. open_id 为空。
3. account_open_id 为空。
4. 事件类型不在允许范围内。
5. lead_status 不符合处理条件。
6. 黑名单用户。
7. 测试数据。
8. 已处理但重复返回的数据。

## 5.3 重复线索处理

当前确认：

1. 同一线索重复进入时，发送给原有跟进销售。
2. 如果没有原有跟进销售，则进入自动分配。
3. 同一客户多次留资时，更新资料。
4. 同一客户多次留资时，优先发送给原有跟进销售。
5. 如果没有原有跟进销售，则进入自动分配。

------

# 6. 销售分配规则

## 6.1 当前分配规则

当前确认：

1. 自动分配。
2. 按客户导入销售列表顺序轮流分配。
3. 目的是避免同一销售接收过多线索无法及时处理。
4. 暂不按门店分配，但预留门店字段。
5. 暂不按销售在线状态分配。
6. 不按销售微信昵称分配。
7. 销售微信昵称由客户维护。
8. 分配失败后自动重试。
9. 多次失败后进入待人工分配。

## 6.2 并发分配要求

由于后端需要考虑 200 QPS 预留，销售分配必须避免并发冲突。

建议：

1. 轮询指针按 customer_id 保存。
2. 分配时必须在事务内更新轮询指针。
3. 同一客户并发分配时必须避免重复读写指针。
4. 销售被停用后跳过。
5. 销售列表为空时进入 manual_required。
6. 原销售已停用时重新进入自动分配。
7. 超时重分配时建议排除上一次超时销售。

------

# 7. 微信通知模板

## 7.1 默认模板

默认发送给销售的线索模板：

【新线索分配】

客户：{customer_name}

来源：{lead_channel}

内容：{lead_type} / {latest_event}

联系方式：{phone_or_wechat}

备注：{remark}

请尽快跟进客户，并在处理完成后回复确认消息。

## 7.2 模板配置

当前确认：

1. 暂不支持完整模板配置。
2. 需要包含手机号、姓名、来源、备注。
3. 允许自动发送。
4. 不需要发送前人工确认。
5. 提示语句应预留可配置能力。
6. 发送内容必须入库，便于追溯。
7. 数据保存时间默认半年。

## 7.3 工作时间

当前确认：

1. 客户可以配置工作时间。
2. 避免夜间或非工作时间自动分配线索。
3. 非工作时间进入待分配或延迟分配。
4. 工作时间配置按 customer_id 隔离。

------

# 8. 回复检测规则

## 8.1 有效回复判断

当前确认：

1. 默认 30 分钟内回复算有效。
2. 第一层使用关键词列表判断。
3. 第二层使用大模型兜底。
4. 关键词需要客户配置。
5. 暂不考虑正则。
6. 不需要人工复核。
7. LLM 默认启用，不允许客户关闭。
8. 判断结果需要入库追溯。
9. 数据默认保存半年。

## 8.2 关键词配置要求

客户配置关键词时，需要提示：

1. 不要与线索模板内容重复。
2. 不要配置过短关键词。
3. 不要配置过宽泛关键词。
4. 建议配置明确表达已处理意图的关键词。

例如：

1. 收到
2. 已添加
3. 已添加微信
4. 已联系
5. 正在跟进
6. 已跟进

## 8.3 LLM 兜底要求

虽然客户不能关闭 LLM 兜底，但系统必须有后端保护：

1. 关键词未命中时才调用 LLM。
2. 每个 reply_check 最多调用一次 LLM。
3. 只对候选销售消息调用 LLM。
4. LLM 请求和响应需要入库。
5. LLM 判断理由需要保存。
6. LLM 超时需要有明确状态。
7. LLM 连续失败需要熔断。
8. LLM 不可用时不能阻塞主链路。
9. LLM 调用需要日志。
10. 后续可预留按客户限流。

------

# 9. 超时与重分配

## 9.1 超时规则

当前确认：

1. 默认 30 分钟超时。
2. 客户可以配置超时时间。
3. 超时后重新分配。
4. 超时后允许管理员人工处理。
5. 超时任务需要进入超时列表。
6. 超时结果需要回调数据源。

## 9.2 重分配规则

建议：

1. 超时后自动重新分配。
2. 重分配时优先排除上一次超时销售。
3. 重分配次数需要设置上限。
4. 超过上限后进入 manual_required。
5. 每次重分配都要记录 reassignment_logs。
6. 每次重分配都要更新 lead 状态。
7. 每次重分配都要触发新的微信通知任务。

------

# 10. 回调策略

## 10.1 是否需要回调

当前确认需要回调数据源。

## 10.2 回调状态

当前确认需要回调：

1. received
2. invalid
3. assigned
4. replied
5. timeout
6. reassigned
7. manual_required
8. failed

建议补充：

1. notified
2. send_failed

不建议把 callback_success 作为对外业务状态。callback_success 应作为内部 callback_logs.status。

## 10.3 内部回调日志状态

callback_logs.status 建议包括：

1. pending
2. sending
3. success
4. failed
5. retrying
6. manual_required

## 10.4 回调失败处理

当前确认：

1. 回调失败重试 5 次。
2. 失败后保存错误信息。
3. 失败后由开发人员复核处理。
4. 回调日志必须入库。

建议补充：

1. 保存 request_payload。
2. 保存 response_status_code。
3. 保存 response_body。
4. 保存 error_message。
5. 保存 retry_count。
6. 保存 next_retry_at。
7. 保存 final_failed_at。
8. 支持后台查看失败回调。

------

# 11. 高并发预留

## 11.1 高并发目标口径

当前暂定 QPS 统一按 200 考虑。

需要注意：

> 200 QPS 应理解为服务端接口与数据库层面的承压预留，不应理解为 Local Agent 操作微信的吞吐能力。

Local Agent 操作真实微信 UI，必须串行。

## 11.2 服务端高并发预留

服务端需要按 200 QPS 做设计预留：

1. 核心表增加 customer_id 索引。
2. 核心状态字段增加索引。
3. 任务拉取接口支持 limit。
4. 任务拉取接口必须幂等。
5. 任务结果回写必须幂等。
6. 线索拉取必须幂等。
7. 回调必须幂等。
8. 定时任务允许错峰。
9. 数据清理必须分批。
10. 查询接口必须分页。
11. 前端列表必须分页。
12. 失败任务需要索引。
13. 超时任务需要索引。
14. LLM 调用需要系统级保护。
15. 数据库连接池需要合理配置。

## 11.3 Local Agent 串行约束

当前每个客户暂考虑一台电脑运行 Local Agent。

Local Agent 必须满足：

1. 同一 agent_client_id 同一时间只执行一个微信任务。
2. poll-and-execute 与 poll-and-detect 必须互斥。
3. 发送任务和检测任务不能并发操作微信。
4. 任务必须排队执行。
5. 服务端可以并发创建任务，但同一 agent_client_id 下发时必须串行。
6. Local Agent 忙碌时返回 agent_busy。
7. 微信窗口异常时停止执行并回写 manual_required。

------

# 12. 数据保存半年与分批清理方案

## 12.1 保存周期

默认保存 180 天。

建议保存 180 天的数据：

1. douyin_leads
2. lead_notifications
3. reply_checks
4. agent_tasks
5. callback_logs
6. lead_source_events
7. assignment_logs
8. reassignment_logs
9. llm_judgement_logs
10. Local Agent 执行摘要日志

截图文件建议默认保存 30 到 90 天，除非客户要求与业务数据一样保存 180 天。

## 12.2 清理原则

必须避免过期清理造成雪崩。

清理原则：

1. 不允许一次性删除大量历史数据。
2. 不允许所有客户同一秒同时清理。
3. 不允许清理任务影响正常任务拉取。
4. 不允许清理任务影响任务回写。
5. 不允许清理失败导致主业务失败。
6. 清理必须记录 cleanup_logs。

## 12.3 清理策略

建议：

1. 每天凌晨低峰期执行。
2. 按 customer_id 分批清理。
3. 每批最多 500 到 1000 条。
4. 每批之间 sleep 100 到 500ms。
5. 每次清理任务设置最大执行时间，例如 10 分钟。
6. 超过时间则下次继续。
7. 使用 id 游标或 created_at 游标分页。
8. 不使用大 offset。
9. 先清理子表，再清理主表。
10. 文件清理和数据库清理分开执行。

## 12.4 推荐清理顺序

1. callback_logs
2. llm_judgement_logs
3. agent_tasks
4. reply_checks
5. lead_notifications
6. lead_source_events
7. assignment_logs
8. reassignment_logs
9. douyin_leads
10. screenshots
11. 本地日志文件

------

# 13. 建议新增或预留的数据表

## 13.1 客户与权限相关

第一版至少预留：

1. customers
2. customer_users
3. customer_feature_flags
4. customer_configs

后续主系统上线后，可由主系统统一管理。

## 13.2 销售与配置相关

需要：

1. staff
2. customer_staff
3. customer_keywords
4. customer_working_hours
5. customer_timeout_configs

## 13.3 线索与任务相关

需要：

1. douyin_leads
2. lead_source_events
3. lead_notifications
4. reply_checks
5. agent_tasks
6. agent_clients

## 13.4 日志与追溯相关

需要：

1. assignment_logs
2. reassignment_logs
3. callback_logs
4. llm_judgement_logs
5. cleanup_logs
6. agent_execution_logs

------

# 14. 状态机调整建议

## 14.1 douyin_leads.status

建议：

1. received
2. cleaned
3. invalid
4. duplicated
5. assigned
6. notify_created
7. notifying
8. notified
9. waiting_reply
10. replied
11. timeout
12. reassigned
13. manual_required
14. failed

不建议将 callback_success 作为线索主状态。

## 14.2 callback_logs.status

建议：

1. pending
2. sending
3. success
4. failed
5. retrying
6. manual_required

## 14.3 agent_tasks.status

建议：

1. created
2. pulled
3. running
4. success
5. failed
6. retrying
7. agent_busy
8. manual_required
9. cancelled

## 14.4 customer.status

建议预留：

1. active
2. disabled
3. expired
4. manual_required

## 14.5 customer_feature_flags.status

建议预留：

1. enabled
2. disabled
3. expired
4. quota_exceeded

------

# 15. 分阶段开发计划调整

## P0：auto_wechat 当前代码探索与独立验收边界冻结

目标：

确认 auto_wechat 当前已有能力、真实调用链、技术债、风险点，并冻结独立验收版边界。

产物：

1. auto_wechat 当前代码探索报告。
2. MVP 能力边界报告。
3. 独立验收版范围清单。
4. 第一版不做事项。
5. 高风险文件清单。
6. Local Agent 安全门禁清单。

## P1：真实 PRD、状态机与接口契约冻结

目标：

冻结独立验收版 PRD、状态机、表结构、接口契约和主系统预留边界。

产物：

1. PRD 确认版。
2. 状态机设计。
3. 数据模型设计。
4. 接口契约文档。
5. 主系统接入预留方案。
6. 高并发预留方案。
7. 数据清理方案。

## P2：客户配置与基础管理能力

目标：

让客户可以登录并维护自己的基础配置。

任务：

1. 客户登录。
2. 客户配置。
3. 销售管理。
4. 关键词管理。
5. 工作时间配置。
6. 超时时间配置。
7. 自动重分配配置。
8. Local Agent 绑定配置。

## P3：线索拉取、清洗、分配闭环

目标：

不依赖真实微信，先跑通线索从拉取到任务创建的闭环。

任务：

1. 主动拉取线索。
2. 原始数据入库。
3. 清洗。
4. 过滤。
5. 去重。
6. 自动分配。
7. 创建微信通知任务。
8. 状态回调。
9. React 展示线索和任务状态。

## P4：Local Agent 微信发送闭环

目标：

跑通 Local Agent / exe 执行微信发送任务并回写结果。

任务：

1. Local Agent 拉取任务。
2. Local Agent 检查微信状态。
3. 搜索销售微信昵称。
4. 确认联系人。
5. 粘贴线索信息。
6. 发送线索信息。
7. 回写执行结果。
8. 前端展示发送结果。

## P5：回复检测、超时、重分配闭环

目标：

跑通销售回复检测、LLM 兜底、超时处理、自动重分配和回调。

任务：

1. 创建回复检测任务。
2. Local Agent 只读检测微信消息。
3. 关键词判断。
4. LLM 兜底判断。
5. 回写检测结果。
6. 超时判断。
7. 自动重分配。
8. 回调数据源。
9. 前端展示检测结果。

## P6：验收、打包、日志、清理与交付

目标：

让系统具备可演示、可部署、可排查、可交付能力。

任务：

1. exe 打包。
2. 统一 exe 名称为“小高AI微信助手”。
3. 日志目录规范。
4. 异常截图归档。
5. 版本号管理。
6. 半年数据清理任务。
7. 部署文档。
8. 客户电脑安装说明。
9. 演示脚本。
10. 回归测试清单。
11. 常见问题排查文档。

------

# 16. VibeCoding 工作约束调整

由于当前主系统尚未开发，VibeCoding 不应再以“探索主系统代码”为第一任务。

新的第一任务应为：

1. 阅读 docs/ai 规则文件。
2. 阅读 CLAUDE.md / AGENTS.md。
3. 阅读当前 project_plan.md。
4. 探索 auto_wechat 当前代码。
5. 输出 auto_wechat 当前真实调用链。
6. 输出当前已验证能力。
7. 输出当前半验证能力。
8. 输出当前未产品化能力。
9. 输出未来主系统接入预留点。
10. 输出本阶段修改范围。
11. 输出是否会影响旧功能。
12. 输出验证方案。

禁止：

1. 不允许假设已有主系统代码。
2. 不允许直接改不存在的主系统接口。
3. 不允许把当前客户配置写死为单客户。
4. 不允许核心表不预留 customer_id / tenant_id。
5. 不允许 Local Agent 并发操作微信。
6. 不允许绕过任务状态机。
7. 不允许失败不回写。
8. 不允许高风险 UI 自动化无日志。
9. 不允许清理任务一次性删除大量历史数据。
10. 不允许 callback_success 混入线索主业务状态。