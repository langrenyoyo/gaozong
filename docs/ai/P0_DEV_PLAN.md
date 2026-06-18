# auto_wechat / 小高AI微信助手 第一版开发计划

版本：P0-DEV-PLAN-1
状态：基于冻结 PRD（`docs/ai/06_PRD_AUTO_WECHAT.md`）和差距分析（`docs/ai/PRD_GAP_ANALYSIS.md`）的阶段性开发计划
范围：只定义阶段目标、修改范围、验收标准、风险点、是否涉及数据库 / 前端 / Local Agent。本文件不是技术方案，不包含数据库迁移 DDL、不包含代码实现。

更新时间：2026-06-15

------

## 0. 阅读前置

本计划严格遵循 `docs/ai/02_EXECUTION_RULES.md`：

1. 最小修改优先、一致性优先、可验证优先。
2. 数据库结构修改必须走既有迁移机制；当前迁移机制缺失，**P2 为硬阻塞**。
3. 高风险变更（数据库 / 认证 / 配置 / 状态流转）必须先出方案、回滚方案、验证方案，确认后才执行。
4. 任何阶段完成后必须按 `04_OUTPUT_RULES.md` 输出修改文件、修改原因、风险等级、影响范围、验证方式、是否需要确认。

阶段顺序遵循用户已批准的稳态节奏：

```text
P0  PRD 与现状冻结
  ↓
DB-MIG 迁移体系方案设计（仅方案，不落库）
  ↓
P2-A 迁移脚本骨架与副本 dry-run
  ↓
P2-A-END WAL/hash 验收口径修正
  ↓
P2-C 开发测试主线库正式迁移（先迁库）
  ↓
P2-B models.py 字段补齐（后补模型）
  ↓
P3~P12 按阶段边界继续推进
```

> **阶段顺序调整（2026-06-15）**：P2-C 先于 P2-B。原因：若先改 `app/models.py` 而主线库未迁移，SQLAlchemy 模型会认为新字段已存在，但实际表里没有这些列，运行接口 / 查询时出现缺列错误。因此**先迁移主线库（P2-C），再补 models.py（P2-B）**，避免模型字段领先于数据库实际结构。

------

## 1. 阶段最终目标与边界总控（最高优先级，先读这一节）

> 本节是整个开发计划的总控。后续每一轮开发开始前，必须先复述本节中对应阶段的「最终目标 + 不属于本阶段」，获得确认后才执行；每一轮结束后，必须按本节「最终目标」验收，不用「顺便完成了什么」代替验收。
>
> 本节定义的阶段编号、最终目标、完成状态、不属于本阶段为权威定义。下文「2. 阶段总览」「3. 各阶段明细」为补充明细，若与本节冲突，以本节为准。

### 1.0 总控规则

后续每一轮开始前，必须先输出：

```text
本阶段目标
本阶段允许修改范围
本阶段禁止事项
本阶段验收标准
是否需要用户确认
```

获得确认后再执行。

每一轮结束后，必须输出：

```text
是否达成本阶段最终目标
是否越界修改
是否提前实现后续阶段能力
修改文件列表
测试结果
风险点
下一阶段建议
```

**范围纪律**：

1. 每个阶段只能交付本阶段目标，不允许提前实现后续阶段功能。
2. 发现后续问题只能记录到风险 / 后续计划，不能擅自开发。
3. 如果发现当前阶段需要做后续阶段内容才能继续，必须**停止并说明阻塞**，不允许自行扩大范围。

### 1.1 P0：PRD 与现状冻结

- **最终目标**：让项目团队明确：最终 PRD 要做什么、当前代码有什么、差距在哪里、后续按什么顺序做。
- **完成状态**：只形成文档共识，不修改业务代码。
- **不属于本阶段**：不改 models.py、不改数据库、不改接口、不改前端、不改 Local Agent、不写迁移脚本。

### 1.2 DB-MIG：迁移体系方案设计

- **最终目标**：确定未来数据库结构演进的方法，避免继续依赖 `Base.metadata.create_all` 处理已有表字段变更。
- **完成状态**：输出迁移体系方案，明确手写迁移脚本、schema_migrations、备份、dry-run、回滚、字段分批策略（见 `docs/ai/14_DB_MIGRATION_PLAN.md`）。
- **不属于本阶段**：不写迁移脚本、不改 models.py、不执行迁移、不改数据库、不做字段回填。
- **补充口径**：当前 `data/auto_wechat.db` 是开发测试库，不是生产库；但迁移体系按准生产规范设计，方便未来真实客户数据上线后沿用。

### 1.3 P2-A：迁移脚本骨架与副本 dry-run（已完成 ✅）

