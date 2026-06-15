# 数据库迁移体系方案（DB-MIG）

版本：DB-MIG-PLAN-1
状态：方案设计（只读探索 + 方案输出）。本阶段未修改任何业务代码、未执行迁移、未新增字段、未安装依赖、未初始化 Alembic、未对任何数据库文件做写操作。
范围：回答 13 个决策问题，给出推荐迁移方案、不推荐方案、第一批迁移字段、回滚方案、风险点、执行前人工确认清单。

更新时间：2026-06-15

------

## 0a. 环境性质说明（重要，先读这一节）

**当前环境定性**：

```text
当前 data/auto_wechat.db 是开发测试库，不是生产库。
库内数据（douyin_leads 44 条等）是开发 / 测试数据，不是正式生产数据。
本阶段不是生产迁移，而是提前建立准生产级迁移规范。
未来真实客户数据上线后，可以沿用同一套迁移机制。
```

两个数据库文件的定位：

| 文件 | 当前定位 | 说明 |
|------|---------|------|
| `data/auto_wechat.db` | **主线开发测试库** | 当前 9000 实际使用，数据为开发 / 测试数据，但作为主线开发库对待。后续迁移以此库为目标。 |
| `docker-data/auto_wechat.db` | **历史副本 / 非主线库** | Docker 构建时生成的副本，当前非主线运行库。第一版迁移不以此库为目标。 |

**措辞约定**（全文统一）：

- 文中"当前开发测试库"指 `data/auto_wechat.db`。
- 文中"未来生产库"指未来真实客户数据上线后的库，当前尚不存在。
- 文中凡涉及"停服迁移""低峰执行""数据保护"等表述，默认指**未来生产化场景**；当前测试库迁移可在确认后直接执行，无需停服。
- 安全原则不因"只是测试数据"而放宽（见第 0b 节）。

------

## 0b. 安全原则（措辞已调整为"准生产级"，但约束力不变）

虽然当前是开发测试数据，本方案仍按准生产级规范设计，安全原则全部保留：

1. 不随意删库重建（即使是测试库，删库重建也会丢失开发过程中积累的调试线索与 webhook 事件）。
2. 不直接依赖 `Base.metadata.create_all` 解决已有表的字段变更（create_all 不 ALTER 已存在表）。
3. 迁移脚本必须支持备份、幂等、dry-run、字段存在检查。
4. 迁移脚本必须支持指定数据库路径（`--db-path`，便于在不同库 / 测试库副本上执行）。
5. 未来真实客户数据上线后，沿用同一套迁移机制，无需重写。

> 目的：现在多花一点成本建立规范，未来客户数据上线时零额外风险。

------

## 0c-1. WAL 模式下的验收口径（2026-06-15 P2-A-END 追加，重要）

> **结论：`.db` 文件 hash / mtime 不能作为「主线数据未变化」的唯一证据。**

背景（P2-A 实测发现）：

```text
当前 data/auto_wechat.db 是开发测试库（非生产库），SQLite 处于 WAL 模式。
主 .db + -wal + -shm 三文件共存，-wal 内有历史积累的未 checkpoint 帧。
P2-A 副本验证期间，主 .db 文件 hash 曾从 101d5e8... 变为 728385e...，
但经排查是 WAL checkpoint 把历史 -wal 帧合并进主 .db 所致，
迁移脚本本身对主线零写入（只读 backup + mode=ro），结构 / 数据语义完全不变。
```

口径（后续 P2-C 主线迁移验收必须遵守）：

1. **不能**用「迁移前后 `.db` 文件 hash 是否一致」判断主线是否被迁移修改。
2. checkpoint 可能导致 `.db` hash 变化，但**不代表业务数据或结构发生变化**。
3. 后续主线库验收**必须以结构对比 + 数据语义对比为主**：
   - `PRAGMA table_info(douyin_leads)` —— 新增列是否存在、类型 / 可空性正确
   - `PRAGMA table_info(sales_staff)` —— 同上
   - `schema_migrations` 是否存在、`version_num` 版本记录是否正确
   - 关键表行数（`COUNT(*)`）迁移前后一致（ADD COLUMN 不应改行数）
   - 新增字段是否存在（尤其确认主线未出现预期外的新列）
   - 旧数据关键字段抽样一致（如 `status`、`source_id`、`customer_name` 未被改动）
   - `reassign_count` 默认值符合预期（旧行自动为 0）
4. 文件 hash **只能作为辅助参考**，不能作为唯一判断依据。
5. P2-C 前如需处理 WAL（如收缩 4MB `-wal`），应**单独确认后再执行 checkpoint**，迁移骨架阶段（P2-A）不执行 checkpoint。

