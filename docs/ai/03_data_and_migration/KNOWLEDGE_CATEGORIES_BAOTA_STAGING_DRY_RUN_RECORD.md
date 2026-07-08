# knowledge_categories 宝塔 staging dry-run 人工 Runbook 与执行记录模板

任务：`P3-C8-BAOTA-STAGING-DRY-RUN-MANUAL-RUNBOOK-1`

范围：本文用于指导宝塔执行人在 Baota staging 宿主机代码目录手动执行 `knowledge_categories` SQLite -> PostgreSQL 迁移 dry-run，并记录结果。本机 VibeCoding 只生成 Runbook 和记录模板，不操作宝塔服务器，不执行宝塔命令，不连接宝塔数据库，不读取宝塔 SQLite。

当前执行状态：P3-C8 已被 PG schema 未初始化阻塞。人工预检查已确认 PostgreSQL `auto_wechat` database 存在，但 `alembic_version` 不存在且无业务表；dry-run 的只读 schema 检查无法继续。进入本文 dry-run 前，必须先按以下 Runbook 完成 Baota staging schema 初始化：

```text
docs/ai/03_data_and_migration/KNOWLEDGE_CATEGORIES_BAOTA_STAGING_SCHEMA_INIT_RUNBOOK.md
```

P3-C8B 只允许初始化 `auto_wechat` schema 到 `0002_create_knowledge_categories`，不得迁移 SQLite 数据，不得切换 9000 默认数据库。

## 1. 本机 VibeCoding 边界说明

本轮只允许本地修改文档。

本机 VibeCoding 不执行：

1. 不登录宝塔服务器。
2. 不执行宝塔命令。
3. 不连接宝塔 PostgreSQL。
4. 不读取宝塔 SQLite。
5. 不执行 `--apply`。
6. 不执行 `--yes`。
7. 不执行 Alembic upgrade。
8. 不重启 9000。
9. 不修改 `.env`、docker-compose、Dockerfile 或业务代码。
10. 不迁移真实数据。

宝塔 staging dry-run 的真实输出必须由执行人贴回，才能判断是否进入 P3-C9。

## 2. 宝塔执行人前置条件

执行人必须在执行前逐项确认并记录：

| 检查项 | 记录值 | 结论 |
|---|---|---|
| 执行机器 | `<宝塔 staging 宿主机 / 其他>` | `<通过/不通过>` |
| 当前代码目录 | `<CODE_DIR>` | `<通过/不通过>` |
| git commit hash | `<COMMIT_HASH>` | `<通过/不通过>` |
| 工作区是否干净 | `<git status --short 输出>` | `<通过/不通过>` |
| Python 可用 | `<python --version>` | `<通过/不通过>` |
| 依赖可用 | `<见第 4 节>` | `<通过/不通过>` |
| SQLite DB 路径已确认 | `<SQLITE_DB_PATH>` | `<通过/不通过>` |
| SQLite 已备份 | `<BACKUP_FILE>` | `<通过/不通过>` |
| PostgreSQL URL 是 staging/dev | `<脱敏 URL>` | `<通过/不通过>` |
| PostgreSQL database 是 auto_wechat | `<是/否>` | `<通过/不通过>` |
| PG schema 已初始化到 0002_create_knowledge_categories | `<是/否>` | `<通过/不通过>` |
| 不使用隐式 DATABASE_URL | `<是/否>` | `<通过/不通过>` |
| 未携带 --apply | `<是/否>` | `<通过/不通过>` |
| 未携带 --yes | `<是/否>` | `<通过/不通过>` |
| 未开启 PG pilot 默认开关 | `<是/否>` | `<通过/不通过>` |
| 默认 DATABASE_URL 未切 PostgreSQL | `<是/否>` | `<通过/不通过>` |

任一项不通过，停止 dry-run 并记录失败原因。

## 3. 宝塔宿主机代码目录执行方式

推荐在宝塔 staging 宿主机代码目录执行，而不是在 9000 生产式镜像容器内执行。

原因：