- **最终目标**：证明迁移脚本机制是安全、幂等、可验证、可回滚的。
- **完成状态**：有 migrations 脚本骨架；能指定数据库路径；默认 dry-run；只有显式 `--apply` 才写库；能在 `data/auto_wechat.db` 的复制副本上完成 dry-run 和 apply 验证；能重复执行不报错、不重复加字段。
- **实际完成**：`migrations/migrate_sqlite.py` + `versions/0001_prd_base_fields.sql`；副本 dry-run / apply / 重复 apply 幂等验证通过；13 项迁移测试通过；全量回归 748 passed；未改 `models.py`、未碰主线库结构。配套 P2-A-END 已修正 WAL/hash 验收口径。
- **不属于本阶段**：不修改 `app/models.py`、不对 `data/auto_wechat.db` 主线库执行真实迁移、不修改业务服务、不修改接口、不修改前端、不修改 Local Agent、不改变分配逻辑、不改变状态机。

### 1.4 P2-C：开发测试主线库正式迁移（下一步，先于 P2-B）

- **最终目标**：把已经在副本验证过的 0001 迁移安全应用到当前开发测试主线库 `data/auto_wechat.db`。
- **完成状态**：迁移前有备份；迁移后字段存在；schema_migrations 有记录；重复执行安全；现有接口和测试不报错。
- **验收口径（WAL 模式，重要）**：`data/auto_wechat.db` 处于 SQLite WAL 模式，`.db` 文件 hash / mtime **不能**作为「主线未变化」的唯一证据——checkpoint 会把历史 `-wal` 帧合并进主 `.db`，导致 hash 变化但业务数据 / 结构完全不变（P2-A 实测确认，详见 `14_DB_MIGRATION_PLAN.md` §0c-1）。本阶段验收**必须以结构对比 + 数据语义对比为主**：`PRAGMA table_info(douyin_leads)` / `PRAGMA table_info(sales_staff)`、`schema_migrations` 版本记录、关键表行数、新增列存在性、旧数据关键字段抽样、`reassign_count` 默认值；文件 hash 仅作辅助参考。P2-C 前如需收缩 WAL，单独确认后再执行 checkpoint，本阶段不主动 checkpoint。
- **顺序说明**：P2-C 先于 P2-B。先迁移主线库落出新列，再补 `models.py`，避免 SQLAlchemy 模型字段领先于数据库实际结构导致缺列错误。
- **不属于本阶段**：不做复杂历史数据回填、不改业务流程、不改状态流转、不改前端页面、不改 `models.py`（留 P2-B）。

### 1.5 P2-B：models.py 字段补齐（P2-C 完成后再执行）

- **最终目标**：让 SQLAlchemy 模型字段与已经迁移落库的字段保持一致。
- **完成状态**：`models.py` 中补齐第一批 PRD 基础字段（与 `14_DB_MIGRATION_PLAN.md` 第一批字段一致）；`DouyinLead.status` 列已存在，仅扩注释 / 取值域，不新增列；主线库迁移后的表结构与模型字段一致；已有测试不因字段新增失败。
- **补充口径**：`schema_migrations` 表是迁移基础设施，**不进入 `app/models.py`**，仅由迁移 runner 维护。
- **顺序说明**：P2-B 在 P2-C 之后。必须等主线库已迁移出新列，才让 `models.py` 声明这些字段，确保模型与数据库结构同步、不领先。
- **不属于本阶段**：不实现状态机重构、不实现 webhook 新业务逻辑、不实现超时重分配、不实现销售导入、不实现 Excel 导出、不实现 NewCarProject 登录。

### 1.6 P3：Webhook 生产化规范

- **最终目标**：让 webhook 接收链路符合最终 PRD 的验签、幂等、返回码和原始事件记录规则。
- **完成状态**：签名校验规则清晰；成功、重复、非线索、invalid、格式错误、签名失败、过期请求、系统异常返回符合 PRD；所有事件可追踪；重复事件不重复创建线索。
- **不属于本阶段**：不做销售分配重构、不做超时重分配、不做 Excel 导出、不做前端大改、不接 LLM。

### 1.7 P4：联系方式提取落库与有效线索生成

- **最终目标**：让用户私信文本中的手机号 / 微信号提取结果结构化保存，并稳定生成有效线索或 invalid 线索。
- **完成状态**：手机号、微信号、多个联系方式、主字段、原始文本、提取状态、失败原因都能落库；有联系方式进入有效线索；无联系方式进入 invalid；invalid 可查询。
- **不属于本阶段**：不做 LLM、不依赖 retain_consult_card、不依赖顶层 phone / wechat 字段、不做复杂自然语言识别。

### 1.8 P5：线索状态机与状态映射

- **最终目标**：统一内部状态和对外状态映射，避免各服务继续硬编码 pending/assigned/replied/timeout/closed。
- **完成状态**：13 个内部状态定义清晰；4 个对外状态映射清晰；状态流转集中管理；不允许非法状态流转。
- **不属于本阶段**：不实现 Excel 导出、不实现销售导入、不实现 NewCarProject 对接、不实现 UI 自动化新能力。

