# PostgreSQL 迁移注意事项

任务：P1-DB-POSTGRESQL-MIGRATION-NOTES-1

范围：本文只记录 auto_wechat 后续从 SQLite 过渡到 PostgreSQL 的注意事项和阶段路线。不修改业务代码，不修改数据库，不执行迁移，不连接 Milvus，不触发 LLM、抖音发送或私信发送。

## 1. 当前数据库现状

### 1.1 9000 SQLite

9000 主服务当前使用 SQLite 作为业务数据库，容器内路径为：

```text
/workspace/data/auto_wechat.db
```

宝塔宿主机挂载路径示例：

```text
/www/wwwroot/XG_AI_System/docker-data/auto_wechat_9000/auto_wechat.db
```

用途包括主服务业务数据、线索、销售、任务、回写、配置、审计类数据等。SQLite 只是开发和过渡数据库，不是最终生产数据库。

### 1.2 9100 SQLite

9100 抖音 AI 客服 / RAG 服务当前使用 SQLite 作为 metadata 数据库，容器内路径为：

```text
/data/xg_douyin_ai_cs.db
```

用途包括知识文档、知识 chunk、训练 run、训练反馈、RAG / AI 客服相关 metadata。该库不等同于 Milvus，仍然承担 metadata 真源或过渡真源职责。

### 1.3 8788 SQLite

car-porject-main 8788 训练端也存在本地 SQLite 过渡库，用于训练页面自身的会话、反馈或转发侧状态。8788 不是 auto_wechat 的最终 metadata 真源，后续正式链路应以 9000 / 9100 的可信接口和数据库为准。

### 1.4 Milvus

Milvus 继续作为向量检索库，用于 embedding / 向量召回。Milvus 不替代 SQLite / PostgreSQL metadata，也不作为文档、训练 run、反馈状态、幂等状态的真源。

需要特别区分：

```text
Milvus 有向量数据 != SQLite 或 PostgreSQL metadata 一定有 active 数据
SQLite 或 PostgreSQL 有 metadata != Milvus 一定已完成 upsert
```

### 1.5 SQLite 定位

SQLite 当前只作为开发过渡库和早期部署过渡库。后续生产数据库目标是 PostgreSQL，业务逻辑不应继续扩散 SQLite 专属写法或依赖 SQLite 细节。

## 2. PostgreSQL 目标架构

已确认采用方案 A：一个 PostgreSQL 实例，两个 database。

### 2.1 database：auto_wechat

用途：

- 9000 主服务使用。
- 存放主业务数据。
- 未来通过 `DATABASE_URL` 连接。

规划示例：

```text
DATABASE_URL=postgresql+asyncpg://...@postgres:5432/auto_wechat
```

### 2.2 database：xg_douyin_ai_cs

用途：

- 9100 RAG / AI 客服 metadata 服务使用。
- 存放知识库、训练、反馈、RAG / AI 客服 metadata。
- 未来通过 `RAG_DATABASE_URL` 连接。

规划示例：

```text
RAG_DATABASE_URL=postgresql+asyncpg://...@postgres:5432/xg_douyin_ai_cs
```

### 2.3 Milvus

Milvus 继续独立存在，只做 embedding / 向量检索，不作为 metadata 真源。未来仍通过以下配置连接：

```text
MILVUS_URI
MILVUS_TOKEN
MILVUS_COLLECTION_NAME
RAG_VECTOR_BACKEND=milvus
```

### 2.4 暂不采用的方案

暂不采用一个 database 多 schema：

- 迁移脚本、权限边界、备份恢复和问题定位更复杂。
- 当前 9000 与 9100 已是相对独立服务，两个 database 更清晰。

不采用 9000 / 9100 共库共表：

- 服务边界过于混乱。
- RAG metadata 与主业务数据的生命周期、迁移节奏、访问模式不同。
- 后续排障、权限、备份、回滚都会放大风险。

## 3. SQLite 到 PostgreSQL 类型映射

| SQLite 当前常见类型 / 用法 | PostgreSQL 建议 | 说明 |
|---|---|---|
| `INTEGER` 0/1 | `BOOLEAN` | 不继续依赖 0/1 隐式布尔语义 |
| `TEXT metadata_json` | `JSONB` | 便于校验、查询和索引 |
| `TEXT timestamp` | `TIMESTAMPTZ` | 统一使用带时区时间 |
| `INTEGER timestamp` | `TIMESTAMPTZ` | 迁移时显式转换秒 / 毫秒时间戳 |
| `INTEGER PRIMARY KEY` | `BIGSERIAL` 或 `UUID` | 按表语义选择；外部引用多的表优先稳定 ID |
| `answer_hash` | `VARCHAR(64)` | 哈希长度固定时不使用无限 `TEXT` |
| `training_id` | `VARCHAR(64)` | 训练链路幂等标识 |
| `ingestion_status` | `VARCHAR(32)` | 反馈自动入库状态 |
| `raw_data` / `raw_body` | `JSONB` 或 `TEXT` | 原始字符串必须保留原文时用 `TEXT`；结构化查询用 `JSONB` |
| `created_at` / `updated_at` | `TIMESTAMPTZ` | 默认值建议由数据库或统一 repository 生成 |

## 4. 禁止继续扩散的 SQLite 专属写法

后续新增代码应避免继续扩大以下写法：

1. 在业务逻辑中使用 `PRAGMA table_info` 判断字段。
2. 使用 `INSERT OR REPLACE` 表达更新语义。
3. 使用 `INSERT OR IGNORE` 表达幂等语义。
4. 依赖 `rowid`。
5. 强依赖 `AUTOINCREMENT` 行为。
6. 在业务 service 中直接 `sqlite3.connect`。
7. 依赖 SQLite 布尔 0/1 隐式语义。
8. 依赖 SQLite JSON 只是 `TEXT` 的行为。
9. 用 SQLite active count 直接决定是否跳过 Milvus RAG。
10. 在 service 层拼接 SQLite 专属分页、upsert 或 schema introspection 语句。

PostgreSQL 目标下，幂等建议使用明确唯一约束和 `ON CONFLICT (...) DO ...`，并封装在 repository 或 migration 层，不泄漏到业务 service。

## 5. 推荐代码分层

后续新增数据库访问应尽量遵守：

1. `config`：只负责读取 `DATABASE_URL` / `RAG_DATABASE_URL` 等配置。
2. `database`：连接工厂、会话生命周期、连接池配置。
3. `repository`：SQL 访问、upsert、分页、事务边界。
4. `service`：业务流程，不关心 SQLite / PostgreSQL 差异。
5. `migration`：独立管理结构变更、数据修复和回滚说明。

原则：

- service 不直接连接 SQLite 或 PostgreSQL。
- service 不直接判断数据库方言。
- metadata 判断是否可靠，应由 repository 或专门的状态服务提供明确结果。

## 6. 迁移工具建议

SQLite 过渡期继续保留当前 `migrate_sqlite.py`，用于现有开发库和过渡部署库。

PostgreSQL 推荐后续引入 Alembic 或独立 PostgreSQL migration runner。不要让一个脚本长期同时兼容 SQLite 和 PostgreSQL，否则会把方言差异扩散到迁移和业务两侧。

生产迁移必须包含：

1. `backup`：迁移前备份 SQLite、PostgreSQL 和必要的 Milvus collection 状态说明。
2. `status`：展示当前迁移版本和待执行版本。
3. `dry-run`：展示计划执行 SQL / 数据搬迁计划，不写入。
4. `apply`：执行迁移。
5. `verify`：验证行数、关键索引、幂等约束、训练状态、RAG 检索状态。
6. `rollback plan`：明确失败后恢复数据库和代码版本的步骤。

## 7. Milvus 与 PostgreSQL 一致性规则

PostgreSQL 是 metadata 真源。Milvus 是检索副本。

以下字段在 PostgreSQL 与 Milvus 中必须保持一致：

1. `document_id`
2. `chunk_id`
3. `tenant_id`
4. `merchant_id`
5. `douyin_account_id`
6. `category_key`
7. `status` / `is_active`
8. `source_type`
9. `content_hash`
10. `updated_at`

一致性要求：

1. 删除或禁用文档时，要同步 Milvus `status` 或删除向量。
2. 训练 / upsert 成功后，要回写 PostgreSQL 状态。
3. Milvus upsert 失败时，不应把训练 run 标记为 completed。
4. Milvus delete 失败时，要保留可重试状态或明确 `cleanup_verified=false` 语义。
5. `ask` 不能因为本地 SQLite / PostgreSQL active count 不可靠就跳过 Milvus 检索。
6. 只有 metadata 判断来源可靠时，才允许空库快速 skip。

## 8. 幂等和事务要求

### 8.1 feedback 自动入库

反馈自动入库涉及：

1. 训练反馈记录。
2. `training_id + answer_hash` 幂等判断。
3. 文档创建或复用。
4. chunk 创建或复用。
5. Milvus upsert。
6. `ingestion_status`、`ingested_document_id`、`ingestion_training_run_id` 回写。
7. 失败后的可恢复状态。

### 8.2 推荐唯一约束

未来 PostgreSQL 应考虑以下唯一约束之一：

```text
UNIQUE(training_id, answer_hash)
```

或：

```text
UNIQUE(source_type, source_id, answer_hash)
```

选择原则：

- 如果一个训练会话内同一回答只允许入库一次，优先 `UNIQUE(training_id, answer_hash)`。
- 如果跨会话也要按来源对象去重，优先 `UNIQUE(source_type, source_id, answer_hash)`。

### 8.3 事务边界

推荐把 PostgreSQL metadata 写入放在明确事务中：

1. 先创建 / 复用文档和 chunk metadata。
2. 再执行 Milvus upsert。
3. Milvus 成功后回写训练 run completed。
4. Milvus 失败时回写 failed，并保留重试所需 metadata。

是否把 Milvus 调用放在数据库事务内，需要后续单独设计。一般不建议长事务等待外部向量库；更稳妥的方式是 metadata 记录 pending / running / completed / failed 状态，并支持重试。

## 9. 环境变量规划

未来建议规划：

```text
DATABASE_URL=postgresql+asyncpg://...@postgres:5432/auto_wechat
RAG_DATABASE_URL=postgresql+asyncpg://...@postgres:5432/xg_douyin_ai_cs
MILVUS_URI=
MILVUS_TOKEN=
MILVUS_COLLECTION_NAME=
RAG_VECTOR_BACKEND=milvus
```

安全要求：

- 文档、测试、提交信息不得写入真实 URI、token、password。
- `.env.example` 只能放占位符或空值。
- 9000 不需要直接持有 Milvus 凭据，Milvus 属于 9100 RAG 服务连接范围。

## 10. 分阶段路线

### P0：保持当前 SQLite + Milvus 链路可用

继续保证 9000 / 9100 当前 SQLite 过渡链路和 Milvus 检索链路可用。已有线上问题先按最小修复处理，不在此阶段强行迁移数据库。

### P1：文档化 PostgreSQL 迁移规范

固化本文档，明确一个 PostgreSQL 实例、两个 database 的目标方案，以及 SQLite 专属写法的停止扩散规则。

### P1：新增代码避免 SQLite 专属写法继续扩散

新增功能尽量通过 repository / database abstraction 访问数据，不在 service 中新增 `sqlite3.connect`、`PRAGMA` 或 `INSERT OR ...`。

### P2：引入 DATABASE_URL / RAG_DATABASE_URL 抽象

分别为 9000 和 9100 引入数据库连接配置抽象：

- 9000 使用 `DATABASE_URL`。
- 9100 使用 `RAG_DATABASE_URL`。

P2-A-DB-DATABASE-URL-CONFIG-ABSTRACTION-1 已完成第一步抽象：

1. 9000 `app/config.py` 已支持读取 `DATABASE_URL`；未配置时仍回落到当前 SQLite 默认路径。
2. 9100 `apps/xg_douyin_ai_cs/config.py` 已支持读取 `RAG_DATABASE_URL`；未配置时仍回落到现有 SQLite 路径，并兼容 `XG_DOUYIN_AI_CS_DB_PATH`。
3. 新增轻量 URL 解析工具，只识别 `sqlite` / `postgresql` 类型并提供脱敏展示，不连接 PostgreSQL。
4. PostgreSQL 是未来 Docker Compose 容器服务，不是外部托管数据库。
5. 本轮不启用 PostgreSQL、不创建连接池、不改业务 SQL、不引入 Alembic、不改迁移脚本。

后续 P2-B / P2-C 再实现 database factory、异步连接池和 repository 收口。高并发 FastAPI 请求链路建议优先使用 asyncpg 或 SQLAlchemy async engine，并预留：

```text
DB_POOL_SIZE
DB_MAX_OVERFLOW
DB_POOL_TIMEOUT
RAG_DB_POOL_SIZE
RAG_DB_MAX_OVERFLOW
RAG_DB_POOL_TIMEOUT
```

### P2：增加 PostgreSQL docker-compose dev profile

提供开发环境 PostgreSQL profile，用于本地验证连接、迁移、基础读写和回滚，不影响当前默认 SQLite 开发路径。

### P3：引入 Alembic / PostgreSQL migration

为 PostgreSQL 正式引入 Alembic 或独立 migration runner，建立版本表、status、dry-run、apply、verify 和 rollback plan。

### P3：SQLite -> PostgreSQL 数据迁移脚本

编写一次性数据迁移脚本，完成 9000 主库和 9100 RAG metadata 库的历史数据搬迁、类型转换、唯一约束校验和抽样验证。

### P4：生产切换与回滚预案

生产切换前必须完成：

1. 备份 SQLite。
2. 初始化 PostgreSQL。
3. 执行迁移。
4. 验证 9000 主业务读写。
5. 验证 9100 RAG metadata 读写。
6. 验证 Milvus 与 PostgreSQL metadata 一致性。
7. 准备代码回滚和数据库回滚预案。

## 11. 近期问题沉淀

近期宝塔环境出现过以下问题：

1. `/knowledge-training/search-preview` 能命中 Milvus。
2. `/knowledge-training/ask` 曾因 SQLite active count 为 0 跳过 RAG。
3. 结果表现为 `used_knowledge_base=false`。
4. 根因是 `ask` 把 SQLite active count 当成是否执行 Milvus 检索的可靠依据。
5. 修复原则：Milvus 模式下不能用 SQLite count=0 作为跳过 RAG 的依据。

这个案例是后续 PostgreSQL + Milvus 一致性设计的警示：