1. 当前 Dockerfile / Dockerfile.backend.dev 未保证 `scripts/` 和 `migrations/` 已 COPY 到镜像内。
2. 宿主机代码目录可以直接访问 `scripts/`、`migrations/` 和文档。
3. dry-run 可以显式传入 `--sqlite-db-path` 和 `--postgres-url`，边界更清楚。

命令模板：

```bash
cd <CODE_DIR>
git rev-parse HEAD
git status --short
```

记录：

```text
执行位置：<宝塔 staging 宿主机代码目录 / 其他>
代码目录：<CODE_DIR>
commit hash：<COMMIT_HASH>
git status --short：<输出；为空表示工作区干净>
```

## 4. Python 依赖检查命令

先确认 Python 和脚本运行依赖可用。

```bash
python --version
python -c "import sqlalchemy, asyncpg, alembic; print('sqlalchemy', sqlalchemy.__version__); print('asyncpg', asyncpg.__version__); print('alembic', alembic.__version__)"
python scripts/migrate_knowledge_categories_sqlite_to_postgres.py --help
```

记录：

| 项目 | 输出 | 结论 |
|---|---|---|
| Python 版本 | `<输出>` | `<通过/不通过>` |
| sqlalchemy | `<输出>` | `<通过/不通过>` |
| asyncpg | `<输出>` | `<通过/不通过>` |
| alembic | `<输出>` | `<通过/不通过>` |
| 迁移脚本 help | `<是否显示参数>` | `<通过/不通过>` |

如果缺少依赖，不要临时修改生产配置；记录失败原因并拆后续依赖修复任务。

## 5. SQLite 路径确认命令模板

SQLite 路径必须由执行人从 staging 实际部署确认，不允许猜测。

```bash
ls -lh <SQLITE_DB_PATH>
python -c "from pathlib import Path; p=Path('<SQLITE_DB_PATH>'); print(p.resolve()); print('exists=', p.exists()); print('size=', p.stat().st_size if p.exists() else 'missing')"
```

如允许读取 SQLite 元数据，可记录 `knowledge_categories` 行数：

```bash
python -c "import sqlite3; p='<SQLITE_DB_PATH>'; conn=sqlite3.connect(p); print(conn.execute('select count(*) from knowledge_categories').fetchone()[0]); conn.close()"
```

记录：

```text
SQLite DB 路径（可脱敏）：<SQLITE_DB_PATH>
SQLite 文件大小：<SIZE>
knowledge_categories 源行数：<COUNT / 未读取>
路径确认人：<NAME>
确认时间：<YYYY-MM-DD HH:mm:ss>
```

## 6. SQLite 备份命令模板

dry-run 本身不写 SQLite，但读取 staging SQLite 前仍必须先备份。

```bash
mkdir -p <BACKUP_DIR>
cp -p <SQLITE_DB_PATH> <BACKUP_DIR>/auto_wechat_knowledge_categories_p3_c8_$(date +%Y%m%d_%H%M%S).db
ls -lh <BACKUP_DIR>/auto_wechat_knowledge_categories_p3_c8_*.db
```

记录：

```text
备份目录（可脱敏）：<BACKUP_DIR>
备份文件（可脱敏）：<BACKUP_FILE>
备份文件大小：<SIZE>
备份执行人：<NAME>
备份时间：<YYYY-MM-DD HH:mm:ss>
```

## 7. PostgreSQL URL 脱敏记录方式

执行命令必须显式传入 `--postgres-url <POSTGRES_URL>`，不得依赖隐式 `DATABASE_URL`。

记录时不得写完整 URL。推荐格式：

```text
postgresql+asyncpg://<USER>:***@<HOST>:<PORT>/auto_wechat
```

确认项：

| 检查项 | 记录值 | 结论 |
|---|---|---|
| URL 来源 | `--postgres-url` | `<通过/不通过>` |
| scheme | `<postgresql / postgresql+asyncpg / postgresql+psycopg>` | `<通过/不通过>` |
| host | `<HOST>` | `<通过/不通过>` |
| database | `auto_wechat` | `<通过/不通过>` |
| password 已脱敏 | `<是/否>` | `<通过/不通过>` |
| 非 production 目标 | `<是/否>` | `<通过/不通过>` |

