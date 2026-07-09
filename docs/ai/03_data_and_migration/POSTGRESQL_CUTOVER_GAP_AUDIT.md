# PostgreSQL cutover gap audit

任务：`P3-Z0-DB-9000-POSTGRESQL-CUTOVER-GAP-AUDIT-1`

本文审计 9000 从 SQLite 切换到 PostgreSQL 的最短可行缺口。本轮只做只读代码审计和文档记录，不新增 migration，不迁移数据，不执行 Alembic，不连接宝塔 production，不读取 production SQLite，不切换 `DATABASE_URL`，不启用 PG pilot，不启用 PG write。

## 1. 当前结论

1. 现在不能直接把 production `DATABASE_URL` 从 SQLite 切到 PostgreSQL。
2. 第一硬阻塞不是单张业务表，而是 `app/database.py` 当前同步主 engine 在识别到 PostgreSQL backend 时会抛出 `PostgreSQL backend 已识别但本轮未启用`；`app/main.py` 导入 `engine` 后还会执行 `Base.metadata.create_all(bind=engine)`，因此直接切库大概率在 9000 启动阶段失败。
3. PostgreSQL Alembic 目前只覆盖 11 张表，尚未覆盖 9000 ORM 中多张 runtime 会访问的表。
4. 已完成的 leads/tasks shadow、agents/accounts contrast、compute dry-run/dev apply 证明局部链路可行，但不能等同于全系统 cutover ready。
5. 后续应停止继续对 leads/tasks 做单表深挖，转入 staging cutover gap closure。

当前工作区补充说明：

1. 本节 11 张表是 P3-Z0 审计基线，依据为 `0001` 到 `0005` PostgreSQL Alembic。
2. 当前工作区已出现 P3-Z1 草案 `0006_create_runtime_cutover_gap_tables.py`，它补齐下文列出的 19 张缺失 runtime 表 schema。
3. 即使计入 P3-Z1 草案，当前仍未完成 cutover：数据迁移、受控 PG runtime 启动、staging `DATABASE_URL` smoke 和 production 切换窗口都还没完成。

## 2. 审计依据

只读审计来源：

1. ORM：`app/models.py`
2. 9000 路由：`app/routers/**`
3. 9000 服务：`app/services/**`
4. 能力子目录：`apps/compute/**`、`apps/agents/**`、`apps/knowledge/**`、`apps/leads/**`
5. SQLite migration：`migrations/versions/*.sql`
6. PostgreSQL Alembic：`migrations/postgres/auto_wechat/versions/*.py`
7. SQLite 专属写法检查：`python scripts/check_sqlite_specific_usage.py`
8. 入口和数据库 runtime：`app/main.py`、`app/database.py`、`app/config.py`

`check_sqlite_specific_usage.py` 结果：

```text
errors=0
warnings=80
```

warning 均在允许清单内，主要来自 9100 RAG SQLite 兼容层、SQLite migration 和测试。9000 主业务本轮未发现新的禁止级 SQLite-only 写法，但同步 SQLAlchemy 主路径仍未启用 PostgreSQL。

## 3. PostgreSQL 已覆盖表

当前 auto_wechat PostgreSQL Alembic `0001` 到 `0005` 已覆盖：

| 表 | PostgreSQL revision | 当前状态 |
|---|---|---|
| `knowledge_categories` | `0002_create_knowledge_categories` | schema / migration / dry-run / production dry-run 已完成，production apply 因 source rows = 0 建议跳过 |
| `sales_staff` | `0003_leads_tasks_core` | schema 已有，leads/tasks migration / contrast / shadow 已完成 |
| `douyin_leads` | `0003_leads_tasks_core` | schema 已有，leads/tasks migration / contrast / shadow 已完成 |
| `douyin_webhook_events` | `0003_leads_tasks_core` | schema 已有，leads/tasks migration / contrast / shadow 已完成 |
| `wechat_tasks` | `0003_leads_tasks_core` | schema 已有，leads/tasks migration / contrast / shadow 已完成 |
| `ai_agents` | `0004_agents_accounts_core` | schema / migration / contrast 已完成 |
| `douyin_authorized_accounts` | `0004_agents_accounts_core` | schema / migration / contrast 已完成 |
| `douyin_account_agent_bindings` | `0004_agents_accounts_core` | schema / migration / contrast 已完成 |
| `agent_knowledge_categories` | `0004_agents_accounts_core` | schema / migration / contrast 已完成 |
| `compute_accounts` | `0005_compute_core` | schema / migration dry-run / dev apply 已完成 |
| `compute_transactions` | `0005_compute_core` | schema / migration dry-run / dev apply 已完成 |

