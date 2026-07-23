# 抖音AI小高客服 2.2.2～2.2.5 专项验收报告

## 1. 验收结论摘要

1. 2.2.2 抖音企业号列表已基本满足头像、昵称、未读消息数展示；`unread_count` 已读/未读协议已通过独立测试（候选 `8e69adc36a7df35c054774f6b482bac2887c0123`，T1 A1-A14 PASS，241+10+10=261 passed），使用 `last_seen_event_id` + `(created_at, event_id)` 单调水位计算。
2. 2.2.3 客户会话列表已具备客户头像、姓名、最后消息、消息时间、未读数、点击切换、搜索和标准标签筛选；在线状态仍没有真实抖音来源。
3. 会话标签已标准化为 `manual_required`、`high_intent`、`retained_contact`、`follow_up`，前端映射为需人工、高意向、已留资、待回访。
4. 2.2.4 聊天面板已区分客户消息、人工客服消息、系统消息和 AI 建议卡片；AI托管自动回复按安全边界降级为“AI建议模式”。
5. 人工接管当前是前端本地展示状态，不改变后端发送策略；所有真实发送仍必须人工确认。
6. 工具栏已展示表情、图片、视频、文件边界；图片仅上传素材获取 `image_id`，表情/视频/文件为只读占位或未接入。
7. 2.2.5 客户信息面板已接入 9000 画像接口，不再依赖 9100 mock profile 作为正式工作台来源。
8. 客户画像可展示姓名、头像、在线状态、来源、车型、年份、预算、城市、标签、溯源、线索评分和进度条；字段质量依赖 `douyin_webhook_events` 与 `douyin_leads.raw_data`。
9. 9000 代理与 9100 回复决策仍保持 `auto_send=false`，当前不开放 AI 自动发送私信。
10. 下一步建议优先确认在线状态来源，再评审媒体能力与自动发送安全方案；已读状态协议已通过独立测试（候选 `8e69adc36a7df35c054774f6b482bac2887c0123`，T1 PASS，261 passed），使用 `last_seen_event_id` + `(created_at, event_id)` 单调水位。

## 2. 提交记录

| commit | 任务 | 范围 | 说明 |
| ------ | -- | -- | -- |
| `8d06282` | 补齐抖音企业号未读数聚合 | 9000 后端、前端、测试 | `/integrations/douyin/accounts` 返回账号级 `unread_count`，前端企业号列表稳定展示未读徽标。 |
| `181f46e` | 标准化抖音会话标签 | 9000 聚合服务、前端、测试 | 会话返回 `tags: string[]`，前端按标准英文枚举展示中文标签并支持筛选。 |
| `5f4f58c` | 聚合抖音会话客户画像 | 9000 后端、测试 | 新增 `GET /integrations/douyin/accounts/{account_id}/conversations/{conversation_key}/profile`，从 webhook 与 lead 聚合画像。 |
| `ee9cc95` | 接入抖音客户画像面板 | 前端工作台 | 右侧客户信息面板调用 9000 profile 接口，展示画像字段、评分和溯源。 |
| `524d091` | 优化抖音聊天面板安全接管状态 | 前端工作台 | 聊天区补齐消息类型展示、AI建议模式/人工接管本地切换、安全提示和工具栏边界。 |

后端画像接口提交已存在：`5f4f58c feat: 聚合抖音会话客户画像`。

## 3. 需求逐项验收矩阵

