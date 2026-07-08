# knowledge_categories production dry-run Runbook

任务：`P3-C11-DB-9000-KNOWLEDGE-CATEGORIES-PRODUCTION-DRY-RUN-MANUAL-RUNBOOK-1`

本文是 production 环境 `knowledge_categories` SQLite -> PostgreSQL dry-run 的正式人工执行 Runbook 和执行记录模板。本文不是审批表，不授权 apply，不授权切换默认数据库，不授权开启 PG pilot。

关键词口径：`P3-C11`；`production dry-run Runbook`；`approval`；`knowledge_categories`；`--dry-run`；不执行 --apply / --yes；PostgreSQL 写入 disabled；`0002_create_knowledge_categories`；不切换 DATABASE_URL；不开启 KNOWLEDGE_CATEGORIES_ASYNC_PG_ENABLED；人工/运维执行。

## 1. 运行边界

1. 本机 VibeCoding 不操作 production。
2. 本 Runbook 只供人工/运维执行。
3. 本 Runbook 只允许 production dry-run。
4. 本 Runbook 不允许 apply。
5. 本 Runbook 不允许切换默认 `DATABASE_URL`。
6. 本 Runbook 不允许开启 `KNOWLEDGE_CATEGORIES_ASYNC_PG_ENABLED`。
7. 本 Runbook 不允许修改 `.env`、docker-compose、Dockerfile、业务代码、迁移脚本或 Alembic revision。
8. 本 Runbook 不涉及 9100 / Milvus / RAG，不触发 LLM、抖音发送、私信发送或自动回复 gate。

## 2. 执行前审批确认

执行前必须引用 P3-C10 审批结果。未完成 P3-C10 审批或审批结论不是“批准”的，禁止执行 production dry-run。

| 审批项 | 记录 |
|---|---|
| P3-C10 审批编号 | `<APPROVAL_ID>` |
| 审批人 | `<NAME>` |
| 审批时间 | `<YYYY-MM-DD HH:mm:ss>` |
| 是否批准 production dry-run | `<是/否>` |
| 是否确认不执行 `--apply / --yes` | `<是/否>` |
| 是否确认不写 PostgreSQL | `<是/否>` |
| 是否确认不重启 9000 | `<是/否>` |
| 是否确认不改 `.env` | `<是/否>` |
| 是否确认不改 docker-compose | `<是/否>` |
| 是否确认不切换 `DATABASE_URL` | `<是/否>` |
| 是否确认不开启 `KNOWLEDGE_CATEGORIES_ASYNC_PG_ENABLED` | `<是/否>` |

任一项为“否”或无法确认，停止执行并回到审批流程。

## 3. 执行前检查步骤

命令模板必须使用占位符。执行记录不得写真实 password、token、完整 URI 或客户敏感数据。

```bash
cd <PRODUCTION_CODE_DIR>
git rev-parse HEAD
git status --short
git diff --check
docker compose -f <COMPOSE_FILE> config --services
docker ps
```

执行人必须确认：

| 检查项 | 记录 |
|---|---|
| production 代码目录 | `<PRODUCTION_CODE_DIR>` |
| 当前 commit hash | `<COMMIT_HASH>` |
| `git status --short` 输出 | `<输出；为空表示干净>` |
| `git diff --check` 结果 | `<通过/不通过>` |
| Compose 文件 | `<COMPOSE_FILE>` |
| Compose services | `<脱敏摘要>` |
| API 服务名 | `<API_SERVICE>` |
| PostgreSQL 服务或容器 | `<POSTGRES_SERVICE / POSTGRES_CONTAINER>` |
| SQLite DB 路径 | `<SQLITE_DB_PATH>` |
| PostgreSQL URL 脱敏 | `<POSTGRES_URL_MASKED>` |
| database 名称 | `auto_wechat` |

`<API_SERVICE>`、`<SQLITE_DB_PATH>`、`<POSTGRES_URL>` 三项未确认前，不允许继续。

## 4. 依赖和脚本可见性检查

参考 Baota staging 实际经验，production 容器内可能缺少 `asyncpg` 或 `alembic`，也可能没有 COPY `scripts/` 和 `migrations/`。执行人必须先检查，不得在 production 宿主机做全局安装。

禁止：

