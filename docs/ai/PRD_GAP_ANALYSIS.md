# PRD 差距分析（P0-DOC-GAP-1）

版本：P0-DOC-GAP-1
状态：第一阶段盘点与差距分析落盘
范围：仅盘点 `docs/ai/06_PRD_AUTO_WECHAT.md` 冻结 PRD 与当前 auto_wechat 真实代码之间的差距，输出能力分级、风险等级、命名映射说明。本文件不含技术方案、数据库迁移方案或代码修改计划。

更新时间：2026-06-15

------

## 0. 阅读与盘点依据

本文件基于以下真实文件盘点，不基于推测：

- PRD：`docs/ai/06_PRD_AUTO_WECHAT.md`（冻结版）
- 项目上下文：`docs/ai/05_PROJECT_CONTEXT.md`（含 0.1~0.16、第 28 章 GMP 直连、P0-DEV-E1）
- 代码：
  - `app/main.py`、`app/config.py`、`app/models.py`
  - `app/integrations/douyin_webhook.py`
  - `app/services/contact_extractor.py`
  - `app/services/webhook_event_service.py`
  - `app/services/assign_service.py`
  - `app/services/wechat_task_service.py`
  - `app/services/notification_service.py`
  - `app/routers/staff.py`、`app/routers/reports.py`
  - `app/scheduler/check_scheduler.py`
  - `app/local_agent_main.py`
- 测试：`tests/` 全量（44 个测试文件，最新全量结果 722 passed）

风险等级口径（与 `04_OUTPUT_RULES.md` §4 一致）：

- HIGH：数据库结构、权限、认证、配置、部署、第三方服务
- MEDIUM：跨模块修改、新增接口、新增业务逻辑、状态流转调整
- LOW：局部逻辑修改、文档修改、测试补充

------

## 1. 重要命名映射说明（先读这一节）

PRD 第 7 节使用概念名 `lead_source_events` 指代"原始线索事件域"。

当前真实代码中承担该职责的物理表是：

```text
douyin_webhook_events
```

两者是**同一个职责域的不同命名**：

| 维度 | PRD 概念名 | 当前物理表名 |
|------|-----------|------------|
| 职责 | 原始线索事件域 | 抖音 GMP Webhook 原始事件日志 |
| 字段 | event / from_user_id / to_user_id / event_key / is_duplicate / lead_id / raw_body | 一致 |
| 写入方 | webhook 接收 | `process_webhook_event()` |

**第一版结论**：

1. 第一版**不重命名** `douyin_webhook_events` 为 `lead_source_events`。
2. 重命名属于表结构变更，会引入不必要的数据库迁移和历史数据风险。
3. 在文档、接口注释、状态映射中统一用「`douyin_webhook_events`（语义承接 PRD 的 `lead_source_events` 原始事件域）」表述。
4. 后续产品化稳定后，若确有必要做物理表名迁移，必须单独出迁移技术方案，经确认后再执行。

> 该结论与 `docs/ai/05_PROJECT_CONTEXT.md` 0.10 节、`docs/ai/08_DATA_MODEL_AUTO_WECHAT.md` 的既有结论保持一致：第一版推荐保留 `douyin_webhook_events` 物理表名。

------

## 2. 能力差距总表

符号口径：

- ✅ 已满足：代码已实现并覆盖 PRD 要求
- ⚠️ 部分满足：已有相关实现，但与 PRD 要求存在缺口
- ❌ 缺失：当前无实现
- ⛔ 暂不做：PRD §21 或第一阶段边界明确不做

### 2.1 Webhook 接入（PRD §6）

| # | 能力 | 状态 | 差距说明 | 风险 |
|---|------|------|----------|------|
| 1 | `/webhook/douyin` 入口 | ✅ | 已部署线上，宝塔整站反代承接 `callback.misanduo.com/webhook/douyin` | — |
| 2 | 双入口共享处理 | ✅ | `/webhook/douyin` 与 `/integrations/douyin/webhook` 共用 `_handle_douyin_webhook()` | — |
| 3 | 验签算法 `sha256Hex(SECRET_KEY + body + "-" + timestamp)` | ✅ | `verify_signature()` 已实现，含时间戳漂移校验 | — |
| 4 | production 强制验签 | ⚠️ | 已加 `APP_ENV` 识别，但线上 `DOUYIN_WEBHOOK_AUTH_REQUIRED=false` 且 `APP_ENV` 实际值需复核；GMP 真实回调是否带签名头尚未最终确认（见第 28 章历史：线上不带签名头） | HIGH |
| 5 | 7 种返回码规范化 | ❌ | 当前未严格区分 PRD §6 的 200 / 400 / 401 / 500 七种语义，对外未统一为 `{code,msg}` | MEDIUM |
| 6 | `body` 原始字符串签名 | ✅ | 已使用原始 body 计算签名 | — |