### 1.9 P6：销售管理与销售导入

- **最终目标**：让客户可以维护销售列表，并通过 Excel 批量导入销售。
- **完成状态**：销售字段满足 PRD；支持备注和排序；Excel 模板可下载；Excel 导入支持部分成功；重复微信昵称覆盖；错误行号和原因清晰。
- **不属于本阶段**：不改 Local Agent、不做回复检测重构、不做超时重分配、不做导出业务数据。

### 1.10 P7：分配、非工作时间与超时重分配

- **最终目标**：让有效线索能按客户销售列表顺序分配，并在非工作时间延迟分配，超时后按规则重分配。
- **完成状态**：按 sort_order 顺序轮流分配；销售为空进入未分配；非工作时间进入 delay_assign；到工作时间后继续分配；超时后重分配；最多重分配 5 次；排除原销售；超过次数进入人工处理或失败。
- **不属于本阶段**：不改 webhook 解析、不改联系方式提取规则、不做 Excel 导出、不做 NewCarProject 登录。

### 1.11 P8：Local Agent 安全回归

- **最终目标**：确认小高AI微信助手本地端继续保持单任务、互斥、安全、失败回写，不因服务端改造破坏 UI 自动化安全。
- **完成状态**：同一 agent_client_id 同一时间只执行一个任务；发送任务和检测任务互斥；agent_busy 正常返回；未确认联系人不发送；搜索框焦点未确认不粘贴；微信异常停止并回写失败；真机测试通过。
- **不属于本阶段**：不新增多微信账号、不支持多台 Local Agent、不做视觉识别大改、不绕过安全门禁。

### 1.12 P9：回复检测

- **最终目标**：让系统能根据客户配置的关键词 / 规则判断销售是否已经有效回复。
- **完成状态**：关键词配置可用；检测任务可执行；命中后进入 replied；未命中继续等待；检测结果可追踪。
- **不属于本阶段**：不接 LLM、不做语义理解、不保存截图、不做多账号检测。

### 1.13 P10：人工处理

- **最终目标**：让失败、超时、异常线索可以被人工闭环处理。
- **完成状态**：支持人工重新分配；支持人工补录销售回复；支持人工关闭线索；closed 不对外回调；closed 后第一版不可恢复；人工操作有记录。
- **不属于本阶段**：不做复杂审批流、不做 closed 恢复、不做权限细分。

### 1.14 P11：Excel 数据导出

- **最终目标**：让客户可以按时间范围导出第一版要求的业务数据。
- **完成状态**：支持导出线索列表、分配记录、微信通知任务、回复检测结果、超时记录、回调失败记录、人工处理记录；invalid 参与导出；第一版不脱敏。
- **不属于本阶段**：不做数据归档、不做脱敏、不做复杂 BI 报表、不做异步大文件导出（除非当前数据量验证确实需要）。

### 1.15 P12：NewCarProject 对接预留

- **最终目标**：为后续 NewCarProject token / cookie / roles / merchant_id 正式对接留下清晰入口，但不强行实现未确认字段。
- **完成状态**：本地 customer_id 存在；external_customer_id 可保存 NewCarProject 商户 ID；token / cookie 解析入口预留；roles / merchant_id 字段待确认；文档明确阻塞项。
- **不属于本阶段**：不猜测 NewCarProject 字段结构、不自行设计完整 RBAC、不允许商户跨子功能跳转、不实现未确认的菜单跳转协议。

### 1.16 阶段编号说明（重要）

本节阶段编号为权威定义，与下方「2. 阶段总览」「3. 各阶段明细」的历史编号存在以下对齐关系：

- 原 P2「models 字段补齐」拆分为 **P2-A（脚本骨架 + 副本 dry-run）/ P2-B（models.py 字段补齐）/ P2-C（开发测试主线库正式迁移）** 三个子阶段。
- **执行顺序（2026-06-15 调整）**：P2-A → P2-A-END → **P2-C → P2-B**（先迁移主线库，再补 models.py）。原因：避免 SQLAlchemy 模型字段领先于数据库实际结构，导致旧库缺列错误。下方 §1.4 已是 P2-C、§1.5 已是 P2-B，编号固定不变、仅执行先后调整。
- 原 P9「人工处理」/ P10「Excel 导出」/ P11「NewCarProject」/ P12「React 前端接入」**重新编号**：本节 P9 = 回复检测、P10 = 人工处理、P11 = Excel 导出、P12 = NewCarProject 对接预留。
- 原「P1 服务边界与配置底座」在总控清单中未单列，作为各阶段内的配置项变更处理，不再作为独立阶段阻塞主线。
- **React 前端不再作为独立阶段**，跟随对应后端阶段（P6 / P10 / P11 等）穿插接入，最后统一收口。