- PostgreSQL / SQLite metadata 与 Milvus 向量副本可能短暂不一致。
- 只有 metadata 判断来源可靠时，才能做空库快速 skip。
- Milvus backend 下，检索路径不能被不可靠的本地 metadata count 提前截断。
- 训练、删除、禁用、重训必须有可观测状态和可重试路径。

## 12. 本轮未改内容

本轮仅新增本文档：

```text
docs/ai/03_data_and_migration/POSTGRESQL_MIGRATION_NOTES.md
```

未执行：

1. 未修改业务代码。
2. 未修改数据库。
3. 未运行迁移。
4. 未连接 Milvus。
5. 未触发 LLM。
6. 未触发抖音发送。
7. 未触发私信发送。
8. 未修改 docker-compose。
9. 未修改 `.env` 或 `.env.example`。
10. 未写入真实 URI、token、password。

## 13. P2-A 数据库 URL 配置抽象补充

任务：`P2-A-DB-DATABASE-URL-CONFIG-ABSTRACTION-1`

本轮已完成：

1. 9000 新增 `DATABASE_URL` 配置读取；未设置时保持当前 SQLite 默认运行路径不变。
2. 9100 新增 `RAG_DATABASE_URL` 配置读取；未设置时保持当前 SQLite 默认运行路径不变，并继续兼容 `XG_DOUYIN_AI_CS_DB_PATH`。
3. 新增数据库 URL 解析工具，支持识别 `sqlite:///relative/path`、`sqlite:////absolute/path`、`postgresql://`、`postgresql+psycopg://`、`postgresql+asyncpg://`。
4. PostgreSQL URL 仅做识别和脱敏展示，不连接数据库，不打印 password。
5. `.env.example` 只补充 SQLite 占位示例，不写入真实 URI、token 或 password。

本轮未执行：

1. 未启用 PostgreSQL。
2. 未新增 PostgreSQL Docker Compose 服务或 profile。
3. 未创建连接池。
4. 未引入 Alembic。
5. 未改业务 SQL。
6. 未改 Milvus upsert / search 逻辑。

后续建议：

1. P2-B / P2-C：建立 database factory、异步连接池配置和 repository 分层收口。
2. P2-D：增加 PostgreSQL docker-compose dev profile，一个 PostgreSQL 容器实例内创建 `auto_wechat` 与 `xg_douyin_ai_cs` 两个 database。

## 14. P2-B 9000 database factory 补充

任务：`P2-B-DB-9000-DATABASE-FACTORY-1`

本轮已完成 9000 主服务的最小 database factory / runtime 抽象：

1. `app/database.py` 继续作为 9000 唯一中心数据库入口，不新增重复职责文件。
2. 对外兼容保留 `engine`、`SessionLocal`、`Base`、`get_db`。
3. 新增 `get_database_runtime()`，从 `DATABASE_URL` 识别 backend，并返回脱敏 URL。
4. 新增 `get_sqlite_path()`，用于 SQLite URL 文件路径解析。
5. 新增 `create_database_engine()`，统一创建 SQLAlchemy engine。
6. SQLite backend 默认行为保持不变，继续使用当前 SQLite 路径和现有连接参数。
7. PostgreSQL backend 本轮只识别、不连接；尝试创建 engine 会明确报“已识别但未启用”。

本轮未执行：

1. 未启用 PostgreSQL。
2. 未新增 PostgreSQL Docker Compose 服务或 profile。
3. 未创建 async pool。
4. 未改业务 SQL。
5. 未改表结构。
6. 未跑迁移。
7. 未改 9100。

并发与后续连接池约束：

1. 后续 PostgreSQL 推荐使用 asyncpg 或 SQLAlchemy async engine。
2. 后续任务再引入 FastAPI startup 初始化连接池、shutdown 关闭连接池。
3. 连接池配置方向继续预留 `DB_POOL_SIZE`、`DB_MAX_OVERFLOW`、`DB_POOL_TIMEOUT`。
4. 本轮没有在 async FastAPI 请求链路中新增阻塞式数据库访问。

SQLite 守门说明：

本轮没有新增 `sqlite3.connect`，因此不需要新增 SQLite guard allowlist。`app/database.py` 是 9000 数据库兼容入口，但当前仍通过 SQLAlchemy `create_engine` 维持旧行为。
## 15. P2-C 9100 database factory 补充

任务：`P2-C-DB-9100-DATABASE-FACTORY-1`

本轮已完成 9100 `xg_douyin_ai_cs` 的最小 database factory / runtime 抽象：

1. `apps/xg_douyin_ai_cs/rag/database.py` 继续作为 9100 RAG metadata 的中心数据库入口。
2. 对外兼容保留 `database_path()`、`connect()`、`init_db()` 行为，现有 repository / service 调用不需要改动。
3. 新增 `get_database_runtime()`，从 `RAG_DATABASE_URL` 识别 backend，并返回脱敏 URL。
4. SQLite backend 默认行为保持不变，未配置 `RAG_DATABASE_URL` 时仍使用当前默认 SQLite 路径。
5. `XG_DOUYIN_AI_CS_DB_PATH` 继续兼容，且在未配置 `RAG_DATABASE_URL` 时生效。
6. PostgreSQL backend 本轮只识别、不连接；尝试通过 9100 factory 创建 PostgreSQL metadata 连接会明确报“已识别但未启用”。
7. 9100 后续 PostgreSQL 仍对应 `xg_douyin_ai_cs` database，未来通过 `RAG_DATABASE_URL` 接入。

最终生产目标补充：

1. 宝塔生产部署最终不再使用 SQLite。
2. 9000 / 9100 metadata 最终全部使用 Docker Compose 中的 PostgreSQL 容器。
3. PostgreSQL 仍采用一个容器实例、两个 database：`auto_wechat` 与 `xg_douyin_ai_cs`。
4. 数据库访问最终需要支持 QPS600。
5. 后续必须补齐 async PostgreSQL driver、连接池、事务边界、索引设计和压测验证。
6. 本轮 P2-C 不启用 PostgreSQL，但 9100 database factory 不得阻碍后续 asyncpg / SQLAlchemy async engine 接入。

本轮未执行：

1. 未启用 PostgreSQL。
2. 未新增 PostgreSQL Docker Compose 服务或 profile。
3. 未创建 async pool。
4. 未改 RAG 检索逻辑。
5. 未改 Milvus upsert / search。
6. 未改业务 SQL。
7. 未改表结构。
8. 未跑迁移。
9. 未改 9000。

并发与后续连接池约束：

1. 后续 9100 PostgreSQL 推荐使用 asyncpg 或 SQLAlchemy async engine。
2. 后续任务再引入 FastAPI startup 初始化连接池、shutdown 关闭连接池。
3. 连接池配置方向继续预留 `RAG_DB_POOL_SIZE`、`RAG_DB_MAX_OVERFLOW`、`RAG_DB_POOL_TIMEOUT`。
4. 本轮没有在 async FastAPI 请求链路中新增阻塞式数据库访问。

SQLite 守门说明：

`apps/xg_douyin_ai_cs/rag/database.py` 已在 SQLite guard allowlist 中，定位为 9100 SQLite 兼容层。本轮未新增 allowlist，也未把 SQLite 专属写法扩散到 routers / services 高频业务链路。

## 16. P2-D PostgreSQL dev profile 补充

任务：`P2-D-DB-POSTGRES-DEV-PROFILE-1`

本轮新增 PostgreSQL Docker Compose dev profile，仅用于后续本地验证 PostgreSQL 连接、迁移、基础读写和回滚流程，不切换 9000 / 9100 当前运行数据库。

新增内容：

1. `docker-compose.dev.yml` 新增 `postgres` service，使用 `postgres:16-alpine`。
2. `postgres` service 放入 `profiles: ["postgres"]`，默认 `docker compose -f docker-compose.dev.yml up -d` 不会强制启动 PostgreSQL。
3. 使用 named volume `postgres_data` 持久化 PostgreSQL 数据。
4. 新增 healthcheck：`pg_isready` 检查 `postgres` 默认库。
5. 新增初始化脚本 `docker/postgres/init/001_create_databases.sql`。
6. 初始化两个 database：
   - `auto_wechat`：未来给 9000 主服务使用，对应 `DATABASE_URL`。
   - `xg_douyin_ai_cs`：未来给 9100 RAG metadata 使用，对应 `RAG_DATABASE_URL`。

启动方式示例：

```bash
docker compose -f docker-compose.dev.yml --profile postgres up -d postgres
```

开发占位连接示例：

```text
DATABASE_URL=postgresql+asyncpg://auto_wechat:change_me@postgres:5432/auto_wechat
RAG_DATABASE_URL=postgresql+asyncpg://xg_douyin_ai_cs:change_me@postgres:5432/xg_douyin_ai_cs
```

边界确认：

1. 默认仍使用 SQLite。
2. 本轮不把 9000 切换到 PostgreSQL。
3. 本轮不把 9100 切换到 PostgreSQL。
4. 本轮不创建业务表、不改表结构、不跑 SQLite -> PostgreSQL 数据迁移。
5. 本轮不引入 Alembic。
6. 本轮不改 Milvus upsert / search。
7. 后续 P2-E / P3 再处理 async pool、Alembic、表结构迁移和生产切换。

## 17. P2-E async pool 并发配置补充

任务：`P2-E-DB-ASYNC-POOL-QPS600-CONCURRENCY-CONFIG-1`

本轮为后续 PostgreSQL + asyncpg / SQLAlchemy async engine + QPS600 做配置预留，但仍不创建真实连接池、不连接 PostgreSQL、不切换 9000 / 9100 当前 SQLite 运行路径。

新增配置项：

```text
9000:
  DB_POOL_SIZE=20
  DB_MAX_OVERFLOW=40
  DB_POOL_TIMEOUT=30
  DB_POOL_RECYCLE=1800
  DB_STATEMENT_TIMEOUT_MS=5000

9100:
  RAG_DB_POOL_SIZE=20
  RAG_DB_MAX_OVERFLOW=40
  RAG_DB_POOL_TIMEOUT=30
  RAG_DB_POOL_RECYCLE=1800
  RAG_DB_STATEMENT_TIMEOUT_MS=5000
```

边界确认：

1. 默认值只适合开发和占位说明，不代表最终生产值。
2. QPS600 不能只靠默认配置保证，必须通过压测、慢查询分析、索引设计、事务边界和后台队列一起验证。
3. 后续 PostgreSQL pool 必须在 FastAPI startup 初始化，在 shutdown 关闭。
4. 禁止每个请求创建 engine / pool。
5. 高频 async 请求链路不应继续扩散阻塞式数据库调用。
6. 本轮未改业务 SQL，未引入 Alembic，未连接 PostgreSQL，未改 Milvus。
7. RAG / LLM / Milvus / 抖音发送不得阻塞主请求链路；需要耗时处理时应走后续后台队列或异步编排设计。

## 18. P3-A Alembic / PostgreSQL migration 方案设计补充

任务：`P3-A-DB-ALEMBIC-POSTGRESQL-MIGRATION-DESIGN-1`

当前已新增 PostgreSQL Alembic migration 方案设计文档：

```text
docs/ai/03_data_and_migration/ALEMBIC_POSTGRESQL_MIGRATION_DESIGN.md
```

本阶段只做设计，不引入 Alembic，不创建 `alembic.ini` / `env.py` / `versions`，不连接 PostgreSQL，不跑迁移，不切换 9000 / 9100 当前运行路径。

方案结论：

1. PostgreSQL 仍采用一个 Docker Compose 容器实例、两个 database：`auto_wechat` 与 `xg_douyin_ai_cs`。
2. 9000 与 9100 应使用两个独立 Alembic migration 环境：
   - `migrations/postgres/auto_wechat/`
   - `migrations/postgres/xg_douyin_ai_cs/`
3. 两个环境分别维护自己的 `alembic_version` 表，分别读取 `DATABASE_URL` 与 `RAG_DATABASE_URL`。
4. 不共用一个 migration 环境，避免服务边界、database、发布节奏和误迁移风险混在一起。
5. Milvus 不参与 Alembic migration；Milvus 仍只是向量检索副本，不是 metadata 真源。

后续路线：

1. P3-B：创建 Alembic skeleton，但不建业务表。
2. P3-C：建立 9000 PostgreSQL 初始 schema。
3. P3-D：建立 9100 PostgreSQL 初始 schema。
4. P3-E：编写 SQLite -> PostgreSQL 数据迁移脚本。
5. P3-F：继续围绕 `GET /knowledge-categories` 做试点接口 PG 对照。
6. P3-G：宝塔灰度切换。
7. P3-H：关闭 SQLite 生产路径。

## 19. P3-B Alembic skeleton 补充

任务：`P3-B-DB-ALEMBIC-SKELETON-NO-BUSINESS-TABLES-1`

当前已为 PostgreSQL migration 建立两个独立 Alembic skeleton：

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

边界确认：

1. `auto_wechat` 环境读取 `DATABASE_URL`。
2. `xg_douyin_ai_cs` 环境读取 `RAG_DATABASE_URL`。
3. 两个 `0001_empty_baseline.py` 都是空 migration，`upgrade()` / `downgrade()` 不创建业务表、不创建 index。
4. `env.py` 遇到 SQLite URL 会拒绝执行，避免误迁移。
5. 本轮只引入 Alembic 依赖和骨架，不执行 migration，不连接 PostgreSQL。
6. P3-C 才开始 9000 PostgreSQL 初始 schema。
7. P3-D 才开始 9100 PostgreSQL 初始 schema。

未来命令示例：

```bash
python -m alembic -c migrations/postgres/auto_wechat/alembic.ini current
python -m alembic -c migrations/postgres/auto_wechat/alembic.ini upgrade head

python -m alembic -c migrations/postgres/xg_douyin_ai_cs/alembic.ini current
python -m alembic -c migrations/postgres/xg_douyin_ai_cs/alembic.ini upgrade head
```

## 20. P3-C 9000 knowledge_categories schema 补充

任务：`P3-C-DB-9000-POSTGRES-KNOWLEDGE-CATEGORIES-SCHEMA-1`

当前已在 `auto_wechat` Alembic 环境新增第一张正式 PostgreSQL 业务表 revision：

```text
migrations/postgres/auto_wechat/versions/0002_create_knowledge_categories.py
```

本轮只处理 9000 `knowledge_categories`：

1. 创建 `knowledge_categories` 表。
2. 使用 `BIGSERIAL` 语义的 `BIGINT` 自增主键。
3. 时间字段使用 `TIMESTAMPTZ`。
4. 保留当前代码依赖的 `category_key` 字段。
5. 同时保留任务和 smoke 对照中的 `"key"` 字段，并用 check constraint 保持 `"key" = category_key`。
6. 增加支撑 `GET /knowledge-categories` 的组合索引：`merchant_id + scope_type + status + deleted_at + sort_order`。
7. 增加同 scope / merchant / key 的唯一约束，base 分类当前仍由服务层虚拟补充，不强制主表落 system 行。

