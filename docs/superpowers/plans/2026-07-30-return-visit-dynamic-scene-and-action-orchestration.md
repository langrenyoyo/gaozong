# 回访动态场景配置 + 命中动作编排 设计文档

创建时间：2026-07-30
状态：待审批

## 1. 背景与需求

甲方期望管理员 `/admin/return-visits` 页面能**自定义配置回访触发场景**，并使命中场景后**执行确定性动作**（不只是发话术）。

甲方示例场景：
- 触发场景：客户留资
- 内容预览：客户表达价格、到店或试驾意向时，优先确认称呼、手机号和方便联系的时间
- 执行动作：微信通知对应跟进销售在 10 分钟内跟进

### 现状（探索结论）

- 回访场景是**固定三键**（`retain_contact_conversion`/`finance_plan_followup`/`silent_customer_wakeup`），在代码 7+ 处硬编码（schema Literal、PROMPT_KEYS 常量、LLM system prompt、关键词词表、路由校验、前端 SCENE_LABELS）。
- `ReturnVisitPrompt` 表本身能存任意键（VARCHAR(64) + UNIQUE，无枚举约束），存储层数据驱动，但外围强制三键。
- 回访命中后**只发客户话术**（`_send_private_message_with_context`），无"通知销售"动作分支。
- 9100 **无 tool/function calling**（纯 chat + prompt 约束 JSON）。
- 现有 `notify_sales` WechatTask 链路是**确定性编排**（服务建任务 → 19000 Local Agent 轮询执行 → 回写 → 自动 detect_reply），与回访解耦。
- `ReturnVisitRun` 已有 `lead_id`/`staff_id`/`dispatch_notification_id` 字段，动作编排挂载点齐备。
- 无"10分钟跟进 SLA"机制（现有 `ReplyCheck.reply_deadline` 是检测销售回复客户，语义不同）。

### 关键判断

甲方需求本质是**确定性动作编排**，不应也不需靠 LLM tool calling。正确分层：
- **LLM 层**：判定是否命中场景 + 生成客户话术（保持现状，不引入 tool）。
- **服务层**：命中后按场景配置的"动作"确定性执行（通知销售 + SLA 计时）。

## 2. 设计目标

1. 管理员可新增/编辑/启停回访场景（不限三键）。
2. 每个场景可配：名称、触发描述、客户话术模板、兜底文案、置信阈值、**命中后动作**。
3. 命中后动作支持"通知销售跟进 + SLA 计时"（确定性编排，复用 WechatTask 链路）。
4. 现有三键场景行为不回归。
5. 安全护栏（关键词抑制/触发/注入检测）保持硬编码，自定义场景仅 LLM 触发。

## 3. 数据模型变更

### 3.1 ReturnVisitPrompt 表加列

- `scene_description` TEXT（可空）：触发描述/内容预览，注入 LLM system prompt 动态枚举场景。
- `action_type` VARCHAR(32)（可空，默认 None）：命中后动作类型。初版支持 `notify_sales`（通知销售+SLA）、`send_light_reminder`（仅发轻提醒话术）、`None`（只发话术，三键现有行为）。
- `action_payload_json` TEXT（可空）：动作参数 JSON。`notify_sales` 含 `{"sla_minutes": 10, "notify_message": "..."}`；`send_light_reminder` 可含 `{"silence_hours": 24}`。
- `silence_hours` INT（可空）：沉默触发阈值，仅触发源 B（沉默扫描）场景生效。定义"最后一条出站消息后多少小时无客户入站则触发"。
- `cooldown_hours` INT（可空，默认 24）：G7 冷却时长，同 prompt_key+会话在该时长内只发一次，防连续追问。
- `trigger_source_type` VARCHAR(32)（可空，默认 `writeback`）：该场景的触发源。`writeback`=销售回复触发（场景一），`silent_scan`=沉默扫描触发（场景二）。扫描器只处理 `trigger_source_type=silent_scan` 的场景。
- 迁移：PG `0021` + SQLite `0041`，三键回填 `scene_description`，`action_type`/`silence_hours`/`trigger_source_type` 留空（不改变三键现有行为）。

### 3.2 新增 ReturnVisitFollowupTask 表（SLA 计时）

