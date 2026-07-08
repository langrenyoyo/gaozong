# knowledge_categories SQLite 到 PostgreSQL 数据迁移设计

任务：`P3-C3-DB-9000-KNOWLEDGE-CATEGORIES-DATA-MIGRATION-DESIGN-1`

范围：本文只设计 9000 `knowledge_categories` 从 SQLite -> PostgreSQL 的最小数据迁移脚本方案。本轮不实现迁移脚本，不连接 PostgreSQL，不读取真实 SQLite，不迁移真实数据，不修改业务代码，不修改 Alembic revision。

## 1. 当前审计结论

### 1.1 SQLite 模型来源

`app/models.py` 中 `KnowledgeCategory` 当前字段为：

| 字段 | 当前 ORM 类型 / 语义 |
|---|---|
| `id` | `Integer` 自增主键 |
| `tenant_id` | `String(128)`，预留租户 ID |
| `merchant_id` | `String(128)`，商户 ID |
| `category_key` | `String(128)`，知识分类稳定标识 |
| `name` | `String(100)`，展示名称 |
| `scope_type` | `String(20)`，`system` / `merchant` |
| `is_base` | `Integer`，SQLite 0/1 布尔语义 |
| `status` | `String(20)`，`active` / `disabled` / `deleted` |
| `sort_order` | `Integer`，默认 100 |
| `created_at` | `DateTime` |
| `updated_at` | `DateTime` |
| `deleted_at` | `DateTime`，软删除标记 |
| `created_by` | `String(128)` |
| `updated_by` | `String(128)` |

当前 ORM 唯一约束为 `merchant_id + category_key`，索引为：

1. `idx_knowledge_categories_merchant_status_sort`
2. `idx_knowledge_categories_merchant_key_status`

### 1.2 SQLite migration 来源

`migrations/versions/0013_knowledge_categories.sql` 创建 9000 SQLite `knowledge_categories` 表。本 migration 明确说明：

1. 只新增知识分类主数据表。
2. 不执行数据迁移。
3. `base` 分类本阶段由服务层逻辑内置，不在本表强制落 system 行。

该 SQLite 表没有 `"key"` 字段，也没有 `description` 字段。

### 1.3 服务和接口语义

`apps/knowledge/services.py` 当前核心逻辑：

1. `list_visible_knowledge_categories()` 返回逻辑 `base` 分类 + 当前商户 active merchant 分类。
2. `base` 由 `_base_category_dict()` 虚拟补充，返回：
   - `category_key=base`
   - `name=基础知识`
   - `scope_type=system`
   - `is_base=True`
3. merchant 分类查询条件为：
   - `merchant_id = RequestContext.merchant_id`
   - `scope_type = merchant`
   - `status = active`
   - `deleted_at IS NULL`
4. 排序为 `sort_order ASC, id ASC`。
5. `create_merchant_knowledge_category()` 当前不允许创建 `base`，并按商户内 `category_key` 判重。

`app/routers/knowledge_categories.py` 当前 `GET /knowledge-categories` 只返回：

```text
category_key
name
scope_type
is_base
```

`app/repositories/knowledge_categories_async_repository.py` 的 PostgreSQL 试点查询也只覆盖上述 GET 语义，并同样在 repository 返回前虚拟补充 `base`。

### 1.4 PostgreSQL 目标表

`migrations/postgres/auto_wechat/versions/0002_create_knowledge_categories.py` 当前已创建正式 PostgreSQL 表：

1. revision 为 `0002_create_knowledge_categories`。
2. 只创建 `knowledge_categories`。
3. `"key"` 与 `category_key` 同时存在。
4. check constraint：`key = category_key`。
5. 唯一约束：`uk_knowledge_categories_scope_merchant_key`，字段为 `scope_type + merchant_id + key`。
6. 查询索引覆盖 `merchant_id + scope_type + status + deleted_at + sort_order`。
7. 时间字段使用 `TIMESTAMPTZ`。
8. `is_base` 使用 PostgreSQL `BOOLEAN`。

P3-C2 dev smoke 已验证该 revision 可以执行到 head，并已确认表、索引、唯一约束和 check constraint 存在。