边界确认：

1. 本轮未切换 9000 到 PostgreSQL。
2. 本轮未迁移真实 SQLite 数据。
3. 本轮未连接 PostgreSQL，未执行 `alembic upgrade`。
4. 本轮未修改 9100 Alembic 环境、Milvus、RAG、业务接口逻辑或 docker-compose。
5. P3-C 后续可以单独做 dev postgres migration smoke，但必须另起受控任务。
6. QPS600 仍需后续索引验证、慢查询分析和压测确认。

## 21. P3-C2 auto_wechat knowledge_categories migration smoke 补充

任务：`P3-C2-DB-9000-KNOWLEDGE-CATEGORIES-PG-MIGRATION-SMOKE-1`

当前已新增 dev PostgreSQL migration smoke 脚本：

```text
scripts/smoke_auto_wechat_alembic_knowledge_categories.py
```

脚本能力：

1. 只验证 `auto_wechat` database。
2. 读取 `SMOKE_DATABASE_URL` 或 `DATABASE_URL`，拒绝 SQLite URL。
3. 执行 `migrations/postgres/auto_wechat/alembic.ini` 的 `upgrade head`。
4. 验证 `alembic_version` 已到 `0002_create_knowledge_categories`。
5. 验证 `knowledge_categories` 表存在。
6. 验证关键字段、`idx_knowledge_categories_visible_lookup`、`idx_knowledge_categories_merchant_category_status`、`uk_knowledge_categories_scope_merchant_key` 和 `ck_knowledge_categories_key_matches_category_key` 存在。
7. 输出 `SMOKE_PASS` 或清晰失败原因。
8. 输出 URL 时只展示脱敏值。

P3-C2-FIX 已修复唯一约束检查误判：smoke 优先读取 `pg_constraint`，要求
`uk_knowledge_categories_scope_merchant_key` 的 `contype='u'`，并输出
`pg_get_constraintdef(oid)`。如果约束缺失，失败信息会同时展示实际
`pg_constraint` 和 `pg_indexes` 结果，便于区分 migration 问题与 inspector
兼容问题。

`auto_wechat` Alembic `env.py` 已支持 `postgresql+asyncpg` 在线迁移分支，用于 dev smoke；该能力仍只属于 migration 环境，不代表 9000 默认运行路径切换到 PostgreSQL。

运行示例：

```bash
docker compose -f docker-compose.dev.yml --profile postgres up -d postgres
python scripts/smoke_auto_wechat_alembic_knowledge_categories.py
docker compose -f docker-compose.dev.yml stop postgres
```

边界确认：

1. 默认运行仍是 SQLite。
2. 本轮不切换 9000。
3. 本轮不迁移真实业务数据。
4. 本轮不插入真实业务数据。
5. 本轮不改业务接口、不改 9100、不改 Milvus / RAG。
6. P3-C3 / P3 后续才处理正式数据迁移、更多表和生产灰度切换。

## 22. P3-C3 knowledge_categories 数据迁移设计补充

任务：`P3-C3-DB-9000-KNOWLEDGE-CATEGORIES-DATA-MIGRATION-DESIGN-1`

当前已新增文档：

```text
docs/ai/03_data_and_migration/KNOWLEDGE_CATEGORIES_SQLITE_TO_POSTGRES_MIGRATION_DESIGN.md
```

本阶段只做 9000 `knowledge_categories` SQLite -> PostgreSQL 数据迁移设计，不实现脚本、不连接 PostgreSQL、不读取真实 SQLite、不迁移真实数据。

核心设计：

1. 只迁移 `knowledge_categories`，不迁移其它 9000 表。
2. 不迁移 9100，不迁移 Milvus。
3. SQLite 源为当前 `auto_wechat.db` 中的 `knowledge_categories`；未来脚本必须通过 `--sqlite-db-path` 或现有配置获取路径，不硬编码宝塔路径。
4. PostgreSQL 目标为 `auto_wechat` database 中 Alembic revision `0002_create_knowledge_categories` 或更高的 `knowledge_categories` 表。
5. SQLite 当前字段以 `category_key` 为稳定标识；PostgreSQL 目标同时写 `"key"` 和 `category_key`，并保证 `key = category_key`。
6. 当前 base 分类仍是服务层虚拟分类，最小迁移不额外插入 base system 行；如 SQLite 中已有真实 base 行，则保留并迁移。
7. 幂等 upsert 使用唯一约束 `scope_type + merchant_id + key`，推荐 `ON CONFLICT (scope_type, merchant_id, key) DO UPDATE`。
8. 未来脚本必须默认 `--dry-run`，输出 insert / update / skip / 异常统计；只有显式 `--apply` 或 `--yes` 才允许真实写入。
9. 迁移验证必须覆盖行数、`merchant_id + category_key`、`deleted_at/status`、`sort_order`、`GET /knowledge-categories` SQLite / PostgreSQL 响应语义一致性。

后续拆分：

1. P3-C4：实现 dry-run-only 迁移脚本骨架。
2. P3-C5：实现 dev PG apply smoke。
3. P3-C6：接入 `GET /knowledge-categories` PG 数据对照。
4. P3-C7：宝塔 staging / 灰度迁移预案。

边界确认：

1. 默认运行仍是 SQLite。
2. 本轮不实现迁移脚本。
3. 本轮不连接 PostgreSQL。
4. 本轮不读取真实 SQLite。
5. 本轮不迁移真实业务数据。
6. 本轮不改业务接口、不改 Alembic revision、不改 9100、不改 Milvus / RAG。

## 23. P3-C4 knowledge_categories dry-run-only 迁移脚本骨架补充

任务：`P3-C4-DB-9000-KNOWLEDGE-CATEGORIES-MIGRATION-DRY-RUN-SKELETON-1`

当前已新增脚本：

```text
scripts/migrate_knowledge_categories_sqlite_to_postgres.py
```

脚本范围：

1. 只覆盖 9000 `knowledge_categories`。
2. 默认 dry-run，不实现 PostgreSQL 写入。
3. 可以读取 SQLite 源库，但必须显式传入 `--sqlite-db-path`，不猜测宝塔路径。
4. 可以通过 `--postgres-url`、`SMOKE_DATABASE_URL` 或 `DATABASE_URL` 连接 PostgreSQL 做只读检查。
5. PostgreSQL URL 输出必须脱敏，不打印 password。
6. PostgreSQL 只读检查仅包含 `alembic_version`、`knowledge_categories` 表存在性和已有唯一键 `scope_type + merchant_id + key`。
7. `--merchant-id` 和 `--limit` 只影响 dry-run 范围，不改变任何数据。
8. `--apply` / `--yes` 当前会明确失败：`apply mode is not implemented in P3-C4`。

字段映射边界：

1. SQLite `category_key` 同时映射到 PostgreSQL `"key"` 与 `category_key`。
2. dry-run 映射阶段校验 `key = category_key`。
3. SQLite `is_base` 0/1 显式转换为 boolean 语义。
4. 缺失 `description` 为 `None`。
5. 缺失 `scope_type` 默认为 `merchant`。
6. 缺失 `status` 默认为 `active`。
7. 缺失 `sort_order` 默认为 `0`，与本轮任务要求一致。
8. 脚本不会主动生成新的 `base` system 行；SQLite 中已有真实 base 行按普通源行进入 dry-run 统计。

当前边界确认：

1. 默认运行仍是 SQLite。
2. 本轮不写 PostgreSQL，不迁移真实业务数据。
3. 本轮不改 Alembic revision，不创建新表或索引。
4. 本轮不改业务代码、不改 docker-compose、不改 `.env` / `.env.example`。
5. 本轮不改 9100 / Milvus / RAG。
6. P3-C5 才实现 dev PG apply smoke；生产迁移仍未开始。

## 24. P3-C5 knowledge_categories 受控 dev apply smoke 补充

任务：`P3-C5-DB-9000-KNOWLEDGE-CATEGORIES-DEV-PG-APPLY-SMOKE-1`

当前已在迁移脚本中增加受控 dev apply 能力：

```text
scripts/migrate_knowledge_categories_sqlite_to_postgres.py
```

安全门：

1. 默认仍为 dry-run，不传 `--apply` 不写 PostgreSQL。
2. apply 必须同时传入 `--apply` 与 `--yes`。
3. apply URL 只能来自 `--postgres-url` 或 `SMOKE_DATABASE_URL`，不能隐式使用 `DATABASE_URL`。
4. apply host 只允许 `localhost`、`127.0.0.1` 或 `postgres`。
5. 目标 database 必须是 `auto_wechat`。
6. schema 检查必须通过：Alembic revision 至少为 `0002_create_knowledge_categories`，且目标表存在。
7. URL 输出继续脱敏，不打印 password。

写入策略：

1. 只写 `knowledge_categories`，不迁移其它表。
2. 使用 `ON CONFLICT (scope_type, merchant_id, "key") DO UPDATE` 做幂等 upsert。
3. `key = category_key`，均来自 SQLite `category_key`。
4. conflict update 不覆盖目标 `created_at`。
5. `status=disabled/deleted` 与非空 `deleted_at` 按源端值保留，不被默认 `active` 复活。
6. 不主动生成 base 行；已有真实 base 行按普通源行处理。

synthetic smoke：

1. 脚本提供 synthetic SQLite 数据 helper，用于创建临时本地 SQLite 测试库。
2. synthetic 数据覆盖 active、disabled、deleted、不同 `sort_order` 和一条显式真实 base 行。
3. 该 smoke 只验证 dev PostgreSQL 闭环，不代表生产迁移。

边界确认：

1. 默认 9000 运行数据库仍是 SQLite。
2. 本轮不迁移真实生产数据。
3. 本轮不切换默认 `DATABASE_URL`。
4. 本轮不改 Alembic revision、不改业务接口、不改 docker-compose。
5. 本轮不改 9100 / Milvus / RAG。
6. 宝塔 staging / 灰度迁移预案留到后续任务。

## 25. P3-C6 knowledge_categories API 对照 smoke 补充

任务：`P3-C6-DB-9000-KNOWLEDGE-CATEGORIES-SQLITE-PG-API-CONTRAST-1`

当前已新增：

```text
scripts/smoke_knowledge_categories_sqlite_pg_api_contrast.py
tests/test_knowledge_categories_sqlite_pg_api_contrast.py
```

smoke 设计：

1. 只覆盖 9000 `GET /knowledge-categories`。
2. 先创建 synthetic SQLite 数据，再通过 P3-C5 迁移脚本 apply 到 dev PostgreSQL。
3. SQLite probe 使用默认同步路径，保持 `KNOWLEDGE_CATEGORIES_ASYNC_PG_ENABLED=false`。
4. PostgreSQL probe 显式开启 PG pilot，并用 `postgresql+asyncpg://` 初始化 async PG runtime。
5. 两侧都通过 FastAPI 路由调用同一个 `GET /knowledge-categories`，不启动前端。
6. 响应归一化后比较 base 虚拟分类、active 分类、disabled/deleted 过滤、商户隔离、排序和公开 schema。
7. mismatch 时输出统一 diff，便于定位 SQLite / PostgreSQL 语义差异。

运行方式：

```bash
docker compose -f docker-compose.dev.yml --profile postgres up -d postgres
$env:SMOKE_DATABASE_URL="postgresql+asyncpg://auto_wechat:change_me@127.0.0.1:5432/auto_wechat"
python scripts/smoke_auto_wechat_alembic_knowledge_categories.py
python scripts/smoke_knowledge_categories_sqlite_pg_api_contrast.py --postgres-url $env:SMOKE_DATABASE_URL
docker compose -f docker-compose.dev.yml stop postgres
```

边界确认：

1. 默认 9000 运行数据库仍是 SQLite。
2. 本轮不切换默认 `DATABASE_URL`。
3. 本轮不把 `KNOWLEDGE_CATEGORIES_ASYNC_PG_ENABLED` 默认改为 true。
4. 本轮不迁移真实生产数据，只使用 synthetic / 本地测试数据。
5. 本轮不改 Alembic revision，不改业务接口契约，不改 docker-compose。
6. 本轮不改 9100 / Milvus / RAG。
7. 下一步才进入宝塔 staging / 灰度迁移预案。

## 26. P3-C7 knowledge_categories 宝塔 staging / 灰度迁移预案补充

任务：`P3-C7-DB-9000-KNOWLEDGE-CATEGORIES-BAOTA-STAGING-GRAY-MIGRATION-PLAN-1`

当前已新增：

```text
docs/ai/03_data_and_migration/KNOWLEDGE_CATEGORIES_BAOTA_STAGING_GRAY_MIGRATION_PLAN.md
```

预案结论：

1. P3-C7 是 Baota staging / gray migration 操作预案，不是执行记录。
2. 目标只覆盖 9000 `knowledge_categories`，不迁移全量 9000，不迁移 9100，不迁移 Milvus。
3. Baota staging dry-run 前必须确认 git commit hash、Docker Compose 状态、9000 健康、SQLite 路径、SQLite backup、PostgreSQL 容器、`auto_wechat` database、Alembic revision、SQLite / PG 行数、PG pilot 开关和默认 `DATABASE_URL`。
4. dry-run 使用 `--dry-run`，必须输出 insert / update / skip / error 计划、字段映射预览、PG schema 状态和 alembic revision，不写 PostgreSQL。
5. staging apply 仅作为后续预案，必须显式 `--apply --yes`，且不允许隐式 `DATABASE_URL` apply。
6. API contrast 必须对比 SQLite 默认路径和 PostgreSQL pilot 路径；mismatch 时立即停止灰度。
7. rollback 默认关闭 `KNOWLEDGE_CATEGORIES_ASYNC_PG_ENABLED`，恢复 SQLite 默认路径；不默认 drop `knowledge_categories` 表。
8. production dry-run、production apply、默认数据库切换都必须进入后续独立审批任务。

边界确认：

1. 本轮只做文档。
2. 不执行宝塔命令。
3. 不连接生产数据库。
4. 不迁移真实数据。
5. 不切换默认数据库。
6. 不改业务代码、迁移脚本、Alembic revision、docker-compose、`.env` 或 `.env.example`。

## 27. P3-C8 Baota staging dry-run 人工 Runbook 补充

任务：`P3-C8-BAOTA-STAGING-DRY-RUN-MANUAL-RUNBOOK-1`

