1. # auto_wechat / 小高AI微信助手 独立验收版 PRD

   版本：V1.2
   阶段：最终 PRD 冻结版
   当前重点链路：AI小高线索 → 小高AI微信助手
   后续文档：CLAUDE.md、docs/ai、架构设计、技术方案、代码方案、接口契约、分阶段开发计划

   ------

   # 1. 项目背景

   当前项目不是单一工具系统，而是 NewCarProject 体系下的一组商户可售卖子功能系统。

   整体结构为：

   ```text
   NewCarProject
     ↓
   外部客户系统 / React 商户端
     ↓
   多个可售卖子功能系统
   ```

   NewCarProject 负责内部运营、商户、账号、权限、菜单、套餐和消耗管理。

   外部客户系统是商户实际使用入口。

   各子功能系统根据商户权限独立售卖、独立启用、独立运行。

   当前重点建设链路为：

   ```text
   AI小高线索 → 小高AI微信助手
   ```

   其中：

   ```text
   AI小高线索：
   负责抖音扫码鉴权、获取抖音私信、识别线索来源。
   
   小高AI微信助手 / auto_wechat：
   负责消费线索，完成销售分配、微信通知、销售回复检测、超时处理、人工处理和数据导出。
   ```

   ------

   # 2. 系统总览

   ## 2.1 NewCarProject

   NewCarProject 是运营人员内部系统。

   职责：

   1. 管理商户账号。
   2. 管理商户权限。
   3. 管理商户可用子功能。
   4. 管理套餐和消耗。
   5. 管理菜单入口。
   6. 控制商户是否可进入某个子功能系统。
   7. 控制非商户角色跳转到多子功能菜单。
   8. 后续统一管理多个子功能模块。

   NewCarProject 不直接承担小高AI微信助手的业务处理逻辑。

   ## 2.2 外部客户系统

   外部客户系统是商户使用入口。

   商户登录后，根据 NewCarProject 分配的权限，进入自己可使用的子功能系统。

   ## 2.3 子功能系统列表

   当前确认的子功能 / 展示项包括：

   1. 抖音AI小高客服
   2. AI小高线索
   3. 小高AI微信助手
   4. AI小高剪辑
   5. 小高素材库
   6. 小高算力

   其中：

   ```text
   小高算力不是子功能系统，而是给商户查看套餐和消耗。
   ```

   ------

   # 3. 各子功能系统边界

   ## 3.1 抖音AI小高客服

   状态：

   ```text
   已完成，非本次重点。
   ```

   本 PRD 不展开该功能。

   ## 3.2 AI小高线索

   AI小高线索是独立售卖的子功能系统。

   它不是小高AI微信助手的普通页面，而是独立的线索来源服务。

   核心职责：

   1. 商户抖音扫码鉴权。
   2. 保存商户抖音授权状态。
   3. 获取商户对应抖音账号私信。
   4. 接收 / 同步抖音或巨量线索事件。
   5. 记录原始线索事件。
   6. 从用户私信文本中提取手机号 / 微信号。
   7. 判断是否产生有效线索。
   8. 向小高AI微信助手提供线索来源。

   使用前置条件：

   ```text
   商户必须完成抖音扫码鉴权后，AI小高线索才能获取对应抖音私信 / 线索。
   ```

   ## 3.3 小高AI微信助手 / auto_wechat

   小高AI微信助手是当前重点建设的子功能系统。

   核心职责：

   1. 获取 AI小高线索提供的有效线索。
   2. 接收 webhook 真实事件。
   3. 记录原始事件。
   4. 识别有效线索。
   5. 分配销售。
   6. 创建微信通知任务。
   7. 调用 Local Agent 操作客户本地微信。
   8. 通知销售。
   9. 检测销售是否有效回复。
   10. 判断已回复 / 超时未回复。
   11. 支持超时重分配。
   12. 支持失败记录。
   13. 支持人工处理。
   14. 支持数据导出。

   小高AI微信助手不负责：

   1. 管理 NewCarProject 商户。
   2. 管理所有子功能权限。
   3. 管理套餐和消耗。
   4. 管理其他子功能系统。
   5. 巨量一键过审。
   6. 抖音扫码鉴权的完整业务闭环，除非后续架构设计明确归入本服务。

   ## 3.4 AI小高剪辑

   AI小高剪辑是独立售卖的子功能系统。

   其中包含：

   ```text
   巨量一键过审
   ```

   巨量一键过审需要：

   ```text
   巨量服务扫码鉴权
   ```

   当前 douyinAPI 中已有巨量一键过审和巨量扫码鉴权相关 demo 代码，但未经过完整验证。

   巨量一键过审不属于小高AI微信助手，不混入 auto_wechat 第一版 PRD。

   后续应单独为 AI小高剪辑 / 巨量一键过审编写 PRD。

   ## 3.5 小高素材库

   小高素材库是独立子功能系统。

   本 PRD 不展开。

   ## 3.6 小高算力

   小高算力不是子功能系统。

   它用于商户查看：

   1. 套餐情况。
   2. 算力消耗。
   3. 功能使用额度。
   4. 可能的计费 / 消耗信息。

   小高算力属于展示和管理类能力，不作为本次小高AI微信助手核心业务范围。

   ------

   # 4. douyinAPI 定位

   douyinAPI 当前不是正式产品系统，也不是未来必须依赖的业务中台。

   当前定位为：

   ```text
   demo / 参考实现 / 历史代码沉淀
   ```

   douyinAPI 中已存在但未完全验证的能力包括：

   1. 抖音扫码鉴权相关代码。
   2. 抖音私信 / 线索相关代码。
   3. 巨量一键过审相关代码。
   4. 巨量服务扫码鉴权相关代码。

   后续产品化时，不应直接把 douyinAPI 作为长期正式依赖，而应按子功能边界拆分、验证和迁移。

   对应关系：

   ```text
   抖音扫码鉴权、抖音私信线索 → AI小高线索
   巨量扫码鉴权、巨量一键过审 → AI小高剪辑
   线索分配、微信通知、回复检测 → 小高AI微信助手
   ```

   ------

   # 5. 服务拆分与隔离要求

   ## 5.1 基本原则

   AI小高线索、小高AI微信助手、AI小高剪辑等子功能服务需要具备独立运行能力。

   要求：

   1. 独立启动。
   2. 独立部署预留。
   3. 独立配置。
   4. 独立健康检查。
   5. 独立日志。
   6. 独立异常处理。
   7. 一个服务异常不影响另一个服务已有功能。
   8. 后续服务器资源不足时，可以将服务拆分到不同服务器部署。

   第一版暂不设计智能路由。

   但必须预留：

   1. 服务地址配置。
   2. 服务端口配置。
   3. 健康检查接口。
   4. 服务启停状态识别。
   5. 服务异常时的降级处理。

   ## 5.2 服务故障隔离

   要求：

   ```text
   AI小高线索故障，不应影响小高AI微信助手继续处理已获取线索和已创建任务。
   小高AI微信助手故障，不应影响 AI小高线索继续接收 / 获取 / 保存线索。
   AI小高剪辑故障，不应影响 AI小高线索 或 小高AI微信助手。
   ```

   ## 5.3 服务器扩展预留

   第一版不做复杂服务治理，不设计智能路由。

   但架构上必须满足：

   1. 后续可以将 AI小高线索迁移到独立服务器。
   2. 后续可以将小高AI微信助手迁移到独立服务器。
   3. 后续可以将 AI小高剪辑迁移到独立服务器。
   4. 服务之间通过明确接口通信。
   5. 服务地址不能写死在代码中。
   6. 必须通过配置管理服务地址。

   ------

   # 6. 当前第一版核心链路

   第一版重点验收链路：

   ```text
   AI小高线索 / webhook 事件
     ↓
   所有事件记录为原始事件
     ↓
   从用户私信纯文本中提取手机号 / 微信号
     ↓
   有效线索生成
     ↓
   小高AI微信助手获取线索
     ↓
   销售分配
     ↓
   创建微信通知任务
     ↓
   Local Agent 操作本地微信通知销售
     ↓
   检测销售回复
     ↓
   更新状态：未分配 / 已分配 / 已回复 / 超时未回复
   ```

   ------

   # 7. webhook 接入规则

   ## 7.1 正式链路

   第一版确认正式验收链路为：

   ```text
   webhook 直收
   ```

   正式 webhook 地址继续使用：

   ```text
   callback.misanduo.com/webhook/douyin
   ```

   所有事件必须记录为原始事件。

   有效线索进入小高AI微信助手处理链路。

   ## 7.2 签名规则

   webhook 回调验签使用《抖音私信能力对外 OpenApi》文档里的签名规则。

   签名规则：

   ```text
   signature = sha256Hex(SECRET_KEY + body + "-" + timestamp)
   ```

   Header：

   ```text
   Authorization: signature
   X-Auth-Timestamp: timestamp
   ```

   说明：

   1. `body` 为请求体原始字符串。
   2. `timestamp` 为秒级时间戳。
   3. `SECRET_KEY` 第一版按客户 / 商户维度配置。
   4. 后续如果每个抖音账号需要不同 `SECRET_KEY`，再扩展到账号维度。
   5. timestamp 过期窗口在技术方案中根据接口文档落地。

   ## 7.3 返回规则

   第一版采用以下返回规则：

   1. 成功接收：HTTP 200
   2. 重复事件：HTTP 200
   3. 非线索事件：HTTP 200
   4. 无效线索：HTTP 200
   5. 请求格式错误：HTTP 400
   6. 签名失败：HTTP 401
   7. 过期请求：HTTP 401
   8. 系统异常：HTTP 500

   原则：

   ```text
   请求合法且系统成功接收，即使不是有效线索，也返回 200，避免外部平台无意义重试。
   ```

   对外成功响应建议：

   ```json
   {
     "code": 0,
     "msg": "success"
   }
   ```

   ------

   # 8. 原始事件与有效线索

   ## 8.1 原始事件

   所有 webhook 事件进入：

   ```text
   lead_source_events
   ```

   包括：

   1. 有效线索事件。
   2. 无效线索事件。
   3. 非线索事件。
   4. 重复事件。
   5. 解析失败但签名通过的事件。

   ## 8.2 有效线索

   有效线索进入：

   ```text
   douyin_leads
   ```

   有效线索判断规则：

   1. 用户留下资料时，联系方式通常出现在用户发出的私信纯文本中。
   2. 系统接收私信 webhook 后，解析用户发出的私信文本内容。
   3. 如果文本中能提取到手机号或微信号，则创建 / 更新有效线索。
   4. 手机号或微信号任一存在，即视为有效线索。
   5. 有效线索进入 `douyin_leads`，并参与销售分配。
   6. 如果文本中无法提取手机号或微信号，则只记录原始事件。
   7. 无联系方式的事件进入 `lead_source_events`，不进入有效线索分配。
   8. invalid 进入前端列表。
   9. invalid 参与数据导出。
   10. invalid 不需要回调。
   11. 第一版不依赖顶层 `phone` / `wechat` 字段。
   12. 第一版不依赖 `retain_consult_card` 留资卡片。
   13. 第一版不接入 LLM。
   14. 第一版采用正则 / 规则提取联系方式。

   ------

   # 9. 联系方式提取规则

   ## 9.1 手机号识别

   第一版识别：

   ```text
   中国大陆 11 位手机号
   ```

   ## 9.2 微信号识别

   第一版识别以下关键词后的账号：

   ```text
   微信
   wx
   vx
   v
   加我
   ```

   示例：

   ```text
   微信 abc123
   wx abc123
   vx abc123
   v abc123
   加我 abc123
   加我微信 abc123
   ```

   ## 9.3 多联系方式处理

   规则：

   1. 一个消息中如果出现多个手机号 / 微信号，全部保存。
   2. 主字段取第一个。
   3. 原始文本完整保存。
   4. 提取结果保存。
   5. 提取失败原因保存。

   建议字段：

   ```text
   raw_message_text
   extracted_phone
   extracted_wechat
   all_extracted_contacts
   contact_extract_status
   contact_extract_reason
   ```

   ------

   # 10. 唯一键与幂等

   ## 10.1 external_lead_id

   优先使用数据源 `id` 作为：

   ```text
   external_lead_id
   ```

   ## 10.2 id 缺失兜底

   如果 `id` 缺失，使用：

   ```text
   open_id + account_open_id
   ```

   ## 10.3 辅助字段

   1. `conversation_short_id`：会话级辅助去重。
   2. `server_message_id`：事件级幂等字段。
   3. `event_key`：webhook 事件幂等字段。

   ## 10.4 重复触发

   1. 同一 `open_id + account_open_id` 多次触发时，更新原线索。
   2. 同一用户不同会话，视为同一用户线索更新。
   3. 重复事件不重复创建线索。
   4. 重复事件需要返回成功。
   5. 重复事件需要记录幂等命中结果。

   ------

   # 11. 线索状态

   ## 11.1 内部状态

   `douyin_leads.status` 建议包括：

   1. received：已接收
   2. invalid：无效线索
   3. delay_assign：非工作时间延迟分配
   4. pending_assign：未分配
   5. assigned：已分配
   6. notified：已通知销售
   7. waiting_reply：等待回复
   8. replied：已回复
   9. timeout：超时未回复
   10. reassigned：已重新分配
   11. manual_required：需要人工处理
   12. failed：失败
   13. closed：人工关闭

   ## 11.2 对外状态

   领导确认对外状态只包括：

   1. 未分配
   2. 已分配
   3. 已回复
   4. 超时未回复

   ## 11.3 内外状态映射

   1. `pending_assign` → 未分配
   2. `delay_assign` → 未分配
   3. `reassigned` → 未分配
   4. `assigned` → 已分配
   5. `replied` → 已回复
   6. `timeout` → 超时未回复

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

   # 12. 字段映射

   ## 12.1 lead_source_events 建议字段

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
   15. message_type
   16. raw_content
   17. message_text
   18. lead_action
   19. is_duplicate
   20. signature_valid
   21. contact_extract_status
   22. contact_extract_reason
   23. raw_payload
   24. received_at
   25. processed_at
   26. process_status
   27. error_message

   ## 12.2 douyin_leads 建议字段

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
   14. all_extracted_contacts
   15. raw_message_text
   16. contact_extract_status
   17. contact_extract_reason
   18. lead_channel
   19. lead_type
   20. latest_event
   21. latest_scene
   22. first_active_time
   23. latest_active_time
   24. source_lead_status
   25. tags_json
   26. last_interaction_record_json
   27. assigned_staff_id
   28. status
   29. raw_payload
   30. cleaned_payload
   31. created_at
   32. updated_at
   33. closed_at

   ## 12.3 字段映射关系

   1. 数据源 `id` → `external_lead_id`
   2. `open_id` → `open_id`
   3. `account_open_id` → `account_open_id`
   4. `display_name` / `nick_name` → `douyin_display_name`
   5. `avatar_url` / `avatar` → `avatar_url`
   6. 用户私信文本提取出的手机号 → `phone`
   7. 用户私信文本提取出的微信号 → `wechat`
   8. 所有联系方式提取结果 → `all_extracted_contacts`
   9. 用户私信原文 → `raw_message_text`
   10. `lead_channel` → `lead_channel`
   11. `lead_type` → `lead_type`
   12. `latest_event` / `event` → `latest_event`
   13. `latest_scene` → `latest_scene`
   14. `conversation_short_id` → `conversation_short_id`
   15. `server_message_id` → `server_message_id`
   16. `first_active_time` → `first_active_time`
   17. `latest_active_time` / `create_time` → `latest_active_time`
   18. `lead_status` → `source_lead_status`
   19. `tags` → `tags_json`
   20. `last_interaction_record` → `last_interaction_record_json`
   21. 完整原始数据 → `raw_payload`
   22. 清洗后数据 → `cleaned_payload`

   ------

   # 13. 销售管理

   ## 13.1 销售字段

   销售信息至少包括：

   1. 微信昵称
   2. 销售姓名
   3. 手机号
   4. 备注
   5. 排序
   6. 状态

   ## 13.2 销售导入

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

   ------

   # 14. 线索分配

   ## 14.1 自动分配

   第一版支持自动分配。

   规则：

   1. 按客户销售列表顺序轮流分配。
   2. 自动排序。
   3. 避免同一销售连续接收过多线索。
   4. 销售列表为空时进入未分配。
   5. 非工作时间按工作时间策略处理。

   ## 14.2 非工作时间分配

   非工作时间收到有效线索时：

   1. 先入库。
   2. 进入内部状态 `delay_assign`。
   3. 对外映射为“未分配”。
   4. 到工作时间后继续自动分配。

   ------

   # 15. 超时与重分配

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

   # 16. 微信通知任务

   ## 16.1 任务创建

   有效线索分配给销售后，系统创建微信通知任务。

   ## 16.2 默认通知模板

   默认模板：

   ```text
   【新线索分配】
   
   客户：{客户名称}
   
   来源：{线索来源}
   
   内容：{线索类型 / 事件}
   
   联系方式：{手机号或微信号}
   
   备注：{备注}
   
   请尽快跟进客户，并在处理完成后回复确认消息。
   ```

   ## 16.3 执行结果

   Local Agent 执行结果包括：

   1. 成功发送。
   2. 联系人未找到。
   3. 微信不可用。
   4. 搜索框异常。
   5. 焦点丢失。
   6. Agent 忙碌。
   7. 执行失败。

   失败需要记录，但截图不保存。

   ------

   # 17. Local Agent / 小高AI微信助手

   ## 17.1 基本规则

   1. 每个客户第一版只考虑一台电脑运行 Local Agent。
   2. 不支持客户多台 Local Agent。
   3. 不支持多个账号。
   4. 同一电脑、同一微信窗口、同一 agent_client_id，同一时间只允许执行一个任务。
   5. 发送任务和检测任务必须互斥。
   6. poll-and-execute 与 poll-and-detect 必须互斥。
   7. 忙碌时返回 agent_busy。
   8. 微信异常时停止操作并回写失败原因。

   ## 17.2 安全规则

   Local Agent 禁止：

   1. 未确认联系人时发送。
   2. 微信窗口不可用时继续操作。
   3. 搜索框焦点未确认时粘贴。
   4. 并发操作微信。
   5. 无任务状态回写。
   6. 无日志执行高风险操作。

   ## 17.3 exe 名称

   统一名称：

   ```text
   小高AI微信助手
   ```

   ------

   # 18. 回复检测

   ## 18.1 第一版检测方式

   第一版不接入大模型。

   回复检测采用：

   1. 关键词判断。
   2. 规则判断。

   ## 18.2 有效回复关键词

   客户可以配置关键词。

   示例：

   1. 收到
   2. 已添加
   3. 已添加微信
   4. 已联系
   5. 正在跟进
   6. 已跟进

   ## 18.3 关键词配置提示

   关键词配置时需要提示客户：

   1. 不要与线索模板内容重复。
   2. 不要设置过短关键词。
   3. 不要设置过宽泛关键词。
   4. 应配置明确表达已处理意图的关键词。

   ------

   # 19. 人工处理

   ## 19.1 适用范围

   第一版人工处理主要面向失败状态。

   暂时只记录失败，不做复杂人工流程。

   ## 19.2 人工处理动作

   允许：

   1. 人工重新分配。
   2. 人工补录销售回复。
   3. 人工关闭线索。

   人工处理后：

   1. 重新分配后进入未分配或分配流程。
   2. 补录销售回复后可进入已回复。
   3. 人工关闭线索后进入 `closed`。
   4. `closed` 不对外回调。
   5. 第一版 `closed` 后不允许恢复。

   ------

   # 20. 登录与权限

   ## 20.1 登录方式

   NewCarProject 跳转 auto_wechat 使用：

   ```text
   token + cookie
   ```

   auto_wechat 需要支持识别 token 和 cookie。

   ## 20.2 NewCarProject 对接状态

   当前 NewCarProject 同事暂时不能继续推进 token / cookie / roles / merchant_id 的具体字段结构。

   因此第一版由 auto_wechat 先做预留设计。

   必须标记为后续待确认项：

   ```text
   NewCarProject token / cookie / roles / merchant_id 的具体字段结构，后续需要与 NewCarProject 同事确认。
   ```

   ## 20.3 customer_id 映射

   第一版规则：

   1. auto_wechat 本地生成 `customer_id`。
   2. NewCarProject 的商户 ID 保存为 `external_customer_id`。
   3. 后续 NewCarProject 正式接入时，通过 `external_customer_id` 建立映射。

   ## 20.4 角色跳转

   规则：

   1. 商户进入 auto_wechat。
   2. 商户不允许跳转到其他子功能。
   3. roles 不是商户的用户，由 NewCarProject 跳转到多子功能菜单。
   4. auto_wechat 只负责自己的子系统使用权限。

   ## 20.5 密码

   第一版支持：

   1. 修改密码。

   第一版不支持：

   1. 重置密码。

   修改密码规则：

   1. 需要输入旧密码。
   2. 新密码最少 8 位。
   3. 建议数字 + 字母。
   4. 修改后强制重新登录。

   ------

   # 21. 前端页面范围

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

   # 22. 数据导出

   ## 22.1 导出格式

   第一版导出格式：

   ```text
   Excel
   ```

   ## 22.2 导出筛选

   支持按时间范围导出。

   ## 22.3 导出内容

   第一版需要导出：

   1. 线索列表
   2. 分配记录
   3. 微信通知任务
   4. 回复检测结果
   5. 超时记录
   6. 回调失败记录
   7. 人工处理记录

   ## 22.4 脱敏要求

   第一版导出不脱敏。

   ------

   # 23. 数据保存与清理

   ## 23.1 业务数据

   业务数据保存：

   ```text
   180 天
   ```

   包括：

   1. 原始事件。
   2. 有效线索。
   3. 分配记录。
   4. 微信任务。
   5. 回复检测。
   6. 超时记录。
   7. 回调失败记录。
   8. 人工处理记录。

   ## 23.2 截图

   第一版：

   1. 截图不保存。
   2. 截图不入库。

   ## 23.3 数据归档

   第一版不做数据归档。

   客户如需历史数据，由客户自行下载。

   ------

   # 24. 高并发与性能口径

   ## 24.1 服务端口径

   第一版服务端按以下口径预留：

   1. 服务端 API 和数据库层面预留 200 QPS。
   2. 单客户峰值按 2000 条线索 / 天考虑。
   3. 查询接口需要分页。
   4. 导出接口需要按时间范围。
   5. webhook 接收需要幂等。
   6. 状态更新需要幂等。
   7. 任务回写需要幂等。

   ## 24.2 Local Agent 口径

   Local Agent 不承诺 200 QPS。

   Local Agent 必须串行执行微信任务。

   ------

   # 25. 验收主链路

   第一版验收主链路如下：

   1. 商户在 NewCarProject / 外部客户系统中拥有 AI小高线索和小高AI微信助手权限。
   2. 商户完成抖音扫码鉴权。
   3. AI小高线索获取商户对应抖音私信 / 线索。
   4. webhook 事件进入 `callback.misanduo.com/webhook/douyin`。
   5. 系统按文档规则校验 webhook 签名。
   6. 所有事件进入 `lead_source_events`。
   7. 系统解析用户发出的私信纯文本。
   8. 系统从文本中提取手机号 / 微信号。
   9. 提取到联系方式的事件创建 / 更新有效线索。
   10. 有效线索进入 `douyin_leads`。
   11. 无效线索只进入原始事件记录。
   12. 有效线索进入未分配或延迟分配状态。
   13. 系统按销售列表自动分配。
   14. 系统创建微信通知任务。
   15. Local Agent 拉取任务。
   16. Local Agent 操作本机微信通知销售。
   17. 系统进入等待销售回复。
   18. Local Agent 检测销售回复。
   19. 命中有效关键词后进入已回复。
   20. 超过配置时间未回复则进入超时未回复。
   21. 超时后按规则自动重分配。
   22. 失败任务进入人工处理。
   23. 商户可在前端查看线索、任务、回复、超时、失败。
   24. 商户可导出 Excel 数据。

   ------

   # 26. 当前仍需外部资料补充

   以下不是 PRD 方向问题，但开发前需要拿到资料或后续对接确认：

   1. webhook 请求体更多真实样例。
   2. NewCarProject token / cookie 传参规则。
   3. NewCarProject roles 字段结构。
   4. NewCarProject 商户 ID 字段。
   5. 状态同步接口格式。
   6. 服务器部署和域名配置说明。
   7. douyinAPI 中抖音扫码鉴权代码位置。
   8. douyinAPI 中抖音私信 / 线索代码位置。
   9. douyinAPI 中巨量扫码鉴权代码位置。
   10. douyinAPI 中巨量一键过审代码位置。

   ------

   # 27. 后续文档计划

   本 PRD 冻结后，后续再分别编写：

   1. CLAUDE.md 更新方案。
   2. docs/ai 相关规则文档更新方案。
   3. 架构设计文档。
   4. 服务拆分设计文档。
   5. 技术方案文档。
   6. 数据模型设计文档。
   7. 接口契约文档。
   8. 代码方案文档。
   9. 分阶段开发计划。
   10. 测试验收计划。
   11. VibeCoding 执行指令。