禁止把真实 password、token、完整 URI 写入文档、群聊或提交记录。

## 8. dry-run 命令模板

全量 dry-run：

```bash
python scripts/migrate_knowledge_categories_sqlite_to_postgres.py \
  --sqlite-db-path <SQLITE_DB_PATH> \
  --postgres-url <POSTGRES_URL> \
  --dry-run
```

按商户过滤 dry-run：

```bash
python scripts/migrate_knowledge_categories_sqlite_to_postgres.py \
  --sqlite-db-path <SQLITE_DB_PATH> \
  --postgres-url <POSTGRES_URL> \
  --merchant-id <MERCHANT_ID> \
  --dry-run
```

小批量 dry-run：

```bash
python scripts/migrate_knowledge_categories_sqlite_to_postgres.py \
  --sqlite-db-path <SQLITE_DB_PATH> \
  --postgres-url <POSTGRES_URL> \
  --limit <LIMIT> \
  --dry-run
```

本轮禁止执行以下命令形态：

```bash
python scripts/migrate_knowledge_categories_sqlite_to_postgres.py --apply
python scripts/migrate_knowledge_categories_sqlite_to_postgres.py --yes
python scripts/smoke_auto_wechat_alembic_knowledge_categories.py
python -m alembic -c migrations/postgres/auto_wechat/alembic.ini upgrade head
```

说明：`smoke_auto_wechat_alembic_knowledge_categories.py` 会执行 Alembic `upgrade head`，不属于 P3-C8 只读 dry-run 默认步骤。

## 9. dry-run 输出记录表

请把脚本输出按下表记录。敏感 URL 必须脱敏。

| 输出项 | 记录值 |
|---|---|
| dry-run 明确提示不写 PostgreSQL | `<是/否>` |
| PostgreSQL URL 脱敏展示 | `<脱敏 URL>` |
| SQLite 源行数 | `<COUNT>` |
| 过滤后待处理行数 | `<COUNT>` |
| PostgreSQL 目标表存在 | `<true/false>` |
| Alembic revision | `<REVISION>` |
| Alembic revision 至少为 0002_create_knowledge_categories | `<true/false>` |
| 字段映射预览 | `<输出摘要>` |
| 异常行数量 | `<COUNT>` |
| PostgreSQL 写入 | `<disabled>` |
| 最终状态 | `<DRY_RUN_PASS / MIGRATION_FAIL>` |

## 10. insert / update / skip / error 记录表

| 指标 | 数量 | 说明 |
|---|---:|---|
| 预计 insert | `<N>` | `<说明>` |
| 预计 update | `<N>` | `<说明>` |
| 预计 skip | `<N>` | `<说明>` |
| 异常行 error | `<N>` | `<说明>` |

判断规则：

1. `error > 0`：不得进入 P3-C9。
2. `PostgreSQL 目标表存在=false`：不得进入 P3-C9。
3. `Alembic revision` 低于 `0002_create_knowledge_categories`：不得进入 P3-C9。
4. insert / update / skip 数量必须能解释来源，不能只记录总数。
5. 如果 `alembic_version` 不存在或 PG 空库无表，先执行 P3-C8B schema 初始化 Runbook，不得在 P3-C8 中临时执行 Alembic upgrade。

## 11. 异常行记录表

如 dry-run 输出异常行预览，必须逐项记录。

| 行标识 | merchant_id | category_key/key | 异常原因 | 处理建议 |
|---|---|---|---|---|
| `<id 或序号>` | `<merchant_id>` | `<category_key>` | `<原因>` | `<建议>` |

常见异常：

1. 缺少 `category_key`。
2. 缺少 `name`。
3. merchant 分类缺少 `merchant_id`。
4. 时间字段无法解析。
5. PostgreSQL schema 不可用。
6. PostgreSQL URL 配置错误。

异常行未处理前，不允许进入 apply 或 API contrast。

## 12. 安全确认清单

