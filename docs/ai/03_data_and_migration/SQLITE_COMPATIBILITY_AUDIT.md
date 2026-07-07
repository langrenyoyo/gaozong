# SQLite 专属写法兼容性审计

任务：P1-DB-SQLITE-SPECIFIC-USAGE-AUDIT-GUARD-1

范围：本轮只做 SQLite-only 写法审计、文档记录和轻量守门检查。不做数据库重构，不引入 PostgreSQL，不修改现有业务 SQL 行为，不跑迁移，不连接 Milvus，不触发 LLM、抖音发送、私信发送或自动回复 gate。

## 1. 审计范围

本轮扫描范围：

```text
app/
apps/xg_douyin_ai_cs/
scripts/
migrations/
tests/
```

`frontend/` 暂未纳入重点范围，因为当前没有数据库访问代码。

## 2. 背景口径

项目已确认 PostgreSQL 目标路线：

1. 方案 A：一个 PostgreSQL 实例，两个 database。
2. `auto_wechat`：9000 主服务未来通过 `DATABASE_URL` 连接。
3. `xg_douyin_ai_cs`：9100 RAG / AI 客服 metadata 未来通过 `RAG_DATABASE_URL` 连接。
4. SQLite 只是开发和过渡库，不是最终生产数据库。
5. Milvus 只做 embedding 和向量检索副本，不是 metadata 真源。
6. Milvus 模式下，`ask` 不能因为 SQLite active count 为 0 跳过 RAG。

## 3. SQLite 专属写法清单

本轮守门脚本识别以下风险模式：

| 模式 | 风险 | 建议 |
|---|---|---|
| `sqlite3.connect` | 业务代码直接绑定 SQLite 连接方式 | 后续收口到 database / repository 层 |
| `PRAGMA table_info` | SQLite schema introspection | 仅迁移脚本或兼容层暂留 |
| `INSERT OR IGNORE` | SQLite 幂等写法 | PostgreSQL 目标应改为唯一约束 + `ON CONFLICT` |
| `INSERT OR REPLACE` | SQLite upsert 写法，可能隐含删除再插入语义 | 后续改为明确 upsert |
| `rowid` | SQLite 隐式行标识 | 不进入业务逻辑 |
| `INTEGER PRIMARY KEY AUTOINCREMENT` | SQLite DDL 写法 | PostgreSQL 目标应映射为 `BIGSERIAL` 或 `UUID` |
| SQL `AUTOINCREMENT` | SQLite DDL 写法 | 仅迁移脚本暂留 |
| service/router 中散落 SQL `?` 占位符 | 业务层直接承载 SQL 方言细节 | 后续收口到 repository |
| SQLite active count 决定 RAG skip | Milvus 与 metadata 短暂不一致时会误跳过检索 | Milvus backend 下不能用该 count 作为 skip 依据 |

说明：SQLAlchemy `Column(..., autoincrement=True)` 不是本轮脚本拦截对象；脚本只拦截 SQL DDL 里的大写 `AUTOINCREMENT`。

## 4. 当前发现位置

### P0 高风险

当前没有未放行的 P0 错误项。守门脚本全量扫描结果为：

```text
errors=0
warnings=77
```

已知历史风险：

| 文件 | 命中 | 处理 |
|---|---|---|
| `apps/xg_douyin_ai_cs/services/knowledge_training_service.py` | `active_doc_count`、`rag_skipped`、service 层 SQL `?` 占位符 | legacy allowlist；已修复 Milvus 模式不能因 SQLite count=0 skip，后续仍需 repository 化 |

### P1 后续应收口

| 文件 | 命中 | 原因 |
|---|---|---|
| `apps/xg_douyin_ai_cs/rag/database.py` | `sqlite3.connect`、`INTEGER PRIMARY KEY AUTOINCREMENT`、`PRAGMA table_info` | 9100 当前 SQLite 兼容层 |
| `apps/xg_douyin_ai_cs/rag/repository.py` | `INSERT OR IGNORE`、SQL `?` 占位符 | 9100 当前 SQLite repository，后续 PostgreSQL 化时替换 |
| `apps/xg_douyin_ai_cs/services/knowledge_training_service.py` | service 层 SQL `?` 占位符、active count 相关逻辑 | 历史实现，短期不改业务行为 |

### P2 允许暂留