当前已新增：

```text
docs/ai/03_data_and_migration/KNOWLEDGE_CATEGORIES_BAOTA_STAGING_DRY_RUN_RECORD.md
```

Runbook 结论：

1. P3-C8 不由本机 VibeCoding 直接执行宝塔命令。
2. 本机只生成 Baota staging dry-run 人工 Runbook 和执行记录模板。
3. 宝塔执行人需要在宿主机代码目录手动确认 commit hash、工作区、Python 依赖、SQLite 路径、SQLite backup、脱敏 PostgreSQL URL 和 dry-run 输出。
4. dry-run 命令必须显式传入 `--sqlite-db-path` 和 `--postgres-url`，不得依赖隐式 `DATABASE_URL`。
5. P3-C8 只读 dry-run 禁止 `--apply`、`--yes`、Alembic upgrade、重启 9000、切换默认 `DATABASE_URL` 或开启 `KNOWLEDGE_CATEGORIES_ASYNC_PG_ENABLED`。
6. 执行记录必须包含 SQLite 源行数、过滤后行数、PG 表状态、Alembic revision、预计 insert / update / skip / error、异常行摘要和安全确认。
7. 宝塔执行结果必须由人工贴回后再判断是否进入 P3-C9。
8. 人工已贴回 P3-C8 执行结果：dry-run 输出 `DRY_RUN_PASS`，详见第 29 节。

边界确认：

1. 本轮只改文档。
2. 不执行宝塔命令。
3. 不连接 PostgreSQL。
4. 不读取宝塔 SQLite。
5. 不写 PostgreSQL。
6. 不执行 migration。
7. 不迁移真实数据。
8. 不修改业务代码、迁移脚本、Alembic revision、docker-compose、`.env` 或 `.env.example`。

## 28. P3-C8B Baota staging PostgreSQL schema 初始化 Runbook 补充

任务：`P3-C8B-BAOTA-STAGING-POSTGRES-SCHEMA-INIT-MANUAL-RUNBOOK-1`

当前已新增：

```text
docs/ai/03_data_and_migration/KNOWLEDGE_CATEGORIES_BAOTA_STAGING_SCHEMA_INIT_RUNBOOK.md
```

P3-C8 历史 blocked 原因：

1. Baota staging SQLite 已确认路径和备份，且 `knowledge_categories` 表存在。
2. Baota staging SQLite `knowledge_categories_count = 0`。
3. PostgreSQL dev 容器可启动且 healthy，`auto_wechat` database 存在。
4. `auto_wechat` database 当前无表，`alembic_version` 不存在。
5. P3-C8 dry-run 需要只读检查 PostgreSQL schema，因此被 PG schema 未初始化阻塞。

该阻塞已通过 P3-C8B schema 初始化解除，后续 P3-C8 dry-run 已通过，详见第 29 节。

Runbook 目标：

1. 只初始化 PostgreSQL `auto_wechat` schema 到 `0002_create_knowledge_categories`。
2. 只创建 `alembic_version`、`knowledge_categories` 表、索引、唯一约束和 check constraint。
3. 推荐通过一次性 `auto-wechat-api` 容器执行 `migrations/postgres/auto_wechat/alembic.ini`。
4. `migrations/postgres/auto_wechat/env.py` 当前读取临时注入的 `DATABASE_URL`，不使用 `ALEMBIC_DATABASE_URL`。
5. 成功后回到 P3-C8 dry-run；P3-C9 才讨论 staging apply + API contrast。

边界确认：

1. 本轮只做文档。
2. 本轮不执行宝塔命令。
3. 本轮不连接 PostgreSQL。
4. 本轮不读取宝塔 SQLite。
5. 本轮不迁移 SQLite 业务数据。
6. 本轮不切换 9000 默认 `DATABASE_URL`。
7. 本轮不开启 `KNOWLEDGE_CATEGORIES_ASYNC_PG_ENABLED`。
8. 本轮不改业务代码、迁移脚本、Alembic revision、docker-compose、`.env` 或 `.env.example`。
9. 本轮不操作 9100 / Milvus / RAG，不触发 LLM、抖音发送、私信发送或自动回复 gate。

## 29. P3-C8B schema 初始化与 P3-C8 dry-run 执行记录补充

任务：`P3-C8-C8B-BAOTA-STAGING-SCHEMA-INIT-AND-DRY-RUN-EXECUTION-RECORD-1`

本阶段只补充人工执行记录。本机 VibeCoding 不执行宝塔命令，不连接 PostgreSQL，不读取 SQLite，不迁移数据。

### 29.1 P3-C8B schema 初始化结果

人工已在 Baota staging 完成 `auto_wechat` PostgreSQL schema 初始化：

1. PostgreSQL dev 容器 `auto-wechat-postgres-dev` 已启动并 healthy。
2. `auto_wechat` database 存在。
3. 初始化前 `auto_wechat` 库无表、无 `alembic_version`。
4. 使用一次性 `auto-wechat-api` 容器，挂载宿主机代码目录。
5. 使用临时 `DATABASE_URL`，未修改 `.env`。
6. 执行 `alembic -c migrations/postgres/auto_wechat/alembic.ini upgrade 0002_create_knowledge_categories`。
7. 初始化后 `alembic_version = 0002_create_knowledge_categories`。
8. `knowledge_categories` 表存在。
9. `uk_knowledge_categories_scope_merchant_key` UNIQUE 约束存在。
10. `ck_knowledge_categories_key_matches_category_key` CHECK 约束存在。
11. PG `knowledge_categories` 行数为 0。

说明：schema 初始化会写 PostgreSQL schema，但不迁移 SQLite 业务数据，不写 PG 业务数据。

### 29.2 P3-C8 dry-run 结果

人工已完成 `knowledge_categories` SQLite -> PostgreSQL dry-run：

1. SQLite 路径：`docker-data/auto_wechat_9000/auto_wechat.db`。
2. SQLite 备份：`backups/p3_c8/auto_wechat_knowledge_categories_p3_c8_20260708_155855.db`。
3. SQLite `knowledge_categories` 表存在。
4. SQLite 源行数: 0。
5. 过滤后待处理行数: 0。
6. PostgreSQL 目标表存在: True。
7. Alembic revision: `0002_create_knowledge_categories`。
8. Alembic revision 至少为 `0002_create_knowledge_categories`: True。
9. 预计 insert: 0。
10. 预计 update: 0。
11. 预计 skip: 0。
12. 异常行数量: 0。
13. 字段映射预览: `[]`。
14. PostgreSQL 写入: disabled。
15. 最终输出：`DRY_RUN_PASS`。

说明：当前 SQLite 源行数为 0，所以 dry-run insert / update / skip 均为 0；这不代表生产数据迁移已完成。

### 29.3 收尾与边界确认

1. `POSTGRES_URL` 已 unset。
2. PostgreSQL dev 容器已停止。
3. `ps postgres` 无运行容器。
4. 未执行 `--apply` / `--yes`。
5. 未写 PostgreSQL 业务数据。
6. 未迁移 SQLite 数据。
7. 未切换 `DATABASE_URL`。
8. 未开启 `KNOWLEDGE_CATEGORIES_ASYNC_PG_ENABLED`。
9. 未改业务代码、迁移脚本、Alembic revision、docker-compose 或 `.env`。
10. 未操作 9100 / Milvus / RAG。

结论：P3-C8B 已执行通过，P3-C8 已从 blocked 更新为 dry-run passed。可以进入 P3-C9 前的人工审批，但 P3-C9 不应自动执行 production apply，也不应自动迁移真实生产数据。

## 30. P3-C9-PRECHECK knowledge_categories staging apply 必要性判断补充

任务：`P3-C9-PRECHECK-DB-9000-KNOWLEDGE-CATEGORIES-STAGING-APPLY-NECESSITY-1`

当前已新增 P3-C9 apply 前置判断记录：

```text
docs/ai/03_data_and_migration/KNOWLEDGE_CATEGORIES_BAOTA_STAGING_APPLY_PRECHECK.md
```

输入依据：

1. P3-C8B schema 初始化已通过，`alembic_version = 0002_create_knowledge_categories`。
2. `knowledge_categories` 表存在。
3. `uk_knowledge_categories_scope_merchant_key` UNIQUE 约束存在。
4. `ck_knowledge_categories_key_matches_category_key` CHECK 约束存在。
5. PG `knowledge_categories` 行数 = 0。
6. P3-C8 dry-run 已通过，最终输出 `DRY_RUN_PASS`。
7. SQLite 源行数 = 0。
8. 过滤后待处理行数 = 0。
9. dry-run insert/update/skip/error = 0/0/0/0。
10. PostgreSQL 写入: disabled。

建议结论：

```text
P3-C9 staging apply: SKIPPED_NO_SOURCE_ROWS
```

当前 staging 没有 `knowledge_categories` 源业务行需要迁移，执行 `--apply --yes` 不会产生业务价值。为避免无意义写操作和误操作风险，建议跳过 P3-C9 staging apply。

后续触发 apply 的条件：

1. 后续 staging 出现 `knowledge_categories` 源数据。
2. 重新执行 P3-C8 dry-run。
3. dry-run 显示 `insert > 0` 或 `update > 0`。
4. dry-run 显示 `error = 0`。
5. PostgreSQL schema 仍至少为 `0002_create_knowledge_categories`。
6. 人工重新审批 P3-C9 apply。

边界确认：

1. 本轮只做文档。
2. 不执行宝塔命令。
3. 不连接 PostgreSQL。
4. 不读取 SQLite。
5. 不执行 `--apply` / `--yes`。
6. 不写 PostgreSQL 业务数据。
7. 不迁移数据。
8. 不切换 `DATABASE_URL`。
9. 不开启 `KNOWLEDGE_CATEGORIES_ASYNC_PG_ENABLED`。
10. 不改业务代码、迁移脚本、Alembic revision、docker-compose 或 `.env`。

## 31. P3-C10 production dry-run 审批模板补充

任务：`P3-C10-DB-9000-KNOWLEDGE-CATEGORIES-PRODUCTION-DRY-RUN-APPROVAL-TEMPLATE-1`

当前已新增 production dry-run 审批模板：

```text
docs/ai/03_data_and_migration/KNOWLEDGE_CATEGORIES_PRODUCTION_DRY_RUN_APPROVAL_TEMPLATE.md
```

输入背景：

1. P3-C8B Baota staging PG schema 初始化已通过。
2. P3-C8 Baota staging dry-run 已通过。
3. P3-C9-PRECHECK 已确认 staging apply 建议跳过。
4. 跳过原因：`SKIPPED_NO_SOURCE_ROWS`。
5. SQLite 源行数 = 0。
6. dry-run insert/update/skip/error = 0/0/0/0。

P3-C10 审批范围：

1. 只审批 production dry-run。
2. 只针对 9000 `knowledge_categories`。
3. 不审批 apply。
4. 不审批切换默认 `DATABASE_URL`。
5. 不审批开启 `KNOWLEDGE_CATEGORIES_ASYNC_PG_ENABLED`。
6. 不涉及 9100 / Milvus / RAG。

production dry-run 命令必须显式传入：

1. `--sqlite-db-path`
2. `--postgres-url`
3. `--dry-run`

通过标准必须包含：

1. `DRY_RUN_PASS`。
2. `error = 0`。
3. PG `knowledge_categories` 表存在。
4. Alembic revision >= `0002_create_knowledge_categories`。
5. PostgreSQL 写入 disabled。
6. 未执行 `--apply` / `--yes`。

边界确认：

1. 本轮只做文档。
2. 不执行 production dry-run。
3. 不连接 production。
4. 不读取 production SQLite。
5. 不写 PostgreSQL。
6. 不迁移数据。
7. 不切换 `DATABASE_URL`。
8. 不开启 `KNOWLEDGE_CATEGORIES_ASYNC_PG_ENABLED`。
9. 不改业务代码、迁移脚本、Alembic revision、docker-compose 或 `.env`。

## 32. P3-C11 production dry-run 人工 Runbook 补充

任务：`P3-C11-DB-9000-KNOWLEDGE-CATEGORIES-PRODUCTION-DRY-RUN-MANUAL-RUNBOOK-1`

当前已新增 production dry-run Runbook：

```text
docs/ai/03_data_and_migration/KNOWLEDGE_CATEGORIES_PRODUCTION_DRY_RUN_RUNBOOK.md
```

P3-C11 范围：

1. 只生成 production dry-run 人工执行 Runbook 和执行记录模板。
2. 只针对 9000 `knowledge_categories`。
3. production 操作必须由人工/运维执行。
4. 执行前必须引用 P3-C10 approval 结果。
5. 本 Runbook 不授权 apply。
6. 本 Runbook 不授权切换默认 `DATABASE_URL`。
7. 本 Runbook 不授权开启 `KNOWLEDGE_CATEGORIES_ASYNC_PG_ENABLED`。
8. 不涉及 9100 / Milvus / RAG。

Runbook 关键内容：

1. 执行前审批确认：审批编号、审批人、审批时间、是否批准 production dry-run、是否确认不执行 `--apply / --yes`。
2. 执行前检查：`cd <PRODUCTION_CODE_DIR>`、`git rev-parse HEAD`、`git status --short`、`git diff --check`、`docker compose -f <COMPOSE_FILE> config --services`、`docker ps`。
3. 依赖和脚本可见性检查：容器内可能缺 `asyncpg` / `alembic`；可通过一次性容器临时安装 `requirements-docker.txt`，但不在宿主机全局安装。
4. SQLite 只读检查与备份：确认 `<SQLITE_DB_PATH>`，读取前先备份，只读查询 `knowledge_categories` 表和源行数。
5. PostgreSQL 只读连接检查：`POSTGRES_URL` 只脱敏记录，确认 database 为 `auto_wechat` 和当前 user。
6. PG schema 检查：`\dt`、`select * from alembic_version`、`\d+ public.knowledge_categories`、唯一约束和 check constraint。
7. schema 缺失时不能在本 Runbook 内执行 Alembic upgrade，必须转独立 schema-init 审批。
8. production dry-run 命令必须显式传 `--sqlite-db-path`、`--postgres-url`、`--dry-run`，不得携带 `--apply` 或 `--yes`。
9. 输出记录模板包含 SQLite 源行数、过滤后待处理行数、PG 表状态、Alembic revision、insert/update/skip/error、字段映射预览、异常行和最终状态。
10. 执行后安全确认必须包含 PostgreSQL 写入 disabled、未切换 `DATABASE_URL`、未开启 `KNOWLEDGE_CATEGORIES_ASYNC_PG_ENABLED`、未执行 Alembic upgrade、未 drop 表、未清 volume。