### 2.2 原始事件与有效线索（PRD §7）

| # | 能力 | 状态 | 差距说明 | 风险 |
|---|------|------|----------|------|
| 7 | 所有事件入 `douyin_webhook_events` | ✅ | 物理表承接 PRD `lead_source_events` 域（见第 1 节映射） | — |
| 8 | 有效线索入 `douyin_leads` | ✅ | im_receive_msg 且提取到联系方式 → 入库 | — |
| 9 | invalid 只记原始事件 | ✅ | 无联系方式 / 非文本 → 仅事件日志 | — |
| 10 | invalid 进入前端列表 | ⚠️ | `/webhook-events` 可查，但 `/leads` 不含 invalid，列表口径未统一 | MEDIUM |
| 11 | invalid 参与导出 | ❌ | 导出未实现（见 2.9） | MEDIUM |
| 12 | invalid 不回调 | ✅ | 当前无回调链路，符合"不需要回调" | — |
| 13 | 不依赖顶层 phone/wechat 字段 | ✅ | 仅从私信纯文本提取 | — |
| 14 | 不依赖 retain_consult_card | ✅ | 未使用留资卡片 | — |
| 15 | 不接 LLM | ✅ | 纯规则 | — |
| 16 | 正则 / 规则提取 | ✅ | 见 2.3 | — |

### 2.3 联系方式提取（PRD §8）

| # | 能力 | 状态 | 差距说明 | 风险 |
|---|------|------|----------|------|
| 17 | 中国大陆 11 位手机号 | ✅ | `1[3-9]\d{9}` 正则 | — |
| 18 | 微信号关键词：微信 / wx / vx / v / 加我 | ✅ | `_WECHAT_KEYWORD_RE` + `_SINGLE_V_WECHAT_RE` 覆盖 | — |
| 19 | 多联系方式全部保存 | ✅ | `all_contacts` 按出现位置排序去重 | — |
| 20 | 主字段取第一个 | ✅ | `phone = phones[0]`、`wechat = wechats[0]` | — |
| 21 | 原始文本保存 | ⚠️ | 保存于 `douyin_leads.raw_data` JSON 内，**无独立列** | MEDIUM |
| 22 | 提取结果保存 | ⚠️ | 同上，存于 `raw_data.contact_extract`，无 `extracted_phone` / `extracted_wechat` / `all_extracted_contacts` 独立列 | HIGH（涉字段） |
| 23 | 提取失败原因保存 | ⚠️ | 同上，无 `contact_extract_status` / `contact_extract_reason` 独立列 | HIGH（涉字段） |

> 第 21~23 项的缺口本质是数据库字段缺失，P0 阶段不补，待数据库迁移体系确认后再补齐（见 P0_DEV_PLAN P2 阶段）。

### 2.4 唯一键与幂等（PRD §9）

| # | 能力 | 状态 | 差距说明 | 风险 |
|---|------|------|----------|------|
| 24 | `event_key` 事件级幂等 | ✅ | SHA256(event\|from\|to\|conv\|msg\|create_time)，`douyin_webhook_events.event_key` 唯一索引 | — |
| 25 | 重复事件返回成功并记录 | ✅ | 写 is_duplicate=1，返回原始 event_id | — |
| 26 | 线索级幂等 | ⚠️ | 当前以 `from_user_id` 作 `source_id` 去重，pending 更新、非 pending 跳过 | — |
| 27 | `external_lead_id`（优先数据源 id） | ❌ | 无独立字段 | HIGH（涉字段） |
| 28 | `open_id + account_open_id` | ❌ | 无 `account_open_id` 独立字段 | HIGH（涉字段） |
| 29 | `conversation_short_id` 会话级辅助 | ❌ | 仅在 raw_body 内，无独立字段 | MEDIUM（涉字段） |
| 30 | `server_message_id` 事件级幂等字段 | ❌ | 仅在 raw_body 内，无独立字段 | MEDIUM（涉字段） |

