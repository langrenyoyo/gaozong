# knowledge_categories 宝塔 staging apply 前置判断记录

任务：`P3-C9-PRECHECK-DB-9000-KNOWLEDGE-CATEGORIES-STAGING-APPLY-NECESSITY-1`

范围：本文只判断宝塔 staging 是否需要进入 `knowledge_categories` SQLite -> PostgreSQL apply。本轮只做文档，不执行宝塔命令，不连接 PostgreSQL，不读取 SQLite，不执行 `--apply`，不执行 `--yes`，不写 PostgreSQL 业务数据，不迁移数据，不切换 `DATABASE_URL`，不开启 `KNOWLEDGE_CATEGORIES_ASYNC_PG_ENABLED`。

## 1. 判断目标

本次判断目标：

1. 判断是否需要进入 P3-C9 staging apply。
2. 只针对 9000 `knowledge_categories`。
3. 不涉及全量 9000 表迁移。
4. 不涉及 9100 / Milvus / RAG。
5. 不涉及 production apply。
6. 不切换 9000 默认 `DATABASE_URL`。
7. 不默认开启 `KNOWLEDGE_CATEGORIES_ASYNC_PG_ENABLED`。

## 2. 输入依据

本判断只基于人工已贴回的 P3-C8B schema 初始化记录和 P3-C8 dry-run 记录。

### 2.1 P3-C8B schema 初始化通过

已确认：

1. PostgreSQL dev 容器 `auto-wechat-postgres-dev` 已启动并 healthy。
2. `auto_wechat` database 存在。
3. 初始化前 `auto_wechat` 库无表、无 `alembic_version`。
4. 使用一次性 `auto-wechat-api` 容器和临时 `DATABASE_URL` 执行 schema 初始化，未修改 `.env`。
5. 执行目标为 `migrations/postgres/auto_wechat/alembic.ini` 的 `0002_create_knowledge_categories`。
6. 初始化后 `alembic_version = 0002_create_knowledge_categories`。
7. `knowledge_categories` 表存在。
8. `uk_knowledge_categories_scope_merchant_key` UNIQUE 约束存在。
9. `ck_knowledge_categories_key_matches_category_key` CHECK 约束存在。
10. PG `knowledge_categories` 行数 = 0。

说明：P3-C8B schema 初始化会写 PostgreSQL schema，但未迁移 SQLite 业务数据，未写 PG 业务数据。

### 2.2 P3-C8 dry-run 通过

已确认：

1. SQLite 路径：`docker-data/auto_wechat_9000/auto_wechat.db`。
2. SQLite 已备份：`backups/p3_c8/auto_wechat_knowledge_categories_p3_c8_20260708_155855.db`。
3. SQLite `knowledge_categories` 表存在。
4. SQLite 源行数 = 0。
5. 过滤后待处理行数 = 0。
6. PostgreSQL 目标表存在: `True`。
7. Alembic revision: `0002_create_knowledge_categories`。
8. Alembic revision 至少为 `0002_create_knowledge_categories`: `True`。
9. dry-run insert/update/skip/error = 0/0/0/0。
10. 异常行数量 = 0。
11. 字段映射预览：`[]`。
12. PostgreSQL 写入: disabled。
13. 最终输出：`DRY_RUN_PASS`。

收尾已确认：

1. `POSTGRES_URL` 已 unset。
2. PostgreSQL dev 容器已停止。
3. `ps postgres` 无运行容器。
4. 未执行 `--apply` / `--yes`。
5. 未切换 `DATABASE_URL`。
6. 未开启 `KNOWLEDGE_CATEGORIES_ASYNC_PG_ENABLED`。

## 3. apply 必要性判断

结论：当前 staging 不需要执行 `knowledge_categories` apply。

依据：

1. 当前 SQLite 源行数 = 0。
2. 当前 PG `knowledge_categories` 行数 = 0。
3. dry-run insert/update/skip/error = 0/0/0/0。
4. 没有可迁移的 `knowledge_categories` 源业务行。
5. 执行 `--apply --yes` 不会产生业务价值。
6. 无数据 apply 容易造成误判，让后续记录看起来像已完成真实数据迁移。
7. 为避免无意义写操作和误操作风险，建议跳过 P3-C9 staging apply。

保留价值：

1. P3-C8B 已验证 Baota staging PostgreSQL schema 初始化链路可用。
2. P3-C8 已验证 Baota staging dry-run 链路可用。
3. schema 与 dry-run 记录可作为 staging 前置验证记录。

## 4. P3-C9 建议结论

推荐结论：

```text
P3-C9 staging apply: SKIPPED_NO_SOURCE_ROWS
```

原因：

```text
SQLite knowledge_categories source rows = 0
```

执行边界：

1. 不执行 `--apply` / `--yes`。
2. 不写 PostgreSQL 业务数据。
3. 不迁移 SQLite 数据。
4. 不切换 `DATABASE_URL`。
5. 不开启 `KNOWLEDGE_CATEGORIES_ASYNC_PG_ENABLED`。
6. 不启动 API contrast 灰度。
7. 不进入 production dry-run 或 production apply。

## 5. 后续替代路径

如果后续 Baota staging 出现 `knowledge_categories` 源数据，必须重新从 P3-C8 dry-run 开始。

重新触发 apply 审批的条件：