------

## 0c. 阶段边界说明（2026-06-15 追加）

本文件所属阶段是 **DB-MIG：迁移体系方案设计**。

```text
当前 data/auto_wechat.db 是开发测试库，不是生产库。
本阶段不是生产迁移，而是提前建立准生产级迁移规范。
DB-MIG 只负责方案设计。
P2-A 只负责迁移脚本骨架与副本 dry-run。
P2-B 才允许 models.py 字段补齐。
P2-C 才允许对当前开发测试主线库执行正式迁移。
```

因此，在 DB-MIG 阶段禁止：

```text
创建 migrations/ 脚本
修改 app/models.py
执行数据库迁移
修改 data/auto_wechat.db
做字段回填
```

------

## 0. 只读探索依据

本方案基于以下只读命令结果（见第 1 节摘要），探索过程严格只读：

- 文件存在性：`ls -la data/`、`find . -name "*.db"`
- 迁移痕迹：`ls alembic.ini migrations/ alembic/`、`grep -rn "schema_version|migration_history|alembic" app/ scripts/`
- 表清单与行数：`sqlite3 ... ".tables"` + `SELECT COUNT(*)`
- 列定义：`PRAGMA table_info(...)`
- 索引：`SELECT ... FROM sqlite_master WHERE type='index'`
- 数据分布：`SELECT status, COUNT(*) FROM douyin_leads GROUP BY status`

探索期间所有操作均为 SELECT / PRAGMA / 元数据查询，未执行任何 INSERT/UPDATE/DELETE/ALTER/DROP。

------

## 1. 只读探索结果摘要

### 1.1 数据库文件现状

| 文件 | 用途 | 表数 | 关键数据量 |
|------|------|------|-----------|
| `data/auto_wechat.db` | 开发主机主库（9000 实际使用） | 8 | douyin_leads 44、reply_checks 11、douyin_webhook_events 3、sales_staff 3、lead_notifications 1 |
| `docker-data/auto_wechat.db` | Docker 构建产物 / 历史库 | 8 | douyin_leads 1、douyin_webhook_events 1，其余 0 |

两个库表结构完全一致。`data/` 是真正在用的库，`docker-data/` 是 Docker 构建时生成的副本，当前不是主线运行库。

数据库启用 WAL 模式（`app/database.py` 的 `_set_sqlite_pragma` 设置 `journal_mode=WAL`），存在 `-wal` / `-shm` 伴生文件。

### 1.2 迁移痕迹

- ❌ 无 `alembic.ini`
- ❌ 无 `migrations/`、无 `alembic/` 目录
- ❌ 代码中无 `schema_version`、`migration_history`、`upgrade()` 痕迹
- ✅ 建表唯一机制：`Base.metadata.create_all(bind=engine)`（`app/database.py`、`app/main.py:51`、`scripts/init_db.py`）

### 1.3 当前 8 张表清单

```text
sales_staff
douyin_leads
reply_checks
check_configs
douyin_webhook_events   ← 语义承接 PRD lead_source_events（第一版不重命名）
feedback_records
lead_notifications
wechat_tasks
```

物理表结构与 `app/models.py` 完全一致，无漂移。

### 1.4 索引现状

唯一显式索引：

```text
douyin_webhook_events.ix_douyin_webhook_events_event_key  (UNIQUE)
```

其余表的主键（id）由 SQLite 自动建索引，无业务二级索引。`douyin_leads.source_id`、`douyin_leads.assigned_staff_id`、`reply_checks.lead_id` 等外键字段无索引。

### 1.5 关键数据分布

`douyin_leads.status` 实际取值（data 库）：

```text
assigned: 10
pending:  33
replied:  1
```

实际只出现 3 种状态，无 `timeout`、无 `closed`（虽然 `models.py:44` 注释包含）。

`check_configs` 表 0 行：

- `create_all` 只建表，不插数据。
- 默认配置靠 `scripts/init_db.py` 单独插入。
- 运行时 `reply_analyzer` / `assign_service` 读不到配置时用代码内默认值兜底。
- 这意味着 `check_configs` 现状不影响迁移，但第一批迁移**不应依赖** check_configs 已有数据。

### 1.6 约束与默认值观察

- 绝大多数业务列 `notnull=0`（允许 NULL），仅主键、`is_duplicate`、`raw_body`、`task_type`、`mode`、`status`（wechat_tasks）、`event_key` 为 NOT NULL。
- **这对迁移有利**：新增列时 SQLite 的 `ALTER TABLE ADD COLUMN` 默认对旧行填 NULL，而现有业务列本就容忍 NULL。
- 没有 `server_default`（`models.py` 的 Column 未声明 `default=` 的服务端默认，只有 Python 侧 `default=datetime.now`）。

