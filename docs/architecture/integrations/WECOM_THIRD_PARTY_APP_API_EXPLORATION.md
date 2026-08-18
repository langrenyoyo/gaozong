# 企业微信第三方应用接入能力探索

```text
TASK                  = WECOM-THIRD-PARTY-APP-API-EXPLORATION-1
TASK_LEVEL            = L3
OWNER                 = M04
TASK_TYPE             = EXPLORATION_ONLY
IMPLEMENTATION        = NOT AUTHORIZED
CODE_CHANGE           = NOT AUTHORIZED
DB_CHANGE             = NOT AUTHORIZED
PRODUCTION_CHANGE     = NOT AUTHORIZED
GOVERNANCE_CHANGE     = NOT AUTHORIZED
DATE                  = 2026-08-18
```

> 本文档是能力探索结论，不是实现方案、不是迁移批准、不是生产授权。
> 所有企业微信结论均来自 developer.work.weixin.qq.com 官方文档；凡官方未明确说明的，标注 `OFFICIAL_EVIDENCE = NOT_CONFIRMED`，禁止凭经验补全。
> 官方资料受登录态门禁影响的点已在第 19、20 节明确列出。

---

## 0. 最终结论（8 问直答）

```text
Q1 第三方应用是否可以满足"小高AI多商户 SaaS 企业授权"？
   = YES（多企业每企业一个授权，permanent_code + 密文 corpid + agentid 按 merchant 隔离，CONFIRMED）

Q2 是否可以由客户管理员扫码授权？
   = YES（3rdapp/install 安装授权 URL，管理员扫码授权，CONFIRMED）

Q3 管理员是否可以选择销售人员可见范围？
   = YES（可见范围 = allow_user/allow_party/allow_tag，管理员可设置并修改，CONFIRMED）

Q4 是否可以同步这些销售成员？
   = YES（但第三方应用拿不到真实姓名/手机/邮箱，仅 open_userid + userid，name 以 userid 代替，CONFIRMED）

Q5 是否可以向指定销售发送派单？
   = YES（message/send，touser 单成员或 | 分隔批量，受可见范围+基础接口许可限制，CONFIRMED）

Q6 销售反馈最推荐使用什么官方机制？
   = 方案 D：template_card 按钮回调（F2）为主 + H5 结构化反馈（F3）为补充；成员直接发消息（F1）仅兜底

Q7 能否彻底取消 OCR / Mouse Automation？
   = YES（反馈改为结构化点击/表单，反馈采集链路不再需要 OCR；派单与身份识别同步去除个人微信 UI 自动化）

Q8 能否彻底退役 19000 Local Agent？
   = CONDITIONAL（能力映射可全覆盖；阻塞条件见第 18 节：需独立服务商主体、suite_ticket 持续接收、基础接口许可、回调可靠投递兜底，且 19000 当前还承载 AI 剪辑本地执行面）
```

Q8 非 YES 的 BLOCKER、OFFICIAL_EVIDENCE、REQUIRED_DECISION 见第 18 节。

---

## 1. Executive Summary

auto_wechat（小高AI系统）当前 M04 微信助手链路是"个人微信 UI 自动化"：19000 Local Agent 在销售所在 Windows 电脑上操作个人微信客户端，靠搜索联系人/OCR/粘贴回车发送派单，再靠 OCR 读回复 + 关键词/固定模板解析销售反馈。

本轮探索确认：企业微信**第三方应用**官方能力可完整覆盖"多企业授权 → 同步销售成员 → 向指定销售派单 → 接收结构化销售反馈"全链路，且关键判断均有官方文档证据：

- **授权链**（Phase A/B/C）：服务商 suite 凭证 + suite_ticket + pre_auth_code + 扫码授权 + permanent_code + 企业 access_token + 可见范围，全链路 CONFIRMED。取消授权 `cancel_auth`、可见范围变更 `change_auth` 事件 CONFIRMED（但官方明示回调无法保证 100% 成功，需对账兜底）。
- **成员同步**（Phase D）：第三方应用以 `open_userid`（全局唯一、同一服务商跨应用一致）为成员身份主线；真实姓名/手机/邮箱第三方应用默认不可获取。CONFIRMED。
- **派单**（Phase E）：`message/send`，模板卡片-按钮交互型最匹配"查看线索/反馈结果"交互，`task_id`/`EventKey` 官方原样回传可绑定 lead_id。CONFIRMED。
- **反馈**（Phase F，P0）：F2 模板卡片按钮回调 = SUPPORTED（lead 精确绑定、无 NLP、可置灰防重复）；F3 H5 结构化反馈 = SUPPORTED；F1 成员直接发消息 = PARTIALLY_SUPPORTED（无法绑定 lead、需 NLP）。推荐 F2 为主 + F3 补充。
- **多租户**：auth_corp_id（密文 corpid）↔ merchant_id 一一绑定，所有企业级凭证 merchant scoped。CONFIRMED。

**退役判断**：能力映射可全覆盖个人微信自动化，`CAN_RETIRE_19000_COMPLETELY = CONDITIONAL`，阻塞条件为非能力缺口（属主体/许可/兜底工程项，见第 18 节）。

**证据缺口**：本轮受开发者文档登录门禁影响，以下第三方专属细节 NOT_CONFIRMED（上线前须用服务商账号确认）：第三方网页授权构造链接 appid 取值、第三方接收消息配置页、服务商许可/接口许可收费规则。

---

## 2. 当前 auto_wechat / 19000 链路事实

> 证据来源：仓库代码只读探索（`file_path:line`）。

### 2.1 19000 Local Agent 当前职责

19000 = "小高AI微信助手"本机微信 UI 自动化进程，只监听 127.0.0.1，运行在微信所在 Windows 电脑上，9000 不直接操作微信。

