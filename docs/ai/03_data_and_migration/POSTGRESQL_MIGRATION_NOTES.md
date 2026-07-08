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
