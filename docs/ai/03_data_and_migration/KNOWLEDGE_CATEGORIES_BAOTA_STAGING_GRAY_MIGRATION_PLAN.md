# knowledge_categories 宝塔 staging / 灰度迁移预案

任务：`P3-C7-DB-9000-KNOWLEDGE-CATEGORIES-BAOTA-STAGING-GRAY-MIGRATION-PLAN-1`

范围：本文只为 9000 `knowledge_categories` 从 SQLite -> PostgreSQL 制定 Baota staging / gray migration 操作预案。本轮只做文档，不执行宝塔命令，不连接生产数据库，不迁移真实数据，不切换默认数据库，不修改 `DATABASE_URL` 默认值，不默认开启 `KNOWLEDGE_CATEGORIES_ASYNC_PG_ENABLED`。

## 1. 目标与非目标

### 1.1 目标

1. 只针对 9000 `knowledge_categories`。
2. 在宝塔环境中形成 staging dry-run、受控 apply、API contrast、回滚和审批模板。
3. 固化 `SQLite backup`、PostgreSQL schema 检查、`0002_create_knowledge_categories` revision 检查和灰度熔断规则。
4. 明确 PostgreSQL 仍是 Docker Compose 容器内 PostgreSQL，不是外部托管数据库。
5. 明确默认运行仍是 SQLite，PG pilot 只能显式开启。

### 1.2 非目标

1. 不迁移全量 9000 表。
2. 不迁移 9100。
3. 不迁移 Milvus / RAG。
4. 不迁移真实生产数据。
5. 不切换默认 `DATABASE_URL`。
6. 不默认开启 `KNOWLEDGE_CATEGORIES_ASYNC_PG_ENABLED`。
7. 不执行宝塔命令。
8. 不修改迁移脚本行为。
9. 不修改 Alembic revision。
10. 不修改 docker-compose、`.env` 或 `.env.example`。

## 2. 环境分层

### 2.1 local dev

local dev 已完成以下验证：

1. P3-C2：PostgreSQL Alembic schema smoke 已验证 `revision = 0002_create_knowledge_categories`，并确认 `knowledge_categories` 表、索引、唯一约束、check constraint 存在。
2. P3-C5：synthetic SQLite -> dev PostgreSQL apply smoke 已验证受控 apply 和幂等 upsert。
3. P3-C6：`GET /knowledge-categories` SQLite / PostgreSQL API contrast 已验证 synthetic 数据下响应语义一致。

local dev 结论只能证明本地受控路径可用，不能替代 Baota staging 或 production 验证。

### 2.2 Baota staging

Baota staging 用于验证真实容器路径、真实卷挂载、SQLite 备份、PostgreSQL 容器网络、只读 dry-run 和受控灰度流程。

Baota staging 阶段允许形成执行记录，但每一步都必须有人工审批。本预案本轮不实际执行。

### 2.3 Baota production

Baota production 暂不执行。当前只形成审批后的操作模板，production dry-run、production apply、默认数据库切换都必须进入后续独立任务和审批。

## 3. 前置检查清单

执行 Baota staging dry-run 或 apply 前，必须逐项记录：

1. git commit hash：确认当前代码版本。
2. Docker Compose 服务状态：确认 9000、PostgreSQL 和相关容器状态。
3. 9000 当前健康状态：确认 SQLite 默认路径下服务可用。
4. SQLite DB 路径确认：记录 `<SQLITE_DB_PATH>`，不得猜测路径。
5. SQLite 文件备份：完成 `<BACKUP_PATH>` 下的 `SQLite backup`。
6. PostgreSQL 容器是否存在：确认 `<POSTGRES_CONTAINER>` 正常运行。
7. PostgreSQL database `auto_wechat` 是否存在。
8. Alembic revision 是否到 `0002_create_knowledge_categories` 或更高。
9. SQLite `knowledge_categories` 当前行数。
10. PostgreSQL `knowledge_categories` 当前行数。
11. 当前 PG pilot 开关状态：`KNOWLEDGE_CATEGORIES_ASYNC_PG_ENABLED`。
12. 当前默认 `DATABASE_URL` 是否仍为 SQLite。
13. 当前 `POSTGRES_URL` 是否为 staging 目标，且输出已脱敏。
14. 当前是否存在未提交代码变更。

命令模板：