1. 明确允许读取 Baota staging SQLite。
2. SQLite 已重新备份。
3. 重新执行 P3-C8 dry-run。
4. dry-run 输出 `DRY_RUN_PASS`。
5. dry-run 显示 `insert > 0` 或 `update > 0`。
6. dry-run 显示 `error = 0`。
7. PostgreSQL 目标表存在。
8. Alembic revision 至少为 `0002_create_knowledge_categories`。
9. 人工确认 `<POSTGRES_URL>` 是 staging/dev `auto_wechat` 目标。
10. 人工重新审批是否进入 P3-C9 apply。

如果只是验证 apply 逻辑：

1. 继续使用 local/dev synthetic smoke。
2. 不在 Baota staging 手工制造假业务数据。
3. 不为了触发 apply 而修改真实 SQLite。
4. 不把 synthetic apply 结果当作真实业务迁移完成证明。

## 6. API contrast 是否需要执行

当前建议：不执行 staging API contrast 灰度。

原因：

1. 当前 SQLite 源行数 = 0。
2. 当前 PG `knowledge_categories` 行数 = 0。
3. 没有业务行可进行 staging 层面的响应语义对照。
4. 接口层 SQLite / PostgreSQL 语义对照已在 P3-C6 local/dev synthetic 数据中通过。
5. 在空数据下开启 PG pilot 没有业务收益，反而增加误操作风险。

记录口径：

```text
staging API contrast: NOT_RUN_NO_BUSINESS_ROWS
```

边界：

1. 默认仍不启用 `KNOWLEDGE_CATEGORIES_ASYNC_PG_ENABLED`。
2. 不把 PG pilot 默认开关改为 true。
3. 不切换默认 `DATABASE_URL`。
4. 如后续需要在 staging 开启 PG pilot，必须另行人工审批。

## 7. 风险与收益

### 7.1 跳过 apply 的风险

| 风险 | 说明 | 应对 |
|---|---|---|
| 后续出现新增源数据 | 当前判断只覆盖本次 P3-C8 dry-run 时间点 | 后续出现源数据时重新执行 P3-C8 dry-run |
| staging 没有真实业务行对照 | 无法用 staging 数据证明 API contrast | 继续保留 P3-C6 local/dev synthetic contrast 结果；真实数据出现后再对照 |
| 误以为生产已完成迁移 | 当前只是 staging 空数据判断 | 文档明确 `SKIPPED_NO_SOURCE_ROWS`，不代表 production 迁移完成 |

### 7.2 执行空数据 apply 的风险

| 风险 | 说明 | 应对 |
|---|---|---|
| 无意义写操作 | 源行数为 0 时 apply 不产生业务价值 | 跳过 `--apply --yes` |
| 审计误判 | 可能被误读为已完成真实数据迁移 | 明确记录 skipped 原因 |
| 误切配置 | apply 阶段更容易误用 `DATABASE_URL` 或 PG pilot | 本轮不进入 apply |
| 灰度误判 | 空数据开启 PG pilot 没有验证价值 | 不执行空数据灰度 |

### 7.3 当前收益

1. Baota staging schema 初始化链路已通过。
2. Baota staging dry-run 链路已通过。
3. 当前空源数据事实已被记录。
4. 跳过 apply 可降低误操作风险。

## 8. 人工审批结论区

| 审批项 | 记录 |
|---|---|
| 是否确认跳过 P3-C9 apply | `<是/否>` |
| 审批人 | `<姓名>` |
| 审批时间 | `<YYYY-MM-DD HH:mm:ss>` |
| 是否确认不执行 `--apply / --yes` | `<是/否>` |
| 是否确认不写 PostgreSQL 业务数据 | `<是/否>` |
| 是否确认不切换 `DATABASE_URL` | `<是/否>` |
| 是否确认不开启 `KNOWLEDGE_CATEGORIES_ASYNC_PG_ENABLED` | `<是/否>` |
| 备注 | `<补充说明>` |

## 9. 本轮边界确认

本轮只做文档记录。

本轮不执行：

1. 不执行宝塔命令。
2. 不连接 PostgreSQL。
3. 不读取 SQLite。
4. 不执行 `--apply`。
5. 不执行 `--yes`。
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

## 10. P3-C10 后续审批模板状态

P3-C10 已进入 production dry-run 审批模板阶段：

```text
docs/ai/03_data_and_migration/KNOWLEDGE_CATEGORIES_PRODUCTION_DRY_RUN_APPROVAL_TEMPLATE.md
```

P3-C10 只审批 production dry-run，不审批 apply，不审批切换默认 `DATABASE_URL`，不审批开启 `KNOWLEDGE_CATEGORIES_ASYNC_PG_ENABLED`。

P3-C10 继承 P3-C9-PRECHECK 结论：

```text
P3-C9 staging apply: SKIPPED_NO_SOURCE_ROWS
```

边界确认：

1. 本轮不执行 production dry-run。
2. 本轮不连接 production。
3. 本轮不读取 production SQLite。
4. 本轮不执行 `--apply` / `--yes`。
5. 本轮不写 PostgreSQL 业务数据。
6. 本轮不切换 `DATABASE_URL`。
7. 本轮不开启 `KNOWLEDGE_CATEGORIES_ASYNC_PG_ENABLED`。
