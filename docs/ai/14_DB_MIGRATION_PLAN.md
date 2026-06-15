# 数据库迁移体系方案（DB-MIG）

版本：DB-MIG-PLAN-1
状态：方案设计（只读探索 + 方案输出）。本阶段未修改任何业务代码、未执行迁移、未新增字段、未安装依赖、未初始化 Alembic、未对任何数据库文件做写操作。
范围：回答 13 个决策问题，给出推荐迁移方案、不推荐方案、第一批迁移字段、回滚方案、风险点、执行前人工确认清单。

更新时间：2026-06-15

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
| 生产库有真实数据 | data 库有 44 条线索 + 11 条检测记录 + webhook 事件 | 直接删库重建会丢数据，不可接受 |
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

见第 2 节。核心：只建不更、无版本、无回滚、生产库有数据。

### Q3. 新增字段如何兼容已有生产库？

采用「ALTER TABLE ADD COLUMN + NULL 默认」策略：

1. 所有新增列在 models.py 中**不设 NOT NULL、不设服务端 default**（Python 侧可给 default，但数据库列保持可空）。
2. 迁移脚本用 `ALTER TABLE 表名 ADD COLUMN 列名 类型;`，SQLite 对旧行自动填 NULL。
3. 由于现有业务列本就大量允许 NULL（见 1.6），新增列容忍 NULL 与现状一致，不会破坏现有读写逻辑。
4. 需要回填的字段（见 Q5）单独走 UPDATE 脚本，与 ADD COLUMN 解耦。

**禁止操作**：不通过删表重建来加字段（会丢生产数据）。

### Q4. 哪些字段允许 NULL 默认？

**全部新增字段都允许 NULL 默认**（第一版策略）。

具体：

- 联系方式提取结果列（`extracted_phone` / `extracted_wechat` / `all_extracted_contacts` / `contact_extract_status` / `contact_extract_reason`）→ NULL，因为旧线索的提取结果已在 `raw_data` JSON 内，迁移后新线索才写独立列，旧线索保持 NULL 或回填（见 Q5）。
- 幂等键列（`external_lead_id` / `account_open_id` / `conversation_short_id` / `server_message_id`）→ NULL，旧线索这些值在 raw_body 内，按需回填。
- `reassign_count` → 允许 NULL，但建议给默认值 0（见下）。
- `customer_id` / `external_customer_id` → NULL，NewCarProject 未对接。
- `SalesStaff.remark` / `sort_order` → NULL；sort_order 建议回填为现有 id 序（见 Q5）。
- `DouyinLead.status` → 不新增列，只是扩展取值域（从 3 态扩到 13 态），无需迁移结构。

**例外（建议给默认值而非纯 NULL）**：

- `reassign_count INTEGER DEFAULT 0`：计数列，NULL 会让 `count + 1` 逻辑出错，应给 0。
- `sort_order INTEGER`：可空，回填脚本赋值。

### Q5. 哪些字段需要历史数据回填？

| 字段 | 是否回填 | 回填来源 | 必要性 |
|------|---------|---------|--------|
| `extracted_phone` / `extracted_wechat` / `all_extracted_contacts` / `contact_extract_status` | 建议回填 | 解析 `douyin_leads.raw_data` JSON 的 `contact_extract` 节点 | 中（不回填则旧线索在列表/导出时提取列空，但 raw_data 仍有值） |
| `contact_extract_reason` | 建议回填 | 同上 | 中 |
| `external_lead_id` | 可回填 | 用现有 `source_id`（= from_user_id）回填，或留空 | 低 |
| `account_open_id` / `conversation_short_id` / `server_message_id` | 可回填 | 解析 `raw_data.webhook_payload.content` | 低（仅在需要事件级幂等查询时才有价值） |
| `reassign_count` | 必须回填 0 | 直接 `UPDATE ... SET reassign_count=0 WHERE reassign_count IS NULL` | 高（计数列不能 NULL） |
| `customer_id` / `external_customer_id` | 不回填 | NewCarProject 未对接 | — |
| `SalesStaff.sort_order` | 建议回填 | `UPDATE sales_staff SET sort_order=id WHERE sort_order IS NULL` | 中（顺序轮询依赖） |
| `SalesStaff.remark` | 不回填 | 无历史值 | — |

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