## 4. runtime 表覆盖矩阵

说明：

1. “SQLite 是否存在”基于 `app/models.py` 的 ORM create_all 路径和 `migrations/versions/*.sql` 判断，不读取任何 production SQLite。
2. “运行时是否会访问”基于路由、service、scheduler 静态扫描。
3. 缺口类型可多选，表格只记录主要缺口。

| table_name | SQLite 是否存在 | ORM model 是否存在 | PostgreSQL schema 是否存在 | 运行时是否会访问 | 访问路径 | 是否 P0 切库必需 | 是否可延后 | 缺口类型 | 建议动作 |
|---|---|---|---|---|---|---|---|---|---|
| `knowledge_categories` | 是 | 是 | 是 | 是 | `/knowledge-categories`、`apps/knowledge/services.py`、`apps/agents/services.py` | 是 | 否 | 无 | 保持已完成链路，切库前做 staging smoke |
| `sales_staff` | 是 | 是 | 是 | 是 | `/staff`、线索分配、报表、通知、任务 | 是 | 否 | data_migration_missing | 纳入 cutover 总迁移校验 |
| `douyin_leads` | 是 | 是 | 是 | 是 | `/leads`、webhook、报表、工作台、通知、任务 | 是 | 否 | data_migration_missing | 纳入 cutover 总迁移校验 |
| `douyin_webhook_events` | 是 | 是 | 是 | 是 | `/webhook-events`、webhook、AI 自动回复、工作台会话 | 是 | 否 | data_migration_missing | 纳入 cutover 总迁移校验 |
| `wechat_tasks` | 是 | 是 | 是 | 是 | `/wechat-tasks`、Local Agent polling、任务结果回写 | 是 | 否 | data_migration_missing | 纳入 cutover 总迁移校验 |
| `ai_agents` | 是 | 是 | 是 | 是 | `/agents`、账号绑定、自动回复 gate | 是 | 否 | data_migration_missing | 纳入 cutover 总迁移校验 |
| `douyin_authorized_accounts` | 是 | 是 | 是 | 是 | 抖音企业号管理、AI 客服代理、live-check、工作台 | 是 | 否 | data_migration_missing | 纳入 cutover 总迁移校验 |
| `douyin_account_agent_bindings` | 是 | 是 | 是 | 是 | 账号 Agent 绑定、自动回复 gate | 是 | 否 | data_migration_missing | 纳入 cutover 总迁移校验 |
| `agent_knowledge_categories` | 是 | 是 | 是 | 是 | `/agents/{id}/knowledge-categories` | 是 | 否 | data_migration_missing | 纳入 cutover 总迁移校验 |
| `compute_accounts` | 是 | 是 | 是 | 是 | `/compute/summary`、充值、套餐发放、内部用量 | 是 | 否 | data_migration_missing | 纳入 cutover 总迁移校验 |
| `compute_transactions` | 是 | 是 | 是 | 是 | `/compute/transactions`、充值、套餐发放、内部用量 | 是 | 否 | data_migration_missing | 纳入 cutover 总迁移校验 |
| `external_merchant_bindings` | 是 | 是 | 否 | 是 | `app/auth/dependencies.py`、`app/auth/external_merchant_binding_service.py` | 是 | 否 | schema_missing, data_migration_missing | P3-Z1 补 schema，P3-Z2 迁移或确认可自动创建 |
| `reply_checks` | 是 | 是 | 否 | 是 | `/checks`、`/replies`、通知、任务、报表、scheduler | 是 | 否 | schema_missing, data_migration_missing | P3-Z1 补 schema，P3-Z2 迁移 |
| `check_configs` | 是 | 是 | 否 | 是 | 自动检测配置、通知模板、scheduler、automation control | 是 | 否 | schema_missing, data_migration_missing | P3-Z1 补 schema，可允许空表加默认配置兜底 |
| `lead_notifications` | 是 | 是 | 否 | 是 | `/lead-notifications/*`、任务回写、线索详情、scheduler | 是 | 否 | schema_missing, data_migration_missing | P3-Z1 补 schema，P3-Z2 迁移 |
| `lead_followup_records` | 是 | 是 | 否 | 是 | `lead_management_service` 分配和详情时间线 | 是 | 否 | schema_missing, data_migration_missing | P3-Z1 补 schema，P3-Z2 迁移 |
| `feedback_records` | 是 | 是 | 否 | 是 | `/feedback`、线索详情历史 | 是 | 否 | schema_missing, data_migration_missing | P3-Z1 补 schema，P3-Z2 迁移或确认空历史可接受 |
| `douyin_oauth_states` | 是 | 是 | 否 | 是 | `/integrations/douyin/live-check/auth-*`、授权回跳 | 是 | 可空表启动 | schema_missing | P3-Z1 补 schema，历史 state 可不迁移 |
| `douyin_account_autoreply_settings` | 是 | 是 | 否 | 是 | `/douyin-autoreply/settings`、自动回复 gate | 是 | 否 | schema_missing, data_migration_missing | P3-Z1 补 schema，P3-Z2 迁移或确认默认关闭 |
| `conversation_autopilot_states` | 是 | 是 | 否 | 是 | 会话人工接管和自动回复托管状态 | 是 | 可空表启动 | schema_missing, data_migration_missing | P3-Z1 补 schema，按真实行数决定迁移 |
| `douyin_conversation_read_states` | 是 | 是 | 否 | 是 | 抖音 AI 客服工作台 mark-read / unread | 是 | 可空表启动 | schema_missing, data_migration_missing | P3-Z1 补 schema，可空表启动但会丢已读水位 |
| `douyin_private_message_sends` | 是 | 是 | 否 | 是 | live-check 手动发送记录、自动回复 send gate、工作台消息合并 | 是 | 否 | schema_missing, data_migration_missing | P3-Z1 补 schema，P3-Z2 迁移，保留防重复字段 |
| `ai_reply_decision_logs` | 是 | 是 | 否 | 是 | `/ai-reply-decision-logs`、AI 回复建议日志、admin rollout | 是 | 否 | schema_missing, data_migration_missing | P3-Z1 补 schema，P3-Z2 迁移 |
| `ai_auto_reply_runs` | 是 | 是 | 否 | 是 | `/ai-auto-reply-runs`、dry-run、admin rollout、gate 统计 | 是 | 否 | schema_missing, data_migration_missing | P3-Z1 补 schema，P3-Z2 迁移 |
| `douyin_message_resource_downloads` | 是 | 是 | 否 | 是 | live-check 资源下载记录 | 是 | 可空表启动 | schema_missing, data_migration_missing | P3-Z1 补 schema，按真实行数决定迁移 |
| `douyin_image_uploads` | 是 | 是 | 否 | 是 | live-check 图片上传记录 | 是 | 可空表启动 | schema_missing, data_migration_missing | P3-Z1 补 schema，按真实行数决定迁移 |
| `autoreply_rollout_configs` | 是 | 是 | 否 | 是 | `/admin/autoreply/rollout/*` | 是 | 可空表启动 | schema_missing, data_migration_missing | P3-Z1 补 schema，可空表保持默认关闭 |
| `autoreply_whitelist_entries` | 是 | 是 | 否 | 是 | `/admin/autoreply/rollout/whitelist`、gate 白名单 | 是 | 可空表启动 | schema_missing, data_migration_missing | P3-Z1 补 schema，可空表保持默认禁止 |
| `autoreply_admin_audit_logs` | 是 | 是 | 否 | 是 | admin rollout 审计 | 是 | 可空表启动 | schema_missing, data_migration_missing | P3-Z1 补 schema，按审计保留要求迁移 |
| `compute_packages` | 是 | 是 | 否 | 是 | `/compute/packages`、`/admin/compute/packages` | 是 | 否 | schema_missing, data_migration_missing | P3-Z1 补 schema，P3-Z2 迁移或 seed |
| `schema_migrations` | 是 | 否 | 否 | 否 | SQLite migration runner 内部表 | 否 | 是 | optional_deferred | 不迁移到 auto_wechat PG 业务库，Alembic 已有 `alembic_version` |

