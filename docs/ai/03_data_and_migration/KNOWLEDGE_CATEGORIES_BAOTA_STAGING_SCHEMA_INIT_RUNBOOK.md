# knowledge_categories 宝塔 staging PostgreSQL schema 初始化人工 Runbook

任务：`P3-C8B-BAOTA-STAGING-POSTGRES-SCHEMA-INIT-MANUAL-RUNBOOK-1`

范围：本文用于指导宝塔执行人在 Baota staging PostgreSQL 空库中执行 `auto_wechat` Alembic migration 到 `0002_create_knowledge_categories`，为后续 P3-C8 `knowledge_categories` SQLite -> PostgreSQL dry-run 提供前置 schema。本机 VibeCoding 只生成 Runbook，不执行宝塔命令，不连接 PostgreSQL，不读取 SQLite，不迁移业务数据。

## 1. 本机 VibeCoding 边界

本机 VibeCoding 本轮只修改文档。

本机 VibeCoding 不执行：

1. 不登录宝塔服务器。
2. 不执行宝塔命令。
3. 不启动 PostgreSQL 容器。
4. 不连接 PostgreSQL。
5. 不读取宝塔 SQLite。
6. 不执行 Alembic migration。
7. 不执行数据迁移脚本。
8. 不执行 `--apply` 或 `--yes`。
9. 不修改 `.env`、docker-compose、Dockerfile、业务代码或 Alembic revision。
10. 不切换 9000 默认 `DATABASE_URL`。
11. 不开启 `KNOWLEDGE_CATEGORIES_ASYNC_PG_ENABLED`。

宝塔命令必须由人工在 Baota staging 环境执行，并把结果贴回后再判断是否回到 P3-C8 dry-run。

## 2. 目标与非目标

### 2.1 目标

1. 仅初始化 PostgreSQL `auto_wechat` database 的 schema。
2. 目标 Alembic revision 为 `0002_create_knowledge_categories` 或当前 head 中包含该 revision。
3. 只创建：
   - `alembic_version`
   - `knowledge_categories`
   - `knowledge_categories` 相关索引
   - `knowledge_categories` 唯一约束
   - `knowledge_categories` check constraint
4. 为 P3-C8 dry-run 提供只读 schema 检查前置条件。

### 2.2 非目标

1. 不迁移 SQLite 业务数据。
2. 不迁移全量 9000 表。
3. 不操作 9100 `xg_douyin_ai_cs` database。
4. 不操作 Milvus / RAG。
5. 不执行 `scripts/migrate_knowledge_categories_sqlite_to_postgres.py --apply --yes`。
6. 不切换 9000 默认 `DATABASE_URL`。
7. 不开启 `KNOWLEDGE_CATEGORIES_ASYNC_PG_ENABLED`。
8. 不重启 9000。

## 3. P3-C8 当前 blocked 摘要

人工 P3-C8 前置检查已确认：

1. 9000 SQLite 路径已确认：

```text
docker-data/auto_wechat_9000/auto_wechat.db
```

2. SQLite `knowledge_categories` 表存在。
3. SQLite `knowledge_categories_count = 0`。
4. SQLite 已备份到：

```text
backups/p3_c8/auto_wechat_knowledge_categories_p3_c8_20260708_155855.db
```

5. PostgreSQL dev 容器可启动且 healthy。
6. PostgreSQL `auto_wechat` database 存在。
7. `auto_wechat` database 当前无业务表，`alembic_version` 不存在。
8. P3-C8 dry-run 被阻塞，原因是 PG schema 未初始化。
9. PostgreSQL 容器已停止。

结论：migration 文件本身不是本轮问题；需要先在 Baota staging PostgreSQL 空库中执行 `auto_wechat` Alembic schema 初始化，再回到 P3-C8 只读 dry-run。

## 4. 前置检查

执行人必须在执行 schema 初始化前逐项确认并记录。