> 后续开发一律以本节（§1）阶段定义为准。下方 §2（阶段总览）/ §3（各阶段明细）保留作为参考明细，不再作为阶段依据。

------

## 2. 阶段总览

| 阶段 | 名称 | 主风险 | 涉及数据库 | 涉及前端 | 涉及 Local Agent | 是否需确认 |
|------|------|--------|-----------|---------|-----------------|-----------|
| P0 | PRD 与现状冻结 | LOW | 否 | 否 | 否 | 已确认 |
| DB-MIG | 数据库迁移体系方案设计 | HIGH | 方案 | 否 | 否 | 已完成方案 |
| P2-A | 迁移脚本骨架与副本 dry-run | HIGH | 副本验证 | 否 | 否 | 已完成 ✅ |
| P2-C | 开发测试主线库正式迁移 | HIGH | 是 | 否 | 否 | **是（下一步，先于 P2-B）** |
| P2-B | models.py 字段补齐 | HIGH | 是 | 否 | 否 | **是（P2-C 完成后）** |
| P3 | Webhook 生产化规范 | HIGH | 否 | 否 | 否 | **是** |
| P4 | 联系方式提取落库与有效线索生成 | MEDIUM | 依赖 P2-B/P2-C | 否 | 否 | 是 |
| P5 | 线索状态机与状态映射 | HIGH | 依赖 P2-B/P2-C | 是 | 否 | **是** |
| P6 | 销售管理与销售导入 | MEDIUM | 依赖 P2-B/P2-C | 是 | 否 | 是 |
| P7 | 分配、非工作时间与超时重分配 | HIGH | 依赖 P2-B/P2-C | 是 | 否 | **是** |
| P8 | Local Agent 安全回归 | MEDIUM | 否 | 否 | 是 | 部分 |
| P9 | 回复检测 | MEDIUM | 依赖 P5 | 是 | 是 | 是 |
| P10 | 人工处理 | MEDIUM | 依赖 P5 | 是 | 否 | 是 |
| P11 | Excel 数据导出 | MEDIUM | 否 | 是 | 否 | 是（新依赖） |
| P12 | NewCarProject 对接预留 | MEDIUM | 依赖 P2-B/P2-C | 是 | 否 | 部分（字段待确认） |

> 后续开发一律以第 1 节阶段定义为准。所有标注依赖 P2-B/P2-C 的阶段，必须在模型字段补齐并完成开发测试库正式迁移后才能开始。

------

## 3. 各阶段明细

> 本节的逐阶段明细（目标 / 修改范围 / 验收标准 / 风险点 / 涉及面）是早期盘点产出的参考实现，编号已与第 1 节总控对齐（P2 拆为 P2-A/B/C，P9=回复检测、P10=人工处理、P11=Excel 导出、P12=NewCarProject，React 不再独立成阶段）。若与本文件第 1 节「阶段最终目标与边界总控」冲突，以第 1 节为准。本节仅作为阶段明细的补充，不覆盖总控的最终目标与禁止范围。

### P0 — PRD 冻结与差距分析落盘

- **目标**：冻结 PRD 边界、盘点真实调用链与已有能力、输出差距分析、明确命名映射。
- **修改范围**：纯文档。
  - 新增 `docs/ai/PRD_GAP_ANALYSIS.md`
  - 新增 `docs/ai/P0_DEV_PLAN.md`
  - 更新 `docs/ai/05_PROJECT_CONTEXT.md`
- **验收标准**：
  1. 差距分析区分 ✅ / ⚠️ / ❌ / ⛔ 四级。
  2. 每项标注 HIGH / MEDIUM / LOW。
  3. 明确 `douyin_webhook_events` ↔ `lead_source_events` 命名映射，且第一版不重命名。
  4. 明确最大阻塞点为数据库迁移体系缺失。
- **风险点**：LOW（仅文档）。
- **涉及**：数据库 否 / 前端 否 / Local Agent 否。
- **是否需确认**：本轮已确认。

### DB-MIG — 数据库迁移体系方案设计（独立前置阶段）

- **目标**：在修改 `models.py` 之前，确定迁移机制。
- **修改范围**：输出技术方案文档（预计 `docs/ai/14_DB_MIGRATION_PLAN.md`），不动业务代码。
- **待决策项**：
  1. 引入 Alembic，还是手写迁移脚本。
  2. 历史 SQLite 数据如何兼容（生产库已有 `douyin_leads` / `douyin_webhook_events` 等表数据）。
  3. 新增字段是否允许 NULL 默认、是否需要历史数据回填脚本。
  4. 回滚方案（down migration）。
  5. 迁移与 `Base.metadata.create_all` 的共存策略（开发库初始化 vs 生产库升级）。