| 需求章节 | 需求点 | 当前状态 | 代码证据 | 验收结论 | 备注 |
| ---- | --- | ---- | ---- | ---- | -- |
| 2.2.2 | 企业号头像 | 已实现 | `app/services/douyin_workbench_conversation_service.py` `_profile_for_account()`、`aggregate_accounts_from_webhook_events()`；`frontend/src/pages/DouyinAiCsWorkbenchPage.tsx` 企业号卡片渲染 | 通过 | 从授权账号和 webhook profile 兜底聚合。 |
| 2.2.2 | 企业号昵称 | 已实现 | `app/routers/douyin_accounts.py` 返回 `nickname/name`；`app/services/douyin_workbench_conversation_service.py` `account_name/name/nickname` | 通过 | 无昵称时使用账号后缀兜底。 |
| 2.2.2 | 未读消息数 | 已通过独立测试 | `app/services/douyin_workbench_conversation_service.py:get_account_unread_counts()`；`app/routers/douyin_accounts.py` 返回 `unread_count`；`tests/test_douyin_accounts_router.py` 未读测试 | 通过 | `unread_count` 使用 `last_seen_event_id` + `(created_at, event_id)` 单调水位计算，统计入站 `im_receive_msg` 中水位之后的消息（候选 `8e69adc36a7df35c054774f6b482bac2887c0123`，T1 PASS）。 |
| 2.2.3 | 客户头像、姓名 | 已实现 | `app/services/douyin_workbench_conversation_service.py:_profile_for_customer()`；`frontend/src/pages/DouyinAiCsWorkbenchPage.tsx` 会话 item 渲染 | 通过 | 缺失时使用 `open_id` 兜底。 |
| 2.2.3 | 最后消息内容、消息时间 | 已实现 | `app/services/douyin_workbench_conversation_service.py:list_account_conversations()`；`frontend/src/pages/DouyinAiCsWorkbenchPage.tsx` 会话列表 | 通过 | 来自 webhook 会话聚合。 |
| 2.2.3 | 在线状态 | 部分实现 | `app/services/douyin_workbench_conversation_service.py:get_conversation_profile()` 返回 `online_status: "unknown"`；`frontend/src/pages/DouyinAiCsWorkbenchPage.tsx:onlineStatusText()` | 降级通过 | 不伪造在线/离线，真实来源待确认。 |
| 2.2.3 | 消息标签 | 已实现 | `build_conversation_tags()`、`_has_retained_contact()`、`_is_high_intent()`、`_is_manual_required()`、`_needs_follow_up()`；`tests/test_douyin_workbench_conversations.py` 标签用例 | 通过 | 后端稳定英文枚举，前端中文映射。 |
| 2.2.3 | 未读消息数 | 已通过独立测试 | `list_account_conversations()` 中 `unread_count` 按 `(created_at, event_id)` 水位统计 `im_receive_msg`；前端会话 item 展示 | 通过 | 与企业号未读一致，使用 `last_seen_event_id` 水位（候选 `8e69adc36a7df35c054774f6b482bac2887c0123`，T1 PASS）。 |
| 2.2.3 | 点击切换会话 | 已实现 | `frontend/src/pages/DouyinAiCsWorkbenchPage.tsx` `selectedConversation` 相关状态与加载逻辑 | 通过 | 切换后加载消息、建议上下文和画像。 |
| 2.2.3 | 搜索客户 | 已实现 | `frontend/src/pages/DouyinAiCsWorkbenchPage.tsx` 搜索过滤逻辑 | 通过 | 当前主要是前端过滤已加载会话。 |
| 2.2.3 | 按标签筛选 | 已实现 | `ConversationFilterKey`、`matchesConversationFilter()`、标签按钮 | 通过 | 基于 `conversation.tags`，不是中文文本猜测。 |
| 2.2.4 | 用户消息 | 已实现 | `frontend/src/pages/DouyinAiCsWorkbenchPage.tsx` 消息 direction / sender 类型展示规则 | 通过 | 入站消息展示为客户侧。 |
| 2.2.4 | AI消息 / AI建议 | 安全降级实现 | `frontend/src/pages/DouyinAiCsWorkbenchPage.tsx` AI建议卡片；`app/routers/douyin_ai_cs_proxy.py` 强制 `auto_send=false`；`apps/xg_douyin_ai_cs/services/reply_decision_service.py` 多处 `auto_send=False` | 通过 | 当前是 AI建议，不是自动发送历史消息。 |
| 2.2.4 | 人工消息 | 已实现 | `frontend/src/pages/DouyinAiCsWorkbenchPage.tsx` outbound / `manual_confirmed` 相关展示与发送保护 | 通过 | 不标记为 AI 自动发送。 |
| 2.2.4 | AI托管模式 | 安全降级实现 | `frontend/src/pages/DouyinAiCsWorkbenchPage.tsx` AI建议模式文案 | 通过 | 不使用“自动回复”行为，只生成建议。 |
| 2.2.4 | 人工接管模式 | 安全降级实现 | `frontend/src/pages/DouyinAiCsWorkbenchPage.tsx` 本地模式切换 | 通过 | 只影响 UI 文案和按钮状态，不写后端。 |
| 2.2.4 | Enter / Shift+Enter | 部分实现 | `frontend/src/pages/DouyinAiCsWorkbenchPage.tsx` 发送弹窗和输入区域 | 保守通过 | 当前不做 Enter 直接真实发送；发送仍需确认。 |
| 2.2.4 | 工具栏：表情、图片、视频、文件 | 部分实现 | `frontend/src/pages/DouyinAiCsWorkbenchPage.tsx` 工具栏、图片上传、占位说明 | 通过安全边界 | 图片仅获取 `image_id`；表情/视频/文件未接入真实发送。 |
| 2.2.5 | 客户姓名、头像、在线状态 | 已实现 | `getDouyinConversationProfileFrom9000()`；`DouyinAiCsWorkbenchPage.tsx` 右侧客户卡片 | 通过 | 在线状态无来源时显示状态未知。 |
| 2.2.5 | 来源渠道、意向车型、年份、预算、城市 | 已实现 | `get_conversation_profile()` 返回 `source_channel/intent_car/car_year/budget/city`；前端基础信息区 | 通过 | 字段依赖 webhook / lead raw_data。 |
| 2.2.5 | 当前标签 | 已实现 | profile `tags` + `selectedConversation.tags` fallback；`conversationTagText()` | 通过 | 复用会话标签中文映射。 |
| 2.2.5 | 溯源信息 | 已实现 | `_profile_trace()`；测试断言不返回 `raw_body`；前端 `traceItems()` | 通过 | 只展示摘要，不暴露原始 body。 |
| 2.2.5 | 线索评分 0-100 | 已实现 | `_profile_lead_score()` clamp；`tests/test_douyin_workbench_conversations.py` `lead_score=120` 断言为 100 | 通过 | 无评分时前端显示暂无评分。 |
| 2.2.5 | 进度条可视化 | 已实现 | `frontend/src/pages/DouyinAiCsWorkbenchPage.tsx` `clampLeadScore()` 与进度条宽度 | 通过 | 宽度限制在 0～100。 |