------

## 2. 当前 SQLite + create_all 的问题

| 问题 | 说明 | 影响 |
|------|------|------|
| create_all 只建不更 | SQLAlchemy `create_all` 对已存在表**不会 ALTER**，新增 / 修改列不生效 | 新字段加到 models.py 后，旧库读不到该列，运行时 `OperationalError: no such column` |
| 无版本追踪 | 不知道库当前处于哪个 schema 版本 | 无法判断某台机器的库是否需要迁移 |
| 无幂等升级 | `init_db.py` 只插默认配置，无 schema 演进逻辑 | 多人 / 多机 / 多环境库结构不可控漂移 |
| 当前开发测试库已有数据 | data 库有 44 条线索 + 11 条检测记录 + webhook 事件（虽为测试数据，但作为主线开发库对待） | 随意删库重建会丢失开发过程中积累的调试线索与 webhook 事件 |
| 两个 db 文件并存 | `data/` 与 `docker-data/` 各一份 | 迁移需明确"迁哪个"，避免迁错库 |
| 无回滚机制 | 改完列无法 down | 试错成本高 |

------

## 3. 决策问题逐条回答

### Q1. 引入 Alembic 还是手写迁移脚本？

**推荐：第一版采用「手写迁移脚本 + schema_version 表」，不引入 Alembic。**

理由：

1. 当前表少（8 张）、字段变更需求明确、无复杂关系演进，Alembic 的 autogenerate 价值有限。
2. Alembic 引入后会带来：依赖增加、学习成本、`env.py` 配置、与 `create_all` 共存策略、exe 打包影响（Local Agent 打包需包含 alembic 目录）。
3. SQLite 对 DDL 支持有限（Alembic 在 SQLite 上 rename/drop column 也需 batch 模式），手写反而更可控。
4. 本项目迁移频率低（第一版一次性补字段为主），不是高频演进场景。
5. 手写迁移脚本可完全自包含、可审计、可逐条 review，符合本项目"可解释、可回滚、可验证"原则。

**前提条件**：必须配合 `schema_version` 表做版本追踪（见 Q6），否则手写脚本会重蹈 create_all 的无版本问题。

> 不排除后续迁移频率上升后（多客户、多服务器）再引入 Alembic。本方案设计为"可平滑切换到 Alembic"：迁移脚本结构、版本号命名、schema_version 表都预留了兼容空间。

### Q2. create_all 的问题是什么？

见第 2 节。核心：只建不更、无版本、无回滚、当前开发测试库已有数据。

### Q3. 新增字段如何兼容已有库（当前开发测试库 / 未来生产库）？

采用「ALTER TABLE ADD COLUMN + NULL 默认」策略：

1. 所有新增列在 models.py 中**不设 NOT NULL、不设服务端 default**（Python 侧可给 default，但数据库列保持可空）。
2. 迁移脚本用 `ALTER TABLE 表名 ADD COLUMN 列名 类型;`，SQLite 对旧行自动填 NULL。
3. 由于现有业务列本就大量允许 NULL（见 1.6），新增列容忍 NULL 与现状一致，不会破坏现有读写逻辑。
4. 需要回填的字段（见 Q5）单独走 UPDATE 脚本，与 ADD COLUMN 解耦。

**禁止操作**：不通过删表重建来加字段（即使是测试库，也会丢失开发过程中积累的调试数据；未来生产库更是不可接受）。

### Q4. 哪些字段允许 NULL 默认？

**全部新增字段都允许 NULL 默认**（第一版策略）。

具体：

- 原始文本与联系方式提取结果列（`raw_message_text` / `extracted_phone` / `extracted_wechat` / `all_extracted_contacts` / `contact_extract_status` / `contact_extract_reason`）→ NULL，因为旧线索的原始文本与提取结果已在 `raw_data` JSON 内，迁移后新线索才写独立列，旧线索保持 NULL 或回填（见 Q5）。
- 幂等键列（`external_lead_id` / `account_open_id` / `conversation_short_id` / `server_message_id`）→ NULL，旧线索这些值在 raw_body 内，按需回填。
- `reassign_count` → `NOT NULL DEFAULT 0`（唯一例外，见下）。
- `customer_id` / `external_customer_id` → NULL，NewCarProject 未对接。
- `SalesStaff.remark` / `sort_order` → NULL；sort_order 建议回填为现有 id 序（见 Q5）。
- `DouyinLead.status` → **不新增列**，只是扩展取值域（从 3 态扩到 13 态），无需迁移结构。