验证清单（迁移脚本结束后自动执行 + 人工复核）：

1. **结构验证**：`PRAGMA table_info(表)` 确认新列存在、类型正确、可空。
2. **版本验证**：`SELECT version_num FROM schema_migrations` 确认版本已写入。
3. **行数验证**：迁移前后各表 `COUNT(*)` 一致（ADD COLUMN 不应改行数；回填 UPDATE 不应改行数）。
4. **回填验证**：抽查 N 条旧记录的新列是否有值（针对回填字段）。
5. **应用冒烟**：启动 uvicorn，调一次只读接口（`GET /leads`、`GET /webhook-events`），确认无 `no such column`。
6. **业务回归**：跑 `tests/` 全量（当前 722 passed 基线），确认无回归。
7. **WAL 检查点**：迁移后执行 `PRAGMA wal_checkpoint(TRUNCATE)`，确保 WAL 内容落主库。

### Q9. 如何回滚？

SQLite 的 ALTER TABLE ADD COLUMN **无法直接 DROP COLUMN**（老版本 SQLite 不支持 DROP COLUMN，3.35+ 支持但有限制）。回滚策略：

1. **首选回滚：恢复备份**——迁移前已做 `backup_to` 备份，回滚即停服 → 用备份覆盖 `data/auto_wechat.db` → 重启。
2. **schema_migrations 回滚**：DELETE 对应版本记录（若用备份恢复则自动回到旧版本，无需手动删）。
3. **代码回滚**：models.py 的字段改动 git revert。
4. **不依赖 DROP COLUMN 回滚**：因为不可靠且 SQLite 版本敏感。

结论：**回滚 = 备份恢复 + 代码 revert**。这是 SQLite 单库场景下最稳的回滚路径。

### Q10. 开发库初始化和生产库升级如何共存？

两套路径，共用同一份迁移脚本：

**路径 A：全新开发库初始化**

```text
Base.metadata.create_all()  # 建所有表（含新字段）
→ 执行 migration 0001（建 schema_migrations 表 + 写基线版本）
→ 可选执行回填脚本（开发库通常不需要历史回填）
```

**路径 B：已有生产库升级**

```text
不停服（WAL backup_to 先备份）
→ 执行 migration 0001（CREATE TABLE IF NOT EXISTS schema_migrations）
→ 执行 migration 0002（ADD COLUMN ...）
→ 执行回填脚本（按需）
→ 执行 migration 0003（写入 schema_migrations 版本）
→ wal_checkpoint
```

**共存原则**：

1. `create_all` 保留，作为全新库的建表入口（开发友好）。
2. 生产库不走 create_all 加列，走迁移脚本。
3. 迁移脚本全部 `IF NOT EXISTS` / 幂等，对全新库（已被 create_all 建好）执行时自动跳过已存在列。
4. `schema_migrations` 是唯一真相源：脚本启动先查它，决定是否执行。

> 即：create_all 负责"建"，migration 负责"演进"，两者不冲突，因为 migration 全部幂等。

### Q11. 第一批最小迁移字段应该包括哪些？

**推荐第一批只做 schema_migrations 基础设施 + 最高优先级字段**，避免一次性大迁移。

第一批（migration 0001 + 0002）：

```text
0001: CREATE TABLE schema_migrations（基础设施）
0002: ALTER TABLE douyin_leads
        ADD COLUMN extracted_phone VARCHAR(100);
        ADD COLUMN extracted_wechat VARCHAR(100);
        ADD COLUMN contact_extract_status VARCHAR(30);
        ADD COLUMN reassign_count INTEGER DEFAULT 0;
        ADD COLUMN customer_id VARCHAR(64);
        ADD COLUMN external_customer_id VARCHAR(64);
      ALTER TABLE sales_staff
        ADD COLUMN sort_order INTEGER;
        ADD COLUMN remark VARCHAR(200);
```