## 5. 切库后核心页面风险

| 页面 / 模块 | 必需表 | PG schema 覆盖情况 | 数据迁移覆盖情况 | 是否可以在 PG staging 启动 | 当前风险 | 最小补齐动作 |
|---|---|---|---|---|---|---|
| 抖音AI客服工作台 | `douyin_authorized_accounts`、`douyin_webhook_events`、`douyin_leads`、`douyin_private_message_sends`、`douyin_conversation_read_states`、`conversation_autopilot_states`、`ai_reply_decision_logs`、`ai_auto_reply_runs` | 只覆盖账号、事件、线索 | 只完成部分表 dev/synthetic 迁移验证 | 否 | 会话已读、自动回复状态、发送记录和日志表缺失会导致工作台或记录页 500 | P3-Z1 补 P1/自动回复相关 schema，P3-Z2 做数据迁移 |
| AI小高线索 | `douyin_leads`、`douyin_webhook_events`、`sales_staff`、`reply_checks`、`lead_notifications`、`lead_followup_records`、`feedback_records` | 只覆盖前三张 | leads/tasks 四表完成，时间线/通知/反馈未迁移 | 否 | 列表可能依赖已覆盖表，但详情、分配、通知状态和跟进历史会访问缺失表 | 补齐回复检测、通知、跟进、反馈 schema 和迁移 |
| AI小高智能体 | `ai_agents`、`agent_knowledge_categories`、`knowledge_categories`、`douyin_account_agent_bindings`、`douyin_authorized_accounts` | 已覆盖 | 已完成本地/dev synthetic contrast | 部分可以 | 主表可用，但仍依赖全局 `get_db` 同步 engine；切库启动阻塞未解 | 先解 runtime PG engine，再 staging smoke |
| 抖音企业号管理 | `douyin_authorized_accounts`、`douyin_account_agent_bindings`、`ai_agents`、`douyin_oauth_states`、`douyin_account_autoreply_settings` | 缺 OAuth state 和自动回复设置 | 主账号绑定迁移已验证，OAuth state 可空，设置未迁移 | 否 | 授权回跳、设置页和取消授权相关路径可能失败 | 补 `douyin_oauth_states`、`douyin_account_autoreply_settings` |
| 小高AI微信助手 | `wechat_tasks`、`reply_checks`、`lead_notifications`、`check_configs`、`douyin_leads`、`sales_staff` | 缺三张关键表 | wechat_tasks 已验证，回复检测/通知/配置未迁移 | 否 | pending 拉取、任务回写、自动检测目标、通知状态联动会失败 | 补回复检测、通知、配置 schema 和迁移 |
| 小高算力 | `compute_accounts`、`compute_transactions`、`compute_packages` | 缺套餐表 | 账户/流水已完成 dev apply，套餐未覆盖 | 否 | 套餐列表、管理员套餐配置、充值弹窗会失败或空缺 | 补 `compute_packages` schema 与迁移/seed |
| 管理员相关页面 | `autoreply_rollout_configs`、`autoreply_whitelist_entries`、`autoreply_admin_audit_logs`、`ai_auto_reply_runs`、`ai_reply_decision_logs`、`douyin_account_autoreply_settings` | 均缺或部分缺 | 未覆盖 | 否 | 灰度配置、白名单、审计和自动回复统计会失败 | 补 admin/autoreply schema，默认保持关闭 |
| NewCar 登录 / 外部账号绑定 | `external_merchant_bindings` | 缺失 | 未覆盖 | 否 | 真实 NewCar auth 启用时，受保护接口依赖本地商户绑定解析；缺表会导致登录后接口失败 | 补 schema，迁移现有绑定或确认首次登录自动创建策略 |