### 2.5 状态规则（PRD §10）

| # | 能力 | 状态 | 差差距说明 | 风险 |
|---|------|------|----------|------|
| 31 | 13 个内部状态 | ❌ | `douyin_leads.status` 当前注释仅 `pending/assigned/replied/timeout/closed`（`models.py:44`），缺 `received/invalid/delay_assign/pending_assign/notified/waiting_reply/reassigned/manual_required/failed` | HIGH |
| 32 | 4 个对外状态 | ❌ | 未实现对外状态映射层（未分配/已分配/已回复/超时未回复） | HIGH |
| 33 | 内外状态映射 | ❌ | 无 status_mapper | HIGH |
| 34 | 不对外回调的状态集 | ⚠️ | 当前无回调链路，部分天然不回调；但缺 `callback_logs.status=success` 内部记录承载 | MEDIUM |

> 状态机重构影响面大（webhook 写入、assign、scheduler、wechat_task、前端展示多处硬编码），P0 阶段不做，列为后续独立阶段。

### 2.6 NewCarProject 对接预留（PRD §11）

| # | 能力 | 状态 | 差距说明 | 风险 |
|---|------|------|----------|------|
| 35 | token + cookie 识别入口 | ❌ | 无中间件 / 依赖注入入口 | MEDIUM（可先预留骨架） |
| 36 | 本地生成 `customer_id` | ❌ | 无字段、无生成逻辑 | HIGH（涉字段） |
| 37 | `external_customer_id` 保存 NewCarProject 商户 ID | ❌ | 无字段 | HIGH（涉字段） |
| 38 | roles / merchant_id 字段预留 | ❌ | 无字段 | MEDIUM（涉字段） |
| 39 | NewCarProject 字段结构确认 | ⛔ | PRD §11 明确"后续与 NewCarProject 同事确认"，第一版只预留 | — |

### 2.7 密码规则（PRD §12）

| # | 能力 | 状态 | 差距说明 | 风险 |
|---|------|------|----------|------|
| 40 | 修改密码（旧密码 + ≥8 位 + 改后重登） | ❌ | 当前无账号体系、无密码表 | MEDIUM |
| 41 | 不支持重置密码 | ⛔ | PRD §12 明确不做 | — |

> 密码体系依赖账号表，PRD 未定义账号表结构。第一版优先级靠后。

### 2.8 销售管理与导入（PRD §13）

| # | 能力 | 状态 | 差距说明 | 风险 |
|---|------|------|----------|------|
| 42 | 销售字段：微信昵称 / 姓名 / 手机号 / 状态 | ✅ | `SalesStaff` 已有 | — |
| 43 | 备注 / 排序字段 | ❌ | 无 `remark` / `sort_order` | HIGH（涉字段） |
| 44 | 微信昵称必填 | ❌ | 当前 `name` 必填、`wechat_nickname` 可空 | MEDIUM |
| 45 | Excel 导入 | ❌ | `routers/staff.py` 仅 CRUD | MEDIUM |
| 46 | 重复昵称覆盖 | ❌ | 无导入逻辑 | MEDIUM |
| 47 | 部分成功 + 行号报错 | ❌ | 无导入逻辑 | MEDIUM |
| 48 | 模板下载 | ❌ | 无 | MEDIUM |
| 49 | 排序自动生成 | ❌ | 无 sort_order | MEDIUM |

### 2.9 分配与超时（PRD §14）

| # | 能力 | 状态 | 差距说明 | 风险 |
|---|------|------|----------|------|
| 50 | 自动分配 | ✅ | `auto_assign_next()` 已实现 | — |
| 51 | 按销售列表顺序轮流 | ❌ | 当前按"当前分配数最少"轮询，**非顺序**；且无 sort_order 支撑 | MEDIUM |
| 52 | 销售列表为空 → 未分配 | ⚠️ | 当前抛 ValueError（`没有可用的活跃销售人员`），非状态化处理 | LOW |
| 53 | 非工作时间 → delay_assign | ❌ | 无工作时间配置、无延迟分配逻辑 | MEDIUM |
| 54 | 到工作时间续分配 | ❌ | 无 | MEDIUM |
| 55 | 超时检测 | ✅ | `check_scheduler` 标记 timeout | — |
| 56 | 超时时间可配置 | ✅ | `reply_deadline_minutes`（默认 30） | — |
| 57 | 超时重分配 | ❌ | 仅标记 timeout，**无 reassign、无 reassign_count、无排除原销售** | HIGH |
| 58 | 最多重分配 5 次 | ❌ | 无 reassign_count 字段 | HIGH（涉字段） |
| 59 | 超限 → 人工处理 / 失败 | ❌ | 无 manual_required / failed 流转入口 | HIGH |