| 检查项 | 命令模板 | 记录值 | 结论 |
|---|---|---|---|
| 当前代码目录 | `pwd` | `<CODE_DIR>` | `<通过/不通过>` |
| commit hash | `git rev-parse HEAD` | `<COMMIT_HASH>` | `<通过/不通过>` |
| 工作区状态 | `git status --short` | `<输出；为空表示干净>` | `<通过/不通过>` |
| PostgreSQL 容器状态 | `docker compose -f <COMPOSE_FILE> ps <POSTGRES_SERVICE>` | `<输出>` | `<通过/不通过>` |
| `auto_wechat` database 存在 | `psql -d postgres -c "\l"` | `<是/否>` | `<通过/不通过>` |
| 当前 schema 状态 | `psql -d auto_wechat -c "\dt"` | `<无表 / 已有表>` | `<通过/不通过>` |
| `scripts/` 可见 | `test -f scripts/migrate_knowledge_categories_sqlite_to_postgres.py && echo ok` | `<ok>` | `<通过/不通过>` |
| `migrations/` 可见 | `test -f migrations/postgres/auto_wechat/alembic.ini && echo ok` | `<ok>` | `<通过/不通过>` |
| 依赖包含 Alembic | `python -c "import alembic; print(alembic.__version__)"` | `<版本>` | `<通过/不通过>` |
| 依赖包含 asyncpg | `python -c "import asyncpg; print(asyncpg.__version__)"` | `<版本>` | `<通过/不通过>` |
| PostgreSQL URL | `<脱敏记录>` | `postgresql+asyncpg://<USER>:***@<HOST>:<PORT>/auto_wechat` | `<通过/不通过>` |

任一项不通过，停止执行并记录失败原因。不得临时修改 `.env`、docker-compose 或默认 `DATABASE_URL` 来绕过检查。

## 5. PostgreSQL URL 规则

schema 初始化只允许使用 staging/dev PostgreSQL URL。

允许：

```text
postgresql://<USER>:<PASSWORD>@<HOST>:<PORT>/auto_wechat
postgresql+asyncpg://<USER>:<PASSWORD>@<HOST>:<PORT>/auto_wechat
postgresql+psycopg://<USER>:<PASSWORD>@<HOST>:<PORT>/auto_wechat
```

禁止：

```text
sqlite:///...
postgresql.../<非 auto_wechat database>
生产 PostgreSQL URL
真实 password 写入文档或提交记录
```

记录时必须脱敏：

```text
postgresql+asyncpg://<USER>:***@<HOST>:<PORT>/auto_wechat
```

## 6. schema 初始化命令模板

`migrations/postgres/auto_wechat/env.py` 当前读取 `DATABASE_URL`。本文命令模板以临时环境变量 `DATABASE_URL=<POSTGRES_URL>` 为准，不修改 `.env`。

推荐通过一次性 `auto-wechat-api` 容器执行，并挂载宿主机代码目录。示例中的 `<API_SERVICE>` 在当前 compose 中通常为 `auto-wechat-api`，但执行人必须以 Baota staging 实际 compose 为准。

### 6.1 启动 PostgreSQL

```bash
docker compose -f <COMPOSE_FILE> up -d <POSTGRES_SERVICE>
docker compose -f <COMPOSE_FILE> ps <POSTGRES_SERVICE>
```

要求：

1. PostgreSQL 容器状态为 running / healthy。
2. `auto_wechat` database 已存在。
3. 目标不是 production。

### 6.2 一次性容器执行 Alembic upgrade

推荐升级到明确 revision：

```bash
docker compose -f <COMPOSE_FILE> run --rm --no-deps \
  -v <CODE_DIR>:/workspace \
  -w /workspace \
  -e DATABASE_URL="<POSTGRES_URL>" \
  <API_SERVICE> \
  sh -lc "python -m pip install -r requirements-docker.txt && python -m alembic -c migrations/postgres/auto_wechat/alembic.ini upgrade 0002_create_knowledge_categories"
```

如果确认 `head` 当前仍只包含 `0002_create_knowledge_categories` 或后续兼容 revision，也可使用：

```bash
docker compose -f <COMPOSE_FILE> run --rm --no-deps \
  -v <CODE_DIR>:/workspace \
  -w /workspace \
  -e DATABASE_URL="<POSTGRES_URL>" \
  <API_SERVICE> \
  sh -lc "python -m pip install -r requirements-docker.txt && python -m alembic -c migrations/postgres/auto_wechat/alembic.ini upgrade head"
```