**例外（建议给默认值而非纯 NULL）**：

- `reassign_count INTEGER NOT NULL DEFAULT 0`：计数列，NULL 会让 `count + 1` 逻辑出错，必须 `NOT NULL DEFAULT 0`。
- `sort_order INTEGER`：可空，回填脚本赋值。

### Q5. 哪些字段需要历史数据回填？

| 字段 | 是否回填 | 回填来源 | 必要性 |
|------|---------|---------|--------|
| `raw_message_text` | 建议回填 | 解析 `douyin_leads.raw_data` JSON 的 `raw_message_text` / `content` 节点 | 中（不回填则旧线索原始文本列空，但 raw_data 仍有值） |
| `extracted_phone` / `extracted_wechat` / `all_extracted_contacts` / `contact_extract_status` | 建议回填 | 解析 `douyin_leads.raw_data` JSON 的 `contact_extract` 节点 | 中（不回填则旧线索在列表/导出时提取列空，但 raw_data 仍有值） |
| `contact_extract_reason` | 建议回填 | 同上 | 中 |
| `external_lead_id` | 可回填 | 用现有 `source_id`（= from_user_id）回填，或留空 | 低 |
| `account_open_id` / `conversation_short_id` / `server_message_id` | 可回填 | 解析 `raw_data.webhook_payload.content` | 低（仅在需要事件级幂等查询时才有价值） |
| `reassign_count` | 由 DEFAULT 自动置 0 | 迁移脚本 `ADD COLUMN ... NOT NULL DEFAULT 0` 对旧行自动填 0 | 高（计数列不能 NULL） |
| `customer_id` / `external_customer_id` | 不回填 | NewCarProject 未对接 | — |
| `SalesStaff.sort_order` | 建议回填 | `UPDATE sales_staff SET sort_order=id WHERE sort_order IS NULL` | 中（顺序轮询依赖，是否回填放 P2-C 或 P6 前确认） |
| `SalesStaff.remark` | 不回填 | 无历史值 | — |

> **P2-A 阶段回填边界（重要）**：上表是迁移方案层面的"最终回填计划"，不等于 P2-A 阶段就要执行。
>
> P2-A 阶段**只验证迁移脚本机制**，回填口径为：
>
> - **允许**：通过 `reassign_count NOT NULL DEFAULT 0` 验证默认值机制（ADD COLUMN 时旧行自动填 0）。
> - **暂不做**：不从 `raw_data` JSON 回填联系方式字段；不回填 `raw_message_text` / `extracted_phone` / `extracted_wechat` / `all_extracted_contacts` / `contact_extract_status` / `contact_extract_reason` / `customer_id` / `external_customer_id`；不改变已有 `status`；不改变分配逻辑。
> - `SalesStaff.sort_order` 是否回填为 id 序，放 P2-C 或 P6 前再确认；P2-A 先不做业务回填。

**回填原则**：

1. 回填脚本与 ADD COLUMN 脚本**分离**，可单独执行、单独验证、单独回滚。
2. 回填用只读解析 + 批量 UPDATE，解析失败的单条记日志跳过，不阻断整体。
3. 回填前先备份（见 Q7）。
4. 回填是"尽力而为"，不要求 100%，因为 raw_data 本就保留了完整信息。

### Q6. 是否需要 schema_version / migration_history 表？

**需要。推荐建一张轻量 `schema_migrations` 表。**

设计：

```sql
CREATE TABLE IF NOT EXISTS schema_migrations (
    version_num  VARCHAR(32) PRIMARY KEY,   -- 形如 20260615_001
    applied_at   DATETIME NOT NULL,         -- DEFAULT CURRENT_TIMESTAMP
    description  VARCHAR(200)               -- 本次迁移说明
);
```

职责：

1. 记录已应用的迁移版本，判断库当前处于哪个 schema。
2. 迁移脚本启动时先查 `schema_migrations`，已应用则跳过（幂等）。
3. 不依赖 Alembic，纯手写即可。

**注意**：

- 这张表自身也通过 create_all 或第一个迁移脚本建。
- 表名用 `schema_migrations`（Alembic 用 `alembic_version`，这里故意区分，避免未来引入 Alembic 时冲突）。
- 该表**不进** PRD 业务模型，是纯基础设施表，放在迁移脚本目录管理，不写进 `models.py`（避免污染业务 ORM）。

### Q7. 如何做迁移前备份？

SQLite 备份策略（按优先级）：