## 4. 当前真实调用链

### 4.1 企业号列表调用链

```text
frontend DouyinAiCsWorkbenchPage
  -> frontend/src/api/douyinAiCsClient.ts listDouyinAccounts()
  -> 9000 GET /integrations/douyin/accounts
  -> app/routers/douyin_accounts.py
  -> DouyinAuthorizedAccount + get_account_unread_counts()
  -> douyin_webhook_events 按 account_open_id 统计入站 im_receive_msg
  -> 返回头像、昵称、授权状态、绑定信息、unread_count
```

边界：`unread_count` 按已授权企业号 `account_open_id` 和可信 `merchant_id` 聚合；`douyin_webhook_events` 已有 `merchant_id` 字段（迁移 0035），按商户隔离查询。

### 4.2 会话列表调用链

```text
frontend DouyinAiCsWorkbenchPage 选择企业号
  -> getDouyinAccountConversations(accountId, account_open_id)
  -> 9000 GET /integrations/douyin/accounts/{account_id}/conversations
  -> app/routers/integrations.py
  -> list_account_conversations()
  -> douyin_webhook_events 聚合 conversation_short_id / open_id
  -> 返回客户头像、昵称、最后消息、时间、unread_count、lead_status、tags
```

搜索与标签筛选位于前端工作台，标签筛选基于后端返回的 `conversation.tags`。