执行边界：

1. 只使用 `migrations/postgres/auto_wechat/alembic.ini`。
2. 不执行 `migrations/postgres/xg_douyin_ai_cs/alembic.ini`。
3. 不执行 `migrations/migrate_sqlite.py`。
4. 不执行数据迁移脚本 apply。
5. 不重启 9000。
6. 不修改 `.env`。
7. 不切换默认 `DATABASE_URL`。

### 6.3 宿主机 Python 兜底方式

如果宝塔宿主机 Python 环境已明确安装 `alembic`、`sqlalchemy`、`asyncpg`，且执行人确认不会污染生产运行环境，可在宿主机代码目录执行：

```bash
cd <CODE_DIR>
DATABASE_URL="<POSTGRES_URL>" python -m alembic -c migrations/postgres/auto_wechat/alembic.ini upgrade 0002_create_knowledge_categories
```

该方式只作为兜底。优先使用一次性容器，避免宿主机 Python 依赖与项目运行依赖不一致。

## 7. schema 初始化后验证

初始化完成后必须验证以下项目。

### 7.1 表清单

```bash
docker compose -f <COMPOSE_FILE> exec <POSTGRES_SERVICE> \
  psql -U <POSTGRES_USER> -d auto_wechat -c "\dt"
```

预期至少看到：

```text
alembic_version
knowledge_categories
```

### 7.2 Alembic revision

```bash
docker compose -f <COMPOSE_FILE> exec <POSTGRES_SERVICE> \
  psql -U <POSTGRES_USER> -d auto_wechat -c "select * from alembic_version;"
```

预期：

```text
0002_create_knowledge_categories
```

或 head 中包含 `0002_create_knowledge_categories` 的后续 revision。

### 7.3 `knowledge_categories` 表结构

```bash
docker compose -f <COMPOSE_FILE> exec <POSTGRES_SERVICE> \
  psql -U <POSTGRES_USER> -d auto_wechat -c "\d+ knowledge_categories"
```

必须确认字段包含：

1. `id`
2. `tenant_id`
3. `merchant_id`
4. `category_key`
5. `key`
6. `name`
7. `description`
8. `scope_type`
9. `is_base`
10. `status`
11. `sort_order`
12. `created_at`
13. `updated_at`
14. `deleted_at`
15. `created_by`
16. `updated_by`

### 7.4 唯一约束

```bash
docker compose -f <COMPOSE_FILE> exec <POSTGRES_SERVICE> \
  psql -U <POSTGRES_USER> -d auto_wechat -c "select conname, contype, pg_get_constraintdef(oid) from pg_constraint where conrelid = 'public.knowledge_categories'::regclass and conname = 'uk_knowledge_categories_scope_merchant_key';"
```

预期：

```text
conname = uk_knowledge_categories_scope_merchant_key
contype = u
pg_get_constraintdef 包含 UNIQUE (scope_type, merchant_id, key)
```

### 7.5 check constraint

```bash
docker compose -f <COMPOSE_FILE> exec <POSTGRES_SERVICE> \
  psql -U <POSTGRES_USER> -d auto_wechat -c "select conname, contype, pg_get_constraintdef(oid) from pg_constraint where conrelid = 'public.knowledge_categories'::regclass and conname = 'ck_knowledge_categories_key_matches_category_key';"
```

预期：

```text
conname = ck_knowledge_categories_key_matches_category_key
contype = c
pg_get_constraintdef 包含 key = category_key
```

### 7.6 行数

```bash
docker compose -f <COMPOSE_FILE> exec <POSTGRES_SERVICE> \
  psql -U <POSTGRES_USER> -d auto_wechat -c "select count(*) from knowledge_categories;"
```

预期：

```text
0
```

如果行数不是 0，停止并记录原因。不要默认 drop 表或清 volume。

## 8. 安全边界

本 Runbook 执行期间禁止：