1. **首选：在线备份 API（sqlite3 backup_to）**——WAL 模式下安全，不锁库：

   ```python
   import sqlite3
   src = sqlite3.connect("data/auto_wechat.db")
   dst = sqlite3.connect(f"data/backup/auto_wechat.db.{timestamp}.bak")
   src.backup(dst)
   ```

   优点：WAL 安全、得到一致性快照、不阻塞业务。

2. **次选：文件拷贝**——必须在业务停机时（停 uvicorn）拷贝 `.db` + `.db-wal` + `.db-shm` 三个文件。

3. **禁止**：迁移前不备份直接 ALTER。

备份位置：`data/backup/`（gitignore 排除）。备份保留至本次迁移验证通过且稳定运行 N 天后再清理。

迁移脚本第一步强制检查备份存在性，未备份则拒绝执行。

### Q8. 如何做迁移后验证？

> **验收口径（见 §0c-1）**：WAL 模式下 `.db` 文件 hash 不能作为「数据未变化」的唯一证据，checkpoint 会改 hash 但不改业务数据。验收以结构对比 + 数据语义对比为主，hash 仅作辅助参考。

验证清单（迁移脚本结束后自动执行 + 人工复核）：

1. **结构验证（主）**：`PRAGMA table_info(douyin_leads)` / `PRAGMA table_info(sales_staff)` 确认新列存在、类型正确、可空性符合预期。
2. **版本验证**：`SELECT version_num FROM schema_migrations` 确认版本已写入。
3. **行数验证（主）**：迁移前后各表 `COUNT(*)` 一致（ADD COLUMN 不应改行数；回填 UPDATE 不应改行数）。
4. **旧数据抽样验证（主）**：抽查关键表旧记录的关键字段（`status` / `source_id` / `customer_name` 等）未被改动；新增联系方式类列旧行应为 NULL（符合不回填边界）；`reassign_count` 旧行应为 0。
5. **回填验证**：抽查 N 条旧记录的新列是否有值（仅针对已执行回填的字段）。
6. **应用冒烟**：启动 uvicorn，调一次只读接口（`GET /leads`、`GET /webhook-events`），确认无 `no such column`。
7. **业务回归**：跑 `tests/` 全量（当前基线见最新运行结果），确认无回归。
8. **WAL 检查点（单独确认后执行）**：迁移稳定后可执行 `PRAGMA wal_checkpoint(TRUNCATE)` 收缩 `-wal`；**但 checkpoint 会改变 `.db` 文件 hash**，因此必须在结构 / 数据验收通过之后再做，不能用它反推验收结论。
9. **文件 hash（仅辅助）**：迁移前后 `.db` hash 可记录备查，但「hash 是否一致」不作为主线是否被修改的判据（见 §0c-1）。

### Q9. 如何回滚？

SQLite 的 ALTER TABLE ADD COLUMN **无法直接 DROP COLUMN**（老版本 SQLite 不支持 DROP COLUMN，3.35+ 支持但有限制）。回滚策略：

1. **首选回滚：恢复备份**——迁移前已做 `backup_to` 备份，回滚即（未来生产场景停服；当前测试库可直接执行）→ 用备份覆盖 `data/auto_wechat.db` → 重启。
2. **schema_migrations 回滚**：DELETE 对应版本记录（若用备份恢复则自动回到旧版本，无需手动删）。
3. **代码回滚**：models.py 的字段改动 git revert。
4. **不依赖 DROP COLUMN 回滚**：因为不可靠且 SQLite 版本敏感。

结论：**回滚 = 备份恢复 + 代码 revert**。这是 SQLite 单库场景下最稳的回滚路径。

### Q10. 开发库初始化和已有库（当前开发测试库 / 未来生产库）升级如何共存？

两套路径，共用同一份迁移脚本：

**路径 A：全新库初始化（开发 / 未来新客户库）**

```text
Base.metadata.create_all()  # 建所有表（含新字段）
→ 执行 migration 0001（建 schema_migrations 表 + 写基线版本）
→ 可选执行回填脚本（全新库通常不需要历史回填）
```

**路径 B：已有库升级（当前开发测试库 / 未来生产库）**

```text
备份（当前测试库可直接 backup_to；未来生产场景建议停服）
→ 执行 migration 0001（CREATE TABLE IF NOT EXISTS schema_migrations）
→ 执行 migration 0002（ADD COLUMN ...）
→ 执行回填脚本（按需）
→ 执行 migration 0003（写入 schema_migrations 版本）
→ wal_checkpoint
```

> 路径 B 对当前开发测试库：确认后可直接执行，无需停服。
> 路径 B 对未来生产库：建议停服 + 低峰执行。

**共存原则**：