## 6. 必须补齐表

最短 cutover 以“9000 能在 PostgreSQL staging 启动并让当前已注册路由不因缺表 500”为标准，必须补齐以下表的 PostgreSQL schema：

1. `external_merchant_bindings`
2. `reply_checks`
3. `check_configs`
4. `lead_notifications`
5. `lead_followup_records`
6. `feedback_records`
7. `douyin_oauth_states`
8. `douyin_account_autoreply_settings`
9. `conversation_autopilot_states`
10. `douyin_conversation_read_states`
11. `douyin_private_message_sends`
12. `ai_reply_decision_logs`
13. `ai_auto_reply_runs`
14. `douyin_message_resource_downloads`
15. `douyin_image_uploads`
16. `autoreply_rollout_configs`
17. `autoreply_whitelist_entries`
18. `autoreply_admin_audit_logs`
19. `compute_packages`

同时必须补齐 runtime PostgreSQL 主路径：

1. `app/database.py` 不能继续在 `DATABASE_URL=postgresql...` 时拒绝同步主 engine。
2. `app/main.py` 不应在 production PostgreSQL cutover 时依赖 `Base.metadata.create_all` 自动建业务表；应改为 Alembic schema readiness 检查或启动前独立迁移。
3. 当前大量路由和 service 仍使用同步 `Depends(get_db)` / `SessionLocal()`，最短路径可以先用同步 PostgreSQL engine 启动 staging smoke，但 QPS600 不能据此宣称达标。

