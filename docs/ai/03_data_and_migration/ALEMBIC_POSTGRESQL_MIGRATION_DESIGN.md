# Alembic PostgreSQL 迁移方案设计

任务：`P3-A-DB-ALEMBIC-POSTGRESQL-MIGRATION-DESIGN-1`

范围：本文只设计 auto_wechat 从 SQLite 过渡到 PostgreSQL 的 Alembic migration 方案。本轮不安装 Alembic，不创建 `alembic.ini` / `env.py` / `versions`，不连接 PostgreSQL，不创建表，不跑迁移，不切换 9000 / 9100 当前运行路径。

## 1. 当前迁移现状审计

### 1.1 9000 当前 SQLite migration

9000 主服务当前迁移体系位于：

```text
migrations/
  migrate_sqlite.py
  versions/
    0001_prd_base_fields.sql
    ...
    0026_external_merchant_bindings_unique_active_user.sql
```

现状结论：

1. 当前 runner 是 `migrations/migrate_sqlite.py`，定位为手写 SQLite 迁移执行器。
2. 版本表使用 `schema_migrations`，故意不同于 Alembic 默认的 `alembic_version`。
3. `migrations/versions/*.sql` 已覆盖 9000 多批 SQLite 结构演进，例如 `douyin_authorized_accounts`、`ai_agents`、`knowledge_categories`、`compute_*`、`external_merchant_bindings` 等。
4. `app/main.py` 仍会执行 `Base.metadata.create_all(bind=engine)`，测试中也大量使用 `Base.metadata.create_all(bind=engine)` 创建当前 ORM 表。
5. `app/models.py` 是 9000 ORM 表结构的主要来源之一；SQLite 迁移 SQL 与 ORM 模型处于并行维护状态。

### 1.2 9000 当前表结构来源

9000 当前表结构主要来自三类来源：

1. `app/models.py`：SQLAlchemy ORM 模型，用于主服务运行和测试建表。
2. `migrations/versions/*.sql`：SQLite 手写迁移，用于历史库补结构。
3. 少量脚本 / smoke：例如 `scripts/smoke_knowledge_categories_sqlite_pg_contrast.py` 会创建临时 `knowledge_categories` smoke 表；该表不是正式 schema，不得作为 PostgreSQL migration 真源。

### 1.3 9100 当前 metadata 表结构来源

9100 RAG / AI 客服 metadata 当前表结构来源为：

```text
apps/xg_douyin_ai_cs/rag/database.py
```

该文件在 `init_db()` 中通过 SQLite `CREATE TABLE IF NOT EXISTS` 和 `_ensure_column()` 初始化 metadata 表，包括：

1. `knowledge_categories`
2. `knowledge_documents`
3. `knowledge_chunks`
4. `rag_training_runs`
5. `llm_call_logs`
6. `knowledge_training_sessions`
7. `knowledge_training_feedbacks`

`apps/xg_douyin_ai_cs/rag/models.py` 当前是 Pydantic schema，不是数据库 ORM 模型。

### 1.4 Alembic 现状

当前代码中没有正式 Alembic 环境：

1. 未发现可执行的 `alembic.ini`。
2. 未发现 PostgreSQL 专用 `env.py`。
3. 未发现 PostgreSQL Alembic `versions/` 目录。
4. 现有文档曾记录“暂不引入 Alembic”或“未来引入 Alembic”的计划，但未落地正式 Alembic migration。

### 1.5 测试 / smoke 与 migration 的关系

当前测试和 smoke 不能替代正式 migration：

1. 大量 9000 测试通过 `Base.metadata.create_all()` 建表，只证明 ORM 当前可建表。
2. SQLite migration runner 测试只验证手写 SQLite SQL 的解析、幂等、dry-run / apply / verify。
3. P2-F5 `GET /knowledge-categories` SQLite / PostgreSQL 对照 smoke 只创建临时最小 PostgreSQL 表，用于接口语义对照，不是正式 migration。
4. 后续 PostgreSQL 正式表结构、索引、唯一约束和回滚策略必须由 P3 Alembic migration 单独管理。

## 2. 目标架构

PostgreSQL 目标方案继续采用方案 A：一个 PostgreSQL 容器实例，两个 database。

```text
PostgreSQL Docker Compose 容器：postgres
  - database: auto_wechat
    - 9000 主服务使用
    - DATABASE_URL

  - database: xg_douyin_ai_cs
    - 9100 RAG / AI 客服 metadata 使用
    - RAG_DATABASE_URL
```

迁移管理目标：