```
return_visit_followup_tasks
- id PK
- return_visit_run_id FK -> return_visit_runs.id
- lead_id, staff_id
- prompt_key VARCHAR(64)
- sla_minutes INT（要求的跟进时限，如 10）
- deadline DateTime（创建时刻 + sla_minutes）
- actual_followup_at DateTime（销售实际跟进时间，由 detect_reply 回写）
- status VARCHAR(20): pending / followed / timeout / cancelled
- wechat_task_id（关联 notify_sales WechatTask.id）
- created_at, updated_at
```

复用现有 `detect_reply` 任务检测销售回复：当 detect_reply 在 deadline 前检测到销售回复客户 → `followed`；超时 → `timeout`（触发告警/升级，初版仅记录状态 + 日志告警，不自动升级）。

## 4. 调用链

系统支持**两种触发源**，覆盖甲方两类场景：

- **触发源 A·销售回复触发**（现有链路）：销售回复客户 → detect_reply 回写 → 触发回访判定。覆盖场景一（客户留资→通知销售10分钟跟进）。
- **触发源 B·客户沉默定时触发**（新增）：定时扫描"最后一条是出站消息且超过 N 小时无客户入站"的会话，触发回访判定。覆盖场景二（客户超24h未回复→轻提醒）。

### 4.0 触发源 B·沉默定时扫描器（新增）

新增调度器 `app/scheduler/return_visit_silent_scan_scheduler.py`：
- 周期扫描（默认 1 小时一轮，可配）。
- 找出满足条件的会话：最后一条消息是出站（销售发的 `im_send_msg`/人工出站）且距今 ≥ `silence_hours`（场景级可配，如 24h），且该会话无 pending/sent 的同 prompt_key ReturnVisitRun（幂等，避免重复提醒）。
- 对命中会话创建 `ReturnVisitRun`（`trigger_source="silent_scan"`，`prompt_key`=配置的沉默场景键），交由 `process_return_visit_run` 走判定+发送。

`get_latest_private_message_state` 扩展：返回 `customer_silence_hours`（最后客户入站消息距今小时数），供扫描器和门禁使用。

`ReturnVisitPrompt` 加 `silence_hours` 列（可空）：仅 `trigger_source` 为沉默扫描时生效，定义该场景的沉默阈值。

### 4.1 场景判定（9100，配置化）

1. 9000 `_load_prompt_inputs` 去掉三键过滤，加载**所有 enabled 的 ReturnVisitPrompt**，含 `scene_description`。
2. 9000 通过 `ReturnVisitJudgeRequest.prompts`（dict[str, ReturnVisitPromptInput]）传入 9100，`ReturnVisitPromptInput` 加 `scene_description` 字段。
3. 9100 `_build_llm_messages`：system prompt 改为**动态枚举**场景（`key（scene_description）`），不再硬编码三键。
4. 9100 `PromptKey`/`JudgementResult` Literal 放宽为 `str`，`_try_llm` 校验改为 `prompt_key in request.prompts`。
5. 9100 `_keyword_fallback` 迭代词表 dict keys（仅三键有词表，自定义场景 `.get(key, ())` 跳过）。

注：触发源 B 的沉默判定由 9000 扫描器完成（确定性时长判定），9100 仍只做"命中后话术生成"。即沉默场景进入 9100 时实际已确定命中，9100 只生成话术（或在多场景下做二次确认）。

### 4.2 命中后动作编排（9000，确定性）

`return_visit_run_service.py` 命中分支（过 G1-G10 门禁、发送客户话术后）：

1. 读命中场景的 `ReturnVisitPrompt.action_type`。
2. 若 `action_type == "notify_sales"`：
   - 读 `action_payload_json`（sla_minutes、notify_message）。
   - 调 `wechat_task_service.create_wechat_task(task_type="notify_sales", lead_id=run.lead_id, staff_id=run.staff_id, target_nickname=销售微信昵称, message=notify_message)`，复用现有 Local Agent 链路派单。
   - 建 `ReturnVisitFollowupTask`（deadline = now + sla_minutes，关联 wechat_task_id）。
3. 若 `action_type == "send_light_reminder"`（场景二类）：仅发客户话术（轻提醒），不通知销售、不建 SLA task。靠 G7 冷却防连续追问。
4. 若 `action_type is None`：仅发话术，不建任务（三键现有行为）。

### 4.3 SLA 检测（复用 detect_reply + 超时扫描）

- 现有 `detect_reply` 任务检测销售回复客户时，顺带检查是否有关联的 `ReturnVisitFollowupTask`（pending）：
  - 销售在 deadline 前回复 → `followed`，记 `actual_followup_at`。
  - deadline 到期未回复 → `timeout`，输出告警日志（初版不自动升级）。
