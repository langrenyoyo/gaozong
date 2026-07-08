# knowledge_categories production dry-run approval template

任务：`P3-C10-DB-9000-KNOWLEDGE-CATEGORIES-PRODUCTION-DRY-RUN-APPROVAL-TEMPLATE-1`

本模板只用于审批 production dry-run。它不是执行记录，不授权 apply，不授权切换数据库，不授权开启 PG pilot。

关键词口径：不执行 --apply / --yes；不写 PostgreSQL；不切换 DATABASE_URL；不开启 KNOWLEDGE_CATEGORIES_ASYNC_PG_ENABLED。

## 1. 审批目标

本次审批只覆盖：

1. production dry-run。
2. 9000 `knowledge_categories`。
3. 读取 production SQLite 并做 PostgreSQL 只读 schema 检查。
4. 输出迁移计划和异常行记录。

本次审批不覆盖：

1. 不审批 `--apply`。
2. 不审批 `--yes`。
3. 不审批写 PostgreSQL。
4. 不审批切换默认 `DATABASE_URL`。
5. 不审批开启 `KNOWLEDGE_CATEGORIES_ASYNC_PG_ENABLED`。
6. 不涉及 9100 / Milvus / RAG。
7. 不涉及 LLM、抖音发送、私信发送或自动回复 gate。

## 2. 执行边界

1. 本机 VibeCoding 不能操作 production。
2. production 命令只能由人工或运维在审批通过后执行。
3. 本模板只是审批表，不是执行记录。
4. 审批通过后也只能执行 dry-run，不允许 apply。
5. production dry-run 输出必须回填到后续执行记录文档，不能口头确认。

## 3. 审批前置条件

审批前必须逐项确认：

1. 当前代码 commit hash 已确认。
2. P3-C8B staging schema init 已通过。
3. P3-C8 staging dry-run 已通过。
4. P3-C9 staging apply 已跳过，原因已记录为 `SKIPPED_NO_SOURCE_ROWS`。
5. production SQLite DB 路径已确认。
6. production SQLite backup 方案已确认。
7. production PostgreSQL 目标已确认。
8. production PostgreSQL schema 初始化方案已确认。
9. 执行人已确认。
10. 审批人已确认。
11. 回滚负责人已确认。
12. 执行时间窗口已确认。

说明：如果 production PostgreSQL schema 尚未初始化到 `0002_create_knowledge_categories`，不得在本审批中顺手执行 Alembic upgrade。schema 初始化必须另走独立 schema-init 审批。

## 4. production dry-run 允许动作

审批通过后仅允许：

1. 读取 production SQLite。
2. 连接 production 或明确的 production-target PostgreSQL 做只读 schema 检查。
3. 查询 `alembic_version`。
4. 检查 `knowledge_categories` 表是否存在。
5. 输出 insert/update/skip/error 计划。
6. 输出字段映射预览。
7. 记录异常行。
8. 确认 PostgreSQL 写入为 disabled。

## 5. production dry-run 禁止动作

必须禁止：

1. 禁止 `--apply`。
2. 禁止 `--yes`。
3. 禁止写 PostgreSQL。
4. 禁止切换 `DATABASE_URL`。
5. 禁止开启 `KNOWLEDGE_CATEGORIES_ASYNC_PG_ENABLED`。
6. 禁止重启 9000。
7. 禁止修改 `.env`。
8. 禁止修改 docker-compose。
9. 禁止执行 Alembic upgrade，除非另有独立 schema-init 审批。
10. 禁止 drop 表。
11. 禁止清 volume。
12. 禁止迁移真实数据。
13. 禁止触发 9100 / Milvus / RAG / LLM。
14. 禁止触发抖音发送、私信发送或自动回复 gate。

## 6. 审批表字段

| 字段 | 记录 |
|---|---|
| 申请人 | `<姓名>` |
| 审批人 | `<姓名>` |
| 执行人 | `<姓名>` |
| 回滚负责人 | `<姓名>` |
| 执行时间窗口 | `<YYYY-MM-DD HH:mm:ss - YYYY-MM-DD HH:mm:ss>` |
| 代码 commit hash | `<commit_hash>` |
| production SQLite 路径（可脱敏） | `<SQLITE_DB_PATH>` |
| SQLite backup 路径（可脱敏） | `<BACKUP_PATH>` |
| PostgreSQL URL 脱敏 | `<POSTGRES_URL_MASKED>` |
| database 名称 | `auto_wechat` |
| 是否仅 dry-run | `<是/否>` |
| 是否确认不执行 `--apply / --yes` | `<是/否>` |
| 是否确认不切 `DATABASE_URL` | `<是/否>` |
| 是否确认不开启 PG pilot | `<是/否>` |
| 是否确认不重启 9000 | `<是/否>` |
| 是否确认不执行 Alembic upgrade | `<是/否>` |
| 审批结论 | `<批准/拒绝/暂缓>` |
| 备注 | `<补充说明>` |