## 7. 可延后或可空表启动

以下表不建议省略 schema，但数据可以按真实行数和业务审批决定是否迁移：

| 表 | 可空启动说明 |
|---|---|
| `douyin_oauth_states` | OAuth state 是短生命周期数据，切库窗口前可要求无未完成授权流程 |
| `douyin_conversation_read_states` | 空表会丢已读水位，但不应阻塞会话数据展示 |
| `conversation_autopilot_states` | 空表会回到默认托管状态，需产品确认 |
| `douyin_message_resource_downloads` | 历史下载记录可按审计要求决定迁移 |
| `douyin_image_uploads` | 历史上传尝试记录可按审计要求决定迁移 |
| `autoreply_rollout_configs` | 空表必须等价于默认关闭 |
| `autoreply_whitelist_entries` | 空表必须等价于无白名单 |
| `autoreply_admin_audit_logs` | 历史审计是否迁移需要审批 |
| `feedback_records` | 如当前反馈发送不作为主功能，可以延后业务验证，但表仍需存在 |

`schema_migrations` 是 SQLite 迁移 runner 内部表，不迁移到 PostgreSQL 业务库；PostgreSQL 使用 Alembic `alembic_version`。

## 8. 必须补齐的数据迁移脚本

已完成但仍需纳入 cutover 汇总执行和真实数据 dry-run 的表：

1. `knowledge_categories`
2. `sales_staff`
3. `douyin_leads`
4. `douyin_webhook_events`
5. `wechat_tasks`
6. `ai_agents`
7. `douyin_authorized_accounts`
8. `douyin_account_agent_bindings`
9. `agent_knowledge_categories`
10. `compute_accounts`
11. `compute_transactions`

尚未补齐的 cutover 必需迁移：

1. 线索 / 微信助手补充表：`reply_checks`、`check_configs`、`lead_notifications`、`lead_followup_records`、`feedback_records`
2. NewCar / 授权表：`external_merchant_bindings`、`douyin_oauth_states`
3. 自动回复 / 工作台表：`douyin_account_autoreply_settings`、`conversation_autopilot_states`、`douyin_conversation_read_states`、`douyin_private_message_sends`、`ai_reply_decision_logs`、`ai_auto_reply_runs`
4. 资源记录表：`douyin_message_resource_downloads`、`douyin_image_uploads`
5. 管理员灰度表：`autoreply_rollout_configs`、`autoreply_whitelist_entries`、`autoreply_admin_audit_logs`
6. 算力套餐表：`compute_packages`

## 9. SQLite 专属查询风险

审计结论：

1. 当前禁止级 SQLite-only 写法检查为 `errors=0`。
2. 仍存在允许清单 warning，主要属于 9100 RAG SQLite 兼容层、SQLite migration、测试。9100 不在本次 9000 cutover 范围内。
3. 9000 当前更大的风险不是散落 `sqlite3.connect`，而是同步主 database factory 仍只允许 SQLite。
4. SQLite 布尔 0/1 到 PostgreSQL Boolean 的转换需要在缺失表 schema 和迁移脚本中统一处理，尤其是自动回复、通知和状态类表。
5. `Base.metadata.create_all` 在 PostgreSQL production cutover 中不应作为建表手段，避免绕过 Alembic、约束和索引审计。

## 10. staging 切库最短任务序列

推荐后续任务不超过 5 个：