### 2.10 Local Agent 安全（PRD §15）

| # | 能力 | 状态 | 差距说明 | 风险 |
|---|------|------|----------|------|
| 60 | 单机单窗单 agent_client_id 单任务 | ✅ | `_wechat_task_lock` 共享运行锁 | — |
| 61 | 发送 / 检测互斥 | ✅ | poll-and-execute / poll-and-detect 共享锁 | — |
| 62 | 忙碌时 agent_busy | ✅ | 锁占用时返回 busy | — |
| 63 | 微信异常停止并回写 | ✅ | failure_stage 回写 | — |
| 64 | 未确认联系人禁止发送 | ✅ | verified=false → blocked | — |
| 65 | 搜索框焦点未确认禁止粘贴 | ✅ | search_text_verified 门禁 | — |
| 66 | 禁止并发操作微信 | ✅ | 运行锁 | — |
| 67 | 高风险操作有日志 | ✅ | stage / failure_stage 已覆盖 | — |
| 68 | 失败必须回写 | ✅ | `submit_wechat_task_result` 统一回写 | — |
| 69 | sent 强制为 false | ✅ | sent=true → failed（安全门禁） | — |

> Local Agent 安全边界在 P1-END-1 后已严格落地，第一版主要做回归验收，不放宽边界。

### 2.11 回复检测（PRD §16）

| # | 能力 | 状态 | 差距说明 | 风险 |
|---|------|------|----------|------|
| 70 | 关键词判断 | ✅ | `effective_keywords` / `expected_reply_text` | — |
| 71 | 规则判断 | ✅ | `reply_analyzer` 长度 / 无效词规则 | — |
| 72 | 关键词客户可配置 | ✅ | `check_configs` 表 | — |
| 73 | 不接入大模型 | ✅ | 纯规则 | — |

### 2.12 人工处理（PRD §17）

| # | 能力 | 状态 | 差距说明 | 风险 |
|---|------|------|----------|------|
| 74 | 人工重新分配 | ❌ | 无接口（手动 assign 存在但非状态化重分配） | MEDIUM |
| 75 | 人工补录销售回复 | ⚠️ | `/replies/manual` 存在，但未与 reassigned/manual_required 状态机打通 | MEDIUM |
| 76 | 人工关闭线索 | ❌ | closed 状态存在但无流转入口 | MEDIUM |
| 77 | closed 不回调 | ✅ | 无回调链路 | — |
| 78 | closed 不可恢复 | ❌ | 无 closed 后守护逻辑 | LOW |

### 2.13 数据导出（PRD §18）

| # | 能力 | 状态 | 差距说明 | 风险 |
|---|------|------|----------|------|
| 79 | Excel 导出 | ❌ | 无导出接口、无 openpyxl 依赖 | MEDIUM |
| 80 | 按时间范围导出 | ❌ | 无 | MEDIUM |
| 81 | 线索 / 分配 / 通知 / 检测 / 超时 / 回调失败 / 人工处理 7 类 | ❌ | 无 | MEDIUM |
| 82 | invalid 参与导出 | ❌ | 无 | MEDIUM |
| 83 | 导出不脱敏 | ⛔ | PRD §18 明确不脱敏 | — |

### 2.14 数据保存与清理（PRD §19）

| # | 能力 | 状态 | 差距说明 | 风险 |
|---|------|------|----------|------|
| 84 | 业务数据保存 180 天 | ❌ | 无保留 / 清理策略实现 | LOW |
| 85 | 截图不保存不入库 | ✅ | 第一版不保存截图 | — |
| 86 | 不做数据归档 | ⛔ | PRD §19 明确不做 | — |

### 2.15 性能口径（PRD §20）

| # | 能力 | 状态 | 差距说明 | 风险 |
|---|------|------|----------|------|
| 87 | 服务端 200 QPS 预留 | ⚠️ | 未做压测，FastAPI + SQLite 单机能力未验证 | MEDIUM |
| 88 | 查询接口分页 | ⚠️ | `/webhook-events` 有分页，`/leads` 前端过滤为主 | LOW |
| 89 | webhook 接收幂等 | ✅ | event_key 幂等 | — |
| 90 | 状态更新幂等 | ⚠️ | 部分幂等，未系统化 | LOW |
| 91 | 任务回写幂等 | ⚠️ | submit_wechat_task_result 未做严格幂等键 | LOW |
| 92 | Local Agent 串行 | ✅ | 运行锁串行 | — |