1. 9000 与 9100 migration 独立管理。
2. 两个 database 各自维护独立 `alembic_version` 表。
3. Milvus 不参与 Alembic migration。
4. Milvus 继续作为 embedding / 向量检索副本，不是 metadata 真源。
5. PostgreSQL 是 metadata 真源，Milvus 与 PostgreSQL 通过 `document_id`、`chunk_id`、`content_hash`、`status` 等字段保持一致。

## 3. 推荐 Alembic 目录方案

推荐使用两个独立 migration 环境：

```text
migrations/
  postgres/
    auto_wechat/
      alembic.ini
      env.py
      versions/
      README.md

    xg_douyin_ai_cs/
      alembic.ini
      env.py
      versions/
      README.md
```

每个环境独立负责：

1. 独立读取对应 database URL。
2. 独立连接目标 database。
3. 独立维护 `alembic_version` 表。
4. 独立生成和执行 migration revision。
5. 独立提供 status / upgrade / downgrade / verify 说明。

建议配置边界：

| 环境 | database | URL 环境变量 | 版本表 |
|---|---|---|---|
| `migrations/postgres/auto_wechat/` | `auto_wechat` | `DATABASE_URL` | `alembic_version` |
| `migrations/postgres/xg_douyin_ai_cs/` | `xg_douyin_ai_cs` | `RAG_DATABASE_URL` | `alembic_version` |

## 4. 为什么不共用一个 migration 环境

不建议用一个 Alembic 环境同时管理 9000 和 9100：

1. 9000 / 9100 服务边界不同。
2. 两者对应不同 database，不是一个 database 内的 schema。
3. 发布节奏不同，9000 主业务表和 9100 RAG metadata 表不应互相阻塞。
4. 回滚半径不同，RAG metadata 失败不应误影响主业务 database。
5. 共用环境容易误把 migration 执行到错误 database。
6. 独立环境能降低宝塔灰度、备份、恢复和审计复杂度。

## 5. 迁移阶段路线

### P3-A：设计

本阶段只产出本文档和上下文同步，不安装 Alembic，不创建 migration 骨架，不连接 PostgreSQL。

### P3-B：Alembic skeleton，不建业务表

已创建两个 Alembic 环境骨架：

```text
migrations/postgres/auto_wechat/
migrations/postgres/xg_douyin_ai_cs/
```

P3-B 只验证配置、脱敏、命令入口和空 migration 环境，不创建业务表。

当前骨架文件：

```text
migrations/postgres/auto_wechat/
  alembic.ini
  env.py
  versions/0001_empty_baseline.py

migrations/postgres/xg_douyin_ai_cs/
  alembic.ini
  env.py
  versions/0001_empty_baseline.py
```

两个 `0001_empty_baseline.py` 均为空基线：

1. `upgrade()` 为空。
2. `downgrade()` 为空。
3. 不创建业务表。
4. 不创建 index。

未来命令示例：

```bash
python -m alembic -c migrations/postgres/auto_wechat/alembic.ini current
python -m alembic -c migrations/postgres/auto_wechat/alembic.ini upgrade head

python -m alembic -c migrations/postgres/xg_douyin_ai_cs/alembic.ini current
python -m alembic -c migrations/postgres/xg_douyin_ai_cs/alembic.ini upgrade head
```

执行边界：

1. `auto_wechat` 环境读取 `DATABASE_URL`。
2. `xg_douyin_ai_cs` 环境读取 `RAG_DATABASE_URL`。
3. `env.py` 遇到 SQLite URL 会拒绝执行，避免误把 SQLite 当 PostgreSQL migration 目标。
4. 本阶段不执行上述命令，不连接 PostgreSQL，不跑 migration。
5. P3-C 才开始设计 / 创建 9000 PostgreSQL 初始 schema。
6. P3-D 才开始设计 / 创建 9100 PostgreSQL 初始 schema。

### P3-C：9000 PostgreSQL 初始 schema

为 `auto_wechat` database 创建 9000 初始 schema。首批优先覆盖低风险和试点所需表，不一次迁移全部发送链路表。

P3-C-DB-9000-POSTGRES-KNOWLEDGE-CATEGORIES-SCHEMA-1 已新增第一张正式业务表 revision：

```text
migrations/postgres/auto_wechat/versions/0002_create_knowledge_categories.py
```

本 revision 只创建 `knowledge_categories` 表和该表查询所需索引，不创建其它业务表，不修改 `xg_douyin_ai_cs` Alembic 环境。当前仍未切换 9000 运行数据库，未迁移真实 SQLite 数据，未连接 PostgreSQL，未执行 `alembic upgrade`。