1. `create_all` 保留，作为全新库的建表入口（开发友好）。
2. 已有库（当前开发测试库 / 未来生产库）不走 create_all 加列，走迁移脚本。
3. 迁移脚本全部 `IF NOT EXISTS` / 幂等，对全新库（已被 create_all 建好）执行时自动跳过已存在列。
4. `schema_migrations` 是唯一真相源：脚本启动先查它，决定是否执行。

> 即：create_all 负责"建"，migration 负责"演进"，两者不冲突，因为 migration 全部幂等。

### Q11. 第一批最小迁移字段应该包括哪些？

**推荐第一批只做 schema_migrations 基础设施 + 最高优先级字段**，避免一次性大迁移。

第一批（migration 0001 + 0002）：

```text
0001: CREATE TABLE schema_migrations（基础设施，不进入 app/models.py）
0002: ALTER TABLE douyin_leads
        ADD COLUMN raw_message_text TEXT;
        ADD COLUMN extracted_phone TEXT;
        ADD COLUMN extracted_wechat TEXT;
        ADD COLUMN all_extracted_contacts TEXT;
        ADD COLUMN contact_extract_status TEXT;
        ADD COLUMN contact_extract_reason TEXT;
        ADD COLUMN reassign_count INTEGER NOT NULL DEFAULT 0;
        ADD COLUMN customer_id TEXT;
        ADD COLUMN external_customer_id TEXT;
      ALTER TABLE sales_staff
        ADD COLUMN sort_order INTEGER;
        ADD COLUMN remark TEXT;
```

> **字段口径声明（最终确认）**：
>
> 1. `DouyinLead.status` **已存在**，不作为新增字段。本批迁移不新增 `status` 列，仅由后续业务阶段（P5 状态机）扩展其取值域。
> 2. 新增列除 `reassign_count` 外，全部允许 `NULL` 默认（SQLite 对旧行自动填 NULL）。
> 3. `reassign_count` 唯一例外：`INTEGER NOT NULL DEFAULT 0`。
> 4. 全部联系方式 / 原始文本 / 备注类列统一用 `TEXT`，不再用 `VARCHAR(n)`（SQLite 不强制长度，`TEXT` 更贴合 PRD 口径）。
> 5. `schema_migrations` 是迁移基础设施表，**不进入 `app/models.py`**，仅由迁移 runner 维护。

选这批的理由：

- `raw_message_text`：保存完整用户私信原文，是联系方式提取与 invalid 展示（P2 PRD §7）的基础。
- `extracted_phone` / `extracted_wechat`：主联系方式字段，导出（P11）和 invalid 展示（P2 PRD §7）依赖。
- `all_extracted_contacts`：保存全部提取结果（建议 JSON 数组），支持一个消息内多个联系方式。
- `contact_extract_status` / `contact_extract_reason`：提取状态与失败原因，invalid 判定与展示依赖。
- `reassign_count`：超时重分配（P7）硬依赖，且必须 `NOT NULL DEFAULT 0`。
- `customer_id` / `external_customer_id`：NewCarProject 预留（P12），先占位。
- `sort_order`：销售顺序轮询（P6）依赖，可回填为现有 id 序。
- `remark`：销售管理（P6）依赖，纯新增无需回填。

第一批**不含**：

- `external_lead_id / account_open_id / conversation_short_id / server_message_id`（幂等键，可单独成第三批，且部分仅在需要事件级查询时才必要）。
- `CallbackLog` 表（状态回调对接时再加，属 P3）。
- 状态机扩展（不改结构，只改取值域与映射层，属 P5 业务改动，不属于迁移；`DouyinLead.status` 列已存在，无需新增）。

### Q12. 哪些字段应该延后？

| 字段 | 延后到 | 原因 |
|------|--------|------|
| `external_lead_id` | P4 幂等体系 | 当前 source_id 去重够用 |
| `account_open_id` | P4 | 同上 |
| `conversation_short_id` / `server_message_id` | P4 事件级查询需求出现时 | 仅查询优化用，非必需 |
| `CallbackLog` 表 | P3 状态回调对接时 | 第一版状态回调未对接 |
| 状态机取值域扩展 | P5 | 不改结构，是业务改动（`status` 列已存在，仅扩取值域） |
| 业务二级索引（source_id 等） | 性能阶段（P20 QPS） | 当前数据量小，无性能瓶颈 |

延后原则：**按需迁移，不为可能的需求提前加列**（遵循 02_EXECUTION_RULES §3 禁止提前抽象）。

### Q13. 迁移执行前需要人工确认哪些事项？

见第 7 节"执行前人工确认清单"。

------

## 4. 推荐迁移方案（总结）

### 4.1 方案选型

```text
手写迁移脚本 + schema_migrations 版本表
不引入 Alembic（第一版）
不删库重建
不依赖 DROP COLUMN 回滚
```