## 2. 迁移目标

本次最小数据迁移设计只覆盖：

1. 从当前 9000 SQLite `auto_wechat.db` 的 `knowledge_categories` 读取数据。
2. 写入 PostgreSQL `auto_wechat` database 的 `knowledge_categories`。
3. 只迁移 `knowledge_categories`。
4. 不迁移其它 9000 表。
5. 不迁移 9100。
6. 不迁移 Milvus。
7. 不迁移真实业务数据，本轮只是设计。
8. 不把 `base` 虚拟分类强制生成 PostgreSQL system 行。

## 3. 数据源和目标

### 3.1 SQLite 源

SQLite 源为当前 9000 过渡库中的 `knowledge_categories` 表。

未来脚本应通过参数或现有配置获取 SQLite 路径：

```text
--sqlite-db-path
```

也可以读取当前 9000 配置推导 SQLite 默认路径，但不能硬编码宝塔路径或生产路径。

### 3.2 PostgreSQL 目标

PostgreSQL 目标为 Docker Compose PostgreSQL 容器中的 `auto_wechat` database。

未来脚本应支持：

```text
--postgres-url
SMOKE_DATABASE_URL
DATABASE_URL
```

URL 只允许 PostgreSQL：

1. `postgresql://...`
2. `postgresql+psycopg://...`
3. `postgresql+asyncpg://...`

脚本输出必须使用脱敏 URL，不得打印 password、token 或真实生产连接串。

## 4. 字段映射

| SQLite 字段 | PostgreSQL 字段 | 映射策略 |
|---|---|---|
| `id` | `id` | 保留原 ID 作为试点迁移的稳定对照值；若未来决定由 PG 自增生成，需要另做外键引用审计。 |
| `tenant_id` | `tenant_id` | 原值迁移；为空时保持 `NULL`，不在迁移脚本中猜测租户。 |
| `merchant_id` | `merchant_id` | 原值迁移；merchant 分类缺失时进入异常清单，除非是已有 system/base 行。 |
| `category_key` | `"key"` | PostgreSQL 的 `"key"` 应等于 SQLite 的 `category_key`。 |
| `category_key` | `category_key` | 保留相同值，满足 check constraint：`key = category_key`。 |
| `name` | `name` | 原值迁移；为空时应记录异常，不能静默写入无意义名称。 |
| SQLite 无字段 | `description` | 默认 `NULL`；如果源库曾补过该列，则按原值迁移。 |
| `scope_type` | `scope_type` | 原值迁移；为空默认 `merchant`，但需在 dry-run 输出默认填充数量。 |
| `is_base` | `is_base` | SQLite 0/1 显式转换为 PostgreSQL BOOLEAN。 |
| `status` | `status` | 原值迁移；为空默认 `active`，但不得把 `disabled` / `deleted` 复活。 |
| `sort_order` | `sort_order` | 原值迁移；为空使用 PostgreSQL 默认或显式 0 / 100 需在脚本中固定一种策略。推荐保持 SQLite 语义默认 100。 |
| `created_at` | `created_at` | 显式转换为 `TIMESTAMPTZ`；为空时允许 PG `now()` 或迁移时填当前时间，需在 dry-run 统计。 |
| `updated_at` | `updated_at` | 显式转换为 `TIMESTAMPTZ`；为空时可跟随 `created_at`。 |
| `deleted_at` | `deleted_at` | 原值转换为 `TIMESTAMPTZ`；不得清空已有删除时间。 |
| `created_by` | `created_by` | 原值迁移。 |
| `updated_by` | `updated_by` | 原值迁移。 |

关键规则：

1. PostgreSQL `"key"` 必须写入 SQLite `category_key`。
2. PostgreSQL `category_key` 也必须写入相同值。
3. 迁移前必须校验 `key = category_key` 的目标行构造结果。
4. 迁移脚本不得为了绕过 check constraint 修改业务 key。

## 5. base 分类策略

当前 `base` 分类是服务层虚拟补充，不依赖 `knowledge_categories` 主表存在 system 行。

本次最小迁移策略：