- **验收标准**：方案经用户确认，能回答"加字段时旧库不会缺列报错、能回滚、能验证"。
- **风险点**：HIGH。当前 `create_all` 对已存在表不会 ALTER，直接加列会导致旧库报错。
- **涉及**：数据库 方案（不落库）/ 前端 否 / Local Agent 否。
- **是否需确认**：**是（硬阻塞，确认前禁止改 models.py）**。

### P1 — 服务边界与配置底座

- **目标**：
  1. 服务地址 / 端口 / 健康检查地址可配置，不写死。
  2. 子功能独立启动 / 配置 / 健康检查 / 日志 / 异常隔离的预留骨架（不物理拆分服务）。
  3. 集中后续业务所需配置项（默认超时 30min、重分配上限 5、工作时间窗口、SECRET_KEY 校验等）。
- **修改范围**（预估，待方案细化）：
  - `app/config.py`：补配置项。
  - `app/main.py`：补 `/health` 端点骨架。
  - 日志结构化预留（参考 05_PROJECT_CONTEXT.md 0.14 日志模板探索结论，但第一版不直接复制，先确认脱敏规则）。
- **验收标准**：
  1. 端口 / 健康检查地址从环境变量读取。
  2. 配置项集中在 config.py，业务代码不硬编码。
- **风险点**：MEDIUM（涉配置项变更，HIGH 风险域之一，需走配置变更确认）。
- **涉及**：数据库 否 / 前端 否 / Local Agent 否。
- **是否需确认**：配置项变更需确认。

### P2 — models 字段补齐

- **目标**：补齐 PRD 要求但当前缺失的持久化字段。
- **修改范围**（预估，DB-MIG 通过后细化）：
  - `DouyinLead`：扩展 status 注释为 13 态（`status` 列已存在，不新增、不改类型，仅扩取值域）；新增 `raw_message_text`、`external_lead_id`、`account_open_id`、`conversation_short_id`、`server_message_id`、`extracted_phone`、`extracted_wechat`、`all_extracted_contacts`、`contact_extract_status`、`contact_extract_reason`、`reassign_count`、`customer_id`、`external_customer_id`。
  - `SalesStaff`：新增 `remark`、`sort_order`。
  - 可选新增 `CallbackLog` 表（若状态回调第一版不对接，可后置）。
- **验收标准**：
  1. 迁移可升级、可回滚。
  2. 历史 SQLite 数据兼容（旧库不报缺列）。
  3. 历史数据回填脚本验证通过。
- **风险点**：HIGH（数据库结构变更）。
- **涉及**：数据库 **是** / 前端 否 / Local Agent 否。
- **是否需确认**：**是**。

### P3 — Webhook 生产验签 + 返回码规范化

- **目标**：
  1. production 环境真正强制验签（复核 `APP_ENV` 实际值、`DY_SECRET_KEY` 配置）。
  2. 复核 GMP 真实回调是否带签名头（第 28 章历史结论：线上不带；需复核当前状态）。
  3. 返回码按 PRD §6 七种规范化（200 / 400 / 401 / 500）。
  4. 对外成功响应统一 `{code:0,msg:"success"}`。
- **修改范围**（预估）：`app/integrations/douyin_webhook.py`、`app/routers/integrations.py`、`app/config.py`。
- **验收标准**：
  1. production + 缺 SECRET_KEY → 拒绝进入业务。
  2. 签名失败 → 401；格式错误 → 400；重复 / 非线索 / 无效线索 → 200。
  3. 回归测试覆盖验签开关、签名一致性、重复事件。
- **风险点**：HIGH（认证 / 配置）。需先与 GMP 侧确认真实回调是否带签名头，避免切换后线上 401 导致事件不入库。
- **涉及**：数据库 否 / 前端 否 / Local Agent 否。
- **是否需确认**：**是**。

### P4 — 联系方式提取落库 + 幂等键体系

- **目标**：
  1. 提取结果从 `raw_data` JSON 落到独立列（依赖 P2）。
  2. 幂等键体系补齐 `external_lead_id` / `open_id+account_open_id` / `conversation_short_id` / `server_message_id`（依赖 P2）。
- **修改范围**（预估）：`app/integrations/douyin_webhook.py`（`upsert_lead_from_webhook`）、`app/services/webhook_event_service.py`。
- **验收标准**：
  1. 新线索写入独立提取列。
  2. 多触发同 open_id 更新而非重建。
  3. 重复 event_key 仍幂等。
- **风险点**：MEDIUM（依赖 P2 字段；需历史数据回填）。
- **涉及**：数据库 依赖 P2 / 前端 否 / Local Agent 否。
- **是否需确认**：是。

### P5 — 状态机 13 态 + 对外映射

- **目标**：
  1. 13 个内部状态落地（received / invalid / delay_assign / pending_assign / assigned / notified / waiting_reply / replied / timeout / reassigned / manual_required / failed / closed）。
  2. 4 个对外状态映射层（未分配 / 已分配 / 已回复 / 超时未回复）。
  3. 不对外回调状态集合明确。