1. 不在宿主机 `apt install`。
2. 不在宿主机全局 `pip install`。
3. 不创建 production 宿主机 venv，除非另有审批。
4. 不修改 Dockerfile 或 docker-compose。
5. 不把依赖修复混入本 Runbook。

推荐通过一次性容器检查依赖和脚本可见性：

```bash
docker compose -f <COMPOSE_FILE> run --rm <API_SERVICE> \
  python --version

docker compose -f <COMPOSE_FILE> run --rm <API_SERVICE> \
  python -c "import sqlalchemy, asyncpg, alembic; print('dependencies_ok')"

docker compose -f <COMPOSE_FILE> run --rm <API_SERVICE> \
  python scripts/migrate_knowledge_categories_sqlite_to_postgres.py --help
```

如果一次性容器缺依赖，但审批允许在一次性容器内临时安装项目依赖，可使用以下模板。该命令只安装容器内临时环境，不修改宿主机全局环境：

```bash
docker compose -f <COMPOSE_FILE> run --rm <API_SERVICE> \
  sh -lc "pip install -r requirements-docker.txt && python scripts/migrate_knowledge_categories_sqlite_to_postgres.py --help"
```

记录：

| 项目 | 输出 | 结论 |
|---|---|---|
| Python 版本 | `<输出>` | `<通过/不通过>` |
| sqlalchemy / asyncpg / alembic | `<输出>` | `<通过/不通过>` |
| `scripts/` 是否可见 | `<是/否>` | `<通过/不通过>` |
| `migrations/` 是否可见 | `<是/否>` | `<通过/不通过>` |
| 迁移脚本 `--help` | `<是否显示参数>` | `<通过/不通过>` |

依赖失败时停止并记录，不现场修 production 配置。

## 5. SQLite 只读检查与备份

production SQLite 路径必须由人工确认，不允许猜测。读取前必须先备份。

路径确认模板：

```bash
ls -lh <SQLITE_DB_PATH>
python -c "from pathlib import Path; p=Path('<SQLITE_DB_PATH>'); print(p.resolve()); print('exists=', p.exists()); print('size=', p.stat().st_size if p.exists() else 'missing')"
```

备份模板：

```bash
mkdir -p <BACKUP_DIR>
cp -p <SQLITE_DB_PATH> <BACKUP_DIR>/auto_wechat_knowledge_categories_p3_c11_$(date +%Y%m%d_%H%M%S).db
ls -lh <BACKUP_DIR>/auto_wechat_knowledge_categories_p3_c11_*.db
```

只读查询模板：

```bash
python -c "import sqlite3; p='<SQLITE_DB_PATH>'; conn=sqlite3.connect(f'file:{p}?mode=ro', uri=True); print('knowledge_categories_exists=', conn.execute(\"select count(*) from sqlite_master where type='table' and name='knowledge_categories'\").fetchone()[0]); print('knowledge_categories_count=', conn.execute('select count(*) from knowledge_categories').fetchone()[0]); conn.close()"
```

记录：

| 项目 | 记录 |
|---|---|
| SQLite 路径（可脱敏） | `<SQLITE_DB_PATH>` |
| SQLite 文件大小 | `<SIZE>` |
| 备份路径（可脱敏） | `<BACKUP_PATH>` |
| 备份文件大小 | `<SIZE>` |
| `knowledge_categories` 表是否存在 | `<是/否>` |
| SQLite 源行数 | `<COUNT>` |
| 是否只读查询 | `<是/否>` |

本步骤不得修改 SQLite。

## 6. PostgreSQL 只读连接检查

`POSTGRES_URL` 只能脱敏记录，执行时通过临时环境变量或命令参数传入。目标 database 必须是 `auto_wechat`。

临时环境变量模板：

```bash
export POSTGRES_URL='<POSTGRES_URL>'
python -c "from urllib.parse import urlparse; u=urlparse('<POSTGRES_URL>'); print('scheme=', u.scheme); print('host=', u.hostname); print('database=', u.path.lstrip('/'))"
```

只读连接模板：

```bash
psql "$POSTGRES_URL" -c "select current_database(), current_user;"
```

记录：

| 检查项 | 记录 | 结论 |
|---|---|---|
| POSTGRES_URL 来源 | `<临时环境变量/命令参数>` | `<通过/不通过>` |
| POSTGRES_URL 脱敏展示 | `postgresql://<USER>:***@<HOST>:<PORT>/auto_wechat` | `<通过/不通过>` |
| database | `auto_wechat` | `<通过/不通过>` |
| current_user | `<USER>` | `<通过/不通过>` |
| 连接是否只读检查 | `<是/否>` | `<通过/不通过>` |

