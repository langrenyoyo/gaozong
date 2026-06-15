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
P0  文档落盘
  ↓
数据库迁移方案设计（独立阶段，先于 P2）
  ↓
P2  models 字段补齐
  ↓
webhook 幂等和验签规范化
  ↓
状态机重构
  ↓
销售导入 / 重分配 / 人工处理 / 导出
```

------

## 1. 阶段总览

| 阶段 | 名称 | 主风险 | 涉及数据库 | 涉及前端 | 涉及 Local Agent | 是否需确认 |
|------|------|--------|-----------|---------|-----------------|-----------|
| P0 | PRD 冻结与差距分析落盘 | LOW | 否 | 否 | 否 | 已确认 |
| DB-MIG | 数据库迁移体系方案设计 | HIGH | 方案 | 否 | 否 | **是** |
| P1 | 服务边界与配置底座 | MEDIUM | 否 | 否 | 否 | 部分 |
| P2 | models 字段补齐 | HIGH | 是 | 否 | 否 | **是** |
| P3 | Webhook 生产验签 + 返回码规范化 | HIGH | 否 | 否 | 否 | **是** |
| P4 | 联系方式提取落库 + 幂等键体系 | MEDIUM | 依赖 P2 | 否 | 否 | 是 |
| P5 | 状态机 13 态 + 对外映射 | HIGH | 依赖 P2 | 是 | 否 | **是** |
| P6 | 销售字段 + Excel 导入 + 顺序轮询 | MEDIUM | 依赖 P2 | 是 | 否 | 是 |
| P7 | delay_assign + 超时重分配 | HIGH | 依赖 P2 | 是 | 否 | **是** |
| P8 | Local Agent 回归与安全门禁复核 | MEDIUM | 否 | 否 | 是 | 部分 |
| P9 | 人工处理 | MEDIUM | 依赖 P5 | 是 | 否 | 是 |
| P10 | Excel 导出（8 类） | MEDIUM | 否 | 是 | 否 | 是（新依赖） |
| P11 | NewCarProject 预留 + customer_id | MEDIUM | 依赖 P2 | 是 | 否 | 部分（字段待确认） |
| P12 | React 前端接入 | MEDIUM | 否 | 是 | 否 | 是 |

> 所有标注「依赖 P2」的阶段，必须在 P2（models 字段补齐）通过迁移落库后才能开始。

------

## 2. 各阶段明细

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
  - `DouyinLead`：扩展 status 注释为 13 态；新增 `external_lead_id`、`account_open_id`、`conversation_short_id`、`server_message_id`、`extracted_phone`、`extracted_wechat`、`all_extracted_contacts`、`contact_extract_status`、`contact_extract_reason`、`reassign_count`、`customer_id`、`external_customer_id`。
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

## 3. 阶段依赖与并行关系

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

## 4. 阶段输出要求

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

## 5. 第一版不做清单（重申）

见 `docs/ai/PRD_GAP_ANALYSIS.md` 第 4 节。核心：

- P0 阶段不重命名 `douyin_webhook_events`。
- DB-MIG 方案未确认前，不改 `models.py`。
- 不引入 openpyxl（直到 P6 / P10 评估通过）。
- 不改 webhook 逻辑、不改 Local Agent、不改 React 前端（直到对应阶段）。

------

## 6. 当前下一步

```text
数据库迁移体系方案设计（DB-MIG）
  ↓
输出 docs/ai/14_DB_MIGRATION_PLAN.md（仅方案，不落库）
  ↓
方案经确认后进入 P2
```