字段设计以当前 9000 查询链路为准：现有代码依赖 `category_key`，P2-F5 smoke 也保留 `"key"` / `category_key` 双字段对照。因此 PostgreSQL 正式表同时保留 `"key"` 和 `category_key`，并用 `ck_knowledge_categories_key_matches_category_key` 保证二者一致，避免后续试点 repository 与迁移数据语义分叉。

### P3-D：9100 PostgreSQL 初始 schema

为 `xg_douyin_ai_cs` database 创建 RAG / AI 客服 metadata 初始 schema，明确 PostgreSQL 为 metadata 真源。

### P3-E：SQLite -> PostgreSQL 数据迁移脚本

编写独立数据迁移脚本，做备份、dry-run、apply、verify、回滚计划和幂等校验。

### P3-F：试点接口切 PG 对照

继续以 `GET /knowledge-categories` 为试点，做 SQLite / PostgreSQL 对照验证和受控切换。

### P3-G：宝塔灰度切换

在宝塔环境先灰度切换试点接口，再逐步扩大范围。

### P3-H：关闭 SQLite 生产路径

完成验证后关闭宝塔生产 SQLite 路径；SQLite 仅保留为本地开发或历史数据只读恢复工具。

## 6. 9000 初始 schema 范围建议

9000 首批 PostgreSQL schema 应优先覆盖低风险、只读试点和基础鉴权绑定相关表：

1. `knowledge_categories`
   - P2-F 试点接口 `GET /knowledge-categories` 已围绕该表建立 async PG repository 和 smoke。
   - P3-C 已优先创建该表的 PostgreSQL revision，便于后续单独做 dev postgres migration smoke 和 SQLite / PostgreSQL 对照。
   - 当前未迁移真实数据，正式数据迁移仍留给 P3-E。
2. `external_merchant_bindings`
   - NewCar 鉴权和 merchant binding 相关。
   - 需要保留 active 用户唯一约束。
3. `merchants` / auth context 相关表
   - 当前 auth context 依赖 merchant_id、权限和外部绑定语义。
   - 若本地没有独立 `merchants` 物理表，P3-C 需要先审计是否应创建最小 merchant registry，或仅迁移现有绑定表。
4. `douyin_authorized_accounts`
   - 抖音账号绑定、账号授权、商户隔离相关。
5. `ai_agents`
   - AI 客服智能体基础配置。
6. `douyin_account_agent_bindings`
   - 抖音账号到 Agent 绑定关系。
7. `compute_accounts`、`compute_transactions`、`compute_packages`
   - 小高算力相关表。
8. `leads` / `douyin_leads`、`lead_notifications`、`wechat_tasks`
   - 后续分批迁移。
   - 首批不建议一次迁移全部高风险发送链路表，避免误触发或误切换微信通知、私信、自动回复 gate。

首批不建议包含：

1. 抖音发送记录正式写路径。
2. 私信发送链路正式写路径。
3. 自动回复真实发送 gate。
4. Local Agent 任务执行切换。

## 7. 9100 初始 schema 范围建议

9100 PostgreSQL 初始 schema 应覆盖 RAG / AI 客服 metadata 真源：

1. `knowledge_categories`
2. `knowledge_documents`
3. `knowledge_chunks`
4. `knowledge_training_feedbacks`
5. `knowledge_training_sessions`
6. `rag_training_runs` 或后续统一命名的 `training_runs`
7. categories / category binding 相关 metadata
8. 必要的 `llm_call_logs` 或回复建议审计 metadata，按 P3-D 审计后决定是否首批纳入。

设计原则：

1. PostgreSQL 是 metadata 真源。
2. Milvus 是向量副本，不保存完整 metadata 真相。
3. `document_id`、`chunk_id`、`content_hash`、`status`、`updated_at` 必须能支撑 PostgreSQL 与 Milvus 一致性校验。
4. 训练 / upsert 成功后必须回写 PostgreSQL 状态。
5. 删除 / 禁用文档时必须能同步 Milvus 状态或删除向量。
6. `ask` 不能因为 metadata count 来源不可靠就跳过 Milvus 检索。

## 8. 类型映射规范