- **修改范围**（预估）：新增 `app/services/lead_status_mapper.py`；改造 webhook 写入、assign、scheduler、wechat_task、reports、routers/leads。
- **验收标准**：
  1. 状态流转全部走 mapper，替换硬编码。
  2. 对外接口只暴露 4 态。
  3. 状态流转测试覆盖合法 / 非法 / 重复 / 回滚。
- **风险点**：HIGH（跨模块 + 状态流转，回归面大）。
- **涉及**：数据库 依赖 P2 / 前端 是（对外状态展示）/ Local Agent 否。
- **是否需确认**：**是**。

### P6 — 销售字段 + Excel 导入 + 顺序轮询

- **目标**：
  1. 补 `remark` / `sort_order`（依赖 P2）。
  2. 微信昵称必填校验。
  3. Excel 导入（昵称必填、重复覆盖、部分成功、行号报错、模板下载）。
  4. `auto_assign_next` 改为按 `sort_order` 顺序轮询。
- **修改范围**（预估）：`app/routers/staff.py`、新增 `app/services/staff_import_service.py`、`app/services/assign_service.py`。
- **验收标准**：
  1. 导入返回成功 / 失败行号与原因。
  2. 重复昵称覆盖。
  3. 分配按 sort_order 顺序。
- **风险点**：MEDIUM（新依赖 openpyxl 评估、分配行为变更需评估存量数据）。
- **涉及**：数据库 依赖 P2 / 前端 是 / Local Agent 否。
- **是否需确认**：是（含 openpyxl 新依赖评估）。

### P7 — delay_assign + 超时重分配

- **目标**：
  1. 非工作时间 → `delay_assign`，到点续分配。
  2. 超时 → `reassign`（排除原销售、reassign_count 递增、上限 5、超限 → manual_required / failed）。
- **修改范围**（预估）：新增 `app/services/work_time_service.py`、`app/services/reassign_service.py`；改造 `app/scheduler/check_scheduler.py`、`app/services/assign_service.py`。
- **验收标准**：
  1. 非工作时间不分配，到点自动续。
  2. 重分配排除原销售。
  3. 第 6 次超时 → manual_required / failed，不再重分配。
- **风险点**：HIGH（业务核心、状态流转、调度器改造）。
- **涉及**：数据库 依赖 P2 / 前端 是 / Local Agent 否。
- **是否需确认**：**是**。

### P8 — Local Agent 回归与安全门禁复核

- **目标**：
  1. 真机回归验收 poll-and-execute / poll-and-detect，保持 sent=false、检测只读、互斥锁。
  2. 复核所有安全门禁（verified / partial_match / manual_review_required / foreground guard）。
  3. 复核 exe 是否为最新代码（已知风险：线上跑旧 exe）。
- **修改范围**（预估）：`app/local_agent_main.py` 回归性微调（不改安全边界）、exe 重新打包。
- **验收标准**：
  1. 真机闭环通过。
  2. sent 始终 false。
  3. 收发互斥生效。
- **风险点**：MEDIUM（真机验收 + exe 打包）。
- **涉及**：数据库 否 / 前端 否 / Local Agent **是**。
- **是否需确认**：部分（安全边界变更需确认；回归验收不需）。

### P9 — 人工处理

- **目标**：
  1. 人工重新分配（状态化，区别于普通 assign）。
  2. 人工补录销售回复（与 replied / manual_required 状态机打通）。
  3. 人工关闭线索 → closed，不可恢复。
- **修改范围**（预估）：新增 `app/routers/manual.py` 或扩展 `app/routers/leads.py`、`app/routers/replies.py`。
- **验收标准**：
  1. 重新分配进入未分配 / 分配流程。
  2. 补录回复可进入 replied。
  3. closed 后不可恢复。
- **风险点**：MEDIUM（依赖 P5 状态机）。
- **涉及**：数据库 依赖 P2/P5 / 前端 是 / Local Agent 否。
- **是否需确认**：是。

### P10 — Excel 导出（8 类）

- **目标**：按时间范围导出线索 / 分配 / 通知 / 检测 / 超时 / 回调失败 / 人工处理 / invalid 共 8 类，不脱敏。
- **修改范围**（预估）：新增 `app/services/export_service.py`、`app/routers/export.py`。
- **验收标准**：
  1. 8 类导出均可按时间范围生成。
  2. invalid 参与导出。
  3. 导出不脱敏（PRD §18 明确）。
- **风险点**：MEDIUM（openpyxl 新依赖、大时间范围性能、文件存储临时方案）。
- **涉及**：数据库 否 / 前端 是 / Local Agent 否。
- **是否需确认**：是（含 openpyxl 新依赖、文件落盘方案）。

### P11 — NewCarProject 预留 + customer_id