1. `P3-Z1`：补齐 PG runtime 缺失表 schema，并让 9000 支持受控 PostgreSQL staging 启动路径。范围包括缺失表 Alembic、同步 PG engine 最小接入、禁用 production 自动 create_all。
2. `P3-Z2`：补齐 cutover 必需表数据迁移脚本。按业务域合并脚本，不再逐表深挖；默认 dry-run，dev/staging apply 受控。
3. `P3-Z3`：staging PG `DATABASE_URL` 启动 smoke。只在 staging，验证启动、`/health`、auth、核心页面读接口、写入禁区和回滚。
4. `P3-Z4`：production dry-run + apply 计划。先审批 production dry-run，再根据 source rows 和 error 决定是否 apply；不得自动 apply。
5. `P3-Z5`：production `DATABASE_URL` 切换窗口。必须具备备份、停写窗口、验证清单、回滚命令和负责人。

## 11. production 切库准入条件

production cutover 前至少满足：

1. `P3-Z1` 缺失 runtime 表 schema 已全部 Alembic 化。
2. `P3-Z2` 必需表迁移 dry-run 通过，`error = 0`。
3. staging 已用 PostgreSQL `DATABASE_URL` 启动并通过核心页面 smoke。
4. NewCar auth 真链路已验证 `external_merchant_bindings`。
5. 微信助手任务创建、pending 拉取、结果回写已在 staging 验证，但不触发真实微信发送。
6. 抖音 webhook 入库在 staging 验证，但不触发真实抖音发送或私信发送。
7. 自动回复 gate 保持关闭，PG write 不包括真实发送。
8. compute 账户、流水和套餐页在 staging 验证，未改支付 / 扣费 / 充值 / 套餐发放业务规则。
9. production SQLite、PostgreSQL volume 和代码版本均已备份。
10. `DATABASE_URL` 切换有明确回滚窗口，回滚默认恢复 SQLite 路径，不清空 PG volume。

## 12. 本轮安全确认

1. 未新增 migration。
2. 未迁移数据。
3. 未执行 Alembic。
4. 未连接宝塔 production。
5. 未读取 production SQLite。
6. 未切换 `DATABASE_URL`。
7. 未开启 PG pilot。
8. 未启用 PG write。
9. 未触发 LLM、抖音发送、微信发送、私信发送或自动回复 gate。
10. 未修改业务代码。

## 13. P3-Z1 schema gap closure 记录

任务：`P3-Z1-DB-9000-POSTGRESQL-RUNTIME-CUTOVER-GAP-SCHEMA-1`

P3-Z1 已新增 PostgreSQL Alembic revision：

```text
migrations/postgres/auto_wechat/versions/0006_create_runtime_cutover_gap_tables.py
revision = 0006_runtime_cutover_gap
down_revision = 0005_compute_core
```

本批补齐 Z0 审计中缺失的 19 张 9000 runtime 表 schema：

1. `external_merchant_bindings`
2. `reply_checks`
3. `check_configs`
4. `lead_notifications`
5. `lead_followup_records`
6. `feedback_records`
7. `douyin_oauth_states`
8. `douyin_account_autoreply_settings`
9. `conversation_autopilot_states`
10. `douyin_conversation_read_states`
11. `douyin_private_message_sends`
12. `ai_reply_decision_logs`
13. `ai_auto_reply_runs`
14. `douyin_message_resource_downloads`
15. `douyin_image_uploads`
16. `autoreply_rollout_configs`
17. `autoreply_whitelist_entries`
18. `autoreply_admin_audit_logs`
19. `compute_packages`

本批新增验证：

```text
tests/test_9000_postgres_runtime_cutover_gap_schema.py
scripts/smoke_auto_wechat_alembic_runtime_cutover_gap.py
```

P3-Z1 schema 结论：

1. PostgreSQL Alembic schema 覆盖从 11 张表扩展到 30 张 9000 runtime 表。
2. 本批只补 schema，不迁移 SQLite 数据。
3. 本批不执行 production apply，不读取 production SQLite，不连接宝塔 production。
4. 本批不切换默认 `DATABASE_URL`，不启用 PG pilot，不启用 PG write。
5. `app/database.py` PostgreSQL 主 engine 启动路径和 `Base.metadata.create_all` 切换风险仍未处理，不能据此直接启动 production cutover。
6. 下一步应进入 `P3-Z2` cutover 必需表数据迁移脚本，或拆出受控 PostgreSQL staging 启动路径任务；不得跳过 staging smoke 直接切 production。