| 区域 | 命中 | 原因 |
|---|---|---|
| `migrations/migrate_sqlite.py` | `sqlite3.connect`、`PRAGMA table_info` | SQLite migration runner，本身就是 SQLite 专用 |
| `migrations/versions/*.sql` | `INTEGER PRIMARY KEY AUTOINCREMENT` | 现有 SQLite 迁移文件 |
| `tests/test_db_migration*.py` | SQLite DDL / 连接 / `?` 占位符 | SQLite 迁移测试 |
| `tests/test_xg_douyin_ai_cs*.py` | SQLite 测试库和 schema 检查 | 9100 SQLite 兼容测试 |
| `tests/test_sqlite_specific_usage_guard.py` | 故意构造 `sqlite3.connect` 用例 | 守门脚本自测 |

## 5. 允许暂留区域

当前 allowlist 策略：

```text
migrations/**
tests/**
apps/xg_douyin_ai_cs/rag/database.py
apps/xg_douyin_ai_cs/rag/repository.py
apps/xg_douyin_ai_cs/services/knowledge_training_service.py
```

暂留原因：

1. `migrations/**` 是现有 SQLite 迁移体系，不在本轮重构。
2. `tests/**` 中存在 SQLite 专用迁移和兼容测试，需要保留。
3. `apps/xg_douyin_ai_cs/rag/database.py` 是当前 9100 SQLite 连接和 schema 初始化兼容层。
4. `apps/xg_douyin_ai_cs/rag/repository.py` 是当前 9100 SQLite RAG repository，后续 PostgreSQL 改造时统一迁移。
5. `apps/xg_douyin_ai_cs/services/knowledge_training_service.py` 已包含历史直接 SQL 和 Milvus skip 修复，本轮不改业务逻辑，只阻止新增扩散。

## 6. 不建议继续新增的区域

以下目录新增 SQLite-only 写法会被守门脚本报错：

```text
app/services/
app/routers/
apps/xg_douyin_ai_cs/services/
apps/xg_douyin_ai_cs/routers/
```

后续如果确实需要新增数据库访问，应优先放到明确的 database / repository 层，并在 PostgreSQL 目标方案下设计可迁移写法。

## 7. 守门检查

新增脚本：

```text
scripts/check_sqlite_specific_usage.py
```

运行方式：

```bash
python scripts/check_sqlite_specific_usage.py
```

行为：

1. 默认扫描 `app/`、`apps/xg_douyin_ai_cs/`、`scripts/`、`migrations/`、`tests/`。
2. allowlist 命中项只输出 `WARNING`，退出码为 0。
3. 非 allowlist 的核心业务目录命中高风险模式时输出 `ERROR`，退出码为 1。
4. 输出文件路径、行号、模式和风险说明。
5. 不自动修复。
6. 不连接数据库。
7. 不依赖第三方包。

新增测试：

```text
tests/test_sqlite_specific_usage_guard.py
```

覆盖：

1. 核心业务目录新增 `sqlite3.connect` 会被报错。
2. allowlist 中的迁移脚本只产生 warning。
3. 核心 service 中散落 SQL `?` 占位符会被识别。

## 8. 后续改造建议

1. P2：引入 `DATABASE_URL` / `RAG_DATABASE_URL` 连接抽象。
2. P2：建立 database / repository 分层，业务 service 不关心 SQLite / PostgreSQL 方言。
3. P2：新增代码避免继续在 service/router 中直接拼 SQL。
4. P3：引入 Alembic 或独立 PostgreSQL migration runner。
5. P3：把 `INSERT OR IGNORE` / `INSERT OR REPLACE` 收口为 PostgreSQL 唯一约束 + `ON CONFLICT`。
6. P3：把 JSON TEXT、时间字符串、0/1 布尔语义迁移为 PostgreSQL `JSONB`、`TIMESTAMPTZ`、`BOOLEAN`。

## 9. 本轮未改内容

1. 未修改业务逻辑。
2. 未修改数据库结构。
3. 未执行迁移。
4. 未引入 PostgreSQL。
5. 未引入 Alembic。
6. 未修改 docker-compose。
7. 未修改 `.env` / `.env.example`。
8. 未连接 Milvus。
9. 未触发 LLM。
10. 未触发抖音发送、私信发送或自动回复 gate。
11. 未删除现有 SQLite 兼容代码。
12. 未写入真实 URI、token、password 或 secret。

## 10. 验证结果

本轮验证命令：

```bash
python scripts/check_sqlite_specific_usage.py
python -m pytest tests/test_sqlite_specific_usage_guard.py -q
git diff --check
```

结果：

```text
python scripts/check_sqlite_specific_usage.py
PASS，errors=0，warnings=77

python -m pytest tests/test_sqlite_specific_usage_guard.py -q
PASS，3 passed
```

`git diff --check` 结果见本任务最终报告。