```bash
git rev-parse HEAD
git status --short

docker compose -f <COMPOSE_FILE> ps
curl -fsS <AUTO_WECHAT_HEALTH_URL>

ls -lh <SQLITE_DB_PATH>
mkdir -p <BACKUP_PATH>
cp -p <SQLITE_DB_PATH> <BACKUP_PATH>/auto_wechat_knowledge_categories_$(date +%Y%m%d_%H%M%S).db

sqlite3 <SQLITE_DB_PATH> "select count(*) from knowledge_categories;"

docker compose -f <COMPOSE_FILE> exec <POSTGRES_CONTAINER> psql -U <POSTGRES_USER> -d postgres -c "\l"
docker compose -f <COMPOSE_FILE> exec <POSTGRES_CONTAINER> psql -U <POSTGRES_USER> -d auto_wechat -c "select version_num from alembic_version;"
docker compose -f <COMPOSE_FILE> exec <POSTGRES_CONTAINER> psql -U <POSTGRES_USER> -d auto_wechat -c "select count(*) from knowledge_categories;"
```

注意：命令中的 `<POSTGRES_USER>`、`<POSTGRES_URL>`、`<SQLITE_DB_PATH>`、`<BACKUP_PATH>`、`<COMPOSE_FILE>`、`<API_CONTAINER>`、`<POSTGRES_CONTAINER>` 都必须由执行人按 staging 环境填写，不能把真实密码写入文档或 git。

## 3A. P3-C8B / P3-C8 执行状态

P3-C8 人工预检查曾确认 Baota staging PostgreSQL `auto_wechat` database 存在，但当时为空库：

1. `alembic_version` 不存在。
2. `knowledge_categories` 表不存在。
3. P3-C8 dry-run 的 PG schema 只读检查无法继续。

该阻塞已通过 P3-C8B 人工 Runbook 解除：

```text
docs/ai/03_data_and_migration/KNOWLEDGE_CATEGORIES_BAOTA_STAGING_SCHEMA_INIT_RUNBOOK.md
```

P3-C8B 已在 Baota staging 执行通过：使用一次性 `auto-wechat-api` 容器和临时 `DATABASE_URL` 执行 `migrations/postgres/auto_wechat/alembic.ini` 到 `0002_create_knowledge_categories`。schema 初始化写入了 PostgreSQL schema，只创建 `alembic_version`、`knowledge_categories` 表、索引、唯一约束和 check constraint；未迁移 SQLite 数据，未执行 `--apply --yes`，未切换默认 `DATABASE_URL`，未默认开启 `KNOWLEDGE_CATEGORIES_ASYNC_PG_ENABLED`。

P3-C8 dry-run 也已执行通过，输出 `DRY_RUN_PASS`。当前 SQLite 源行数为 0，因此 dry-run 计划为 insert=0、update=0、skip=0、error=0，`PostgreSQL 写入: disabled`。PostgreSQL dev 容器已停止。

## 4. Baota staging dry-run 步骤

dry-run 必须不写 PostgreSQL，只输出计划和风险。

### 4.1 schema 状态确认

P3-C8 dry-run 默认只做只读检查，不在 dry-run 步骤里执行 Alembic upgrade。若目标 PostgreSQL 为空库，先按 P3-C8B Runbook 初始化 schema。

schema 初始化完成后，再确认目标 PostgreSQL schema 可用：

```bash
docker compose -f <COMPOSE_FILE> exec <POSTGRES_CONTAINER> psql -U <POSTGRES_USER> -d auto_wechat -c "select * from alembic_version;"
docker compose -f <COMPOSE_FILE> exec <POSTGRES_CONTAINER> psql -U <POSTGRES_USER> -d auto_wechat -c "\d+ knowledge_categories"
```

预期：

1. `alembic_version` 为 `0002_create_knowledge_categories` 或更高。
2. `knowledge_categories` 表、索引、唯一约束、check constraint 均存在。
3. `knowledge_categories` 行数符合预期；当前 P3-C8 前置结果期望为 0。
4. 输出 URL 或连接信息必须脱敏。

### 4.2 dry-run 迁移计划

```bash
python scripts/migrate_knowledge_categories_sqlite_to_postgres.py \
  --sqlite-db-path <SQLITE_DB_PATH> \
  --postgres-url <POSTGRES_URL> \
  --dry-run
```

可选缩小范围：

```bash
python scripts/migrate_knowledge_categories_sqlite_to_postgres.py \
  --sqlite-db-path <SQLITE_DB_PATH> \
  --postgres-url <POSTGRES_URL> \
  --merchant-id <MERCHANT_ID> \
  --limit <LIMIT> \
  --dry-run
```

dry-run 输出必须包含：