1. 不主动插入新的 `base` system 行。
2. 不把服务层虚拟 `base` 固化成 PostgreSQL 物理行。
3. 如果 SQLite 中已有真实 `base` 行，脚本保留真实已有行并按字段原样迁移。
4. 如果已有 `base` 行与目标唯一约束 `scope_type + merchant_id + key` 冲突，按普通幂等 upsert 处理。
5. 如果 SQLite 里没有 `base` 行，迁移后 GET 仍应由服务层或 async repository 虚拟补充 `base`。

推荐原因：

1. 与 `migrations/versions/0013_knowledge_categories.sql` 的边界一致。
2. 避免迁移脚本额外生成业务数据。
3. 避免后续把虚拟 system 分类和真实商户分类混在同一批迁移里。

## 6. 幂等策略

PostgreSQL 目标表已经有唯一约束：

```text
scope_type + merchant_id + key
```

未来迁移脚本应使用该约束作为 upsert 依据：

```sql
ON CONFLICT (scope_type, merchant_id, key) DO UPDATE
```

更新字段建议仅包含：

1. `category_key`
2. `name`
3. `description`
4. `is_base`
5. `status`
6. `sort_order`
7. `deleted_at`
8. `updated_at`
9. `updated_by`

幂等保护要求：

1. 重复执行不会插入重复数据。
2. `deleted_at` 不得被源端空值错误清空。
3. `status=disabled` 或 `status=deleted` 不得被默认值错误复活为 `active`。
4. 如果目标已有更晚 `updated_at`，未来脚本应提供策略：默认跳过、仅 dry-run 标记冲突，或显式 `--overwrite` 才覆盖。本次最小设计不默认覆盖更晚目标数据。
5. 每次 apply 建议写入批次标识或至少输出批次摘要，便于回滚和审计；是否新增批次表留到 P3-C4 / P3-C5 决定。

## 7. dry-run 策略

未来脚本必须默认 dry-run。`--dry-run` 行为：

1. 读取源 SQLite 表结构和行数据摘要。
2. 校验 PostgreSQL URL 和 Alembic revision，但不写 PostgreSQL。
3. 输出计划迁移总数。
4. 输出预计 `insert` / `update` / `skip` 数量。
5. 输出异常数量，例如缺少 `merchant_id`、缺少 `category_key`、时间无法解析、违反 `key = category_key`。
6. 输出 merchant 维度摘要，可按 `merchant_id` 分组展示。
7. 不连接生产数据库时也不能误报成功；缺少目标环境应清晰提示。

`--dry-run` 不应：

1. 写 PostgreSQL。
2. 修改 SQLite。
3. 修改 `.env`。
4. 创建业务表或执行 Alembic migration。

## 8. 安全参数设计

未来脚本参数建议：

```text
--sqlite-db-path <path>
--postgres-url <url>
--merchant-id <merchant_id>
--limit <n>
--dry-run
--apply
--yes
```

安全规则：

1. 默认等价于 `--dry-run`。
2. 只有显式传入 `--apply` 或 `--yes` 才允许真实写入。
3. `--merchant-id` 用于单商户灰度验证。
4. `--limit` 用于小批量 smoke。
5. SQLite 路径必须来自参数或配置，不硬编码宝塔路径。
6. PostgreSQL URL 必须脱敏展示。
7. 脚本应拒绝 SQLite URL 作为 PostgreSQL 目标。
8. 脚本应在 apply 前输出目标 database 名称、目标 revision 和写入摘要，并要求显式确认参数。

## 9. 验证规则

迁移后验证必须至少覆盖：

1. Alembic revision 必须为 `0002_create_knowledge_categories` 或更高。
2. SQLite 源行数与 PostgreSQL 目标匹配，按过滤条件和 skip 规则解释差异。
3. `merchant_id + category_key` 对比一致。
4. PostgreSQL `"key"` 与 `category_key` 一致。
5. `inactive` / `disabled` / `deleted` 状态保持，不被错误复活。
6. `deleted_at` 保持，不被错误清空。
7. `sort_order` 保持。
8. `GET /knowledge-categories` SQLite / PG 响应语义一致。
9. `base` 虚拟分类仍由服务层补充；没有物理 base 行时 GET 仍包含 base。
10. 重复执行迁移后，行数不增加，upsert 更新数量可解释。