### 4.2 目录结构建议（执行阶段才创建，本阶段不建）

```text
migrations/
├── README.md
├── runner.py                    # 迁移执行器（查 schema_migrations → 执行未应用脚本 → 写版本）
├── backup.py                    # backup_to 在线备份
├── versions/
│   ├── 0001_schema_migrations.py
│   ├── 0002_douyin_leads_staff_fields.py
│   └── 0002b_backfill_extracted_contacts.py   # 回填脚本，与结构脚本分离
└── verify.py                    # 迁移后验证
```

> 本阶段只设计结构，不创建上述文件（禁止初始化 Alembic / 建目录是本阶段约束）。

### 4.3 迁移执行流程

```text
1. 确认目标库（data/auto_wechat.db，非 docker-data）
2. 备份（当前测试库可直接 backup_to；未来生产场景停服或低峰）
3. backup_to 备份到 data/backup/
4. 运行 runner.py：
   a. 建 schema_migrations（IF NOT EXISTS）
   b. 逐个 version 检查是否已应用，未应用则执行
   c. 执行成功 → 写 schema_migrations
   d. 失败 → 抛异常，不写版本，人工回滚
5. 运行回填脚本（按需）
6. 运行 verify.py
7. wal_checkpoint(TRUNCATE)
8. 启动 uvicorn 冒烟
9. 跑 tests/ 全量回归
```

### 4.4 幂等性保证

- 每个 ADD COLUMN 前先 `PRAGMA table_info` 检查列是否已存在，存在则跳过。
- 每个 version 先查 `schema_migrations`，已应用则跳过。
- 回填 UPDATE 带 `WHERE col IS NULL`，可重复执行。

------

## 5. 不推荐方案及原因

| 方案 | 不推荐原因 |
|------|-----------|
| 引入 Alembic（第一版） | 依赖增加、学习成本、与 create_all 共存复杂、exe 打包影响、SQLite DDL 限制下 autogenerate 价值有限；手写更可控 |
| 删库重建加字段 | 会丢失开发测试数据（44 线索 + 11 检测 + webhook 事件）；未来生产库更是不可接受 |
| 依赖 DROP COLUMN 回滚 | SQLite 版本敏感、不可靠；回滚应走备份恢复 |
| 在 create_all 里直接加列 | create_all 不 ALTER 已存在表，新列不生效，旧库报 `no such column` |
| 一次性大迁移（所有字段一批） | 回归面大、回填逻辑复杂、出错难定位；应分批小步迁移 |
| 用 Django/其他 ORM 迁移工具 | 与现有 SQLAlchemy 2.x + DeclarativeBase 架构冲突 |
| 共享 douyinAPI 的 SQLite 文件 | 违反系统边界（CLAUDE.md Upstream System Constraints 禁止 SQLite 文件共享） |

------

## 6. 回滚方案

```text
触发条件：
  - 迁移后应用启动报 no such column
  - 迁移后 tests/ 回归失败
  - 迁移后业务接口异常
  - 回填脚本数据异常

回滚步骤：
  1. 停 uvicorn
  2. 用 data/backup/auto_wechat.db.{timestamp}.bak 覆盖 data/auto_wechat.db
     （同时处理 -wal / -shm，或直接删除它们让 SQLite 重建）
  3. git revert models.py 的字段改动
  4. 重启 uvicorn
  5. 跑 tests/ 确认回到迁移前基线（722 passed）

注意：
  - schema_migrations 表在回滚后随备份一起回到旧版本（不存在），无需手动处理
  - 回填脚本独立，回滚结构后回填的数据也随备份一起消失
```

------

## 7. 执行前人工确认清单

> 本阶段（DB-MIG）只输出方案，以下确认项是**下一阶段（执行迁移）**开始前的 gate，不是现在就要回答。

执行迁移前必须人工确认：

