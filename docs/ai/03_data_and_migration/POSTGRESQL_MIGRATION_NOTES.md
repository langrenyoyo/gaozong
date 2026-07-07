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
DATABASE_URL=postgresql://.../auto_wechat
```

### 2.2 database：xg_douyin_ai_cs

用途：

- 9100 RAG / AI 客服 metadata 服务使用。
- 存放知识库、训练、反馈、RAG / AI 客服 metadata。
- 未来通过 `RAG_DATABASE_URL` 连接。

规划示例：

```text
RAG_DATABASE_URL=postgresql://.../xg_douyin_ai_cs
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
DATABASE_URL=postgresql://.../auto_wechat
RAG_DATABASE_URL=postgresql://.../xg_douyin_ai_cs
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