1. SQLite 源行数。
2. 过滤后待处理行数。
3. PostgreSQL 目标表是否存在。
4. Alembic revision 状态。
5. 预计 insert / update / skip / error 数量。
6. 字段映射预览。
7. 异常行数量和原因。
8. “不写 PostgreSQL”的明确提示。

dry-run 失败时不得进入 apply。

## 5. Baota staging apply 步骤

本节只是预案，不在本轮执行。

P3-C9-PRECHECK 已完成当前 staging apply 必要性判断：由于 P3-C8 dry-run 显示 SQLite 源行数 = 0，insert/update/skip/error = 0/0/0/0，当前建议将 P3-C9 staging apply 标记为 `SKIPPED_NO_SOURCE_ROWS`，不执行 `--apply --yes`，不写 PostgreSQL 业务数据。

apply 前必须满足：

1. 已完成 SQLite backup。
2. 已完成 schema smoke。
3. 已完成 dry-run，且 insert / update / skip / error 结果被人工确认。
4. 已人工确认目标是 Baota staging，不是 production。
5. 已人工确认 `<POSTGRES_URL>` 是受控 staging URL。
6. `--apply --yes` 必须显式传入。
7. 不允许隐式使用 `DATABASE_URL` 触发 apply。
8. 只允许写 `knowledge_categories`。
9. apply 后立即做 API contrast。

命令模板：

```bash
python scripts/migrate_knowledge_categories_sqlite_to_postgres.py \
  --sqlite-db-path <SQLITE_DB_PATH> \
  --postgres-url <POSTGRES_URL> \
  --apply \
  --yes
```

apply 输出必须记录：

1. 脱敏后的 PostgreSQL URL。
2. 目标 database：必须为 `auto_wechat`。
3. Alembic revision：必须为 `0002_create_knowledge_categories` 或更高。
4. insert / update / skip / error 计划摘要。
5. 实际 insert / update / skip / error 结果。
6. 是否只写入 `knowledge_categories`。

## 6. API contrast 灰度验证

API contrast 用于验证 `GET /knowledge-categories` 在 SQLite 默认路径和 PostgreSQL pilot 路径下响应语义一致。

验证要求：

1. SQLite 默认路径调用 `GET /knowledge-categories`。
2. PG pilot 路径调用同一个 `GET /knowledge-categories`。
3. 归一化响应后比较语义一致。
4. mismatch 时立即停止 gray migration。
5. 不把 PG pilot 默认开关改为 true。
6. 不切换默认 `DATABASE_URL`。
7. 如需灰度，只允许指定 staging 容器或指定环境变量临时启动验证。

临时验证原则：

```text
KNOWLEDGE_CATEGORIES_ASYNC_PG_ENABLED=false
```

用于 SQLite 默认路径。

```text
KNOWLEDGE_CATEGORIES_ASYNC_PG_ENABLED=true
DATABASE_URL=<POSTGRES_URL>
```

仅用于 staging 临时 PG pilot 验证，不写入默认配置。

对照内容：

1. base 虚拟分类行为一致。
2. `category_key` / `key` 语义一致。
3. disabled / deleted 过滤一致。
4. `sort_order ASC, id ASC` 排序一致。
5. `merchant_id` 隔离一致。
6. 响应字段缺省值一致。
7. 不丢失 `description`、`is_base`、`status`、`sort_order` 等迁移字段语义。

熔断规则：

1. API contrast mismatch 非空：停止灰度。
2. PG 503 或 runtime 不可用：停止灰度。
3. PostgreSQL error 增加：停止灰度。
4. SQLite 默认路径异常：停止灰度并先恢复 SQLite 路径健康。
5. 任何真实发送链路被触发：立即停止并回滚到 SQLite 默认路径。

## 7. 回滚策略（rollback）

默认回滚不是删表，而是关闭 PG pilot，恢复 SQLite 默认路径。

回滚步骤模板：

1. 关闭 `KNOWLEDGE_CATEGORIES_ASYNC_PG_ENABLED`。
2. 确认默认 `DATABASE_URL` 仍为 SQLite。
3. 重启或恢复 staging 9000 到 SQLite 默认路径。
4. 重新调用 `GET /knowledge-categories` 验证 SQLite 路径。
5. 保留 PostgreSQL 数据用于排查，不默认 drop `knowledge_categories`。

如 apply 已写入 staging PostgreSQL：