选这批的理由：

- `reassign_count`：超时重分配（P7）硬依赖，且必须 DEFAULT 0。
- `extracted_phone/wechat/status`：导出（P10）和 invalid 展示（P2 PRD §7）依赖，回填来源清晰（raw_data JSON）。
- `customer_id/external_customer_id`：NewCarProject 预留（P11），先占位。
- `sort_order`：销售顺序轮询（P6）依赖，可回填为现有 id 序。
- `remark`：销售管理（P6）依赖，纯新增无需回填。

第一批**不含**：

- `all_extracted_contacts`（TEXT JSON 列，可延后，导出第一版可不导全量）。
- `external_lead_id / account_open_id / conversation_short_id / server_message_id`（幂等键，可单独成第三批，且部分仅在需要事件级查询时才必要）。
- `contact_extract_reason`（可延后，失败原因已在 raw_data）。
- 状态机扩展（不改结构，只改取值域与映射层，属 P5 业务改动，不属于迁移）。

### Q12. 哪些字段应该延后？

| 字段 | 延后到 | 原因 |
|------|--------|------|
| `all_extracted_contacts`（TEXT） | P10 导出阶段 | 体积大，第一版导出未必需要全量 |
| `contact_extract_reason` | P4 后 | 失败原因已有 raw_data 兜底 |
| `external_lead_id` | P4 幂等体系 | 当前 source_id 去重够用 |
| `account_open_id` | P4 | 同上 |
| `conversation_short_id` / `server_message_id` | P4 事件级查询需求出现时 | 仅查询优化用，非必需 |
| `CallbackLog` 表 | P3 状态回调对接时 | 第一版状态回调未对接 |
| 状态机取值域扩展 | P5 | 不改结构，是业务改动 |
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
2. 停服或确认低峰（WAL backup_to 可在线，但建议低峰）
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
| 删库重建加字段 | 会丢生产数据（44 线索 + 11 检测 + webhook 事件） |
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
2. **停机窗口确认**：迁移是否需要停 uvicorn？WAL backup_to 虽可在线，但 ADD COLUMN 在 SQLite 上会短暂锁表，建议低峰。
3. **备份策略确认**：采用 `backup_to` 在线备份还是停服文件拷贝？备份保留多久？
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
| MEDIUM | WAL 文件过大（当前 -wal 4MB）影响备份一致性 | 备份用 backup_to（WAL 安全），迁移后 wal_checkpoint |
| MEDIUM | check_configs 0 行，迁移不应依赖它 | 第一批迁移不涉及 check_configs，独立处理 |
| LOW | sort_order 回填后顺序轮询改变现有分配行为 | 回填为 id 序，与现有 auto_assign_next 的"最少分配"行为不同，需在 P6 评估 |
| LOW | 无业务二级索引，大数据量下查询慢 | 当前数据量小（44 行），延后到性能阶段 |

------

## 9. 结论与下一步

### 9.1 结论

- 第一版采用**手写迁移脚本 + schema_migrations 版本表**，不引入 Alembic。
- 第一批迁移只做基础设施（schema_migrations）+ 6 个高优先级字段（reassign_count、extracted_phone/wechat/status、customer_id、external_customer_id、sort_order、remark）。
- 回滚 = 备份恢复 + 代码 revert，不依赖 DROP COLUMN。
- create_all（建）与 migration（演进）共存，migration 全部幂等。

### 9.2 下一步

本阶段（DB-MIG）只输出方案。下一步需等待用户对第 7 节"执行前人工确认清单"逐条确认后，才进入迁移执行阶段（P2 models 字段补齐 + 迁移脚本编写）。

```text
当前：DB-MIG 方案已输出（本文件）
  ↓
用户确认第 7 节 13 项
  ↓
编写 migrations/ 脚本骨架（runner / backup / verify）+ models.py 字段补齐
  ↓
本地 data/ 库执行迁移（先备份 → 迁移 → 验证 → 回归测试）
  ↓
通过后进入 P3 webhook 验签规范化
```