1. **目标库确认**：迁移目标是 `data/auto_wechat.db`（9000 实际使用），`docker-data/auto_wechat.db` 是否也要迁？还是废弃？
2. **停机窗口确认（仅未来生产场景适用）**：当前测试库迁移无需停服；未来生产场景是否停 uvicorn / 低峰执行。
3. **备份策略确认**：采用 `backup_to` 在线备份（当前测试库与未来生产库均适用）还是停服文件拷贝（仅未来生产场景）？备份保留多久？
4. **第一批字段范围确认**：第 Q11 的第一批字段范围是否认可？是否要增删？
5. **回填范围确认**：第 Q5 的回填字段哪些必须回填（reassign_count=0 必做，其余按需）？
6. **schema_migrations 表名确认**：用 `schema_migrations`（避免与未来 Alembic 的 `alembic_version` 冲突）是否认可？
7. **sort_order 回填策略确认**：回填为现有 `id` 序，还是其他业务排序？
8. **字段命名确认**：`extracted_phone` / `customer_id` / `external_customer_id` 等命名是否符合 PRD §8 / §11 口径？
9. **DEFAULT 策略确认**：除 `reassign_count=0` 外，其余新增列是否都接受 NULL 默认？
10. **测试基线确认**：当前 722 passed 是回归基线，迁移后必须维持或增加。
11. **WAL 处理确认**：迁移后是否执行 `wal_checkpoint(TRUNCATE)` 收缩 WAL（当前 -wal 已达 4MB）？
12. **迁移脚本是否纳入版本管理**：`migrations/` 目录是否进 git？（建议进，便于多机同步）
13. **执行人确认**：迁移由谁执行、谁复核、谁签字。

------

## 8. 风险点

| 级别 | 风险 | 缓解 |
|------|------|------|
| HIGH | 迁移写错库（误迁 docker-data 而非 data） | 迁移脚本强制显示目标库绝对路径并二次确认 |
| HIGH | 迁移前未备份导致数据丢失 | runner.py 强制检查备份文件存在性，无备份拒绝执行 |
| HIGH | ADD COLUMN 后应用未重启 / 旧进程缓存 schema | 迁移后强制重启 uvicorn，冒烟验证 |
| MEDIUM | 回填脚本解析 raw_data JSON 失败 | 单条失败记日志跳过，不阻断；raw_data 本身保留完整信息 |
| MEDIUM | 两个 db 文件并存导致环境混乱 | 明确 data/ 为主库，docker-data/ 标注为非主线；第一版迁移只针对 data/ |
| MEDIUM | WAL 文件过大（当前 -wal 4MB）影响备份一致性 | 备份用 backup_to（WAL 安全），迁移稳定后单独确认再 wal_checkpoint |
| HIGH | 误用 `.db` 文件 hash 判断主线是否被迁移修改 | WAL checkpoint 会改 hash 但不改业务数据（P2-A 实测确认，见 §0c-1）；验收必须以 `PRAGMA table_info` / 行数 / 关键字段抽样为主，hash 仅辅助 |
| MEDIUM | check_configs 0 行，迁移不应依赖它 | 第一批迁移不涉及 check_configs，独立处理 |
| LOW | sort_order 回填后顺序轮询改变现有分配行为 | 回填为 id 序，与现有 auto_assign_next 的"最少分配"行为不同，需在 P6 评估 |
| LOW | 无业务二级索引，大数据量下查询慢 | 当前数据量小（44 行），延后到性能阶段 |

------

## 9. 结论与下一步

### 9.1 结论

- 第一版采用**手写迁移脚本 + schema_migrations 版本表**，不引入 Alembic。
- 第一批迁移只做基础设施（`schema_migrations`，不进入 `app/models.py`）+ 第一批字段：
  - `douyin_leads` 新增 9 列：`raw_message_text`、`extracted_phone`、`extracted_wechat`、`all_extracted_contacts`、`contact_extract_status`、`contact_extract_reason`、`reassign_count`（`NOT NULL DEFAULT 0`）、`customer_id`、`external_customer_id`。
  - `sales_staff` 新增 2 列：`sort_order`、`remark`。
  - **`DouyinLead.status` 已存在，本批不新增、不改动**（取值域扩展属 P5 业务阶段）。
- 回滚 = 备份恢复 + 代码 revert，不依赖 DROP COLUMN。
- create_all（建）与 migration（演进）共存，migration 全部幂等。

### 9.2 下一步

本阶段（DB-MIG）只输出方案。下一步不是直接修改 `models.py`，也不是直接迁移 `data/auto_wechat.db`，而是等待用户确认后进入 **P2-A：迁移脚本骨架与副本 dry-run**。

```text
当前：DB-MIG 方案已输出（本文件）
  ↓
用户确认是否进入 P2-A
  ↓
P2-A：编写 migrations/ 脚本骨架（runner / backup / verify），并只在 data/auto_wechat.db 的复制副本上 dry-run / apply 验证
  ↓
P2-B：确认 P2-A 安全后，才允许 models.py 字段补齐
  ↓
P2-C：确认 P2-B 后，才允许对当前开发测试主线库 data/auto_wechat.db 执行正式迁移
  ↓
P3~P12 按阶段边界继续推进
```

进入 P2-A 前必须重新复述 P2-A 的阶段目标、允许修改范围、禁止事项、验收标准，并等待用户确认。