1. staging 可按 `merchant_id`、migration batch 或明确条件清理。
2. 不允许默认 drop 整个 `knowledge_categories` 表。
3. production 回滚必须先备份。
4. 若目标 PG 中已有人工新增数据，清理条件必须避免误删。
5. 回滚后重新执行 SQLite 路径 API 验证。

production 回滚建议另起任务设计 source marker / migration batch id，本文不实现。

## 8. 风险与熔断

| 风险 | 说明 | 熔断 / 应对 |
|---|---|---|
| 误连生产 PostgreSQL | `<POSTGRES_URL>` 指向 production | apply 前人工确认 URL、database、host；输出脱敏 URL |
| 误用 `DATABASE_URL` apply | 默认配置可能指向当前运行路径 | apply 只允许 `--postgres-url` 或受控 staging URL，不允许隐式 `DATABASE_URL` |
| SQLite 路径错误 | `<SQLITE_DB_PATH>` 可能指向旧库或空库 | 执行前记录路径、文件大小、行数和 backup |
| PG schema 未到 `0002_create_knowledge_categories` | 目标表或约束不完整 | schema smoke 不通过则停止 |
| base 虚拟分类和真实 base 行混淆 | 服务层虚拟 base 与历史物理 base 可能同时存在 | 不主动生成 base；已有真实行按普通行迁移和对照 |
| disabled/deleted 被错误复活 | upsert 默认值可能覆盖状态 | dry-run 检查状态；apply 后 API contrast |
| API contrast 不一致 | SQLite / PG 语义不一致 | 立即停止灰度，关闭 PG pilot |
| staging 与 production 环境变量差异 | staging 验证不能直接代表 production | production 单独 dry-run 和审批 |
| 宝塔反代 / 容器网络差异 | 容器内外地址、反代路径不同 | staging 先验证健康检查和容器网络 |
| QPS600 未被证明 | 本次迁移验证正确性，不验证性能 | 后续压测、慢查询、索引验证单独执行 |

## 9. 人工审批点（approval）

必须逐项审批：

1. 是否允许在宝塔 staging 读取真实 SQLite。
2. 是否允许在宝塔 staging 写入 PG。
3. 是否允许开启 PG pilot。
4. 是否允许进入 production dry-run。
5. 是否允许 production apply。
6. 是否允许默认 `DATABASE_URL` 从 SQLite 切到 PostgreSQL。
7. 是否允许扩大到 `knowledge_categories` 以外的表。
8. 是否允许从单接口灰度扩大到更多只读接口。

production apply 和默认数据库切换必须是后续独立任务，不能在 P3-C7 中顺手执行。

## 10. 后续阶段建议

1. P3-C8：宝塔 staging dry-run 人工 Runbook 与执行记录模板。
2. P3-C9-PRECHECK：宝塔 staging apply 必要性判断，当前建议 `SKIPPED_NO_SOURCE_ROWS`。
3. P3-C9：仅当后续 dry-run 显示 insert/update > 0 且 error = 0，并完成人工审批后，才进入 staging apply + API contrast 执行记录。
4. P3-C10：production dry-run 审批模板。
5. P3-D：下一个表的 PostgreSQL migration 设计，不能直接全量迁移。
6. P3 后续：QPS600 压测、慢查询分析、索引验证、事务边界、幂等批次记录和生产回滚实现。

## 11. P3-C8 人工 Runbook 补充

P3-C8 不由本机 VibeCoding 直接执行宝塔命令，而是新增人工 Runbook 和执行记录模板：

```text
docs/ai/03_data_and_migration/KNOWLEDGE_CATEGORIES_BAOTA_STAGING_DRY_RUN_RECORD.md
```

P3-C8 的宝塔 dry-run 结果需要由人工在 Baota staging 宿主机代码目录执行后贴回，再判断是否进入 P3-C9。

P3-C8 只读 dry-run 默认不执行 `scripts/smoke_auto_wechat_alembic_knowledge_categories.py`，因为该脚本会执行 Alembic `upgrade head`，不属于只读 dry-run 边界。P3-C8 只允许使用 `scripts/migrate_knowledge_categories_sqlite_to_postgres.py --dry-run` 读取 SQLite 和 PostgreSQL 元数据，禁止 `--apply`、`--yes`、Alembic upgrade、重启 9000、切换 `DATABASE_URL` 或开启 `KNOWLEDGE_CATEGORIES_ASYNC_PG_ENABLED`。

## 11A. P3-C8B schema 初始化 Runbook 补充

P3-C8 人工预检查发现 Baota staging PostgreSQL `auto_wechat` database 为空，`alembic_version` 不存在，导致 dry-run 被阻塞。P3-C8B 新增人工 Runbook：