- **目标**：
  1. 本地生成 `customer_id`（依赖 P2）。
  2. NewCarProject 商户 ID 存 `external_customer_id`（依赖 P2）。
  3. 预留 token / cookie 识别入口骨架、roles / merchant_id 字段。
- **修改范围**（预估）：新增 `app/middleware/newcar_identity.py`（骨架）、`app/config.py`、`app/models.py`（依赖 P2）。
- **验收标准**：
  1. customer_id 本地生成并落库。
  2. token / cookie 解析骨架存在但默认放行（不阻断业务）。
  3. roles / merchant_id 字段预留。
- **风险点**：MEDIUM（字段结构待 NewCarProject 同事确认，只能预留）。
- **涉及**：数据库 依赖 P2 / 前端 是 / Local Agent 否。
- **是否需确认**：部分（字段结构待 NewCarProject 确认）。

### P12 — React 前端接入

- **目标**：将 P3~P11 的后端能力接入 React（`E:\work\project\react`）。
- **修改范围**（预估）：`react/src/api/` 扩展、对应页面接入（销售导入、导出、人工处理、invalid 列表、对外状态展示）。
- **验收标准**：各页面接入真实 API，替换 Mock；遵循 `CLAUDE.md` React TypeScript 配置约束（ignoreDeprecations 5.0 / composite / emitDeclarationOnly 不动）。
- **风险点**：MEDIUM。
- **涉及**：数据库 否 / 前端 **是** / Local Agent 否。
- **是否需确认**：是。

------

## 4. 阶段依赖与并行关系

```text
P0 ─── DB-MIG ─── P2 ──┬── P4
                       ├── P5 ── P9
                       ├── P6
                       ├── P7
                       └── P11

P1（配置底座）可与 DB-MIG 并行，但不应阻塞 DB-MIG。
P3（webhook 验签 / 返回码）可与 P2 并行（不依赖新字段）。
P8（Local Agent 回归）可与 P5/P6/P7 并行（独立真机验收）。
P10（导出）依赖业务表稳定，建议在 P5 之后。
P12（前端）跟随各后端阶段穿插，最后整体收口。
```

------

## 5. 阶段输出要求

每个阶段完成后必须输出（遵循 `04_OUTPUT_RULES.md` §8、§16）：

```text
1. 修改文件列表
2. 每个文件的修改原因
3. 是否符合 PRD
4. 是否涉及数据库变更
5. 是否涉及接口变更
6. 是否涉及前端变更
7. 是否涉及 Local Agent 变更
8. 测试结果（已执行 / 未执行 / 未执行原因）
9. 未完成项
10. 风险点
11. 下一步建议
12. commit 建议（中文）
```

------

## 6. 第一版不做清单（重申）

见 `docs/ai/PRD_GAP_ANALYSIS.md` 第 4 节。核心：

- P0 阶段不重命名 `douyin_webhook_events`。
- DB-MIG 方案未确认前，不改 `models.py`。
- 不引入 openpyxl（直到 P6 / P10 评估通过）。
- 不改 webhook 逻辑、不改 Local Agent、不改 React 前端（直到对应阶段）。

------

## 7. 当前下一步

```text
P0 与 DB-MIG 文档阶段已完成
  ↓
P2-A 迁移脚本骨架 + 副本 dry-run / apply 验证（已完成 ✅）
  ↓
P2-A-END WAL/hash 验收口径修正（已完成 ✅）
  ↓
等待用户确认后进入 P2-C：开发测试主线库正式迁移（先迁库）
  ↓
P2-C 完成并确认后，才进入 P2-B：models.py 字段补齐（后补模型）
  ↓
P2-B 与 P2-C 都完成后，才继续 P3~P12
```

> **顺序说明**：P2-C 先于 P2-B。原因：若先改 `models.py` 而主线库未迁移，模型会认为新字段已存在但实际表无此列，运行时缺列报错。先迁库再补模型，确保数据库结构与模型同步。

注意：本文件只定义阶段目标与边界，不代表自动进入 P2-C。进入 P2-C 前必须重新复述阶段目标、允许范围、禁止事项、验收标准，并等待用户确认。

------

## 8. 2026-06-18 一期需求与 Agent Runtime 补充规划

本节基于《小高AI系统需求文档（一期）》与现有代码只读探索结果补充。以下 P0 / P1 / P2 是面向新一期需求的产品化拆分建议，不代表自动进入开发；每个阶段执行前仍需单独确认范围、数据库策略、接口契约和验收标准。

### 8.1 P0：边界固化与架构预留

目标：先把现有能力边界、真实功能、mock 功能、占位功能和待确认项固化清楚，避免把一期需求误当作一次性开发范围。

范围：