## 14. P3-Z2 cutover 一次性迁移脚本记录

任务：`P3-Z2-DB-9000-POSTGRESQL-CUTOVER-DATA-MIGRATION-1`

P3-Z2 已新增一次性 cutover 迁移脚本：

```text
scripts/migrate_9000_sqlite_to_postgres_cutover.py
tests/test_cutover_sqlite_to_postgres_migration.py
```

覆盖范围为 30 张 9000 runtime 表，即 Z0 基线 11 张表加 Z1 补齐的 19 张表。脚本口径：

1. 默认 `--dry-run`，不写 PostgreSQL，不修改 SQLite，不修改 `.env`。
2. SQLite 源库必须显式传 `--sqlite-db-path`。
3. PostgreSQL URL 可来自 `--postgres-url`、`SMOKE_DATABASE_URL` 或 `DATABASE_URL`；但 apply 不允许隐式使用 `DATABASE_URL`。
4. `--apply` 必须同时传 `--yes`。
5. `APP_ENV=production` 时拒绝 apply。
6. apply 只允许 dev/staging host：`localhost`、`127.0.0.1`、`postgres`、`auto-wechat-postgres-dev`。
7. apply 目标 database 必须是 `auto_wechat`。
8. 迁移按 `id` 做通用 upsert，保留 SQLite id，避免破坏现有跨表引用。
9. `knowledge_categories` 兼容 PG 侧 `"key"` 字段，源行缺 `key` 时使用 `category_key` 填充。
10. JSON / datetime / bool 字段做保守转换；预览输出会脱敏手机号、open_id、token、raw JSON。

当前限制：

1. P3-Z2 脚本是 cutover 统一迁移骨架，不代表已在宝塔 staging 执行。
2. 当前未执行 staging apply，未迁移真实数据。
3. 当前仍未切换默认 `DATABASE_URL`。
4. 下一步仍需 `P3-Z3` 用 PostgreSQL `DATABASE_URL` 启动 9000 staging smoke。

## 15. P3-Z3 PostgreSQL DATABASE_URL startup smoke scaffold

任务：`P3-Z3-DB-9000-POSTGRESQL-DATABASE-URL-STARTUP-SMOKE-1`

P3-Z3 当前补齐了 9000 主 runtime 的最小 PostgreSQL 启动能力：

```text
app/database.py
app/main.py
scripts/smoke_9000_postgres_startup.py
tests/test_9000_database_factory.py
tests/test_9000_postgres_runtime_startup.py
```

runtime 口径：

1. SQLite 默认路径保持不变，仍继续自动 `Base.metadata.create_all(bind=engine)`。
2. PostgreSQL `DATABASE_URL` 下，主同步 engine 使用 `psycopg` 驱动。
3. 传入 `postgresql+asyncpg://...` 时，主同步 engine 会派生为 `postgresql+psycopg://...`；async PG pilot 仍可继续使用原始 asyncpg URL。
4. PostgreSQL 连接使用 `DB_POOL_SIZE`、`DB_MAX_OVERFLOW`、`DB_POOL_TIMEOUT`、`DB_POOL_RECYCLE` 和 `DB_STATEMENT_TIMEOUT_MS`。
5. PostgreSQL runtime 启动时不再执行 `Base.metadata.create_all`，schema 必须先通过 Alembic 初始化。
6. 新增 `psycopg[binary]` 依赖，用于同步 SQLAlchemy runtime；不改变业务接口默认数据库。

startup smoke 口径：

```bash
python scripts/smoke_9000_postgres_startup.py --database-url <POSTGRES_URL>
```

该 smoke 只验证 app import / create_app 阶段可在 PostgreSQL `DATABASE_URL` 下完成，不进入 FastAPI lifespan，不启动 scheduler、热键或桌面浮层，不连接宝塔 production，不读取 production SQLite。

当前限制：

1. 本地未安装 `psycopg` 时，真实 PostgreSQL app import 需要先安装更新后的 requirements。
2. 本轮没有连接 dev/staging PostgreSQL 实库执行 smoke。
3. 本轮没有执行 `DATABASE_URL` 切换，也没有启用 PG write。
4. 下一步仍需在宝塔 staging 先完成 Alembic 到 head、数据 dry-run / apply 审批，再执行真实 startup smoke 和核心接口 smoke。