| SQLite 用法 | PostgreSQL 建议 | 说明 |
|---|---|---|
| `INTEGER` 0/1 | `BOOLEAN` | 不继续依赖 SQLite 0/1 隐式布尔语义 |
| `TEXT` JSON | `JSONB` | 适合 metadata、raw payload、结构化配置 |
| timestamp `TEXT` | `TIMESTAMPTZ` | 迁移时显式解析时区 |
| timestamp `INTEGER` | `TIMESTAMPTZ` | 明确秒 / 毫秒，不做隐式猜测 |
| `INTEGER PRIMARY KEY` | `BIGSERIAL` 或 `UUID` | 内部自增用 `BIGSERIAL`，跨系统稳定引用可考虑 `UUID` |
| `answer_hash` | `VARCHAR(64)` | 固定 SHA-256 等哈希长度 |
| `training_id` | `VARCHAR(64)` | 训练反馈幂等标识 |
| `status` | `VARCHAR(32)` | 后续可加 CHECK 或枚举约束 |
| `ingestion_status` | `VARCHAR(32)` | 反馈入库状态 |
| `merchant_id` | `VARCHAR(128)` | 与 NewCar / 外部系统商户标识兼容 |
| `tenant_id` | `VARCHAR(128)` | 9100 统一知识库 scope 需要 |
| `account_open_id` | `VARCHAR(128)` | 抖音账号 / 会话隔离字段 |
| `conversation_short_id` | `VARCHAR(128)` | 高频会话查询字段 |

字段类型选择要求：

1. 不把所有字段都无脑放大为 `TEXT`。
2. 多租户隔离字段必须类型统一，避免 JOIN / WHERE 隐式转换。
3. JSONB 字段只存结构化查询确实需要的数据；必须保留原始字符串签名语义时继续使用 `TEXT`。
4. 时间统一使用 `TIMESTAMPTZ`，应用层展示再转换时区。

## 9. 索引策略

QPS600 目标下，索引必须围绕高频 WHERE、JOIN、ORDER BY 和软删除过滤设计。P3-C / P3-D 应至少评估以下字段：

1. `merchant_id`
2. `tenant_id`
3. `account_open_id`
4. `conversation_short_id`
5. `status`
6. `deleted_at`
7. `created_at`
8. `updated_at`

`knowledge_categories` 建议组合索引：

```text
merchant_id + scope_type + status + deleted_at + sort_order
```

如 PostgreSQL schema 保留 `is_base` 或系统分类逻辑，也需要补充支撑 base 分类查询的索引。

`leads` / `tasks` / `logs` 后续需要组合索引：

1. `douyin_leads`: `merchant_id + status + created_at`
2. `douyin_leads`: `merchant_id + conversation_short_id`
3. `douyin_leads`: `merchant_id + account_open_id + source_id`
4. `lead_notifications`: `merchant_id + lead_id + send_status`
5. `wechat_tasks`: `merchant_id + task_type + status + created_at`
6. `douyin_webhook_events`: `event_key` 唯一约束，另加 `merchant_id + created_at`
7. AI 回复日志：`merchant_id + created_at`、`merchant_id + conversation_short_id`

索引注意事项：

1. 首批不要为每个字段单独建索引。
2. 高频列表查询优先用组合索引覆盖过滤和排序。
3. `deleted_at IS NULL` 可考虑 partial index。
4. QPS600 是否达标必须用压测和慢查询验证，不能只靠索引清单判断。

## 10. 事务、幂等和回滚

### 10.1 migration 前置流程

生产 migration 必须按以下顺序：

1. `backup`：备份 SQLite 文件、PostgreSQL volume 快照或 dump、关键配置。
2. `status`：确认当前 Alembic revision、待执行 revision、目标 database。
3. `dry-run`：输出计划，不写库。
4. `apply`：执行 Alembic upgrade。
5. `verify`：验证表、列、索引、约束、行数和抽样数据。
6. `rollback plan`：明确失败后代码和数据如何回退。

### 10.2 数据迁移幂等

SQLite -> PostgreSQL 数据迁移脚本必须幂等：

1. 重复执行不应重复插入业务数据。
2. 依赖唯一约束或 staging 表记录迁移批次。
3. 每批迁移记录 source row id / source hash / target id。
4. verify 阶段校验行数、hash、关键字段和软删除状态。

### 10.3 关键唯一约束

后续 PostgreSQL 应考虑：

```text
UNIQUE(training_id, answer_hash)
```

或：

```text
UNIQUE(source_type, source_id, answer_hash)
```

webhook 事件幂等必须保留：

```text
UNIQUE(event_key)
```

外部商户绑定必须保留 active 用户唯一语义，避免同一个 NewCar 用户绑定到多个 active merchant 上下文。

### 10.4 Milvus upsert 与 PostgreSQL 状态一致性

RAG 训练链路建议拆成可恢复状态：