后续判断：

1. dry-run 通过不等于允许 apply。
2. 如 source rows = 0，可记录 `SKIPPED_NO_SOURCE_ROWS`。
3. 如 insert/update > 0 且 error = 0，进入 production apply 审批模板。
4. 如 error > 0，先处理异常行，不允许 apply。
5. 不允许从 dry-run 自动进入 apply。

边界确认：

1. 本轮只做文档。
2. 本轮不执行 production 命令。
3. 本轮不连接 production 数据库。
4. 本轮不读取 production SQLite。
5. 本轮不执行 dry-run。
6. 本轮不执行 `--apply` / `--yes`。
7. 本轮不写 PostgreSQL。
8. 本轮不迁移数据。
9. 本轮不切换 `DATABASE_URL`。
10. 本轮不默认开启 `KNOWLEDGE_CATEGORIES_ASYNC_PG_ENABLED`。
11. 本轮不改业务代码、迁移脚本、Alembic revision、docker-compose 或 `.env`。

## 33. P3-C11 production dry-run 执行记录补充

任务：`P3-C11-DB-9000-KNOWLEDGE-CATEGORIES-PRODUCTION-DRY-RUN-EXECUTION-RECORD-1`

当前已新增 production dry-run 执行记录：

```text
docs/ai/03_data_and_migration/KNOWLEDGE_CATEGORIES_PRODUCTION_DRY_RUN_EXECUTION_RECORD.md
```

人工执行结果：

1. P3-C11 production dry-run：`PASS`。
2. commit hash：`26f4762763e71f25f66efba8d83015ff7ff8b633`。
3. `.env` PGSQL 变量仍为注释状态。
4. 未切换默认 `DATABASE_URL`。
5. 未开启 `KNOWLEDGE_CATEGORIES_ASYNC_PG_ENABLED`。
6. PostgreSQL schema 已满足前置条件：`alembic_version = 0002_create_knowledge_categories`，`knowledge_categories` 表存在。
7. PG `knowledge_categories_count = 0`。
8. SQLite 路径：`docker-data/auto_wechat_9000/auto_wechat.db`。
9. SQLite `knowledge_categories` 表存在，SQLite 源行数：0。
10. SQLite 备份存在：`backups/p3_c8/auto_wechat_knowledge_categories_p3_c8_20260708_155855.db`，size = 4.0K。
11. dry-run 输出：`DRY_RUN_PASS`。
12. 过滤后待处理行数 = 0。
13. insert/update/skip/error = 0/0/0/0。
14. 异常行数量 = 0。
15. 字段映射预览：`[]`。
16. PostgreSQL 写入：disabled。

收尾确认：

1. `POSTGRES_URL` 已 unset。
2. `auto-wechat-postgres-dev` 已停止。
3. `ps postgres` 无运行容器。
4. PostgreSQL 容器已停止。
5. `.venv-p3c8/` 和 `backups/` 是服务器本地未跟踪操作文件，不应提交。

边界确认：

1. 本轮只补充文档记录。
2. 本轮不执行 production 命令。
3. 本轮不连接 PostgreSQL。
4. 本轮不读取 SQLite。
5. 本轮不执行 dry-run。
6. 本轮不执行 `--apply / --yes`。
7. 本轮不写 PostgreSQL。
8. 本轮不迁移数据。
9. 本轮不切换 `DATABASE_URL`。
10. 本轮不默认开启 `KNOWLEDGE_CATEGORIES_ASYNC_PG_ENABLED`。
11. 本轮不改业务代码、迁移脚本、Alembic revision、docker-compose 或 `.env`。

后续建议：

```text
P3-C12 production apply: SKIPPED_NO_SOURCE_ROWS
```

原因是 production SQLite `knowledge_categories` 源行数 = 0，dry-run insert/update/skip/error = 0/0/0/0，执行 apply 没有业务价值。

## 34. P3-D0 PostgreSQL switch readiness 与 QPS600 路线

任务：`P3-D0-DB-9000-POSTGRESQL-SWITCH-READINESS-AND-QPS600-ROADMAP-1`

当前已新增 9000 PostgreSQL switch readiness 与 QPS600 路线文档：

```text
docs/ai/03_data_and_migration/POSTGRESQL_SWITCH_READINESS_AND_QPS600_ROADMAP.md
```

阶段结论：

1. `knowledge_categories` 单表链路已阶段性关闭。
2. production dry-run 已通过，输出 `DRY_RUN_PASS`。
3. production apply 建议结论为 `SKIPPED_NO_SOURCE_ROWS`，原因是 production SQLite `knowledge_categories` source rows = 0。
4. 单表验证不能等同于 9000 全系统 PostgreSQL 切库完成。
5. 当前仍不能切换默认 `DATABASE_URL` 到 PostgreSQL。
6. 当前仍不能把 `KNOWLEDGE_CATEGORIES_ASYNC_PG_ENABLED` 默认改为 true。
7. QPS600 仍需要 asyncpg / SQLAlchemy async、connection pool、索引、事务、幂等和压测共同验证。

readiness 准入条件：

1. 核心业务表完成 PostgreSQL schema。
2. 核心业务表完成 SQLite -> PostgreSQL dry-run / apply / verify。
3. 核心接口完成 SQLite / PG API contrast。
4. 写入链路完成事务边界和幂等保护。
5. 宝塔 staging 完成灰度验证和回滚演练。
6. worker、pool_size、max_overflow、pool_timeout 和 PostgreSQL `max_connections` 完成容量核算。
7. 高频查询完成 PostgreSQL 索引和 explain 验证。
8. QPS600 压测达标。

下一阶段进入 P3-D：

1. P3-D1：表盘点与读写路径审计。
2. P3-D2：核心基础表 schema 设计。
3. P3-D3：线索链路 PG schema + migration。
4. P3-D4：Local Agent task 链路 PG schema + migration。
5. P3-D5：智能体 / 账号绑定 PG schema + migration。
6. P3-D6：算力账户 / 流水 PG schema + migration。
7. P3-D7：核心接口 SQLite / PG contrast。
8. P3-D8 / P3-D9：staging 与 production 灰度、dry-run、apply 判断。
9. P3-E：默认 `DATABASE_URL` 切换预案。

边界确认：

1. 本轮只做文档和只读代码审计。
2. 本轮不改业务代码。
3. 本轮不改迁移脚本。
4. 本轮不新增 Alembic migration。
5. 本轮不执行宝塔命令。
6. 本轮不连接数据库。
7. 本轮不读取 SQLite。
8. 本轮不执行 dry-run / apply。
9. 本轮不切换 `DATABASE_URL`。
10. 本轮不默认开启 `KNOWLEDGE_CATEGORIES_ASYNC_PG_ENABLED`。

## 35. P3-D1 leads/tasks core PostgreSQL schema batch 补充

任务：`P3-D1-DB-9000-POSTGRESQL-LEADS-TASKS-CORE-SCHEMA-BATCH-1`

P3-D1 开始从 `knowledge_categories` 单表验证进入 9000 业务域批量 schema。当前 batch 只覆盖 4 张 P0 核心表：

```text
douyin_leads
douyin_webhook_events
sales_staff
wechat_tasks
```

当前新增：

```text
migrations/postgres/auto_wechat/versions/0003_create_leads_tasks_core_tables.py
tests/test_9000_postgres_leads_tasks_core_schema.py
scripts/smoke_auto_wechat_alembic_leads_tasks_core.py
```

revision 链路：

1. `revision = 0003_leads_tasks_core`。
2. `down_revision = 0002_create_knowledge_categories`。
3. `upgrade()` 只创建 `douyin_leads`、`douyin_webhook_events`、`sales_staff`、`wechat_tasks`。
4. `downgrade()` 只 drop 本批 4 张表。

只读审计摘要：

1. `douyin_leads` 读写路径覆盖线索列表、详情、报表统计、销售分配、webhook 会话归并和留资字段回填。
2. `douyin_webhook_events` 读写路径覆盖 webhook 原始事件落库、`event_key` 幂等去重、重复事件记录、解析字段保存和会话消息读取。
3. `sales_staff` 读写路径覆盖销售配置、商户内 active 销售过滤、微信昵称/微信号检索和自动分配候选。
4. `wechat_tasks` 读写路径覆盖 `notify_sales` / `detect_reply` 创建、pending 拉取、结果回写、检测次数和后续检测任务生成。

字段与类型口径：

1. 主键使用 `BigInteger` 自增。
2. 时间字段使用 `DateTime(timezone=True)`。
3. JSON 类字段使用 PostgreSQL `JSONB`。
4. boolean 字段使用 PostgreSQL `Boolean`。
5. 状态字段继续使用字符串，避免本轮引入状态枚举迁移。
6. schema 保留 `tenant_id`、`merchant_id`、`account_open_id`、`conversation_short_id` 等隔离和归并字段。

QPS600 相关 schema 起点：

1. `douyin_webhook_events.event_key` 建唯一约束，作为 webhook 幂等键。
2. `douyin_leads(account_open_id, conversation_short_id)` 保留唯一约束，延续会话归并口径。
3. `douyin_leads` 建商户更新时间、商户状态更新时间、商户账号会话、销售状态索引。
4. `douyin_webhook_events` 建商户时间、事件时间、账号会话、open_id 时间和消息 ID 索引。
5. `sales_staff` 建商户状态、商户微信昵称、商户微信号索引。
6. `wechat_tasks` 建商户状态时间、任务类型状态时间、线索任务类型、销售状态索引。

dev smoke 口径：

1. `scripts/smoke_auto_wechat_alembic_leads_tasks_core.py` 只读取 `SMOKE_DATABASE_URL`。
2. smoke 拒绝 SQLite URL，并脱敏展示 PostgreSQL URL。
3. smoke 执行 `alembic -c migrations/postgres/auto_wechat/alembic.ini upgrade head`。
4. smoke 只读验证 `alembic_version` 到 `0003_leads_tasks_core`、4 张表、关键字段、关键索引和关键约束。
5. smoke 不插入业务数据，不迁移 SQLite 数据，不执行 apply。

边界确认：

1. 本轮只新增 PostgreSQL schema batch、静态测试、dev smoke 和文档。
2. 本轮不迁移 SQLite 数据。
3. 本轮不执行 apply。
4. 本轮不切换默认 `DATABASE_URL`。
5. 本轮不改业务接口默认数据库。
6. 本轮不连接宝塔生产。
7. 本轮不改 9100 / Milvus / RAG。
8. 本轮不触发 LLM、抖音发送、私信发送或自动回复 gate。

后续：P3-D1 只是核心链路 schema 起点；后续仍需针对本批表补数据迁移 dry-run、受控 dev apply smoke、SQLite / PG API contrast、staging dry-run、production dry-run 与是否 apply 的人工判断，不能直接切换默认数据库。

## 36. P3-D2 leads/tasks core 数据迁移 dry-run 与 dev apply smoke 补充

任务：`P3-D2-DB-9000-POSTGRESQL-LEADS-TASKS-DATA-MIGRATION-DRY-RUN-AND-DEV-APPLY-1`

P3-D2 为 P3-D1 已创建的 4 张 PostgreSQL 表补充 SQLite -> PostgreSQL 数据迁移脚本、dry-run 统计、静态测试和 dev apply smoke。本轮仍只覆盖：

```text
sales_staff
douyin_leads
douyin_webhook_events
wechat_tasks
```

新增文件：

```text
scripts/migrate_leads_tasks_core_sqlite_to_postgres.py
scripts/smoke_migrate_leads_tasks_core_dev_apply.py
tests/test_migrate_leads_tasks_core_sqlite_to_postgres.py
```

脚本能力：

1. 默认 dry-run，不传 `--apply --yes` 不写 PostgreSQL。
2. 支持 `--sqlite-db-path`、`--postgres-url`、`--dry-run`、`--apply`、`--yes`、`--tables`。
3. `--postgres-url` 只允许 PostgreSQL URL，输出时通过 `parse_database_url().safe_url` 脱敏。
4. apply 必须显式 `--apply --yes`，且 host 只允许 `localhost`、`127.0.0.1`、`postgres`、`auto-wechat-postgres-dev`。
5. apply 目标 database 必须是 `auto_wechat`，并拒绝 `APP_ENV=production`。
6. `DATABASE_URL` 不允许隐式触发 apply；dev apply 需要显式 `--postgres-url` 或 `SMOKE_DATABASE_URL`。
7. dry-run 每表输出 source rows、insert/update/skip/error 预估、ignored/defaulted 字段、脱敏 mapping preview 和 warning。
8. apply 每表输出 inserted/updated/skipped/errors/before_count/after_count，不允许有异常行时静默部分成功。

迁移顺序：

```text
sales_staff -> douyin_leads -> douyin_webhook_events -> wechat_tasks
```

说明：任务原建议顺序为 `sales_staff -> douyin_webhook_events -> douyin_leads -> wechat_tasks`，但 P3-D1 PostgreSQL schema 中 `douyin_webhook_events.lead_id` 外键指向 `douyin_leads.id`，因此 P3-D2 按实际 schema 依赖调整为先迁移 `douyin_leads`，再迁移 `douyin_webhook_events`。

upsert / 幂等策略：

1. `sales_staff`：按 `id` 主键 upsert，属于过渡期最小迁移策略；后续如需跨环境真实迁移，应补更稳定业务键或人工确认 ID 保留策略。
2. `douyin_leads`：按 P3-D1 唯一约束 `account_open_id + conversation_short_id` upsert。
3. `douyin_webhook_events`：按 P3-D1 唯一约束 `event_key` upsert。
4. `wechat_tasks`：按 `id` 主键 upsert，属于任务队列迁移的最小幂等策略；不删除、不 truncate PostgreSQL 既有数据。
5. JSON 字段做安全解析，失败时保留原始字符串并记录 warning，不中断整批。
6. datetime 字段解析失败进入 error_rows，避免错误时间静默写入。
7. 联系方式字段在 mapping preview 中脱敏。

dev apply smoke：

1. `scripts/smoke_migrate_leads_tasks_core_dev_apply.py` 只读取 `SMOKE_DATABASE_URL`。
2. smoke 自动创建临时 synthetic SQLite fixture，不读取真实生产 SQLite。
3. fixture 至少包含每表 2 行 synthetic 数据。
4. smoke 先执行 auto_wechat Alembic `upgrade head`，确保 PG schema 到 `0003_leads_tasks_core`。
5. smoke 先 dry-run，确认预计 insert；再执行 apply；再执行第二次 dry-run，确认不会重复 insert。
6. smoke 校验四表 synthetic ID 范围内行数均不少于 2。
7. 成功输出 `SMOKE_PASS: leads/tasks core data migration dev apply ready`。