- 沉默扫描调度器（4.0）顺带扫描 `ReturnVisitFollowupTask` 超时（pending 且 deadline < now → timeout），避免单独再加定时器。

### 4.4 G7 冷却可配化

- 现有 G7 冷却 `_COOLDOWN_HOURS = 24` 硬编码，改为读 `ReturnVisitPrompt.cooldown_hours`（可空，默认 24）。
- 场景二"不连续追问"靠此：同 prompt_key+会话在 cooldown_hours 内只发一次轻提醒。

## 5. 管理员接口

- `GET /admin/return-visit-prompts`：去掉三键过滤，返回所有场景（含 scene_description/action_type）。
- `PUT /admin/return-visit-prompts/{prompt_key}`：去掉三键校验，按 key 查任意行；支持改 scene_description/action_type/action_payload。
- `POST /admin/return-visit-prompts`：新建场景（系统生成 `custom_<自增>` key，写审计）。
- 权限：`auto_wechat:admin:return_visit_prompts`（仅超管），写审计日志。

## 6. 前端

- `AdminReturnVisitsPage.tsx`：
  - 去掉 `SCENE_LABELS` 硬编码，用后端 `name`。
  - 提示词配置 tab 加"新增场景"按钮 + 表单（名称/触发描述/话术模板/兜底文案/置信度/启用/动作类型/动作参数）。
  - 表格动态渲染所有场景行。
- `adminReturnVisits.ts` 加 createReturnVisitPrompt + action 字段。

## 7. 安全边界

- 关键词词表（抑制/触发/注入检测）保持硬编码——安全护栏，自定义场景仅 LLM 触发。
- 9100 保持"纯判定无 DB"边界——9000 读配置传入，9100 不直连 DB。
- 命中后通知销售走 WechatTask 链路，复用现有 lead_wechat_notify_eligibility 只读校验（商户/权限/归属/销售活跃/微信昵称/联系方式/幂等/限频）。
- SLA 超时初版仅告警，不自动升级（避免误升级）。
- 创建/编辑场景仅超管，写审计。

## 8. 风险

- 高风险区：回访判定核心逻辑变更（LLM prompt 动态化）+ 发送编排（新增通知销售动作）+ 新表迁移。
- 现有三键场景行为不变（action_type 留空）。
- 自定义场景无关键词兜底，完全依赖 LLM 判定 + 置信度门禁 + G1-G10 发送 gate。

## 9. 任务分解

1. Task 1：数据层 + 迁移（ReturnVisitPrompt 加 6 列：scene_description/action_type/action_payload_json/silence_hours/trigger_source_type/cooldown_hours + 新增 ReturnVisitFollowupTask 表 + 三键回填 scene_description）。
2. Task 2：9100 schema + 判定服务动态场景（Literal 放宽 + system prompt 动态枚举 + 去三键校验）。
3. Task 3：9000 运行服务去三键依赖 + 命中后动作编排（notify_sales + 建 followup task；send_light_reminder 仅发话术）+ G7 冷却可配化。
4. Task 4：沉默定时扫描器（新增调度器 + latest_message_state 加 customer_silence_hours + trigger_source=silent_scan + 幂等 + followup task 超时扫描）。
5. Task 5：SLA 检测（detect_reply 回写联动 followup task 状态 followed/timeout）。
6. Task 6：管理员路由（list/update 去三键 + 新增 POST 创建 + action/trigger 字段）。
7. Task 7：前端（去 SCENE_LABELS + 新增场景 UI + 动作/触发源配置）。
8. Task 8：验证（tsc + test_phase9_return_visit_* 系列，重点判定行为 + 动作编排 + 沉默扫描 + SLA）。

## 10. 文档影响

任务结束检查 `docs/ai` 回访配置相关结论（新增动态场景 + 动作编排 + SLA + 沉默定时触发能力）。

## 11. 允许范围 / 禁止事项

- 允许：ReturnVisitPrompt 表加列、新增 followup task 表、9100 判定动态化、回访命中动作编排、沉默定时扫描器、管理员场景 CRUD、前端场景配置 UI、G7 冷却可配化。
- 禁止：改 9100 引入 tool/function calling、改关键词安全护栏词表为配置化、绕过 WechatTask 现有发送安全校验、改既有三键场景行为。