执行后必须逐项确认：

| 安全项 | 确认 |
|---|---|
| 未写 PostgreSQL | `<是/否>` |
| 未执行 `--apply` | `<是/否>` |
| 未执行 `--yes` | `<是/否>` |
| 未切换 `DATABASE_URL` | `<是/否>` |
| 未开启 `KNOWLEDGE_CATEGORIES_ASYNC_PG_ENABLED` | `<是/否>` |
| 未重启 9000 | `<是/否>` |
| 未修改 `.env` | `<是/否>` |
| 未修改 docker-compose | `<是/否>` |
| 未执行 Alembic upgrade | `<是/否>` |
| 未 drop 表 | `<是/否>` |
| 未清 volume | `<是/否>` |
| 未迁移真实数据 | `<是/否>` |
| 未触发 LLM / 抖音发送 / 私信发送 / 自动回复 gate | `<是/否>` |

任一项为“否”，必须停止并升级为事故 / 风险记录。

## 13. 失败处理规则

dry-run 失败时只记录失败原因，不做临时修复。

禁止：

1. 不临时修改生产 `.env`。
2. 不临时改 docker-compose。
3. 不直接执行 Alembic upgrade。
4. 不直接执行 `--apply --yes`。
5. 不 drop 表。
6. 不清 PostgreSQL volume。
7. 不重启 9000 作为默认处理。
8. 不在生产式容器里临时安装依赖后继续执行。

失败记录模板：

```text
失败时间：<YYYY-MM-DD HH:mm:ss>
失败命令：<脱敏命令>
失败输出：<MIGRATION_FAIL 或异常摘要>
失败阶段：<依赖检查 / SQLite 路径 / SQLite 备份 / PostgreSQL URL / PG schema / dry-run 计划>
是否写 PostgreSQL：否
是否执行 --apply / --yes：否
建议后续任务：<任务名>
```

建议后续任务命名：

```text
P3-C8-FIX-BAOTA-STAGING-DRY-RUN-DEPENDENCY-1
P3-C8-FIX-BAOTA-STAGING-SQLITE-PATH-1
P3-C8-FIX-BAOTA-STAGING-PG-SCHEMA-READONLY-1
P3-C8-FIX-BAOTA-STAGING-DATA-ANOMALY-1
```

## 14. 是否允许进入 P3-C9 的判断标准

只有同时满足以下条件，才允许进入 P3-C9：

1. dry-run 在宝塔 staging 宿主机代码目录完成。
2. git commit hash 已记录。
3. 工作区干净或非本轮变更已明确排除。
4. Python 依赖检查通过。
5. SQLite 路径已确认。
6. SQLite 已备份。
7. PostgreSQL URL 已脱敏记录，且目标为 staging/dev `auto_wechat`。
8. dry-run 输出 `DRY_RUN_PASS`。
9. PostgreSQL 目标表存在。
10. Alembic revision 至少为 `0002_create_knowledge_categories`。
11. insert / update / skip / error 计划已记录。
12. `error = 0`，或异常行已有明确处理方案并另起任务。
13. 已确认未写 PostgreSQL。
14. 已确认未执行 `--apply` / `--yes`。
15. 已确认未切换默认数据库。
16. 已确认未开启 PG pilot。
17. 执行结果已贴回并完成审查。

任一条件不满足，不进入 P3-C9。

## 15. 本轮文档边界确认

本轮新增本文档并同步现有上下文文档。

本轮不执行：

1. 不执行宝塔命令。
2. 不连接 PostgreSQL。
3. 不读取宝塔 SQLite。
4. 不写 PostgreSQL。
5. 不执行 `--apply`。
6. 不执行 `--yes`。
7. 不切换 `DATABASE_URL`。
8. 不开启 `KNOWLEDGE_CATEGORIES_ASYNC_PG_ENABLED`。
9. 不重启 9000。
10. 不改 `.env`。
11. 不改 docker-compose。
12. 不执行 Alembic upgrade。
13. 不 drop 表。
14. 不清 volume。
15. 不迁移真实数据。