1. 禁止执行 `--apply`。
2. 禁止执行 `--yes`。
3. 禁止执行 `scripts/migrate_knowledge_categories_sqlite_to_postgres.py` 写入模式。
4. 禁止修改 `.env`。
5. 禁止切换默认 `DATABASE_URL`。
6. 禁止开启 `KNOWLEDGE_CATEGORIES_ASYNC_PG_ENABLED`。
7. 禁止重启 9000。
8. 禁止 drop 表。
9. 禁止清 PostgreSQL volume。
10. 禁止迁移 SQLite 业务数据。
11. 禁止操作 9100、Milvus 或 RAG。
12. 禁止触发 LLM、抖音发送、私信发送或自动回复 gate。
13. 禁止写入真实 URI、token 或 password 到文档、提交记录或群聊。

## 9. 回滚策略

schema 初始化失败时：

1. 立即停止。
2. 记录失败命令、脱敏 URL、失败阶段和错误输出摘要。
3. 不继续执行 P3-C8 dry-run。
4. 不临时修改 `.env` 或 compose。
5. 不默认 drop 表。
6. 不默认清 volume。
7. 不默认重启 9000。

是否允许 drop schema/table 只能由人工审批决定。即使 Baota staging 当前是空库，也必须先确认：

1. 当前 database 是否确认为 staging/dev。
2. 当前 `knowledge_categories` 行数是否为 0。
3. 是否存在其它表或其它任务写入。
4. 是否已有备份或 dump。

production 不适用本 Runbook。production schema 初始化必须单独制定审批和回滚预案。

## 10. 成功标准

只有同时满足以下条件，才算 P3-C8B schema 初始化成功：

1. `alembic_version = 0002_create_knowledge_categories`，或 head 中包含该 revision。
2. `knowledge_categories` 表存在。
3. `uk_knowledge_categories_scope_merchant_key` 唯一约束存在。
4. `ck_knowledge_categories_key_matches_category_key` check constraint 存在。
5. 支撑查询的 `knowledge_categories` 索引存在。
6. `knowledge_categories` 行数为 0。
7. 未迁移 SQLite 数据。
8. 未执行 `--apply` 或 `--yes`。
9. 未切换 9000 默认数据库。
10. 未开启 PG pilot。
11. 未操作 9100 / Milvus / RAG。

## 11. 后续

schema 初始化成功后，回到 P3-C8 dry-run：

```bash
python scripts/migrate_knowledge_categories_sqlite_to_postgres.py \
  --sqlite-db-path <SQLITE_DB_PATH> \
  --postgres-url <POSTGRES_URL> \
  --dry-run
```

P3-C8 仍只做 dry-run：

1. 不写 PostgreSQL。
2. 不执行 `--apply`。
3. 不执行 `--yes`。
4. 不切换默认数据库。
5. 不开启 PG pilot。

P3-C9 才讨论 Baota staging apply + API contrast 执行记录。

## 12. 执行记录模板

```text
执行任务：P3-C8B-BAOTA-STAGING-POSTGRES-SCHEMA-INIT-MANUAL-RUNBOOK-1
执行机器：<Baota staging 宿主机 / 其他>
执行人：<NAME>
执行时间：<YYYY-MM-DD HH:mm:ss>
代码目录：<CODE_DIR>
commit hash：<COMMIT_HASH>
git status --short：<输出>
PostgreSQL URL：postgresql+asyncpg://<USER>:***@<HOST>:<PORT>/auto_wechat
DATABASE_URL 是否仅临时注入：<是/否>
执行命令：<脱敏命令>
Alembic 输出摘要：<输出摘要>
alembic_version：<REVISION>
knowledge_categories 表存在：<是/否>
唯一约束存在：<是/否>
check constraint 存在：<是/否>
knowledge_categories 行数：<COUNT>
是否执行数据迁移 apply：否
是否切换默认 DATABASE_URL：否
是否开启 KNOWLEDGE_CATEGORIES_ASYNC_PG_ENABLED：否
是否重启 9000：否
是否操作 9100 / Milvus / RAG：否
结论：<SCHEMA_INIT_PASS / SCHEMA_INIT_FAIL>
后续：<回到 P3-C8 dry-run / 停止并拆后续任务>
```