### 4.3 会话标签生成链路

```text
douyin_webhook_events + douyin_leads
  -> WorkbenchMessage 列表
  -> build_conversation_tags()
  -> retained_contact / high_intent / manual_required / follow_up
  -> frontend conversationTagText()
  -> 需人工 / 高意向 / 已留资 / 待回访
```

标签规则是确定性规则，不调用 LLM，不依赖前端中文文本猜测。

### 4.4 客户画像调用链

```text
frontend 选择会话
  -> getDouyinConversationProfileFrom9000(accountId, conversationKey)
  -> 9000 GET /integrations/douyin/accounts/{account_id}/conversations/{conversation_key}/profile
  -> app/routers/integrations.py:get_douyin_conversation_profile()
  -> app/services/douyin_workbench_conversation_service.py:get_conversation_profile()
  -> douyin_webhook_events + douyin_leads / raw_data
  -> 返回 profile、lead、trace、tags、lead_score
  -> 前端右侧客户信息面板展示
```

正式工作台不使用 9100 mock profile 作为画像来源。

### 4.5 AI建议生成链路

```text
frontend 请求回复建议
  -> 9000 app/routers/douyin_ai_cs_proxy.py
  -> 注入 9000 可信账号/智能体上下文
  -> 9100 apps/xg_douyin_ai_cs/services/reply_decision_service.py
  -> RAG / LLM 或降级建议
  -> 返回 suggested_reply / manual_required / auto_send=false
  -> 前端 AI建议卡片展示
```

安全边界：9000 代理会把结果 `auto_send` 强制设为 `False`；9100 回复决策服务各路径也返回 `auto_send=False`。

### 4.6 人工确认发送链路

```text
frontend AI建议或人工输入
  -> 打开人工确认发送弹窗
  -> 确认后调用发送接口并携带 manual_confirmed=true
  -> 不携带 auto_send 放开信号
  -> 图片上传只获取 image_id，不自动发送
```

该链路不触发 AI 自动发送，不改 9100 自动发送策略。

## 5. 安全边界

1. AI只生成建议，不自动发送。
2. 9000 代理继续强制 `auto_send=false`。
3. 所有真实发送必须人工确认。
4. 图片上传只获取 `image_id`，不自动发送。
5. 工具栏里的表情、视频、文件当前是只读占位或未接入。
6. 正式工作台画像来源是 9000 profile 接口，不依赖 9100 mock profile。
7. 未读数已读/未读协议已通过独立测试（候选 `8e69adc36a7df35c054774f6b482bac2887c0123`，T1 A1-A14 PASS，261 passed）：`mark-read` 请求必填 `last_seen_event_id`，服务端验证事件归属后精确推进 `(created_at, event_id)` 单调水位，前端仅在详情成功渲染后提交；非私信事件和空 `created_at` 事件拒绝推进；并发通过 DB 条件更新和 `IntegrityError` 恢复保护。
8. 当前在线状态没有真实来源时显示 `unknown` / 状态未知，不伪造在线状态。
9. 本轮验收没有调用真实抖音发送、真实 LLM、真实 Embedding、微信自动化、真实支付或数据库迁移。

## 6. 剩余缺口

1. 企业号与会话 `unread_count` 已读/未读协议已通过独立测试（DY-CS-CONVERSATION-READ-PROTOCOL-1 候选 `8e69adc36a7df35c054774f6b482bac2887c0123`，T1 A1-A14 PASS，261 passed），使用 `last_seen_event_id` + `(created_at, event_id)` 单调水位；候选尚未推送、合并或发布，未验证真实 PostgreSQL 和生产环境。
2. 客户在线状态仍缺少真实抖音来源，当前只能返回 `unknown` 并在前端展示状态未知。
3. Enter 直接发送未实现，且当前不建议开放；如果后续实现，也必须只打开确认弹窗。
4. 视频、文件、表情真实发送能力未接入，媒体工具栏仍需单独契约设计。
5. AI托管自动发送未开放，当前不建议开放；如要开放必须独立安全评审。
6. 客户画像字段质量依赖 webhook 与 `douyin_leads.raw_data`，不同上游 payload 的字段覆盖率仍需样本验证。
7. `douyin_webhook_events` 已有 `merchant_id` 字段（迁移 0035），商户隔离查询已闭合；未读数按商户和已授权企业号 `account_open_id` 聚合。
8. 会话搜索当前主要是前端过滤已加载数据，后续大量会话场景需要后端分页、搜索和标签过滤参数。