- 端口/身份：[app/local_agent_main.py:66-70](../../../app/local_agent_main.py#L66-L70)（`DEFAULT_HOST="127.0.0.1"`、`DEFAULT_PORT=19000`、`AGENT_DISPLAY_NAME="小高AI微信助手"`）；exe 入口 [app/local_agent_exe_entry.py:27-29](../../../app/local_agent_exe_entry.py#L27-L29)
- **收发消息（派单）**：`POST /agent/tasks/poll-and-execute` → 拉取 `notify_sales` 任务 → 搜索联系人 → OCR 验证 → 粘贴/回车发送 → 回写 [app/local_agent_main.py:1878-2251](../../../app/local_agent_main.py#L1878-L2251)
- **回复检测（OCR 只读）**：`POST /agent/tasks/poll-and-detect`（[app/local_agent_main.py:2255-2488](../../../app/local_agent_main.py#L2255-L2488)）与 `POST /agent/replies/detect`，读微信气泡 → 调 9000 `/replies/agent-write-back`
- **后台轮询**：`/runtime/enable-task-polling` 启动轮询循环 [app/local_agent_main.py:1598-1668](../../../app/local_agent_main.py#L1598-L1668)
- **在线状态**：心跳每 10 秒 POST 9000 `/agent/heartbeat` [app/local_agent_main.py:502-538](../../../app/local_agent_main.py#L502-L538)
- **日报附件投递**：`POST /agent/tasks/poll-and-send-report`（默认 dry_run 探针，真实发送禁用）[app/local_agent_main.py:2491-2577](../../../app/local_agent_main.py#L2491-L2577)
- **OCR/鼠标/窗口诊断**：`/agent/ocr/status`、`/agent/wechat/windows` 等 [app/local_agent_main.py:1689-1866](../../../app/local_agent_main.py#L1689-L1866)
- 另承载 **AI 剪辑本地执行**（[frontend/src/features/ai-edit/localApi.ts:13](../../../frontend/src/features/ai-edit/localApi.ts#L13) 直连 19000）——属 Phase 12 剪辑模块，独立于线索链路

### 2.2 9000 如何创建微信任务

- 模型：[app/models.py:290-342](../../../app/models.py#L290-L342)（`WechatTask`）
- 创建：[app/services/wechat_task_service.py:66-128](../../../app/services/wechat_task_service.py#L66-L128)（`create_wechat_task`，`task_type=notify_sales/detect_reply`，`mode=paste_only/single_send`，初始 `status=pending`）
- 路由 POST 创建**已禁用**：[app/routers/wechat_tasks.py:36-49](../../../app/routers/wechat_tasks.py#L36-L49)（注释"必须通过内部受控链路"）
- **手动派单主链路**：`POST /lead-notifications/send-to-staff` → 创建 WechatTask（`target_nickname=staff.wechat_nickname`）+ 原子创建 LeadNotification [app/routers/lead_notification_actions.py:41-153](../../../app/routers/lead_notification_actions.py#L41-L153)
- **webhook 自动链路已禁用**：[app/integrations/douyin_webhook.py:1030-1031](../../../app/integrations/douyin_webhook.py#L1030-L1031)（`task_reason="auto_notify_disabled"`）
- 任务状态机：`pending/running/pasted/sent/failed/blocked/cancelled`（[app/models.py:307-308](../../../app/models.py#L307-L308)）；P2-M04 claim/lease 扩展：`claim_token_hash/lease_expires_at/attempt_count/claimed_by`（[app/models.py:334-337](../../../app/models.py#L334-L337)）
- **注意**：`send_source` 属于抖音私信表 `DouyinPrivateMessageSend`，不在微信任务链路

### 2.3 wechat_tasks 数据结构与职责

WechatTask 是"个人微信 UI 自动化任务队列"（M04 执行载体），绑定销售微信昵称、以粘贴/发送模式驱动本机微信。字段含 `task_type/lead_id/staff_id/reply_check_id/target_nickname（销售微信昵称）/message/mode/status/failure_stage/raw_result/agent_hostname/agent_pid/pasted_at/sent_at/report_delivery_id` 及多组安全令牌 hash、claim/lease 字段 [app/models.py:290-342](../../../app/models.py#L290-L342)。外键 `lead_id → douyin_leads.id`、`staff_id → sales_staff.id`、`reply_check_id → reply_checks.id`、`report_delivery_id → daily_report_deliveries.id`。与 lead/staff 均做商户 AND 隔离 [app/services/wechat_task_service.py:152-161](../../../app/services/wechat_task_service.py#L152-L161)。

> **判断**：`wechat_tasks` 本质是"销售通知任务"业务概念（任务分发 + claim/lease + 回写状态机），但其 `target_nickname/mode=paste_only` 等字段是个人微信专属实现。**不应因退役个人微信就立刻删表**（详见第 16 节 ADAPT 判断）。

### 2.4 sales_staff 当前如何绑定销售

[app/models.py:94-117](../../../app/models.py#L94-L117)：`id/name/wechat_id/wechat_nickname/phone/status/merchant_id` + 5 项报表开关。身份唯一键=自增 id；`wechat_nickname` 用作派单 `target_nickname`（[app/routers/lead_notification_actions.py:109](../../../app/routers/lead_notification_actions.py#L109)）。**无任何 wecom userid/open_userid 字段**。

### 2.5 线索如何分配给销售

`assign_service.assign_lead`（手动指定、跨商户拒绝）[app/services/assign_service.py:23-87](../../../app/services/assign_service.py#L23-L87)；`auto_assign_next`（同商户活跃销售轮询）[app/services/assign_service.py:90-133](../../../app/services/assign_service.py#L90-L133)。分配后创建 `notify_sales` 任务 → 19000 在个人微信粘贴/发送。通知文本含反馈编号 `build_feedback_no(lead_id, staff_id)`。

### 2.6 销售反馈现在如何进入系统

反馈采集 = 19000 OCR 读销售个人微信消息 → 9000 关键词判定 → 固定模板解析落库。
- 19000 读消息回传：`POST /replies/agent-write-back` [app/local_agent_main.py:1361-1370](../../../app/local_agent_main.py#L1361-L1370)
- 关键词判定：[app/services/wechat_ui_reply_service.py:280-478](../../../app/services/wechat_ui_reply_service.py#L280-L478)（关键词表 `收到,已添加,已联系,已通过...`）
- 模板解析落库：[app/services/sales_feedback_parser.py:85-150](../../../app/services/sales_feedback_parser.py#L85-L150)（`【线索反馈】`/`【线索更新】`/`【每日线索总结】`）
- 手动补录：`POST /sales-feedback/parse` [app/routers/sales_feedback.py:24-73](../../../app/routers/sales_feedback.py#L24-L73)
- 旧 `FeedbackRecord`（主机微信 B → 数据源微信 A）属更早旧方案，与当前销售反馈链路不同

### 2.7 日报/报表是否依赖微信反馈结果

**是（部分）**：每日线索销售反馈表（daily_sales_feedback）直接依赖 `SalesLeadFeedback`（由 19000/个人微信反馈模板解析而来）[app/services/daily_report_service.py:167-191](../../../app/services/daily_report_service.py#L167-L191)、[app/services/daily_report_service.py:450-494](../../../app/services/daily_report_service.py#L450-L494)。其他报表（短视频/直播留资表）基于 `DouyinLead + DailyAdMetric`，不依赖微信反馈。

### 2.8 前端是否存在"小高AI微信助手"相关页面

存在完整 wechat-assistant 前端模块，对 19000 依赖面大：`frontend/src/features/wechat-assistant/`（`WechatAgent.tsx`/`DailyReports.tsx`/`LocalWechatAgentTestPanel.tsx`/`WechatTaskPanel.tsx`），直连 `127.0.0.1:19000`（[frontend/src/api/localWechatAgent.ts:1-13](../../../frontend/src/api/localWechatAgent.ts#L1-L13)），不走 VITE_API_BASE_URL。

---

## 3. 目标业务流程

```text
购买小高AI → 创建/已有企业微信 → 管理员点"绑定企业微信" → 扫码授权安装"小高AI"
→ 选择销售人员可见范围 → 小高AI获取授权 → 同步销售成员 → sales_staff ↔ 企业微信成员绑定
→ 开始派单 → 接收销售反馈
```

本轮只做官方接口能力探索，不修改任何代码。

---

## 4. 第三方应用整体身份模型

```text
SERVICE_PROVIDER（服务商级，跨商户共享，非 merchant scoped）
  ├─ suite_id / suite_secret          长期，敏感
  ├─ Token / EncodingAESKey           长期，回调签名/加解密
  ├─ suite_ticket                     30 分钟有效、10 分钟推送，须始终用最新值
  └─ suite_access_token               2 小时，缓存

MERCHANT（企业级，merchant scoped）
  ├─ auth_corp_id（密文 corpid）       长期，↔ merchant_id 一一绑定
  ├─ permanent_code                   永久，须加密持久化
  ├─ agentid                          每企业安装的应用 id
  ├─ corp_access_token（企业 access_token）  2 小时，缓存，merchant 隔离
  └─ 可见范围 privilege（allow_user/party/tag）

MEMBER（成员级，merchant scoped）
  ├─ open_userid                     第三方应用成员身份主线，全局唯一
  └─ userid                           企业内 ID，明文不保证
```

- **官方证据**：服务商凭证层级 [/document/path/90593](https://developer.work.weixin.qq.com/document/path/90593)、[/document/path/91199](https://developer.work.weixin.qq.com/document/path/91199)；suite_ticket [/document/path/90628](https://developer.work.weixin.qq.com/document/path/90628)；suite_access_token [/document/path/90600](https://developer.work.weixin.qq.com/document/path/90600)；permanent_code / corp_access_token [/document/path/100776](https://developer.work.weixin.qq.com/document/path/100776)、[/document/path/90605](https://developer.work.weixin.qq.com/document/path/90605)；密文 corpid / open_userid 跨企业一致性 [/document/path/98728](https://developer.work.weixin.qq.com/document/path/98728)、[/document/path/90196](https://developer.work.weixin.qq.com/document/path/90196)。
- **所有 token 均不可发往浏览器**；suite_secret / provider_secret / permanent_code / Token / EncodingAESKey 属长期敏感凭证，绝不进前端。
- `OFFICIAL_EVIDENCE = CONFIRMED`（身份层级与凭证分类）。

---

## 5. 企业安装授权链（Phase A/B）

### Phase A：服务商/第三方应用基础

1. 第三方应用创建：需服务商或个人开发者身份，在服务商官网 open.work.weixin.qq.com 或开发者中心注册，创建"网页应用/小程序"后获得 SuiteId/SuiteSecret/Token/EncodingAESKey [/document/path/90594](https://developer.work.weixin.qq.com/document/path/90594)、[/document/path/90595](https://developer.work.weixin.qq.com/document/path/90595)。`CONFIRMED`。
2. suite_id（应用唯一身份，ww/wx 开头）、suite_secret（调用密钥）、Token（回调签名密钥，≤32 位）、EncodingAESKey（AES 密钥，43 位）[/document/path/90593](https://developer.work.weixin.qq.com/document/path/90593)、[/document/path/91199](https://developer.work.weixin.qq.com/document/path/91199)、[/document/path/91116](https://developer.work.weixin.qq.com/document/path/91116)。`CONFIRMED`。
3. suite_ticket：企业微信每 10 分钟推送一次，有效 30 分钟，须始终用最新值；丢失可在服务商平台手动触发推送 [/document/path/90628](https://developer.work.weixin.qq.com/document/path/90628)。`CONFIRMED`。
4. suite_access_token：`POST /cgi-bin/service/get_suite_token`，入参 suite_id+suite_secret+suite_ticket，返回 expires_in=7200（2 小时），须自行缓存，不可频繁获取 [/document/path/90600](https://developer.work.weixin.qq.com/document/path/90600)。`CONFIRMED`。

### Phase B：客户企业扫码授权

| 步骤 | 接口/动作 | 官方 URL | INPUT | OUTPUT | 有效期 | 一次性 | 长期保存 | 租户层级 | 失败处理 |
|---|---|---|---|---|---|---|---|---|---|
| 换 suite_access_token | get_suite_token | /90600 | suite 三件套 | suite_access_token | 2h | 否 | 缓存 | SERVICE_PROVIDER | 重取 |
| 获取预授权码 | get_pre_auth_code | /90601 | suite_access_token | pre_auth_code | 20min | 是 | 否 | 流程 | 重取 |
| 设置授权配置（可选） | set_session_info | /90602 | pre_auth_code, session_info{auth_type} | errcode | — | — | — | 流程 | — |
| 安装授权 URL | 3rdapp/install | /90597 | suite_id+pre_auth_code+redirect_uri+state | 跳转/回调 auth_code | — | 是 | 否 | 流程 | state 校验 |
| 换永久授权码 | get_permanent_code v2 | /100776 | auth_code（10min） | permanent_code+auth_corp_info+state | 永久 | 是 | **是（加密）** | MERCHANT | auth_code 过期需重走授权 |
| 换企业 access_token | get_corp_token | /90605 | auth_corpid+permanent_code | access_token | 2h | 否 | 缓存 | MERCHANT | 刷新 |
| 获取授权信息（对账） | get_auth_info v2 | /100779 | auth_corpid+permanent_code | auth_info.agent[]{agentid,privilege} | 实时 | 否 | — | MERCHANT | — |

- 授权发起有两种：服务商网站发起走 redirect 回调（不推 create_auth）；企业微信应用市场发起推 `create_auth` 事件 [/document/path/90597](https://developer.work.weixin.qq.com/document/path/90597)、[/document/path/100964](https://developer.work.weixin.qq.com/document/path/100964)。
- v2 get_permanent_code 不返回 agentid/appid，agentid 须从 get_auth_info 获取 [/document/path/100779](https://developer.work.weixin.qq.com/document/path/100779)。
- `OFFICIAL_EVIDENCE = CONFIRMED`。

### 重点验证：管理员能否选择"可见范围/销售人员"

**`OFFICIAL_EVIDENCE = CONFIRMED`**，多方佐证：
1. get_auth_info 的 `privilege.allow_user/allow_party/allow_tag` 即"应用可见范围（成员/部门/标签）"[/document/path/100779](https://developer.work.weixin.qq.com/document/path/100779)。
2. 通讯录权限："第三方应用可读取管理员所设置的应用使用范围内成员信息"[/document/path/91143](https://developer.work.weixin.qq.com/document/path/91143)。
3. change_auth 触发条件明确含"应用的可见范围变更"[/document/path/100964](https://developer.work.weixin.qq.com/document/path/100964)。
4. 设置授权应用可见范围接口 allow_user/allow_party/allow_tag [/document/path/90583](https://developer.work.weixin.qq.com/document/path/90583)。

即"销售人员"粒度可用"成员"维度表达，管理员在授权安装/管理中可设置并修改。

---

## 6. Token / Credential 生命周期

| 凭证 | 层级 | 有效期 | 长期保存 | 发浏览器 | 官方 URL |
|---|---|---|---|---|---|
| suite_id/suite_secret | SERVICE_PROVIDER | 长期 | 是 | secret 禁 | /90593 |
| Token/EncodingAESKey | SERVICE_PROVIDER | 长期（回调配置） | 是 | 禁 | /91116 |
| suite_ticket | SERVICE_PROVIDER | 30min（10min 推送） | 缓存最新值 | 禁 | /90628 |
| suite_access_token | SERVICE_PROVIDER | 2h | 缓存 | 禁 | /90600 |
| pre_auth_code | 流程 | 20min | 否 | 可 | /90601 |
| auth_code | 流程 | 10min | 否 | 可 | /90597 |
| auth_corp_id（密文 corpid） | MERCHANT | 长期 | 是 | 禁 | /100776 |
| permanent_code | MERCHANT | 永久 | **是（加密）** | 禁 | /100776 |
| agentid | MERCHANT | 长期 | 是 | 禁 | /100779 |
| corp_access_token | MERCHANT | 2h | 缓存（merchant 隔离） | 禁 | /90605 |

- access_token 失效重取：官方明示"企业微信可能出于运营需要提前使 access_token 失效，开发者应实现失效时重新获取"[/document/path/91039](https://developer.work.weixin.qq.com/document/path/91039)。`CONFIRMED`。
- permanent_code 失效条件：仅"代开发应用重新获取 secret"触发 reset_permanent_code 明确 [/document/path/94758](https://developer.work.weixin.qq.com/document/path/94758)；cancel_auth 是否使 permanent_code 失效 **官方未说明** = `NOT_CONFIRMED`；无通用过期时间。
- `OFFICIAL_EVIDENCE = CONFIRMED`（除 permanent_code 在 cancel_auth 下失效条件为 NOT_CONFIRMED）。

---

## 7. Callback / Event 模型（Phase C/G）

### 配置

第三方应用配置**两个回调 URL**（官方分两套而非一套）[/document/path/90595](https://developer.work.weixin.qq.com/document/path/90595)：
- **指令回调 URL**：接收 suite_ticket、授权变更（create_auth/change_auth/cancel_auth）等系统/指令事件。
- **数据回调 URL**：接收成员消息、按钮/菜单点击等业务回调（支持 `$CORPID$` 参数）。

加解密/签名机制统一：Token + EncodingAESKey + msg_signature + timestamp + nonce + echostr/AES 密文 [/document/path/91116](https://developer.work.weixin.qq.com/document/path/91116)、[/document/path/90613](https://developer.work.weixin.qq.com/document/path/90613)。`CONFIRMED`。

### URL 验证

保存回调配置时 `GET url?msg_signature&timestamp&nonce&echostr`：校验签名 + 解密 echostr + **1 秒内返回明文**（不能加引号/BOM/换行）。timestamp+nonce 防重放。`CONFIRMED`。

### 应答 / 重试 / 异步

- 指令回调返回字符串 `"success"`，否则当错误 [/document/path/90613](https://developer.work.weixin.qq.com/document/path/90613)。
- **5 秒**内无响应断连重试，共 **3 次**；授权类事件要求 **1000ms** 内响应。
- 官方建议"接受回调后立即应答，业务异步处理"。
- **官方明示："目前无法保证 100% 回调成功……建议不要强依赖回调，需额外机制对齐业务数据"** [/document/path/91116](https://developer.work.weixin.qq.com/document/path/91116)。`CONFIRMED`。

### 授权生命周期事件

| InfoType | 含义 | 关键字段 | 官方处置要求 | URL |
|---|---|---|---|---|
| suite_ticket | 每 10 分钟推送 | SuiteTicket | 用最新值 | /90628 |
| create_auth | 授权成功（仅应用市场发起） | AuthCode（10min）、State | 1000ms 响应，先记 AuthCode 立即回应 | /100964 |
| change_auth | 变更授权（含可见范围变更/禁启用/模式切换/权限修改） | AuthCorpId、State | 1000ms 响应，须调 get_auth_info + agent/get_permissions 比对 | /100964 |
| cancel_auth | 取消授权 | AuthCorpId | 1000ms 响应，官方要求"删除该企业所有相关数据" | /100964 |
| reset_permanent_code | 重置永久授权码 | AuthCode（10min） | 用新 auth_code 换最新 permanent_code | /94758 |
| corp_arch_auth | 同意授权组织架构权限 | — | — | /97378 |

- **(1) 客户取消授权如何可靠知道**：`cancel_auth` 事件 CONFIRMED [/document/path/100964](https://developer.work.weixin.qq.com/document/path/100964)；但回调不保证 100% 成功，须配定期 get_auth_info 对账兜底。
- **(2) 管理员修改可见范围如何重新同步**：`change_auth` 事件 CONFIRMED [/document/path/100964](https://developer.work.weixin.qq.com/document/path/100964)，收到后调 v2/get_auth_info（privilege 可见范围）+ agent/get_permissions（[/document/path/99052](https://developer.work.weixin.qq.com/document/path/99052)）比对。

### 幂等

- 官方回调 XML **不提供消息 ID / 幂等 key / 事件序号**，不承诺 exactly-once（重试 3 次造成重复投递，且可能乱序/丢弃）。`幂等 key 由服务商自行设计`（如 InfoType + AuthCorpId + SuiteId + CreateTime / FromUserName + CreateTime）。`STATUS = OFFICIAL_DOC_NOT_CONFIRMED`（官方无现成幂等机制）。
- 处理建议（官方原文）：立即应答 → 异步处理 → 幂等落库 → 以查询接口（get_auth_info / 通讯录拉取）对账兜底。

---

## 8. 企业成员同步（Phase D）

第三方应用读取成员受**应用可见范围**限制，范围外不可读（`CONFIRMED`）。

| 接口 | URL | 关键返回 | 第三方限制 |
|---|---|---|---|
| CONTACT-01 部门列表 | /90208 | id/name/parentid/order | 仅可见范围；**name 第三方不返回**（以 id 代替，仅通讯录应用可获取） |
| CONTACT-02 部门成员 | /90200 | userid/name/department/open_userid | 仅可见范围；**name 第三方不返回真实值**；open_userid 仅第三方可获取 |
| CONTACT-03 成员详情 | /90196 | userid/department/position/status | 仅可见范围；status 1已激活/2禁用/4未激活/5退出；**头像/性别/手机/邮箱等 2022-06-20 起默认不返回** |
| CONTACT-04 成员 ID 列表 | /96067 | userid+department 分页 | **仅通讯录同步 secret**，普通第三方不可用；不返回 open_userid |

- 写成员（创建/更新/删除）仅通讯录同步助手/第三方通讯录应用可调用，普通第三方**只读不可写** [/document/path/90197](https://developer.work.weixin.qq.com/document/path/90197)。`CONFIRMED`。

### 第三方应用成员 ID 体系（重点）

- **open_userid 是主线**：全局唯一；同一服务商不同应用获取企业内同一成员 open_userid 相同；最多 64 字节；仅第三方应用可获取 [/document/path/90196](https://developer.work.weixin.qq.com/document/path/90196)、[/document/path/90200](https://developer.work.weixin.qq.com/document/path/90200)、[/document/path/91121](https://developer.work.weixin.qq.com/document/path/91121)。`CONFIRMED`。
- **userid 明文不保证**：第三方应用读取接口返回的 userid 字段实际填充 open_userid；OAuth 场景（getuserinfo3rd）企业有授权关系时按"升级后 ID 策略"返回明文或密文 [/document/path/91121](https://developer.work.weixin.qq.com/document/path/91121)。`CONFIRMED`。
- **跨企业/换企业 open_userid 是否相同**：官方只确认"全局唯一 + 同服务商跨应用一致"，**未明说换企业是否相同** = `NOT_CONFIRMED`。
- **userid ↔ open_userid 专用转换接口**：未找到官方接口（"userid 与 openid 互换"[/document/path/90202](https://developer.work.weixin.qq.com/document/path/90202) 是企业支付 openid，不适用）；建议用 CONTACT-02（同时返回 userid + open_userid）一次性建映射。`CONFIRMED`（无专用接口）。
- **第三方应用禁止获取明文 userid/external_userid** [/document/path/98728](https://developer.work.weixin.qq.com/document/path/98728)、[/document/path/95884](https://developer.work.weixin.qq.com/document/path/95884)。`CONFIRMED`。

### sales_staff ↔ 企业微信成员 identity 字段建议（仅数据模型建议，不建表）

| 建议字段 | 说明 |
|---|---|
| wecom_corpid | 密文 corpid（auth_corp_id），多企业 SaaS 必须 |
| wecom_open_userid | **主绑定键**，第三方全局唯一成员标识 |
| wecom_userid | 企业内 userid（明文不保证），辅助 |
| wecom_department_ids | 成员所属部门（可见范围归属校验） |
| wecom_status | 1/2/4/5，停用同步 |
| wecom_agentid | 该企业下应用 agentid |
| 手机号/邮箱 | 第三方不可获取，须来自业务侧，不得依赖企业微信补 |

---

## 9. sales_staff 成员绑定建议

- 绑定键：`merchant_id + wecom_corpid + wecom_open_userid`（唯一约束防重）；wecom_userid 辅助。
- 推荐新建 `wecom_member_bindings` 概念实体（复用现有 `ExternalMerchantBinding` 模式，[app/models.py:120](../../../app/models.py#L120)），而非直接给 sales_staff 加列——前者支持多应用/部门，后者多应用场景会退化。最小化替代=给 sales_staff 加 2 个 nullable 列。
- sales_staff 现有 `wechat_id/wechat_nickname`（个人微信）保留为历史，不删。
- **明文 userid/external_userid 不进 9000**；如小高另有自建应用需打通，用 SEC-04 转换并保证双应用可见范围。

---

## 10. 企业应用派单（Phase E）

### 发送接口

`POST https://qyapi.weixin.qq.com/cgi-bin/message/send?access_token=` [/document/path/90236](https://developer.work.weixin.qq.com/document/path/90236)
- access_token = 企业 access_token（get_corp_token，非 suite_access_token）[/document/path/90605](https://developer.work.weixin.qq.com/document/path/90605)。`CONFIRMED`。
- agentid 第三方经 get_auth_info 获取 [/document/path/90236](https://developer.work.weixin.qq.com/document/path/90236)。`CONFIRMED`。
- 接收人：touser 单成员或 `|` 分隔最多 1000；@all；toparty/totag。**发送页未明文说明第三方 touser 用 open_userid 还是 userid** = `NOT_CONFIRMED`（建议按 open_userid，与读取接口返回一致）。

### 消息类型

官方支持：text/image/voice/video/file/textcard/news/mpnews/markdown/miniprogram_notice/**template_card**（文本通知/图文展示/按钮交互/投票/多项选择 5 种）。`CONFIRMED`。

### 派单形式建议

期望内容"小高AI新线索 + 线索字段 + [查看线索][反馈结果]"最匹配**模板卡片-按钮交互型（button_interaction）**：
- 一个按钮跳 H5（type=1，查看线索）+ 一个或多个按钮回调事件（type=0，反馈结果）；
- 事后 update_template_card 把按钮置灰防重复点击 [/document/path/94888](https://developer.work.weixin.qq.com/document/path/94888)。
- 备选：textcard（文本卡片+单链接）、news（图文）。纯 text/markdown 无按钮，不适合。

### 可见范围 / 限频 / 结果 / 重试 / 错误码

- 可见范围：部分接收人不在范围 → 该成员进 invaliduser 且实际不下发；全部不在 → errcode 81013 [/document/path/90236](https://developer.work.weixin.qq.com/document/path/90236)。`CONFIRMED`。
- unlicenseduser：在可见范围但无基础接口许可（含过期）。`CONFIRMED`。
- 限频：每应用每天 ≤ 账号上限数×200 人次；每应用对同一成员 ≤ 30 次/分、1000 次/时，超出丢弃。`CONFIRMED`。
- 结果追踪：返回 msgid（可撤回 24h 内消息 [/document/path/94867](https://developer.work.weixin.qq.com/document/path/94867)）。`CONFIRMED`。
- 幂等重试：`enable_duplicate_check` + `duplicate_check_interval`（默认 1800 秒）防同样内容重复下发。`CONFIRMED`。
- 关键错误码：81013（全无权限，CONFIRMED）、invaliduser/unlicenseduser（CONFIRMED）、40029 invalid code（CONFIRMED）；40014/43004/60011 官方全局错误码附录存在但本次未逐条引用正文 = `NOT_CONFIRMED`。

---

## 11. 销售反馈方案专项分析（Phase F，P0）

### F1 成员直接给第三方应用发消息

**`DIRECT_MEMBER_MESSAGE_FEEDBACK = PARTIALLY_SUPPORTED`**

- 第三方应用接收成员消息：自建明确支持"接收消息模式"[/document/path/90238](https://developer.work.weixin.qq.com/document/path/90238)、[/document/path/90239](https://developer.work.weixin.qq.com/document/path/90239)；第三方套件回调存在（官方注明"第三方套件回调事件时 CorpID 为 suiteid"）。**第三方接收消息配置页在登录门禁内未直接取证** = 配置细节 `NOT_CONFIRMED`。
- 消息类型：text/image/voice/video/location/link；FromUserName=成员 UserID（第三方拿 open_userid）；含 MsgId。`CONFIRMED`。
- **能否绑定 lead**：回调只有 FromUserName/MsgId/CreateTime/Content，**无 lead/会话上下文**。要对应 lead 只能靠"发送者+时间窗口+自然语言内容"推断。官方排重建议：普通消息用 MsgId，事件用 FromUserName+CreateTime。`CONFIRMED`（无法绑定 lead）。
- 传输：POST XML，5 秒未响应断连重试 3 次。`CONFIRMED`。

### F2 模板卡片按钮回调

**`TEMPLATE_CARD_FEEDBACK = SUPPORTED`**

- 发送 button_interaction 卡片，button_list ≤6，type=0 回调/1 跳转 URL，key 回调作 EventKey，task_id（≤128 字节，全局唯一）[/document/path/90236](https://developer.work.weixin.qq.com/document/path/90236)。`CONFIRMED`。
- 回调事件 template_card_event：EventKey=按钮 key、TaskId=发送时 task_id、ResponseCode、FromUserName=成员 ID [/document/path/90240](https://developer.work.weixin.qq.com/document/path/90240)。→ **lead_id/sales_staff_id 可靠回传**：把 lead_id 编入 task_id + 按钮 key 表反馈类型，回调原样带回。`CONFIRMED`。
- 更新卡片 update_template_card：response_code 必填，72 小时内一次性，可置灰按钮 [/document/path/94888](https://developer.work.weixin.qq.com/document/path/94888)。`CONFIRMED`。
- 前置：须配置回调接口；接收人须可见+基础接口许可（否则 unlicenseduser/81013）。`CONFIRMED`。

### F3 H5 结构化反馈

**`H5_STRUCTURED_FEEDBACK = SUPPORTED`**

- 网页授权 OAuth2：企业微信终端内打开网页，redirect_uri 须与可信域名完全一致（含端口），否则 50001 [/document/path/91335](https://developer.work.weixin.qq.com/document/path/91335)、[/document/path/91022](https://developer.work.weixin.qq.com/document/path/91022)。`CONFIRMED`。
- 获取成员身份 getuserinfo：企业成员返回 userid；非成员返回 openid [/document/path/91023](https://developer.work.weixin.qq.com/document/path/91023)。code 一次性、5 分钟过期。`CONFIRMED`。
- 第三方应用走同一 OAuth 入口、需 agentid、触发接口许可自动激活 [/document/path/91022](https://developer.work.weixin.qq.com/document/path/91022)；升级后第三方拿 open_userid [/document/path/98728](https://developer.work.weixin.qq.com/document/path/98728)。`CONFIRMED`。
- **第三方构造链接 appid 用 suite_id 还是 corpid**：该页门禁内 = `NOT_CONFIRMED`。
- 外部浏览器打开需"企业微信 Web 登录"（须自建应用）[/document/path/98151](https://developer.work.weixin.qq.com/document/path/98151)。
- **是否比自然语言消息回调更稳定：是**（结构化表单、lead_id 带 URL/state、身份精确、提交可幂等、无 NLP）。

### 推荐

**推荐方案 D：F2（模板卡片按钮）为主 + F3（H5）为补充；F1 仅兜底。**

证据驱动对比：

| 维度 | F1(A) | F2(B) | F3(C) |
|---|---|---|---|
| 官方支持程度 | PARTIALLY | **SUPPORTED** | SUPPORTED（第三方 OAuth 细节部分 NOT_CONFIRMED） |
| 可靠性 | 低（NLP 误解析） | 高（结构化） | 高（结构化） |
| 能否绑定 lead_id | 不能 | **能（task_id/EventKey 官方回传）** | 能（URL/state） |
| 开发复杂度 | 中（+NLP） | 低-中 | 中（OAuth+可信域名+前端） |
| 用户操作成本 | 低（打字） | **低（点按钮）** | 中（点开+表单） |
| 幂等 | MsgId 去重 | task_id/response_code(72h 一次性)官方内置 | 自建幂等键 |
| 错误恢复 | 弱 | 强（卡片可置灰/重发） | 强（可重试） |
| 多商户隔离 | 密文 corpid/suiteid 路由 | 企业 access_token+agentid | 每企业 OAuth+可信域名 |
| 需要 NLP | **是** | 否 | 否 |
| 可彻底取消 OCR | 否 | **是** | **是** |

落地要点：为每条已分配 lead 向对应销售发一张 button_interaction 卡片（需可见范围+基础接口许可，注意 30次/分 1000次/时 频控，高峰排队）→ 销售点击 → template_card_event 回调（EventKey=反馈类型、TaskId=lead_id）→ update_template_card 置灰。F3 作补充入口（卡片加"查看线索"跳转 URL 按钮，进 H5 做备注/复杂反馈，身份取 open_userid）。

---

## 12. API Catalog

> 格式：编号/业务用途/官方 URL/HTTP/鉴权/关键参数/关键响应/凭证生命周期/层级/持久化/敏感/失败策略/官方限制/备注。

### AUTH 域

- **WECOM-AUTH-001 获取服务商凭证 get_provider_token**｜/91200｜POST｜corpid+provider_secret｜provider_access_token,expires_in 7200｜2h 缓存｜SERVICE_PROVIDER｜否｜高｜刷新｜—｜—
- **WECOM-AUTH-002 获取第三方应用凭证 get_suite_token**｜/90600｜POST｜suite_id+suite_secret+suite_ticket｜suite_access_token,expires_in 7200｜2h 缓存｜SERVICE_PROVIDER｜否｜高｜重取｜不可频繁获取｜—
- **WECOM-AUTH-003 获取预授权码 get_pre_auth_code**｜/90601｜GET｜suite_access_token｜pre_auth_code,expires_in 1200｜20min 一次性｜流程｜否｜中｜重取｜—｜—
- **WECOM-AUTH-004 设置授权配置 set_session_info**｜/90602｜POST｜pre_auth_code,session_info{auth_type}｜errcode｜—｜流程｜否｜低｜—｜—｜—
- **WECOM-AUTH-005 安装授权 URL**｜/90597｜浏览器 GET｜suite_id+pre_auth_code+redirect_uri+state｜跳转/回调 auth_code｜一次性｜流程｜否｜低｜state 校验｜redirect_uri 须属安装完成回调域名｜—
- **WECOM-AUTH-006 获取企业永久授权码 v2**｜/100776｜POST｜suite_access_token+auth_code(10min)｜permanent_code,auth_corp_info,state｜永久｜MERCHANT｜**是（加密）**｜高｜auth_code 过期重走授权｜auth_code 64-512 字节一次有效｜v2 不返回 agentid
- **WECOM-AUTH-007 获取企业授权信息 v2**｜/100779｜POST｜suite_access_token+auth_corpid+permanent_code｜auth_corp_info,auth_info.agent[]{agentid,privilege}｜实时｜MERCHANT｜否｜中｜—｜—｜agentid/可见范围来源
- **WECOM-AUTH-008 获取企业凭证 get_corp_token**｜/90605｜POST｜suite_access_token+auth_corpid+permanent_code｜access_token,expires_in 7200｜2h 缓存(merchant 隔离)｜MERCHANT｜否｜高｜刷新｜—｜发消息用此 token
- **WECOM-AUTH-009 获取应用二维码**｜/95430｜POST｜suite_access_token｜二维码 buffer/url｜一次性｜SERVICE_PROVIDER｜否｜低｜—｜—｜—
- **WECOM-AUTH-010 获取应用权限详情**｜/99052｜POST｜企业 access_token｜app_permissions[]｜实时｜MERCHANT｜否｜中｜—｜—｜change_auth 后比对
- **WECOM-AUTH-011 获取应用管理员列表**｜/100073｜POST｜suite_access_token+auth_corpid+permanent_code｜管理员列表｜实时｜MERCHANT｜否｜中｜—｜—｜—
- **WECOM-AUTH-012 设置授权应用可见范围**｜/90583｜POST｜注册 access_token+agentid+allow_user/party/tag｜invaliduser/party/tag｜30min 窗口｜MERCHANT｜否｜中｜—｜—｜—

### EVENT 域（回调）

- **WECOM-EVENT-01 推送 suite_ticket**｜/90628｜POST 回调｜指令回调签名｜SuiteTicket｜10min 推送/30min 有效｜SERVICE_PROVIDER｜缓存最新｜中｜始终用最新值｜—｜—
- **WECOM-EVENT-02 授权成功 create_auth**｜/100964｜POST 回调｜指令回调签名｜AuthCode(10min),State｜一次性｜流程｜处理即落库｜中｜1000ms 响应｜仅应用市场发起｜—
- **WECOM-EVENT-03 授权变更 change_auth**｜/100964｜POST 回调｜指令回调签名｜AuthCorpId,State｜一次性｜流程｜处理即落库｜中｜1000ms 响应，须对账 get_auth_info｜触发含可见范围变更｜—
- **WECOM-EVENT-04 取消授权 cancel_auth**｜/100964｜POST 回调｜指令回调签名｜AuthCorpId｜一次性｜流程｜处理即落库｜中｜1000ms 响应，删除企业数据｜不保证 100% 成功，须对账｜—

### CONTACT 域

- **WECOM-CONTACT-01 获取部门列表**｜/90208｜GET｜企业 access_token｜department[]｜2h｜MERCHANT｜部门 id 持久化｜否｜—｜受可见范围，第三方不返回 name｜—
- **WECOM-CONTACT-02 获取部门成员**｜/90200｜GET｜企业 access_token+department_id｜userlist[](userid,open_userid)｜2h｜MERCHANT｜userid+open_userid 映射持久化｜否｜—｜受可见范围，name 以 userid 代替｜建映射主接口
- **WECOM-CONTACT-03 读取成员**｜/90196｜GET｜企业 access_token+userid｜userid,department,position,status｜2h｜MERCHANT｜status 按需｜是(手机/邮箱不返回)｜—｜受可见范围｜—
- **WECOM-CONTACT-04 获取成员 ID 列表**｜/96067｜POST｜**仅通讯录同步 secret**｜dept_user[](userid,department)｜长效｜通讯录同步应用｜userid-部门关系｜否｜—｜普通第三方不可用，不返回 open_userid｜—
- **WECOM-CONTACT-05（OAuth 身份）getuserinfo3rd**｜/91121｜GET｜suite_access_token+code｜userid(明文/密文),open_userid｜code 5min｜流程｜身份映射落绑定表｜高｜redirect_uri 完全匹配可信域名｜—｜—

### MSG 域

- **WECOM-MSG-01 发送应用消息**｜/90236｜POST｜企业 access_token｜touser(|≤1000)/toparty/totag/agentid/msgtype/enable_duplicate_check｜errcode/invaliduser/unlicenseduser/msgid/response_code｜2h｜MERCHANT｜msgid 短期｜是(内容)｜81013/invaliduser 可见范围问题；token 失效重取｜每天≤账号上限×200；同成员≤30次/分 1000次/时｜—
- **WECOM-MSG-02 撤回应用消息**｜/94867｜POST｜企业 access_token｜msgid｜errcode｜2h｜MERCHANT｜否｜否｜—｜仅 24h 内；仅企业微信端｜—
- **WECOM-MSG-03 更新模板卡片**｜/94888｜POST｜企业 access_token｜agentid+response_code(72h 一次性)+template_card｜errcode/invaliduser｜2h｜MERCHANT｜response_code 消费状态｜中｜—｜response_code 只能用一次，72h 内｜置灰按钮用

### FEEDBACK 域

- **WECOM-FEEDBACK-01 接收成员消息/卡片事件回调**｜/90238,/90239,/90240｜POST(XML 加密)｜msg_signature+AES 解密｜ToUserName(密文corpid/suiteid),FromUserName(成员 ID/open_userid),MsgType,MsgId,Event/EventKey/TaskId/ResponseCode｜静态配置｜回调接入层(9000)｜**必须落库** wecom_callback_events｜高(内容+身份)｜5s 超时重试 3 次；须排重｜须排重｜—
- **WECOM-FEEDBACK-02 发送按钮交互型卡片**｜/90236｜POST｜企业 access_token(merchant scoped)｜touser(open_userid),msgtype=template_card,agentid,card_type=button_interaction,task_id(≤128),button_list(≤6,key=反馈类型)｜msgid,response_code,invaliduser/unlicenseduser｜2h｜9000→企微｜**必须** wecom_message_deliveries｜中｜81013/unlicenseduser 可见范围/许可；token 失效重取｜同 MSG-01 频控｜task_id 编 lead_id
- **WECOM-FEEDBACK-03 更新卡片（按钮置灰）**｜/94888｜POST｜企业 access_token｜agentid+response_code+template_card/button.replace_name｜errcode/invaliduser｜2h｜9000→企微｜response_code 消费状态｜中｜response_code 一次性 72h｜—｜—

### SEC 域

- **WECOM-SEC-01 回调验签**｜/91116｜GET(URL 验证)/—｜Token+timestamp+nonce+echostr｜明文 echostr｜静态｜回调接入层｜否｜否｜1s 内返回明文｜timestamp+nonce 防重放｜—
- **WECOM-SEC-02 AES 加解密**｜/91116｜—｜EncodingAESKey｜明文/密文｜静态｜回调接入层｜否｜是｜—｜—｜—
- **WECOM-SEC-03 Token lifecycle**｜/90600,/90605,/91039｜—｜—｜—｜见 AUTH 域｜—｜—｜—｜token 失效重取｜—｜—
- **WECOM-SEC-04 成员身份转换 openuserid_to_userid**｜/95884｜POST｜**自建应用** access_token｜open_userid_list(≤1000),source_agentid｜userid_list,invalid_open_userid_list｜自建应用 token｜9000(小高自建侧)→企微｜转换结果按 merchant 落绑定表｜高｜成员须同时在两应用可见范围｜明文 userid 仅限小高自建侧｜打通第三方与自建

---

## 13. Permission Matrix

| 能力 | 所需权限/许可 | 与可见范围关系 | 是否管理员授权 | 额外许可/收费 | 官方 URL |
|---|---|---|---|---|---|
| 获取成员 | 应用拥有成员查看权限（通讯录权限）；第三方仅"通讯录应用"可获取且非第三方创建成员不可获取；头像/性别/手机/邮箱等 2022-06-20 起默认不返回 | 必须可见 | 是 | 基础接口许可 | /90196、/90236 |
| 发应用消息（含模板卡片） | 基础接口许可；未许可=unlicenseduser；全无权限=81013 | 接收人必须可见 | 是（可见范围+接收消息配置） | **基础接口许可**（基础/互通账号均可，含过期判定）；价格官方未给，不推测 | /90236 |
| 收成员消息 | 自建：开启接收消息模式+配置 URL/Token/EncodingAESKey；第三方：套件回调（CorpID=suiteid），配置页门禁未取证 | 成员须可见 | 是 | 无公开收费说明 | /90238 |
| Template Card 按钮回调 | 同发应用消息许可 + **必须配置回调接口** | 同发消息 | 是 | 同发消息 | /90236、/94888 |
| H5 网页授权 OAuth | 可信域名完全匹配（含端口）；第三方/代开发填 agentid 触发接口许可自动激活；snsapi_privateinfo 需成员可见 | snsapi_privateinfo 必须可见 | 是 | 接口许可自动激活（无额外收费公开说明） | /91022、/91023 |
| 企业微信 Web 登录（浏览器） | 自建应用 + 授权回调域完全匹配 | 不限 | 是 | 无公开收费说明 | /98151 |
| 服务商/第三方应用主体 | 企业授权安装 → 服务商获密文 corpid/permanent_code；升级后 ID 切 open_userid | 授权应用可见范围 | 企业管理员授权 | 第三方应用许可/基础接口许可机制存在；具体价格与"接口许可"页在登录门禁内 = `NOT_CONFIRMED`，不推测 | /98728、/10012(门禁) |

---

## 14. Error / Retry / Idempotency

- **access_token 失效**：官方可能提前使 token 失效，须实现失效重取 [/document/path/91039](https://developer.work.weixin.qq.com/document/path/91039)。40014（不合法 token）建议重取后重试一次。
- **81013 / invaliduser / unlicenseduser**：可见范围/成员状态/许可问题，回写"该销售不可达"，不盲目重试。
- **消息重复下发**：enable_duplicate_check=1 + duplicate_check_interval 防同样内容重复。
- **卡片重复点击**：response_code 72h 一次性，update_template_card 置灰；task_id 全局唯一作幂等键。
- **回调投递**：5s 超时重试 3 次；无消息 ID/幂等 key，须自行按业务键（InfoType+AuthCorpId+CreateTime / FromUserName+CreateTime）去重，并立即应答+异步处理+查询接口对账兜底。
- **关键错误码 40014/43004/60011**：官方全局错误码附录 [/document/path/90396](https://developer.work.weixin.qq.com/document/path/90396) 存在但本次未逐条引用正文 = `NOT_CONFIRMED`，对接时须以官方附录核对。

---

## 15. Multi-tenant / Security

### auth_corp_id ↔ merchant_id 绑定

- auth_corp_id（密文 corpid）= 服务商主体下的密文 corpid，同一服务商不同应用获取到的密文 corpid 相同 → 一个企业微信企业一个稳定标识，适合与 merchant_id 一一绑定 [/document/path/98728](https://developer.work.weixin.qq.com/document/path/98728)。`CONFIRMED`。
- open_userid = 服务商主体下密文 userid，同一服务商跨应用稳定。`CONFIRMED`。
- 第三方应用**禁止**拿明文 userid/external_userid [/document/path/95884](https://developer.work.weixin.qq.com/document/path/95884)。`CONFIRMED`。

### 各数据 merchant 归属

| 数据 | 归属 | 依据 |
|---|---|---|
| permanent_code | merchant scoped（每企业一个，与服务商绑定） | /100776 |
| corp_access_token | merchant scoped（permanent_code 换取，2h 刷新） | /90605 |
| agentid | merchant scoped（每企业安装的 agentid） | /100779 |
| wecom member identity | merchant scoped（open_userid/密文 corpid） | /98728 |
| department | merchant scoped | /90196 |
| callback event | 按 ToUserName(密文 corpid/suiteid) 路由到对应 merchant | /90238、/90240 |
| message delivery | merchant scoped（企业 token+agentid 发送，touser=open_userid） | /90236 |

### 设计红线建议（不写代码）

1. 凭证三要素（permanent_code / corp_access_token / 密文 corpid）只允许挂在 `wecom_enterprise_authorizations.merchant_id` 名下；corp_access_token 缓存键 = `merchant_id:corpid`，**禁止全局共享 token 池**。
2. 回调统一入口先解密 → 按 ToUserName(密文 corpid) 解析 merchant → 拒绝未知 corpid；touser 一律用该 merchant 自己绑定表解析出的 open_userid。
3. **A 商户 token 绝不能读取/发送 B 商户数据**；明文 userid/external_userid 不进 9000。

---

## 16. 建议的数据实体（概念模型，不建表）

| 实体 | 建议 | 理由 |
|---|---|---|
| wecom_enterprise_authorizations | **NEW（必须）** | 承载 permanent_code(加密)、密文 corpid、agentid、企业 access_token 缓存+过期、merchant_id FK、安装状态。现有表无此能力 |
| wecom_member_bindings | **NEW（推荐）**，复用 ExternalMerchantBinding 模式 | 映射 (merchant_id, 密文 corpid, open_userid) ↔ sales_staff.id，唯一约束防重。比给 sales_staff 加列更清晰（支持多应用/部门） |
| wecom_callback_events | **NEW（推荐）**，复用 DouyinWebhookEvent 模式 | 回调原始事件落地 + 去重(MsgId/FromUserName+CreateTime) + 处理状态 + 审计。第三方回调重试 3 次必须幂等落地 |
| wecom_message_deliveries | **NEW（推荐）** | 记录每条已发卡片：lead_id、staff_id、企微 task_id(唯一)、button keys、response_code(一次性 72h)、状态机(sent→card_updated→feedback_received→expired)、反馈结果 |
| sales_staff | **ADAPT**（加企微身份绑定，不删 wechat_id 历史字段） | 通过 wecom_member_bindings 关联或加列；个人微信字段保留为历史 |
| wechat_tasks | **REUSE/ADAPT，绝不因个人微信退役就删** | 它是"销售通知任务"业务概念（任务分发+claim/lease+回写状态机），不是个人微信实现本身。应**抽象通知渠道**（个人微信 LocalAgent / 企业微信消息 API），或由 wecom_message_deliveries 承载企微通道，wechat_tasks 保留为遗留通道。DEPRECATE 需另立迁移审批 |

---

## 17. 推荐目标架构

```text
Lead Assignment
      ↓
9000
      ↓
WeCom Integration Layer（凭证服务/回调路由/消息发送）
      ↓
Credential Service（suite_access_token 服务商级；corp_access_token merchant 隔离缓存）
      ↓
企业微信 API（get_corp_token → message/send button_interaction）
      ↓
销售企业微信

销售反馈
      ↓
Official Callback（数据回调 URL：template_card_event）
      ↓
WeCom Callback Router（解密 → 按 ToUserName 解析 merchant → 幂等落库 wecom_callback_events）
      ↓
9000（lead_id 从 TaskId 回传 → 反馈落库 + update_template_card 置灰）
      ↓
Lead Feedback / 日报数据源
```

退出阶段：
- **OCR**：从"派单回写/反馈采集"阶段完全退出（派单不再需 OCR 验证联系人，反馈改为结构化点击）。
- **鼠标自动化**：从"派单发送"阶段完全退出。
- **个人微信**：从"派单+反馈"阶段完全退出。
- **19000 Local Agent**：从"线索派单/反馈"链路完全退出；**但 19000 当前还承载 AI 剪辑本地执行面**（[frontend/src/features/ai-edit/localApi.ts:13](../../../frontend/src/features/ai-edit/localApi.ts#L13)），退役 19000 需一并处置剪辑本地执行面（属 M06，不在本轮范围）。

---

## 18. Migration Phases & 19000 退役条件

### 迁移阶段建议

```text
P0 官方能力可行性验证（用服务商账号补齐门禁内 NOT_CONFIRMED 项）
P1 第三方应用授权闭环（suite 凭证 + suite_ticket 接收 + 扫码授权 + permanent_code）
P2 企业成员同步 + sales_staff binding（open_userid 主键）
P3 企业微信派单（button_interaction 卡片）
P4 销售反馈闭环（template_card_event 回调 + update_template_card）
P5 双轨验证（个人微信链路与企微链路并行，日报数据源切换）
P6 19000 / OCR / Mouse Automation 退役（线索链路）+ M06 剪辑本地执行面独立处置
```

### CAN_RETIRE_19000_COMPLETELY = CONDITIONAL

阻塞条件（均为非能力缺口的工程/主体/许可项，非 ARCHITECTURE_BLOCKER）：

| BLOCKER | 说明 | OFFICIAL_EVIDENCE | REQUIRED_DECISION |
|---|---|---|---|
| B1 独立服务商主体 | 第三方应用须以服务商（或个人开发者）身份注册，获取 suite_id/suite_secret | CONFIRMED /90594 | 公司决定服务商主体归属 |
| B2 suite_ticket 持续接收 | 须长期稳定接收 suite_ticket（10min 推送、30min 有效），丢失则 suite_access_token 无法换取，全链路中断 | CONFIRMED /90628 | 9000 常驻回调服务设计 |
| B3 基础接口许可 | 发消息/收回调需基础接口许可，未许可成员=unlicenseduser，全无权限=81013；具体许可/收费规则门禁内 NOT_CONFIRMED | 部分CONFIRMED /90236 / NOT_CONFIRMED 收费 | 与企业微信确认许可与收费 |
| B4 回调可靠投递兜底 | 官方明示回调不保证 100% 成功，cancel_auth/change_auth 须配定期 get_auth_info 对账 | CONFIRMED /91116 | 对账任务设计 |
| B5 M06 剪辑本地执行面 | 19000 另承载 AI 剪辑本地执行，退役 19000 需独立处置该面（属 M06，本轮范围外） | 代码事实 localApi.ts:13 | M06 独立任务 |
| B6 门禁内 NOT_CONFIRMED 项 | 第三方网页授权 appid 取值、第三方接收消息配置页、许可/收费规则，须用服务商账号确认 | NOT_CONFIRMED | 立项前用服务商账号补证 |

能力映射本身**无 ARCHITECTURE_BLOCKER**——第三方应用官方能力可覆盖全部目标链路。

---

## 19. Blockers / Unknowns

### ARCHITECTURE_BLOCKER

无。第三方应用官方能力可满足"多商户 SaaS 企业授权 + 扫码授权 + 选可见范围 + 同步成员 + 派单 + 反馈"全链路。

### UNKNOWN_OFFICIAL_CAPABILITIES（须用服务商账号补证）

1. 第三方网页授权构造链接 appid 取值（suite_id 还是 corpid）——门禁内 `/10110` 等。
2. 第三方接收消息配置页细节——门禁内。
3. permanent_code 在 cancel_auth 后是否自动失效——官方未说明。
4. 同一自然人换企业后 open_userid 是否相同——官方未明说。
5. 服务商许可/接口许可具体收费规则——门禁内 `/10012`/`/10013`/`/10020`。
6. 关键错误码 40014/43004/60011 逐条正文——全局错误码附录 `/90396` 未逐条引用。

### OUT_OF_SCOPE_FINDING

- 企业微信客户联系 externalcontact / 客户群 / 朋友圈 / 会话内容存档 / 企业支付等与"销售派单+销售反馈"无关能力，本轮不探索、不设计。若后续为"售后客户触达"等场景需要 external_userid，属独立任务。
- M06 AI 剪辑本地执行面（19000 承载）退役属 M06 独立任务，本轮仅记录其存在。

---

## 20. 官方资料索引

> 全部来自 developer.work.weixin.qq.com。教程站点 `/tutorial/*` 为登录态页面无法抓取正文，以下结论取自 `/document/path/*` 接口/概念文档。

| 主题 | URL |
|---|---|
| 第三方应用开发概述 | /90594 |
| 服务商注册应用 | /90595 |
| 基本概念 | /90593、/91199 |
| 回调配置/加解密 | /91116、/90613 |
| 推送 suite_ticket | /90628 |
| 获取 suite_access_token | /90600 |
| 获取 pre_auth_code | /90601 |
| 设置授权配置 | /90602 |
| 企业授权应用（安装授权 URL） | /90597 |
| 获取 permanent_code v2 | /100776 |
| 获取企业授权信息 v2 | /100779 |
| 获取企业凭证 get_corp_token | /90605 |
| 获取应用二维码 | /95430 |
| 获取应用权限详情 | /99052 |
| 获取应用管理员列表 | /100073 |
| 设置授权应用可见范围 | /90583 |
| 授权通知事件（create/change/cancel_auth） | /100964 |
| 重置永久授权码 | /94758 |
| 授权组织架构权限 | /97378 |
| 获取部门列表 | /90208 |
| 获取部门成员 | /90200 |
| 读取成员 | /90196 |
| 更新成员（写权限） | /90197 |
| 获取成员 ID 列表 | /96067 |
| userid 与 openid 互换（不适用 open_userid） | /90202 |
| 发送应用消息 | /90236 |
| 撤回应用消息 | /94867 |
| 更新模板卡片 | /94888 |
| 接收消息（自建）/消息解析 | /90238、/90239 |
| 事件回调（template_card_event 等） | /90240 |
| 网页授权 OAuth | /91335、/91022 |
| 获取访问用户身份 getuserinfo | /91023 |
| 第三方应用 OAuth 身份 getuserinfo3rd | /91121 |
| 企业微信 Web 登录 | /98151 |
| ID 体系（密文 corpid/open_userid） | /98728、/95884 |
| 通讯录权限 | /91143 |
| access_token 失效重取 | /91039 |
| 全局错误码附录 | /90396 |
| 成员身份转换 openuserid_to_userid | /95884 |

门禁未取证页（NOT_CONFIRMED）：`/10012`、`/10013`、`/10020`、`/10110` 等"第三方应用/服务商"分区根页面。

---

## 21. Recommendation

1. **技术路线维持"企业微信第三方应用"**，无 ARCHITECTURE_BLOCKER，不重新选型。
2. **反馈主通道 = 模板卡片按钮回调（F2）**：唯一无 NLP 且 lead 精确绑定的官方通道；F3 H5 作补充入口；F1 成员直接发消息仅兜底。
3. **成员身份主线 = open_userid**（全局唯一、跨应用一致），绑定键 `merchant_id + 密文 corpid + open_userid`。
4. **多租户**：auth_corp_id（密文 corpid）↔ merchant_id 一一绑定，所有企业级凭证 merchant scoped，禁止全局共享 token 池。
5. **wechat_tasks 不删**，ADAPT 为通知渠道抽象或由 wecom_message_deliveries 承载企微通道，DEPRECATE 需另立迁移审批。
6. **退役 19000 = CONDITIONAL**：能力可全覆盖，阻塞为服务商主体/许可/回调兜底/M06 剪辑面，立项前须用服务商账号补齐 6 项 NOT_CONFIRMED。

---

## 22. 任务结束报告

```text
TASK                             = WECOM-THIRD-PARTY-APP-API-EXPLORATION-1
TASK_LEVEL                       = L3
OWNER                            = M04
OFFICIAL_DOCS_REVIEWED           = developer.work.weixin.qq.com /document/path/* 30+ 篇（见第 20 节）
CURRENT_19000_FLOW_EXPLORED      = YES
AUTHORIZATION_FLOW               = CONFIRMED
MEMBER_SYNC                     = CONFIRMED（open_userid 主线；真实姓名/手机/邮箱不可获取）
SALES_DISPATCH                   = CONFIRMED（button_interaction 卡片）
SALES_FEEDBACK                   = CONFIRMED（F2 为主 + F3 补充；F1 仅兜底）
CAN_RETIRE_19000                 = CONDITIONAL（能力全覆盖；阻塞见第 18 节 B1-B6）
KEY_BLOCKERS                     = B1 服务商主体 / B2 suite_ticket 持续接收 / B3 基础接口许可 / B4 回调兜底 / B5 M06 剪辑本地执行面 / B6 门禁内 NOT_CONFIRMED 项
UNKNOWN_OFFICIAL_CAPABILITIES    = 第三方 OAuth appid 取值 / 第三方接收消息配置页 / permanent_code 在 cancel_auth 失效 / 换企业 open_userid 一致性 / 许可收费 / 错误码逐条正文
RECOMMENDED_FEEDBACK_MODE        = D（F2 模板卡片按钮为主 + F3 H5 补充）
DOCUMENT                         = docs/architecture/integrations/WECOM_THIRD_PARTY_APP_API_EXPLORATION.md
CODE_CHANGE                      = 0
DB_CHANGE                        = 0
PRODUCTION_CHANGE                = 0
G1_DELTA                         = NO（新增探索文档，非代码/owner 事实变化，不动 code_index.yaml）
G2_DELTA                         = NO
G3_DELTA                         = NO
G4_DELTA                         = NO
GIT_STATUS                       = 探索文档新增待提交（docs commit）
RESULT                           = EXPLORATION_COMPLETE
```

不自动进入技术设计。不创建 migration。不实现企业微信 client。不删除 19000。不修改生产配置。等待 Owner 审批探索报告。