边界确认：

1. 本轮未连接宝塔生产。
2. 本轮未读取宝塔生产 SQLite。
3. 本轮未执行 production apply。
4. 本轮未切换默认 `DATABASE_URL`。
5. 本轮未修改业务接口默认数据库。
6. 本轮未改 9000 runtime DB 逻辑。
7. 本轮未改 9100 / Milvus / RAG。
8. 本轮未触发 LLM、抖音发送、微信发送、私信发送或自动回复 gate。
9. 当前仍不能切换宝塔 SQLite 到 PostgreSQL。

后续建议：P3-D3 进入四表 API contrast 与 async PG pilot 方案，不应直接进入默认 `DATABASE_URL` 切换。

## 37. P3-D3 leads/tasks core API contrast 与 async PG pilot 方案

任务：`P3-D3-DB-9000-LEADS-TASKS-API-CONTRAST-AND-ASYNC-PG-PILOT-1`

P3-D3 在 P3-D1 四表 PostgreSQL schema 和 P3-D2 四表数据迁移 dry-run / dev apply smoke 基础上，新增四表 SQLite vs PostgreSQL contrast 框架、dev synthetic contrast smoke，并补充 async PG pilot 方案。

新增文件：

```text
scripts/contrast_leads_tasks_core_sqlite_vs_postgres.py
scripts/smoke_contrast_leads_tasks_core_dev.py
tests/test_contrast_leads_tasks_core_sqlite_vs_postgres.py
docs/ai/03_data_and_migration/LEADS_TASKS_ASYNC_PG_PILOT_PLAN.md
```

contrast 口径：

1. 覆盖 `sales_staff`、`douyin_leads`、`douyin_webhook_events`、`wechat_tasks`。
2. 默认只读，PostgreSQL 写入为 `disabled`。
3. 对比 SQLite / PostgreSQL 行数、业务 key、必要字段、JSON parseability、datetime parseability。
4. mismatch_count 已收窄为 key 层面的缺失 / 多出。
5. JSON / datetime 解析异常在非 strict 模式下作为 warning；strict 模式下 warning 可导致失败。
6. PostgreSQL URL 输出必须脱敏。

async PG pilot 方案：

1. 当前仍不切换默认 `DATABASE_URL`。
2. 当前不默认开启 PG pilot。
3. 后续开关默认全部 false：`LEADS_TASKS_PG_PILOT_ENABLED=false`、`LEADS_TASKS_PG_READ_SHADOW_ENABLED=false`、`LEADS_TASKS_PG_WRITE_ENABLED=false`、`LEADS_TASKS_PG_STRICT_CONTRAST=false`。
4. 推荐先做 read-only shadow：`sales_staff` -> `wechat_tasks` history -> `douyin_leads` list/detail -> `douyin_webhook_events`。
5. SQLite 仍是返回源，PostgreSQL 只做 shadow read；mismatch 只记录日志，不影响用户。
6. webhook write 与 `wechat_tasks` result write 必须最后灰度，且需要单独事务、幂等和回滚设计。

边界确认：

1. 本轮未连接宝塔生产。
2. 本轮未读取生产 SQLite。
3. 本轮未执行 production apply。
4. 本轮未切换默认 `DATABASE_URL`。
5. 本轮未改业务接口默认数据库。
6. 本轮未默认开启 PG pilot。
7. 本轮未触发 LLM、抖音发送、微信发送、私信发送或自动回复 gate。

后续建议：P3-D4 进入 runtime shadow read scaffolding，默认关闭。

## 38. P3-D4 leads/tasks runtime shadow read scaffolding 补充

任务：`P3-D4-DB-9000-LEADS-TASKS-RUNTIME-SHADOW-READ-SCAFFOLDING-DEFAULT-OFF-1`

P3-D4 已新增 9000 leads/tasks runtime PostgreSQL shadow read scaffolding，默认全部关闭。本轮只覆盖 P3-D3 推荐顺序中最安全的两个 read-only 点：

```text
GET /staff                  -> sales_staff list shadow read
GET /wechat-tasks           -> wechat_tasks history shadow read
```

新增配置项：

```text
LEADS_TASKS_PG_PILOT_ENABLED=false
LEADS_TASKS_PG_READ_SHADOW_ENABLED=false
LEADS_TASKS_PG_WRITE_ENABLED=false
LEADS_TASKS_PG_STRICT_CONTRAST=false
LEADS_TASKS_PG_DATABASE_URL=
LEADS_TASKS_PG_POOL_SIZE=5
LEADS_TASKS_PG_MAX_OVERFLOW=5
LEADS_TASKS_PG_POOL_TIMEOUT=3
LEADS_TASKS_PG_STATEMENT_TIMEOUT_MS=1500
LEADS_TASKS_PG_SHADOW_TIMEOUT_MS=800
```

新增运行态文件：

```text
app/services/leads_tasks_pg_shadow.py
app/services/leads_tasks_shadow_compare.py
tests/test_leads_tasks_pg_shadow_runtime.py
```

运行边界：

1. 默认配置下不初始化 PG engine，不连接 PostgreSQL。
2. SQLite 仍是唯一响应源，接口 response model 和返回内容不变。
3. PostgreSQL shadow read 只做 count/key 轻量对照。
4. shadow mismatch、异常、超时只记录 warning，不影响用户响应。
5. URL 必须脱敏，不打印 password。
6. 本阶段不消费 `LEADS_TASKS_PG_WRITE_ENABLED`，不接入任何 PG write。
7. 当前仍不能切换默认 `DATABASE_URL`。

未接入范围：

1. `douyin_leads` list/detail runtime hook。
2. `douyin_webhook_events` runtime hook。
3. `GET /wechat-tasks/pending` pending polling。
4. `POST /wechat-tasks/{task_id}/result` result write。
5. webhook write。
6. production apply 或真实生产数据迁移。

## 39. P3-D5 douyin_leads runtime shadow read 与 observability

任务：`P3-D5-DB-9000-LEADS-RUNTIME-SHADOW-READ-AND-OBSERVABILITY-1`

P3-D5 在 P3-D4 默认关闭的 leads/tasks PG shadow read 脚手架基础上，扩展到 `douyin_leads` 运行态只读 shadow：

```text
GET /leads             -> douyin_leads list shadow read
GET /leads/{lead_id}   -> douyin_leads detail shadow read
```

新增 / 扩展文件：

```text
app/services/leads_tasks_shadow_observability.py
app/services/leads_tasks_pg_shadow.py
app/routers/leads.py
tests/test_leads_tasks_pg_shadow_runtime.py
```

leads list/detail 审计摘要：

1. `GET /leads` 位于 `app/routers/leads.py`，通过 `Depends(get_db)` 使用同步 SQLAlchemy session。
2. 列表查询由 `LeadListQuery` 和 `lead_management_service.list_leads()` 承载，支持 `merchant_id`、`status`、`keyword`、`source`、`assigned_staff_id`、`page/page_size`。
3. 非 `super_admin` 的 `merchant_id` 来自可信 `RequestContext`，不接受前端传入；`super_admin` 跨商户场景本轮跳过 PG shadow，避免无隔离查询。
4. `GET /leads/{lead_id}` 先读 SQLite，再通过 `require_lead_ownership()` 校验归属，最后构造 detail payload。
5. detail shadow 使用 SQLite 命中的 `lead.merchant_id + lead_id` 查询 PG；SQLite 不存在或无权访问时仍按原接口返回 404，不盲查 PG。

shadow read 扩展摘要：

1. 新增 operation：`douyin_leads.list`、`douyin_leads.detail`。
2. PG 查询只生成 `SELECT`，不包含 insert/update/delete/truncate/drop/create/alter。
3. list 查询按现有 SQLite 列表条件做近似对齐：`merchant_id`、`status`、`source`、`assigned_staff_id`、`keyword`、分页。
4. detail 查询要求 `merchant_id + lead_id`。
5. 对照仍为轻量 count/key：主键 `id` 为第一批运行态 key；`account_open_id + conversation_short_id` 作为查询结果字段保留给后续增强。
6. shadow 异常、timeout、mismatch 均不影响主响应，SQLite 仍是唯一响应源。

observability 摘要：

1. 新增 `record_shadow_result(result)` 输出结构化日志摘要。
2. 日志字段包含 `component=leads_tasks_pg_shadow`、table、operation、status、count_match、key_match、mismatch_count、duration_ms、warnings_count、strict、request_scope、merchant_id_present、`pii_redacted=True`。
3. 新增内存指标 snapshot：`total_shadow_reads`、`total_shadow_pass`、`total_shadow_warn`、`total_shadow_failed`、`total_shadow_timeout`、`total_shadow_error`、`total_mismatch_count`、`by_operation`。
4. 本轮不新增数据库表、不写文件、不暴露公网 metrics endpoint。
5. 日志不记录完整手机号、微信号、客户名、nickname 或 PostgreSQL URL 密码。

当前已接入范围：

1. `sales_staff` list。
2. `wechat_tasks` history。
3. `douyin_leads` list。
4. `douyin_leads` detail。

当前未接入范围：

1. `douyin_webhook_events` runtime hook。
2. webhook write。
3. pending task。
4. task result write。
5. `notify_sales` / `detect_reply` write。
6. 任何 PostgreSQL write。

边界确认：

1. 默认仍关闭 PG shadow。
2. SQLite 仍是唯一接口响应源。
3. 本轮未切换 `DATABASE_URL`。
4. 本轮未启用 PG write。
5. 本轮未连接宝塔生产，未读取生产 SQLite，未执行 production apply。
6. 本轮未触发 LLM、抖音发送、微信发送、私信发送或自动回复 gate。

后续建议：P3-D6 可接入 `douyin_webhook_events` read-only shadow + 受限 metrics debug endpoint；或进入 P3-E1 智能体 / 抖音账号绑定 schema batch。

## 40. P3-D6 douyin_webhook_events shadow read 与 metrics endpoint

任务：`P3-D6-DB-9000-WEBHOOK-EVENTS-SHADOW-READ-AND-METRICS-ENDPOINT-1`

P3-D6 已在默认关闭的 leads/tasks PG shadow read 基础上新增：

```text
GET /webhook-events
  -> douyin_webhook_events list read-only shadow

GET /admin/debug/leads-tasks-pg-shadow/metrics
  -> shadow metrics snapshot
```

webhook events 只读路径审计：

1. `GET /webhook-events` 和 `GET /webhook-events/{event_id}` 位于 `app/routers/webhook_events.py`。
2. 当前只接入列表接口 shadow；详情接口仍保持 SQLite-only，不新增 PG 查询。
3. 列表服务 `list_webhook_events()` 使用同步 SQLAlchemy session，从 `douyin_webhook_events` 读取 SQLite 数据并推导展示字段。
4. SQLite 过滤字段包含 event、duplicate、created_at range、keyword、lead_id、conversation_short_id、open_id 和 lead_action。
5. `lead_action`、open_id raw body fallback 等 post-filter 语义本轮不在 PG shadow 中完全复制，避免扩大 raw body 比较和 PII 日志面。

shadow read 扩展摘要：

1. 新增 operation：`douyin_webhook_events.list`。
2. PG 查询仅生成 `SELECT`，按 `merchant_id` 强制隔离；缺失 `merchant_id` 时跳过 shadow，不做无隔离查询。
3. 支持主要结构化过滤：`merchant_id`、`event`、`account_open_id`、`conversation_short_id`、`open_id`、`msg_id`、`created_at range`、`limit/offset`。
4. 对照维度保持轻量：count + `event_key` key set；查询结果保留 `server_message_id`、`to_user_id`、`conversation_short_id` 供后续增强。
5. 不比较 `raw_body` 全量内容，不记录完整 content、手机号、微信号或 nickname。
6. shadow mismatch、异常和 timeout 仍只进入结构化日志与内存指标，不影响主接口响应。

metrics endpoint 摘要：

1. 新增 `app/routers/admin_debug.py` 并在 `app/main.py` 注册。
2. `GET /admin/debug/leads-tasks-pg-shadow/metrics` 只返回内存指标只读快照。
3. endpoint 需要 `super_admin` 或 admin 权限，普通 merchant 和未登录请求不可访问。
4. endpoint 不触发 PG 连接、不要求 PG pilot 开启、不修改 metrics、不暴露 reset。
5. 返回值只包含指标聚合，不含 PII。

当前 read-only shadow 覆盖：

1. `sales_staff` list。
2. `wechat_tasks` history。
3. `douyin_leads` list。
4. `douyin_leads` detail。
5. `douyin_webhook_events` list。

当前未接入范围：

1. webhook write。
2. pending task。
3. task result write。
4. `notify_sales` / `detect_reply` write。
5. 任何 PostgreSQL write。

边界确认：

1. 默认仍关闭 PG shadow。
2. SQLite 仍是唯一接口响应源。
3. 本轮未切换 `DATABASE_URL`。
4. 本轮未启用 PG write。
5. 本轮未连接宝塔生产，未读取生产 SQLite，未执行 production apply。
6. 本轮未触发 LLM、抖音发送、微信发送、私信发送或自动回复 gate。

后续建议：P3-D7 做本地 synthetic runtime shadow smoke + 全量 shadow 覆盖回归；或进入 P3-E1 智能体 / 抖音账号绑定 schema batch。

## 41. P3-D7 runtime shadow synthetic smoke 与回归

任务：`P3-D7-DB-9000-LEADS-TASKS-RUNTIME-SHADOW-SYNTHETIC-SMOKE-AND-REGRESSION-1`

P3-D7 在 P3-D4/P3-D5/P3-D6 默认关闭的 runtime PostgreSQL shadow read 基础上，新增本地/dev synthetic smoke 与回归验证：

```text
scripts/smoke_leads_tasks_runtime_shadow_dev.py
tests/test_leads_tasks_runtime_shadow_smoke.py
```

smoke 覆盖的 read-only operation：

1. `sales_staff.list`
2. `wechat_tasks.history`
3. `douyin_leads.list`
4. `douyin_leads.detail`
5. `douyin_webhook_events.list`

验证重点：