### 2.16 服务拆分与隔离（PRD §5）

| # | 能力 | 状态 | 差距说明 | 风险 |
|---|------|------|----------|------|
| 93 | 子功能独立启动 / 配置 / 健康检查 / 日志 / 异常隔离 | ❌ | 当前 auto_wechat 单体，未拆分 | MEDIUM |
| 94 | 服务地址 / 端口 / 健康检查可配置 | ⚠️ | 端口硬编码 `SERVER_PORT=9000`（config.py:17），健康检查无独立端点 | LOW |

------

## 3. 风险汇总（按等级）

### 3.1 HIGH（数据库 / 认证 / 配置 / 状态流转）

| 风险 | 涉及项 | 阻塞前提 |
|------|--------|----------|
| 数据库迁移体系缺失 | #21~#23、#27~#30、#36~#38、#43、#58 | 当前 `Base.metadata.create_all` 对已存在表不会 ALTER；生产 SQLite 已有数据。**Alembic / 手写迁移方案未确认前，禁止改 models.py** |
| 生产验签切换 | #4 | production + DY_SECRET_KEY 切换前，必须确认 GMP 真实回调是否带签名头 |
| 状态机重构 | #31~#33 | 13 内部态 + 4 对外态映射，影响 webhook / assign / scheduler / wechat_task / 前端多处硬编码 |
| 提取结果 / 幂等键字段缺失 | #22~#23、#27~#30 | 当前散落在 raw_data JSON，新增独立列需回填历史数据 |
| customer_id / external_customer_id 缺失 | #36~#37 | grep 全仓无匹配，需统一预留 |

### 3.2 MEDIUM（跨模块 / 新增接口 / 新增业务逻辑）

- #5 返回码规范化、#10 invalid 列表口径、#11 invalid 导出
- #35 NewCarProject 识别入口（可先预留）
- #40 修改密码（依赖账号表）
- #44~#49 销售导入系列
- #51 顺序轮询、#53~#54 工作时间延迟分配、#57~#59 超时重分配
- #74~#78 人工处理
- #79~#82 Excel 导出（需评估 openpyxl 新依赖，影响 exe 打包体积）
- #87 200 QPS 压测、#93 服务拆分

### 3.3 LOW（局部逻辑 / 文档 / 测试）

- #52 销售列表为空的状态化处理
- #78 closed 不可恢复守护
- #84 180 天保留策略
- #88~#91 分页与幂等系统化
- #94 端口 / 健康检查可配置化

------

## 4. 第一版明确暂不做（PRD §21 + P0 边界）

1. 不把 douyinAPI 作为正式生产长期依赖。
2. 不把 AI小高线索 / 小高AI微信助手 / AI小高剪辑 混成一个服务。
3. 不做巨量一键过审。
4. 不接 LLM。
5. 不保存截图、不入库。
6. 不做数据归档。
7. 不支持客户多台 Local Agent / 多微信账号。
8. 不支持重置密码。
9. 不设计智能路由。
10. **P0 阶段不重命名 `douyin_webhook_events` 为 `lead_source_events`**（见第 1 节）。
11. **P0 阶段不修改 models.py、不新增数据库字段、不引入 openpyxl、不改 webhook 逻辑、不改 Local Agent、不改 React 前端**。

------

## 5. 结论

- 已满足项主要集中在：webhook 直收与验签算法、原始事件入库、联系方式提取规则、Local Agent 安全门禁、回复关键词配置、超时标记、紧急停止。
- 主要缺口集中在三个底层域：
  1. **数据库字段与迁移体系**（提取结果列、幂等键列、customer_id、sort_order、reassign_count 等）。
  2. **状态机**（13 内部态 + 4 对外态映射）。
  3. **产品化业务功能**（销售 Excel 导入、超时重分配、delay_assign、人工处理、Excel 导出）。
- 下一阶段首要任务是**数据库迁移体系方案设计**，在 Alembic / 手写迁移脚本方案未确认前，禁止修改 `models.py`。

详见开发计划：`docs/ai/P0_DEV_PLAN.md`。