## 7. 验证记录

本轮为 docs-only 验收沉淀，只执行 Git 状态与提交记录核验，未重新跑完整前后端测试，避免引入无关运行成本或外部调用风险。

| 验证项 | 本轮/历史结果 | 说明 |
| ------ | ------ | ---- |
| `git status --short` | 本轮执行，输出为空 | 文档编写前工作区干净。 |
| `git branch --show-current` | 本轮执行：`master` | 当前分支确认。 |
| `git log --oneline -n 20` | 本轮执行 | 已确认 `8d06282`、`181f46e`、`5f4f58c`、`ee9cc95`、`524d091` 均存在。 |
| `tests/test_douyin_accounts_router.py` | 沿用对应提交验证：`17 passed` | 覆盖企业号未读数聚合。 |
| `tests/test_douyin_workbench_conversations.py` | 沿用对应提交验证：`28 passed` | 覆盖会话标签与客户画像聚合。 |
| `frontend npm run build` | 沿用对应提交验证：通过 | 最近前端画像与聊天面板任务均通过；仅有既有字体解析和 chunk 体积警告。 |
| `py_compile` | 沿用对应提交验证：通过 | 覆盖 integrations/service 等相关后端文件。 |
| `DY-CS-CONVERSATION-READ-PROTOCOL-1` 独立测试 | 候选 `8e69adc36a7df35c054774f6b482bac2887c0123`，Test-Revision T1，A1-A14 全部验收通过，任务级结论 PASS | 指定专项及回归集 241 passed, 0 failed；IntegrityError 竞争重复 10 次通过；Barrier 双线程竞争重复 10 次通过；合计 261 passed, 0 failed；Python 语法检查通过；前端 TypeScript 检查通过。 |

## 8. 下一步建议

| 任务编号 | 任务名称 | 目标 | 修改范围 | 风险 | 验收方式 |
| ---- | ---- | -- | ---- | -- | ---- |
| `P1-DYCS-ONLINE-1` | 在线状态来源确认 | 确认抖音是否提供在线/离线事件或接口，不直接伪造状态 | 9000 聚合服务、前端状态展示、接口契约文档 | 中 | 样本 payload 验证；无来源时继续展示 unknown。 |
| `P1-DYCS-READSTATE-1` | 真实已读/未读状态设计 | 已通过独立测试（候选 `8e69adc36a7df35c054774f6b482bac2887c0123`，T1 A1-A14 PASS，261 passed），使用 `last_seen_event_id` + `(created_at, event_id)` 单调水位（DY-CS-CONVERSATION-READ-PROTOCOL-1） | `mark_conversation_read` 服务端、前端渲染后提交、测试 | 高 | 候选尚未推送、合并或发布；未验证真实 PostgreSQL 和生产环境。 |
| `P2-DYCS-MEDIA-1` | 媒体工具栏契约设计 | 明确表情、图片、视频、文件的上传、预览、确认发送边界 | 前端、9000 代理、9100 或抖音发送契约文档 | 中 | mock 接口测试；确认不自动发送。 |
| `P3-DYCS-AUTOSEND-REVIEW` | AI自动发送安全评审 | 独立评审是否允许自动发送、触发条件、审计和回滚 | 安全方案、权限、审计、风控、人工兜底 | 高 | 安全评审通过前不进入开发。 |