如果 PostgreSQL 连接失败，只记录失败，不继续 dry-run。

## 7. PG schema 检查

production dry-run 依赖目标 PostgreSQL schema 已存在。本 Runbook 不允许执行 Alembic upgrade。

只读 schema 检查模板：

```bash
psql "$POSTGRES_URL" -c "\dt"
psql "$POSTGRES_URL" -c "select * from alembic_version;"
psql "$POSTGRES_URL" -c "\d+ public.knowledge_categories"
psql "$POSTGRES_URL" -c "select conname, contype, pg_get_constraintdef(oid) from pg_constraint where conrelid = 'public.knowledge_categories'::regclass and conname = 'uk_knowledge_categories_scope_merchant_key';"
psql "$POSTGRES_URL" -c "select conname, contype, pg_get_constraintdef(oid) from pg_constraint where conrelid = 'public.knowledge_categories'::regclass and conname = 'ck_knowledge_categories_key_matches_category_key';"
```

记录：

| 检查项 | 预期 | 记录 |
|---|---|---|
| `\dt` | 包含 `alembic_version` 和 `knowledge_categories` | `<输出摘要>` |
| `alembic_version` | `0002_create_knowledge_categories` 或更高 | `<revision>` |
| `knowledge_categories` 表 | 存在 | `<是/否>` |
| UNIQUE 约束 | `uk_knowledge_categories_scope_merchant_key` | `<是/否>` |
| CHECK 约束 | `ck_knowledge_categories_key_matches_category_key` | `<是/否>` |
| schema 是否满足 dry-run | `<是/否>` | `<结论>` |

如果 schema 不存在或 revision 低于 `0002_create_knowledge_categories`，不能在本 Runbook 内执行 Alembic upgrade；必须转独立 schema-init 审批。

## 8. production dry-run 命令

命令必须显式传入 `--sqlite-db-path`、`--postgres-url`、`--dry-run`。命令不得携带 `--apply` 或 `--yes`。

全量 dry-run：

```bash
docker compose -f <COMPOSE_FILE> run --rm <API_SERVICE> \
  python scripts/migrate_knowledge_categories_sqlite_to_postgres.py \
    --sqlite-db-path <SQLITE_DB_PATH> \
    --postgres-url <POSTGRES_URL> \
    --dry-run
```

按商户过滤 dry-run：

```bash
docker compose -f <COMPOSE_FILE> run --rm <API_SERVICE> \
  python scripts/migrate_knowledge_categories_sqlite_to_postgres.py \
    --sqlite-db-path <SQLITE_DB_PATH> \
    --postgres-url <POSTGRES_URL> \
    --merchant-id <MERCHANT_ID> \
    --dry-run
```

执行记录必须保存脱敏命令：

```text
执行命令（脱敏）：python scripts/migrate_knowledge_categories_sqlite_to_postgres.py --sqlite-db-path <SQLITE_DB_PATH> --postgres-url postgresql://<USER>:***@<HOST>:<PORT>/auto_wechat --dry-run
```

## 9. dry-run 输出记录模板

| 输出项 | 记录 |
|---|---|
| SQLite 源行数 | `<COUNT>` |
| 过滤后待处理行数 | `<COUNT>` |
| PG 目标表是否存在 | `<true/false>` |
| Alembic revision | `<REVISION>` |
| revision 是否 >= `0002_create_knowledge_categories` | `<true/false>` |
| 预计 insert | `<COUNT>` |
| 预计 update | `<COUNT>` |
| 预计 skip | `<COUNT>` |
| error | `<COUNT>` |
| 字段映射预览 | `<脱敏摘要>` |
| 异常行列表 | `<无/脱敏摘要>` |
| PostgreSQL 写入是否 disabled | `<是/否>` |
| 最终状态 | `<DRY_RUN_PASS / DRY_RUN_FAIL>` |

判断提示：

1. `DRY_RUN_PASS` 且 `error = 0` 才能进入后续决策。
2. `insert/update > 0` 只代表存在可迁移计划，不代表允许 apply。
3. `source rows = 0` 时可记录 `SKIPPED_NO_SOURCE_ROWS`，不得为了验证 apply 而制造 production 数据。
4. 输出中如出现 PostgreSQL 写入行为，立即停止并升级事故排查。