```text
docs/ai/03_data_and_migration/KNOWLEDGE_CATEGORIES_BAOTA_STAGING_SCHEMA_INIT_RUNBOOK.md
```

该 Runbook 只用于在 Baota staging PostgreSQL 空库中执行 `migrations/postgres/auto_wechat/alembic.ini` 到 `0002_create_knowledge_categories`，创建 `alembic_version` 与 `knowledge_categories` schema。它不迁移 SQLite 数据，不执行数据脚本 apply，不切换 9000 默认数据库，不开启 PG pilot，不操作 9100 / Milvus / RAG。

## 11B. P3-C8B / P3-C8 人工执行结果补充

人工已在 Baota staging 完成两步前置执行：

1. P3-C8B schema 初始化通过：
   - PostgreSQL dev 容器 `auto-wechat-postgres-dev` 启动并 healthy。
   - `auto_wechat` database 初始化到 `0002_create_knowledge_categories`。
   - `alembic_version` 与 `knowledge_categories` 表存在。
   - `uk_knowledge_categories_scope_merchant_key` UNIQUE 约束存在。
   - `ck_knowledge_categories_key_matches_category_key` CHECK 约束存在。
   - PG `knowledge_categories` 行数为 0。

2. P3-C8 dry-run 通过：
   - SQLite 路径：`docker-data/auto_wechat_9000/auto_wechat.db`。
   - SQLite 备份：`backups/p3_c8/auto_wechat_knowledge_categories_p3_c8_20260708_155855.db`。
   - SQLite 源行数: 0。
   - 过滤后待处理行数: 0。
   - Alembic revision: `0002_create_knowledge_categories`。
   - 预计 insert / update / skip / error 均为 0。
   - 字段映射预览: `[]`。
   - PostgreSQL 写入: disabled。
   - 最终输出：`DRY_RUN_PASS`。

安全边界：

1. schema 初始化写入了 PG schema；dry-run 未写 PG 业务数据。
2. 未迁移 SQLite 数据。
3. 未执行 `--apply` / `--yes`。
4. 未切换 `DATABASE_URL`。
5. 未开启 `KNOWLEDGE_CATEGORIES_ASYNC_PG_ENABLED`。
6. PostgreSQL dev 容器已停止。

结论：可以进入 P3-C9 前的人工审批；P3-C9 不应自动执行 production apply，也不应自动迁移真实生产数据。

## 11C. P3-C9-PRECHECK apply 必要性判断补充

当前已新增 P3-C9 前置判断记录：

```text
docs/ai/03_data_and_migration/KNOWLEDGE_CATEGORIES_BAOTA_STAGING_APPLY_PRECHECK.md
```

判断结论：

```text
P3-C9 staging apply: SKIPPED_NO_SOURCE_ROWS
```

判断依据：

1. P3-C8B schema 初始化已通过，PG `knowledge_categories` 行数为 0。
2. P3-C8 dry-run 已通过，最终输出 `DRY_RUN_PASS`。
3. SQLite 源行数 = 0。
4. dry-run insert/update/skip/error = 0/0/0/0。
5. PostgreSQL 写入: disabled。

当前 staging 没有 `knowledge_categories` 源业务行需要迁移，执行 `--apply --yes` 没有业务价值。为避免无意义写操作和误操作风险，本预案当前建议跳过 P3-C9 staging apply，不执行空数据 API contrast 灰度，不开启 `KNOWLEDGE_CATEGORIES_ASYNC_PG_ENABLED`，不切换 `DATABASE_URL`。

后续若 staging 出现源数据，必须先重新执行 P3-C8 dry-run；只有 dry-run 显示 `insert > 0` 或 `update > 0` 且 `error = 0`，才重新审批 P3-C9 apply。

## 12. 本轮边界确认

本轮只新增预案文档并同步现有文档。

本轮不执行：

1. 不执行宝塔命令。
2. 不连接生产数据库。
3. 不迁移真实数据。
4. 不切换默认 `DATABASE_URL`。
5. 不默认开启 `KNOWLEDGE_CATEGORIES_ASYNC_PG_ENABLED`。
6. 不改业务代码。
7. 不改迁移脚本行为。
8. 不改 Alembic revision。
9. 不改 docker-compose。
10. 不改 `.env` / `.env.example`。
11. 不改 9100 / Milvus / RAG。
12. 不触发 LLM、抖音发送、私信发送或自动回复 gate。
13. 不写真实 URI、token 或 password。