1. 固化 `9000` / `19000` / `9100` 三服务边界。
   - `9000` 主服务：抖音 webhook、线索、销售、微信任务、回复检测、后台业务 API。
   - `19000` Local Agent：小高AI微信助手，本机微信 UI 自动化，只负责本地微信检测 / 任务执行。
   - `9100 apps/xg_douyin_ai_cs`：抖音AI客服、RAG、LLM 回复建议、未来 LangChain / Agent Tools。
2. 明确一期真实功能、mock 功能、占位功能。
   - 真实功能：抖音 webhook 原始事件入库、有效线索生成、线索分配、微信 Local Agent 检测销售回复、9100 AI 回复建议。
   - mock / 演示功能：部分工作台账号、Agent 绑定、知识库、后台管理页面能力。
   - 占位功能：小高算力、套餐消耗、完整管理员后台、完整 NewCarProject 权限接入。
3. 明确登录 / 权限 / NewCarProject 对接待确认项。
   - token / cookie 字段结构。
   - roles / permissions / menu 字段结构。
   - `merchant_id` 来源、可信传递方式和本地映射关系。
4. 明确 `merchant_id` / `douyin_account_id` / `agent_id` 上下文设计。
   - `merchant_id` 用于商户数据隔离。
   - `douyin_account_id` 用于抖音账号、会话和授权隔离。
   - `agent_id` 用于智能体配置、提示词、知识库和工具启停策略。
5. 明确 Agent Runtime 只做架构预留。
   - 不安装 LangChain。
   - 不替换 `OpenAICompatibleClient`。
   - 不替换 `ArkEmbeddingClient`。
   - 不重构现有 `reply_decision_service` 主链路。
   - 默认关闭 `XG_DOUYIN_AI_AGENT_RUNTIME_ENABLED=false`。

P0 禁止事项：

- 不改业务代码。
- 不执行数据库迁移。
- 不安装依赖。
- 不真实调用库存、支付、金融或其他外部系统。
- 不把 `19000 Local Agent` 误设计为 LLM Agent。

### 8.2 P1：一期核心产品化补齐

目标：在保留现有抖音线索、销售微信回复检测和 Local Agent 能力的前提下，补齐一期可验收的最小产品闭环。

建议范围：

1. 抖音客服真实会话 + AI 回复建议 + 人工确认。
   - 保持 `auto_send=false`。
   - AI 回复建议继续由 `9100` 提供。
   - 人工确认发送前必须保留审计记录。
2. 线索状态、详情、分配、跟进记录。
   - 保留当前有效线索和销售回复检测链路。
   - 明确内部状态与对外状态映射。
   - 补齐详情页、分配记录、跟进记录的一致性。
3. 智能体最小 CRUD + 绑定抖音号 + 绑定知识库。
   - 最小化实现智能体配置、提示词、知识库绑定。
   - 与 `douyin_account_id` 建立明确绑定关系。
4. 商户级查询过滤。
   - 后端查询统一按可信 `merchant_id` 过滤。
   - 前端传入商户字段不能作为唯一可信来源。
5. AgentRuntime mock tool 骨架。
   - 仅在关闭态或 mock 态预留。
   - 不接真实 LangChain。
   - tool 失败必须回退到普通 AI 回复建议。

P1 风险：

- 商户隔离字段来源未确认会阻塞生产化过滤。
- 状态机补齐会影响 webhook、线索、任务、前端展示多个模块。
- 人工确认发送涉及抖音私信发送能力与合规审计，必须单独验收。

### 8.3 P2：二期扩展与生产化

目标：在一期产品闭环稳定后，再扩展 Agent Tools、算力计费和多商户生产化能力。

建议范围：

1. LangChain 可选编排。
   - 只作为 `9100` 内部可选实现。
   - 业务层通过 `AgentRuntimeFacade` 访问，不直接依赖 LangChain。
2. 二期 tools。
   - `inventory_search_tool`：查询商户库存。
   - `vehicle_price_tool`：查询车辆价格 / 报价。
   - `customer_history_tool`：查询客户历史消息和跟进记录。
   - `merchant_kb_tool`：查询商户知识库。
   - `compliance_check_tool`：违禁词 / 合规检查。
3. 小高算力、套餐、消耗、充值。
   - 需要与 NewCarProject 套餐、消耗、充值、账单口径统一。
   - 不应在 auto_wechat 内孤立实现一套计费口径。
4. 多商户、多抖音号、多智能体生产化。
   - 商户、账号、智能体、知识库、会话、线索、回复记录必须全链路隔离。
   - 需要补齐审计日志、异常降级、权限校验和数据导出边界。
5. 抖音私信人工确认发送和附件能力。
   - 人工确认发送优先。
   - 附件、图片、素材发送需单独接口契约和合规确认。

P2 禁止默认行为：

- 不默认自动发送 AI 回复。
- 不默认真实调用库存、支付、金融或外部系统。
- 不允许 tool 无超时、无审计、无商户隔离。
- 合规检查失败时必须 `manual_required=true`，不允许自动发送。