## 10. 执行后安全确认

执行后必须逐项确认：

| 安全项 | 确认 |
|---|---|
| 未执行 `--apply` | `<是/否>` |
| 未执行 `--yes` | `<是/否>` |
| 未写 PostgreSQL | `<是/否>` |
| PostgreSQL 写入 disabled | `<是/否>` |
| 未修改 SQLite | `<是/否>` |
| 未切换 `DATABASE_URL` | `<是/否>` |
| 未开启 `KNOWLEDGE_CATEGORIES_ASYNC_PG_ENABLED` | `<是/否>` |
| 未重启 9000 | `<是/否>` |
| 未修改 `.env` | `<是/否>` |
| 未修改 docker-compose | `<是/否>` |
| 未执行 Alembic upgrade | `<是/否>` |
| 未 drop 表 | `<是/否>` |
| 未清 volume | `<是/否>` |
| 未触发 9100 / Milvus / RAG / LLM / 抖音发送 / 私信发送 / 自动回复 gate | `<是/否>` |

任一项为“否”，必须停止后续动作并升级风险记录。

## 11. 失败处理

失败时只记录原因，不现场临时修 production 配置。

处理规则：

1. 依赖失败：停止，记录，不改宿主机，不全局安装依赖。
2. SQLite 路径错误：停止，记录，重新确认路径和备份方案。
3. PG 连接失败：停止，记录，不继续 dry-run。
4. PG schema 缺失：停止，转 schema-init 独立审批。
5. Alembic revision 不满足：停止，转 schema-init 独立审批。
6. `error > 0`：停止，不 apply，先分析异常行。
7. 出现写入迹象：立即停止并升级事故排查。
8. 不现场修改 `.env`、docker-compose、Dockerfile 或迁移脚本。
9. 不通过重启 9000 作为默认处理。

失败记录模板：

```text
失败时间：<YYYY-MM-DD HH:mm:ss>
失败命令（脱敏）：<COMMAND_MASKED>
失败阶段：<approval / dependency / sqlite_path / sqlite_backup / pg_connection / pg_schema / dry_run>
失败输出摘要：<SUMMARY>
是否执行 --apply / --yes：否
是否写 PostgreSQL：否
是否修改 SQLite：否
是否切换 DATABASE_URL：否
建议后续任务：<TASK_NAME>
```

建议后续任务命名：

```text
P3-C11-FIX-PRODUCTION-DRY-RUN-DEPENDENCY-1
P3-C11-FIX-PRODUCTION-SQLITE-PATH-1
P3-C11-FIX-PRODUCTION-PG-SCHEMA-INIT-APPROVAL-1
P3-C11-FIX-PRODUCTION-DATA-ANOMALY-1
```

## 12. 后续判断

production dry-run 通过不等于允许 apply。

后续判断：

1. 如果 `source rows = 0`，可记录 `SKIPPED_NO_SOURCE_ROWS`，不进入 apply。
2. 如果 `insert/update = 0` 且 `error = 0`，记录无待迁移行，不进入 apply。
3. 如果 `insert > 0` 或 `update > 0`，且 `error = 0`，进入 production apply 审批模板。
4. 如果 `error > 0`，先处理异常行，不允许 apply。
5. 不允许从 dry-run 自动进入 apply。

后续任务只能是：

1. `P3-C11` production dry-run 执行记录回填。
2. `P3-C12` production apply 审批模板。
3. production schema-init 独立审批任务。
4. production dry-run 失败修复任务。

## 13. 本轮文档边界确认

本轮只生成 Runbook 文档，不执行 production dry-run。

本轮不执行：

1. 不执行 production 命令。
2. 不连接 production 数据库。
3. 不读取 production SQLite。
4. 不执行 dry-run。
5. 不执行 `--apply` / `--yes`。
6. 不写 PostgreSQL。
7. 不迁移数据。
8. 不切换 `DATABASE_URL`。
9. 不开启 `KNOWLEDGE_CATEGORIES_ASYNC_PG_ENABLED`。
10. 不改业务代码。
11. 不改迁移脚本。
12. 不改 Alembic revision。
13. 不改 docker-compose。
14. 不改 `.env`。