## 7. dry-run 命令模板

命令必须使用占位符，不得包含真实密码。

通过一次性服务容器执行的模板：

```bash
docker compose -f <COMPOSE_FILE> run --rm <API_SERVICE> \
  python scripts/migrate_knowledge_categories_sqlite_to_postgres.py \
    --sqlite-db-path <SQLITE_DB_PATH> \
    --postgres-url <POSTGRES_URL> \
    --dry-run
```

按商户过滤的模板：

```bash
docker compose -f <COMPOSE_FILE> run --rm <API_SERVICE> \
  python scripts/migrate_knowledge_categories_sqlite_to_postgres.py \
    --sqlite-db-path <SQLITE_DB_PATH> \
    --postgres-url <POSTGRES_URL> \
    --merchant-id <MERCHANT_ID 可选> \
    --dry-run
```

记录要求：

1. `<POSTGRES_URL>` 只能出现在命令执行环境中。
2. 文档记录只能写脱敏 URL。
3. 命令必须显式传入 `--sqlite-db-path`、`--postgres-url`、`--dry-run`。
4. 命令不得依赖隐式 `DATABASE_URL`。

## 8. 输出记录模板

| 输出项 | 记录 |
|---|---|
| SQLite 源行数 | `<number>` |
| 过滤后待处理行数 | `<number>` |
| PG 表是否存在 | `<true/false>` |
| Alembic revision | `<revision>` |
| Alembic revision 是否 >= `0002_create_knowledge_categories` | `<true/false>` |
| insert/update/skip/error | `<n/n/n/n>` |
| 字段映射预览 | `<脱敏摘要>` |
| 异常行列表 | `<无/脱敏摘要>` |
| 最终状态 | `<DRY_RUN_PASS/DRY_RUN_FAIL>` |
| 是否未写 PostgreSQL | `<是/否>` |
| 是否未执行 `--apply / --yes` | `<是/否>` |
| 是否未切换 `DATABASE_URL` | `<是/否>` |
| 是否未开启 `KNOWLEDGE_CATEGORIES_ASYNC_PG_ENABLED` | `<是/否>` |

## 9. 通过 / 失败判断标准

dry-run 通过条件：

1. 输出 `DRY_RUN_PASS`。
2. `error = 0`。
3. PG `knowledge_categories` 表存在。
4. Alembic revision >= `0002_create_knowledge_categories`。
5. PostgreSQL 写入为 disabled。
6. 未执行 `--apply` / `--yes`。
7. 未切换 `DATABASE_URL`。
8. 未开启 `KNOWLEDGE_CATEGORIES_ASYNC_PG_ENABLED`。

dry-run 失败条件：

1. SQLite 路径错误。
2. PG 连接失败。
3. PG schema 不存在。
4. Alembic revision 不满足。
5. `error > 0`。
6. 输出中出现写入行为。
7. 使用了 `--apply` 或 `--yes`。
8. 任何命令越权。

## 10. 后续决策

production dry-run 后不能自动 apply。

后续只允许进入以下独立任务之一：

1. P3-C11：production dry-run 人工执行 Runbook 和执行记录模板。
2. P3-C12：production apply 审批模板。

是否进入 P3-C12 取决于 production dry-run 结果和人工审批。即使 dry-run 通过，也不代表允许 apply。

P3-C11 已生成正式人工 Runbook：

```text
docs/ai/03_data_and_migration/KNOWLEDGE_CATEGORIES_PRODUCTION_DRY_RUN_RUNBOOK.md
```

P3-C11 仍不执行 production dry-run，不连接 production，不读取 production SQLite，不执行 apply；production 操作必须由人工/运维按 P3-C10 approval 结果执行并回填记录。

## 11. 本轮边界确认

本轮只做文档。

本轮不执行：

1. 不执行生产命令。
2. 不连接生产数据库。
3. 不读取生产 SQLite。
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
15. 不提交非文档改动。