1. 默认关闭时不初始化 PG engine，不触发 shadow read，metrics 不增长。
2. dev/synthetic 开启 shadow 后，SQLite synthetic fixture 仍是响应源，PG shadow 只做只读对照。
3. metrics `total_shadow_reads` 增长，`by_operation` 覆盖五个 operation。
4. mismatch、PG error、timeout 不改变 SQLite 主响应，只记录 warning / metrics。
5. metrics endpoint 仍只读，不触发 PG 连接，不暴露 reset endpoint 或 PII。
6. shadow 相关 SQL 模板和 D7 smoke 脚本不包含 PostgreSQL 写入语句；`LEADS_TASKS_PG_WRITE_ENABLED` 仍未被业务写路径消费。

安全边界：

1. 本轮未连接宝塔生产。
2. 本轮未读取生产 SQLite。
3. 本轮未执行 production apply。
4. 本轮未切换默认 `DATABASE_URL`。
5. 本轮未默认开启 PG pilot。
6. 本轮未启用 PG write。
7. 本轮未接入 webhook write、pending task、task result write、`notify_sales` / `detect_reply` write。
8. 本轮未触发 LLM、抖音发送、微信发送、私信发送或自动回复 gate。

后续建议：P3-D8 进入本地 QPS baseline + shadow overhead 压测；或进入 P3-E1 智能体 / 抖音账号绑定 schema batch。仍不得直接进入默认数据库切换。

## 42. P3-D8 leads/tasks shadow QPS baseline 与 overhead benchmark

任务：`P3-D8-DB-9000-LEADS-TASKS-QPS-BASELINE-AND-SHADOW-OVERHEAD-1`

P3-D8 在 P3-D4/P3-D5/P3-D6/P3-D7 的 runtime read-only shadow 覆盖基础上，新增本地/dev synthetic benchmark，用于对比 shadow off baseline 与 shadow on overhead。

新增文件：

```text
scripts/benchmark_leads_tasks_shadow_overhead_dev.py
tests/test_leads_tasks_shadow_benchmark.py
docs/ai/03_data_and_migration/LEADS_TASKS_SHADOW_QPS_BENCHMARK_GUIDE.md
```

benchmark 能力：

1. 只允许 `BENCHMARK_DATABASE_URL` 或 `SMOKE_DATABASE_URL` 提供 dev PostgreSQL URL。
2. 拒绝隐式 `DATABASE_URL`，拒绝 SQLite URL，URL 输出必须脱敏。
3. 只允许本地/dev host，目标 database 必须是 `auto_wechat`。
4. 自动创建 synthetic SQLite fixture。
5. 复用 P3-D2 migration helper 将 synthetic rows 写入 dev PostgreSQL。
6. 压测运行态以 SQLite synthetic rows 作为响应源，PostgreSQL 只做 read-only shadow。
7. 执行 shadow off 与 shadow on 两轮，对比 p50 / p95 / p99 / avg / max / error_rate / throughput。
8. 输出 `total_shadow_reads`、`total_shadow_pass`、`total_shadow_warn`、`total_shadow_failed`、`total_shadow_timeout`、`total_shadow_error`、`by_operation`。
9. 计算 overhead delta，并可输出 JSON 结果。
10. 结束时清理 synthetic PG 数据。

当前 read-only shadow 覆盖：

1. `sales_staff.list`
2. `wechat_tasks.history`
3. `douyin_leads.list`
4. `douyin_leads.detail`
5. `douyin_webhook_events.list`

边界确认：

1. 本轮 benchmark 仅限 dev/synthetic。
2. 本轮 benchmark 不代表 production QPS600 达标。
3. 本轮不连接宝塔生产。
4. 本轮不读取生产 SQLite。
5. 本轮不执行 production apply。
6. 本轮不切换默认 `DATABASE_URL`。
7. 本轮不默认开启 PG pilot。
8. 本轮不启用 PG write。
9. 本轮不接 webhook write、pending task、task result write、`notify_sales` / `detect_reply` 写链路。
10. 本轮不触发 LLM、抖音发送、微信发送、私信发送或自动回复 gate。

后续建议：

1. `P3-D9`：async session / connection pool runtime design hardening。
2. 或 `P3-E1`：智能体 / 抖音账号绑定 schema batch。

## 43. P3-D9 leads/tasks async engine / pool 生命周期加固

任务：`P3-D9-DB-9000-LEADS-TASKS-ASYNC-ENGINE-POOL-HARDENING-1`

P3-D9 基于 P3-D8 benchmark 暴露的 shadow overhead，对 leads/tasks PostgreSQL read-only shadow 的 async engine 生命周期做了加固。本轮仍保持默认关闭 PG pilot，不切换 `DATABASE_URL`，不启用 PG write。

新增 / 修改文件：

```text
app/services/leads_tasks_pg_engine.py
app/services/leads_tasks_pg_shadow.py
scripts/benchmark_leads_tasks_shadow_overhead_dev.py
tests/test_leads_tasks_pg_engine_manager.py
tests/test_leads_tasks_pg_shadow_runtime.py
tests/test_leads_tasks_shadow_benchmark.py
```

engine manager 规则：

1. 默认关闭或 URL 为空时不创建 engine。
2. 拒绝 SQLite URL 和非 `postgresql+asyncpg://` URL。
3. 按 event loop 缓存 engine，同一个 event loop 复用，不同 event loop 不复用。
4. URL 或 pool 参数变化时重建 engine，并 dispose 旧 engine。
5. 提供 `dispose_shadow_engines()`，benchmark / smoke 收尾时显式释放。
6. `get_engine_manager_snapshot()` 输出 `engine_count`、`loop_count`、`created_count`、`disposed_count`、`cache_hit_count`、`cache_miss_count`，URL 脱敏。

shadow service 调整：

1. `leads_tasks_pg_shadow.py` 改用 engine manager，不再每次 shadow query create/dispose engine。
2. 同步请求路径通过后台 event loop 运行 async PG shadow read，避免每次 `asyncio.run()` 造成独立 event loop 和 engine 重建。
3. PG 查询仍只允许 SELECT。
4. shadow timeout、异常和 mismatch 仍只记录 warning / metrics，不影响 SQLite 主响应。
5. `LEADS_TASKS_PG_WRITE_ENABLED` 仍未被任何业务写路径消费。

P3-D8 benchmark baseline：

```text
shadow off: throughput_rps=15089.898, p50=0.881ms, p95=1.357ms, p99=1.634ms
shadow on:  throughput_rps=39.301, p50=536.994ms, p95=734.568ms, p99=909.916ms
overhead:   p50 +536.113ms, p95 +733.211ms, p99 +908.282ms, throughput -99.74%
```

P3-D9 本地/dev synthetic benchmark：

```text
命令：python scripts/benchmark_leads_tasks_shadow_overhead_dev.py --requests 200 --concurrency 20 --warmup 20 --strict
结果：BENCHMARK_PASS
shadow off: throughput_rps=12613.203, p50=0.971ms, p95=3.234ms, p99=3.683ms
shadow on:  throughput_rps=441.390, p50=33.621ms, p95=155.103ms, p99=170.014ms
overhead:   p50 +32.650ms, p95 +151.869ms, p99 +166.331ms, throughput -96.501%
```

相对 P3-D8 shadow on 改善：

1. p50 降低 503.373ms，约 93.74%。
2. p95 降低 579.465ms，约 78.89%。
3. p99 降低 739.902ms，约 81.32%。
4. throughput 提升 402.089 rps，约 11.23 倍。

engine manager snapshot：

```text
engine_count=1
loop_count=1
created_count=1
disposed_count=0
cache_hit_count=183
cache_miss_count=1
```

边界确认：

1. 本轮未连接宝塔生产。
2. 本轮未读取生产 SQLite。
3. 本轮未执行 production apply。
4. 本轮未切换默认 `DATABASE_URL`。
5. 本轮未默认开启 PG pilot。
6. 本轮未启用 PG write。
7. 本轮未接入 webhook write、pending task、task result write、`notify_sales` / `detect_reply` 写链路。
8. 本轮未触发 LLM、抖音发送、微信发送、私信发送或自动回复 gate。
9. P3-D9 benchmark 仍是本地/dev synthetic，不代表 production QPS600 达标。

后续建议：

1. `P3-D10`：真实 Uvicorn / HTTP benchmark 脚手架，用真实 ASGI/HTTP 路径继续量化 shadow overhead。
2. 或 `P3-E1`：智能体 / 抖音账号绑定 schema batch。

## 44. P3-D10 leads/tasks HTTP benchmark scaffold

任务：`P3-D10-DB-9000-LEADS-TASKS-REAL-HTTP-BENCHMARK-SCAFFOLD-1`

P3-D10 在 P3-D9 event-loop-safe async engine manager 基础上，新增真实 Uvicorn/HTTP 层 benchmark 脚手架，用于继续量化 leads/tasks PostgreSQL read-only shadow 的 HTTP 层 overhead。

新增 / 修改文件：

```text
scripts/benchmark_leads_tasks_shadow_http_dev.py
tests/test_leads_tasks_shadow_http_benchmark.py
docs/ai/03_data_and_migration/LEADS_TASKS_SHADOW_HTTP_BENCHMARK_GUIDE.md
app/routers/admin_debug.py
```

脚手架能力：

1. 支持 `--start-server` 自动启动本地 Uvicorn，使用临时 SQLite fixture。
2. 支持 `--base-url` 连接已启动的本地 9000 dev 服务，但该模式不能由脚本切换服务环境，会输出 warning。
3. 仅允许 `BENCHMARK_DATABASE_URL` 或 `SMOKE_DATABASE_URL` 作为 dev PostgreSQL URL；拒绝 SQLite URL 和隐式 `DATABASE_URL`。
4. 仅允许 localhost / 127.0.0.1 / 0.0.0.0 base-url。
5. 覆盖 `GET /staff`、`GET /wechat-tasks`、`GET /leads`、`GET /leads/{lead_id}`、`GET /webhook-events` 和 metrics endpoint。
6. 输出 p50 / p95 / p99 / avg / max / error_rate / throughput / per-endpoint / overhead delta。
7. metrics endpoint 额外返回 `engine_manager_snapshot`，不触发 PG 初始化，不包含 PII 或数据库密码。

边界确认：

1. 本轮仍只使用本地/dev synthetic 数据。
2. 本轮未连接宝塔生产。
3. 本轮未读取生产 SQLite。
4. 本轮未执行 production apply。
5. 本轮未切换默认 `DATABASE_URL`。
6. 本轮未默认开启 PG pilot。
7. 本轮未启用 PG write。
8. 本轮未接入 webhook write、pending task、task result write、`notify_sales` / `detect_reply` 写链路。
9. 本轮未触发 LLM、抖音发送、微信发送、私信发送或自动回复 gate。
10. P3-D10 benchmark 仍不代表 production QPS600 达标。

后续建议：

1. `P3-D11`：Uvicorn multi-worker benchmark / connection pool sizing。
2. 或 `P3-E1`：智能体 / 抖音账号绑定 schema batch。

## 45. P3-D11 leads/tasks worker/pool sizing benchmark

任务：`P3-D11-DB-9000-LEADS-TASKS-UVICORN-MULTI-WORKER-POOL-SIZING-1`

P3-D11 基于 P3-D10 真实 Uvicorn/HTTP benchmark，新增 worker/pool sizing benchmark scaffold：

```text
scripts/benchmark_leads_tasks_shadow_workers_dev.py
tests/test_leads_tasks_shadow_worker_benchmark.py
docs/ai/03_data_and_migration/LEADS_TASKS_SHADOW_WORKER_POOL_SIZING_GUIDE.md
```

新增 shadow 配置：

```text
LEADS_TASKS_PG_SHADOW_MAX_CONCURRENCY=10
LEADS_TASKS_PG_SHADOW_SAMPLE_RATE=1.0
```

运行语义：

1. 默认仍不切换 `DATABASE_URL`。
2. 默认仍不启用 PG pilot。
3. PG pilot/read shadow 未开启时，新配置不生效。
4. `sampled_out` / `concurrency_limited` 只跳过 shadow read，不影响 SQLite 主响应，不连接 PostgreSQL，不视为 error。
5. metrics 新增 `total_shadow_sampled_out`、`total_shadow_concurrency_limited`、`current_shadow_inflight`、`max_shadow_inflight_seen`。

worker benchmark 能力：

1. 支持 `--workers`、`--pool-sizes`、`--max-overflows` 矩阵。
2. 支持 `--shadow-max-concurrency`、`--shadow-sample-rates` 矩阵。
3. 输出 `estimated_pg_connections = workers * (pool_size + max_overflow)`。
4. 输出 HTTP throughput / p50 / p95 / p99 / error_rate、shadow metrics、engine manager snapshot。
5. 至少执行一组 shadow off baseline，再执行 shadow on matrix。

边界确认：

1. 本轮仍只使用本地/dev synthetic 数据。
2. 本轮不连接宝塔 production。
3. 本轮不读取 production SQLite。
4. 本轮不执行 production apply。
5. 本轮不切换默认 `DATABASE_URL`。
6. 本轮不默认开启 PG pilot。
7. 本轮不启用 PG write。
8. 本轮不接入 webhook write、pending task、task result write、`notify_sales` / `detect_reply` 写链路。
9. 本轮不触发 LLM、抖音发送、微信发送、私信发送或自动回复 gate。
10. P3-D11 benchmark 仍不代表 production QPS600 达标。

后续建议：

1. `P3-D12`：shadow sampling / max concurrency 策略调优。
2. 或 `P3-E1`：智能体 / 抖音账号绑定 schema batch。

## 46. P3-D12 leads/tasks shadow sampling / concurrency tuning

任务：`P3-D12-DB-9000-LEADS-TASKS-SHADOW-SAMPLING-CONCURRENCY-TUNING-1`

P3-D12 已基于 P3-D11 worker/pool sizing benchmark 扩展本地/dev synthetic tuning：

```text
scripts/benchmark_leads_tasks_shadow_workers_dev.py
tests/test_leads_tasks_shadow_worker_benchmark.py
docs/ai/03_data_and_migration/LEADS_TASKS_SHADOW_SAMPLING_TUNING_REPORT.md
```

脚本新增能力：

1. `--quick-tuning` 快速矩阵。
2. `shadow_sample_rate=1.0,0.5,0.2,0.1`。
3. `shadow_max_concurrency=1,3,5,10`。
4. `theoretical_shadow_attempts` 与 `shadow_coverage_ratio`。
5. `tuning_summary`，包含 `best_throughput`、`best_p95_under_150ms`、`best_low_pg_connections`、`recommended_gray_config`。

本地/dev synthetic quick-tuning 结果：

```text
SAMPLING_TUNING_PASS
recommended_gray_config:
  workers=2
  pool_size=5
  max_overflow=5
  shadow_max_concurrency=10
  shadow_sample_rate=0.1
  estimated_pg_connections=20
best_throughput_rps=570.102
p95_ms=52.178
p99_ms=59.518
QPS600 remaining_rps=29.898
```