1. PostgreSQL 记录 document / chunk metadata 为 pending。
2. 执行 Milvus upsert。
3. upsert 成功后回写 completed。
4. upsert 失败后回写 failed，并保留 retry 所需字段。
5. 禁用或删除文档时同步 Milvus status 或删除向量；失败时保留 cleanup pending 状态。

不建议用一个长数据库事务包住外部 Milvus 调用。更稳妥的是 metadata 状态机 + 幂等重试。

## 11. 宝塔部署策略

宝塔生产切换不得直接全量切库。推荐顺序：

1. 先启动 PostgreSQL Docker Compose 容器。
2. 初始化两个 database：`auto_wechat` 和 `xg_douyin_ai_cs`。
3. 检查 volume、初始化脚本和 database 是否为预期状态。
4. 对两个 database 分别执行 Alembic migration。
5. 执行 SQLite -> PostgreSQL 数据迁移脚本。
6. 只灰度切换试点接口，例如 `GET /knowledge-categories`。
7. 对照 SQLite / PostgreSQL 响应、日志、延迟和错误率。
8. 验证后再扩大到低风险读接口。
9. 写接口、发送链路、自动回复 gate 必须最后分批切换。
10. 出现异常时先关闭试点开关，回到 SQLite 默认路径，再分析数据差异。

禁止：

1. 不允许直接全量切库。
2. 不允许在未完成 Alembic schema 和数据 verify 前切生产流量。
3. 不允许把 P2-F5 smoke 表当成正式 schema。
4. 不允许在同一轮同时做 schema、数据迁移、业务流量切换和删除 SQLite 回退路径。

## 12. 风险清单

| 风险 | 说明 | 应对 |
|---|---|---|
| SQLite 与 PostgreSQL SQL 方言差异 | `INSERT OR IGNORE`、`PRAGMA`、`AUTOINCREMENT`、`rowid` 不能直接迁移 | 收口到 repository / migration，PostgreSQL 用明确约束和 `ON CONFLICT` |
| JSONB 差异 | SQLite JSON 多为 `TEXT`，PostgreSQL `JSONB` 会校验结构 | 迁移前校验 JSON 格式，坏数据进入异常清单 |
| BOOLEAN 差异 | SQLite 0/1 与 PostgreSQL `BOOLEAN` 行为不同 | 迁移时显式转换，应用层不再依赖 0/1 |
| TIMESTAMPTZ 差异 | SQLite timestamp 可能是字符串或整数 | 明确秒 / 毫秒 / 时区转换规则 |
| 同步 DB 调用阻塞 FastAPI | QPS600 下同步调用会放大延迟 | 高频路径走 asyncpg 或 SQLAlchemy async engine |
| 连接池配置不当 | pool 太小会排队，太大压垮 PostgreSQL | `DB_POOL_SIZE` 等参数压测后确定 |
| 索引缺失 | 高频列表、会话、任务查询可能慢 | P3 schema 带核心索引，P4 做慢查询和压测 |
| Milvus 与 PostgreSQL metadata 不一致 | 向量存在但 metadata inactive，或反过来 | 状态机、verify、重试和一致性检查 |
| 迁移脚本重复执行风险 | 数据重复、状态覆盖、hash 不一致 | 幂等约束、批次记录、dry-run 和 verify |
| 宝塔 volume / init SQL 旧数据问题 | 已存在 volume 时 init 脚本不会自动重跑 | 部署前检查 database 列表和 revision 状态 |
| 误迁移 database | 一个容器两个 database，URL 配错会迁错库 | 两套 Alembic 环境分别校验 database name |
| 误触发发送链路 | 高风险表提前切换可能影响抖音 / 微信发送 | 首批避开发送链路，开关灰度，只读先行 |

## 13. 本轮边界确认

本轮只新增方案文档和同步现有文档：

```text
docs/ai/03_data_and_migration/ALEMBIC_POSTGRESQL_MIGRATION_DESIGN.md
docs/ai/03_data_and_migration/POSTGRESQL_MIGRATION_NOTES.md
docs/ai/05_PROJECT_CONTEXT.md
```

本轮不执行：

1. 不安装 Alembic。
2. 不新增 `alembic.ini`、`env.py` 或 `versions/`。
3. 不创建 PostgreSQL 表。
4. 不连接 PostgreSQL。
5. 不跑迁移。
6. 不改业务代码。
7. 不改 docker-compose。
8. 不改 `.env` / `.env.example`。
9. 不改 9000 / 9100 运行路径。
10. 不改 Milvus / RAG。
11. 不触发 LLM、抖音发送、私信发送或自动回复 gate。
12. 不写入真实 URI、token、password。