建议后续 P3-C6 使用现有 `GET /knowledge-categories` 试点开关做 SQLite / PostgreSQL 对照：

1. 默认 SQLite 路径返回预期数据。
2. PostgreSQL 试点路径返回同一商户可见分类。
3. inactive / deleted 不返回。
4. 排序保持 `sort_order ASC, id ASC`。
5. 响应 schema 保持 `category_key/name/scope_type/is_base`。

## 10. 回滚策略

本次最小设计不实现生产回滚，只规定未来脚本必须具备回滚预案。

迁移前：

1. 备份 SQLite 文件。
2. 确认 PostgreSQL 是 dev / staging / 明确目标环境。
3. 记录 PostgreSQL 当前 Alembic revision。
4. 记录迁移批次、行数和目标 database。

回滚原则：

1. dev / smoke 环境可以在明确允许下清表或重建 database。
2. staging / 生产不能简单 `DROP TABLE` 或全表删除。
3. 生产回滚建议按 source marker / migration batch id 删除本批写入或恢复备份。
4. 如果目标已有人工更新，回滚必须避免覆盖或删除迁移后新增的有效数据。
5. 如果迁移失败，优先停止流量切换并保留 SQLite 默认路径。

## 11. 风险清单

| 风险 | 说明 | 应对 |
|---|---|---|
| SQLite 和 PostgreSQL 时间类型差异 | SQLite 可能保存 naive datetime，PostgreSQL 为 `TIMESTAMPTZ` | 迁移时显式解析并统一时区策略，异常进入清单 |
| `merchant_id` 为空或类型不一致 | merchant 分类唯一约束依赖 merchant 维度 | dry-run 统计空值；apply 前要求处理策略 |
| `key/category_key` 不一致 | PostgreSQL check constraint 要求 `key = category_key` | 目标构造阶段统一取 SQLite `category_key` |
| base 虚拟分类和真实行冲突 | 服务层虚拟 base 与历史物理 base 行可能同时存在 | 不额外生成 base；已有真实行按普通行迁移 |
| `deleted_at/status` 被错误覆盖 | upsert 默认值可能复活 disabled/deleted 行 | 更新策略保留源端状态和删除时间，不用默认 active 覆盖 |
| 重复执行产生误更新 | `ON CONFLICT` 可能覆盖目标新值 | 默认不覆盖目标更晚 `updated_at`，冲突先输出 |
| 生产误连风险 | `DATABASE_URL` 可能指向真实生产 | 输出脱敏 URL、目标 database、revision，并要求 `--apply` 或 `--yes` |
| SQLite 源 schema 演进差异 | 有些库可能补过 `description` 等字段 | dry-run 先检查列存在性，缺失字段按默认策略 |
| QPS600 与数据迁移无直接证明关系 | 数据迁移只验证正确性，不证明性能 | QPS600 仍留给索引验证、慢查询和压测 |

## 12. 后续实施拆分

1. P3-C4：实现 dry-run-only 迁移脚本骨架，只做读取、规范化、计划输出和安全校验，不写 PostgreSQL。
2. P3-C5：实现 dev PG apply smoke，只写 synthetic / dev 目标或受控 dev 数据，不迁移真实生产数据。
3. P3-C6：接入 `GET /knowledge-categories` PG 数据对照，验证 SQLite / PostgreSQL 响应语义一致。
4. P3-C7：宝塔 staging / 灰度迁移预案，包含备份、回滚、单商户灰度和停用 SQLite 生产路径前置条件。

## 13. 本轮边界确认

本轮只新增本文档并同步现有上下文文档。

本轮不执行：

1. 不实现迁移脚本。
2. 不连接 PostgreSQL。
3. 不读取真实 SQLite。
4. 不迁移真实数据。
5. 不改业务代码。
6. 不改 Alembic revision。
7. 不改 docker-compose。
8. 不改 `.env` / `.env.example`。
9. 不改 9100 / Milvus / RAG。
10. 不触发 LLM、抖音发送、私信发送或自动回复 gate。
11. 不写真实 URI、token、password。