边界确认：

1. P3-D12 仍只使用本地/dev synthetic。
2. P3-D12 不连接宝塔 production。
3. P3-D12 不读取 production SQLite。
4. P3-D12 不执行 production apply。
5. P3-D12 不切换默认 `DATABASE_URL`。
6. P3-D12 不默认开启 PG pilot。
7. P3-D12 不启用 PG write。
8. P3-D12 不接入 webhook write、pending task、task result write、`notify_sales` / `detect_reply` 写链路。
9. P3-D12 不触发 LLM、抖音发送、微信发送、私信发送或自动回复 gate。
10. P3-D12 benchmark 不代表 production QPS600 达标。

后续建议：`P3-D13` 做 runtime shadow gray config preset 与环境变量文档，默认关闭；或 `P3-E1` 进入智能体 / 抖音账号绑定 schema batch。

## 47. P3-D13 leads/tasks shadow gray preset 与 Runbook

任务：`P3-D13-DB-9000-LEADS-TASKS-SHADOW-GRAY-PRESET-AND-RUNBOOK-1`

P3-D13 已基于 P3-D12 本地/dev synthetic tuning 结果，新增 leads/tasks PostgreSQL read-only shadow 灰度预设与启停 Runbook：

```text
docs/ai/03_data_and_migration/LEADS_TASKS_SHADOW_GRAY_PRESET_RUNBOOK.md
```

本轮同步更新 `.env.example`，只增加默认关闭的注释示例，不改变运行时默认值。

当前灰度候选来自 P3-D12：

```text
workers=2
pool_size=5
max_overflow=5
shadow_max_concurrency=10
shadow_sample_rate=0.1
estimated_pg_connections=20
throughput_rps=570.102
p95_ms=52.178
p99_ms=59.518
error_rate=0
```

P3-D13 结论：

1. dev 可按推荐值做本地/dev synthetic 验证。
2. staging 建议从更保守的 `shadow_sample_rate=0.05`、`shadow_max_concurrency=5` 开始，观察通过后再审批提升。
3. production 当前为 `not approved / not executed`，必须保持 `LEADS_TASKS_PG_PILOT_ENABLED=false`、`LEADS_TASKS_PG_READ_SHADOW_ENABLED=false`、`LEADS_TASKS_PG_WRITE_ENABLED=false`。
4. 任何环境都不允许通过本 Runbook 切换默认 `DATABASE_URL`。
5. 任何环境都不允许启用 PG write。
6. 本轮不连接宝塔 production，不读取 production SQLite，不执行 production apply。
7. P3-D12/P3-D13 仍不能作为 production QPS600 达标证明。

监控与熔断口径：

1. 观察 `total_shadow_reads`、`total_shadow_pass`、`total_shadow_warn`、`total_shadow_timeout`、`total_shadow_error`、`total_shadow_sampled_out`、`total_shadow_concurrency_limited`、`total_mismatch_count`。
2. 观察接口 p50 / p95 / p99、HTTP 5xx、PostgreSQL 当前连接数、慢查询、锁等待和 statement timeout。
3. 出现 error、timeout、mismatch 持续增长、接口延迟明显恶化、连接数接近预算或任何写 PG 迹象时，立即关闭 shadow。

后续建议：P3-D14 做宝塔 staging read-only shadow 人工审批模板与执行记录；不得自动进入 production shadow 或 PG write。
## 48. P3-E1 agents/accounts core PostgreSQL schema batch

任务：`P3-E1-DB-9000-POSTGRESQL-AGENTS-ACCOUNTS-SCHEMA-BATCH-1`

P3-E1 开始第二批 P0 核心域 PostgreSQL schema。本批只覆盖智能体与抖音账号绑定链路的四张表：

1. `ai_agents`
2. `douyin_authorized_accounts`
3. `douyin_account_agent_bindings`
4. `agent_knowledge_categories`

只读审计摘要：

1. ORM 模型位于 `app/models.py`：`AiAgent`、`DouyinAuthorizedAccount`、`DouyinAccountAgentBinding`、`AgentKnowledgeCategory`。
2. SQLite 迁移来源包括 `0002_douyin_authorized_accounts.sql`、`0007_ai_agents.sql`、`0008_douyin_account_agent_bindings.sql`、`0012_agent_knowledge_categories.sql`。
3. 主要路由 / service 包括 `app/routers/agents.py`、`apps/agents/services.py`、`app/routers/douyin_accounts.py`、`app/services/douyin_account_agent_binding_service.py`、`app/routers/douyin_ai_cs_proxy.py`。
4. 当前隔离字段以 `merchant_id` 为主，预留 `tenant_id`；绑定关系使用 `account_open_id`、`agent_id`、`category_key`。
5. 当前高频读路径包括智能体列表/详情、抖音授权账号列表、账号绑定默认 Agent、Agent 知识分类绑定读取。

新增 migration：

```text
migrations/postgres/auto_wechat/versions/0004_create_agents_accounts_core_tables.py
revision = 0004_agents_accounts_core
down_revision = 0003_leads_tasks_core
```

schema 摘要：

1. `ai_agents`：保留 `agent_id` 唯一约束，增加 `merchant_id + status`、`merchant_id + name`、`merchant_id + updated_at` 索引；不强制同商户 name 唯一，避免破坏现有多智能体命名弹性。
2. `douyin_authorized_accounts`：保留 `main_account_id + open_id` 唯一约束，增加 `merchant_id + open_id` 唯一约束，以及 `merchant_id + bind_status`、`open_id`、`last_synced_at` 索引。
3. `douyin_account_agent_bindings`：保留 `merchant_id + account_open_id`、`merchant_id + agent_id` 查询索引，增加 active default 局部唯一索引，保证同商户同账号只有一个 active default 绑定。
4. `agent_knowledge_categories`：保留 `merchant_id + agent_id + status`、`merchant_id + category_key + status` 查询索引，增加 `category_key` 索引和 active 局部唯一索引。

dev smoke：

```text
scripts/smoke_auto_wechat_alembic_agents_accounts_core.py
```

该 smoke 只读取 `SMOKE_DATABASE_URL`，拒绝 SQLite URL，URL 输出脱敏，目标 database 必须是 `auto_wechat`，dev host 仅允许 `localhost` / `127.0.0.1` / `postgres`。脚本执行 auto_wechat Alembic `upgrade head`，验证 `alembic_version = 0004_agents_accounts_core`，并验证四张表、关键索引和关键约束存在。

边界确认：

1. 本轮只建 PostgreSQL schema，不迁移 SQLite 数据。
2. 本轮不执行数据 apply。
3. 本轮不切换默认 `DATABASE_URL`。
4. 本轮不修改业务接口默认数据库。
5. 本轮不默认开启 PG pilot。
6. 本轮不启用 PG write。
7. 本轮不连接宝塔 production，不读取 production SQLite。
8. 本轮不触发 LLM、抖音发送、微信发送、私信发送或自动回复 gate。

后续建议：

1. `P3-E2`：agents/accounts 数据迁移 dry-run + dev apply smoke。
2. `P3-E3`：agents/accounts API contrast。
3. leads/tasks shadow 链路虽已进入 gray preset 阶段，但仍未 production 执行，不能据此切换默认数据库。

## 49. P3-E2 agents/accounts 数据迁移 dry-run 与 dev apply smoke

任务：`P3-E2-DB-9000-POSTGRESQL-AGENTS-ACCOUNTS-DATA-MIGRATION-DRY-RUN-AND-DEV-APPLY-1`

P3-E2 已为 P3-E1 创建的四张 agents/accounts PostgreSQL 表补充 SQLite -> PostgreSQL 数据迁移脚本、dry-run 能力、静态测试和本地/dev synthetic apply smoke：

```text
scripts/migrate_agents_accounts_core_sqlite_to_postgres.py
scripts/smoke_migrate_agents_accounts_core_dev_apply.py
tests/test_migrate_agents_accounts_core_sqlite_to_postgres.py
```

覆盖表：

1. `ai_agents`
2. `douyin_authorized_accounts`
3. `douyin_account_agent_bindings`
4. `agent_knowledge_categories`

迁移顺序：

1. `ai_agents`
2. `douyin_authorized_accounts`
3. `douyin_account_agent_bindings`
4. `agent_knowledge_categories`

upsert / 幂等策略：

1. `ai_agents`：按 `agent_id` upsert。
2. `douyin_authorized_accounts`：按 `merchant_id + open_id` upsert；历史 `merchant_id` 缺失会记录 warning，不静默伪造商户归属。
3. `douyin_account_agent_bindings`：按 `id` upsert，并在源数据内拦截同一 `merchant_id + account_open_id` 的双 active default 绑定，避免破坏默认绑定语义。
4. `agent_knowledge_categories`：active 行按 `merchant_id + agent_id + category_key` 与 PG 局部唯一索引 upsert，并在源数据内拦截重复 active 分类绑定。

脚本安全门：

1. 默认 dry-run，`--apply` 必须同时显式传 `--yes`。
2. `postgres-url` 拒绝 SQLite URL，输出必须脱敏。
3. apply 只允许 dev/local host：`localhost`、`127.0.0.1`、`postgres`、`auto-wechat-postgres-dev`。
4. apply 目标 database 必须是 `auto_wechat`。
5. `APP_ENV=production` 时拒绝 apply。
6. apply 不允许隐式使用 `DATABASE_URL`，必须显式 `--postgres-url` 或 `SMOKE_DATABASE_URL`。
7. 脚本不执行 `delete` / `truncate` / `drop`；dev smoke 仅按 synthetic merchant/id 范围清理测试数据。

dev apply smoke 结果：

```text
第一次 dry-run: total_insert=8, total_update=0, total_skip=0, total_errors=0, DRY_RUN_PASS
apply: inserted=8, updated=0, skipped=0, errors=0, APPLY_PASS
第二次 dry-run: total_insert=0, total_update=8, total_skip=0, total_errors=0, DRY_RUN_PASS
PostgreSQL 行数: 四表各 >= 2
SMOKE_PASS: agents/accounts core data migration dev apply ready
```

边界确认：

1. 本轮只验证 dry-run 和本地/dev synthetic apply smoke。
2. 本轮未连接宝塔 production。
3. 本轮未读取 production SQLite。
4. 本轮未执行 production apply。
5. 本轮未切换默认 `DATABASE_URL`。
6. 本轮未修改业务接口默认数据库。
7. 本轮未默认开启 PG pilot，未启用 PG write。
8. 本轮未触发 LLM、抖音发送、微信发送、私信发送或自动回复 gate。

当前切库结论不变：仍不能把宝塔 SQLite 直接切到 PostgreSQL。P3-E2 只证明 agents/accounts 四表迁移脚本在本地/dev synthetic 数据上具备 dry-run、受控 apply 与幂等闭环。

后续建议：

1. `P3-E3`：agents/accounts API contrast。
2. `P3-E4`：agents/accounts runtime shadow read 方案，视复杂度决定。
3. 不得跳过 contrast / staging 审批直接进入默认数据库切换。

## 50. P3-E3 agents/accounts SQLite / PostgreSQL contrast

任务：`P3-E3-DB-9000-AGENTS-ACCOUNTS-API-CONTRAST-1`

P3-E3 已为 P3-E1/P3-E2 完成的 agents/accounts 四表新增离线只读 SQLite vs PostgreSQL data contrast 框架和本地/dev synthetic contrast smoke：

```text
scripts/contrast_agents_accounts_core_sqlite_vs_postgres.py
scripts/smoke_contrast_agents_accounts_core_dev.py
tests/test_contrast_agents_accounts_core_sqlite_vs_postgres.py
```

覆盖表：

1. `ai_agents`
2. `douyin_authorized_accounts`
3. `douyin_account_agent_bindings`
4. `agent_knowledge_categories`

contrast 规则：

1. 只读读取 SQLite 与 PostgreSQL，不执行 `insert` / `update` / `delete` / `truncate` / `drop`。
2. `postgres-url` 拒绝 SQLite URL，输出 URL 必须脱敏。
3. 对比 `sqlite_count`、`postgres_count`、`count_match`、`sample_key_match`、`required_columns_match`、nullable/default compatibility、JSON parseability、datetime parseability、`mismatch_count` 和 warnings。
4. 对照 key 沿用 P3-E2 迁移 key：`ai_agents.agent_id`、`douyin_authorized_accounts.merchant_id + open_id`、`douyin_account_agent_bindings.id`、`agent_knowledge_categories.merchant_id + agent_id + category_key`。
5. `token`、`secret`、`access_token`、`refresh_token`、`open_id`、`user_id`、`union_id`、raw JSON 等敏感内容不得完整明文输出。
6. 非 strict 模式下 JSON / datetime parse warning 不阻断；strict 模式下 warning 会返回 `CONTRAST_FAILED`。

dev synthetic contrast smoke：

1. 通过 `SMOKE_DATABASE_URL` 读取 dev PostgreSQL URL。
2. 自动创建临时 SQLite fixture。
3. 复用 P3-E2 迁移 helper 将 synthetic SQLite 数据 apply 到 dev PostgreSQL。
4. 执行 contrast，要求四表 `count_match=true`、`sample_key_match=true`、`mismatch_count=0`。
5. smoke 后只清理 synthetic merchant/id 范围的 PG 数据。
6. 成功输出：`SMOKE_PASS: agents/accounts core SQLite vs PostgreSQL contrast ready`。

边界确认：

1. 本轮只做离线 contrast、dev synthetic smoke、测试和文档。
2. 本轮未连接宝塔 production。
3. 本轮未读取 production SQLite。
4. 本轮未执行 production apply。
5. 本轮未切换默认 `DATABASE_URL`。
6. 本轮未默认开启 PG pilot。
7. 本轮未启用 PG write。
8. 本轮未接 runtime shadow。
9. 本轮未修改业务接口默认数据库。
10. 本轮未触发 LLM、抖音发送、微信发送、私信发送或自动回复 gate。

当前切库结论不变：P3-E3 只证明 agents/accounts 四表本地/dev synthetic 数据在 SQLite 与 PostgreSQL 之间可以离线对照，不等于宝塔真实数据 contrast，不等于 runtime shadow 已接入，也不等于可以切换默认数据库。

后续建议：

1. `P3-E4`：agents/accounts runtime shadow read 方案，默认关闭。
2. 或 `P3-F1`：`compute_accounts` / `compute_transactions` schema batch。
3. 仍不得跳过 contrast / staging 审批直接切换默认 `DATABASE_URL`。
