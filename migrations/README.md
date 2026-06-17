# 数据库迁移骨架（P2-A）

本目录是 `auto_wechat` 的 SQLite 迁移基础设施。第一版采用**手写迁移脚本 + `schema_migrations` 版本表**，不引入 Alembic。

## 目录结构

```text
migrations/
├── migrate_sqlite.py                  # 迁移执行器（单文件，自包含，不 import app）
├── versions/
│   └── 0001_prd_base_fields.sql       # 首批 PRD 基础字段（schema_migrations + douyin_leads 9 列 + sales_staff 2 列）
└── README.md
```

## 安全边界（P2-A 阶段）

- **不修改** `app/models.py`（`schema_migrations` 不进入 ORM 模型，仅由本目录维护）。
- **不对** `data/auto_wechat.db` 主线开发测试库执行真实迁移（默认拒绝主线路径，需 `--allow-mainline` 才放行，P2-A 不使用）。
- dry-run / verify 使用只读连接（`?mode=ro`），apply 使用读写连接。
- apply 在单一事务内执行全部 DDL + 版本记录，任一失败整体回滚。
- 幂等：`schema_migrations` 版本表 + 列存在性检查双重保护，重复执行不报错、不重复加字段。

## 字段清单（0001，已锁定）

| 表 | 新增列 | 类型 |
|----|--------|------|
| `schema_migrations` | `version_num` / `applied_at` / `description` | 基础设施（不进 models.py） |
| `douyin_leads` | `raw_message_text` | TEXT NULL |
| `douyin_leads` | `extracted_phone` | TEXT NULL |
| `douyin_leads` | `extracted_wechat` | TEXT NULL |
| `douyin_leads` | `all_extracted_contacts` | TEXT NULL |
| `douyin_leads` | `contact_extract_status` | TEXT NULL |
| `douyin_leads` | `contact_extract_reason` | TEXT NULL |
| `douyin_leads` | `reassign_count` | **INTEGER NOT NULL DEFAULT 0** |
| `douyin_leads` | `customer_id` | TEXT NULL |
| `douyin_leads` | `external_customer_id` | TEXT NULL |
| `sales_staff` | `sort_order` | INTEGER NULL |
| `sales_staff` | `remark` | TEXT NULL |

> `douyin_leads.status` **已存在**，本批不新增、不改动；取值域扩展属 P5 状态机阶段。

## P2-A 回填边界

P2-A 只验证迁移机制，不做复杂业务回填：

- **允许**：`reassign_count` 由 `ADD COLUMN ... NOT NULL DEFAULT 0` 对旧行自动填 0。
- **不做**：不从 `raw_data` JSON 回填联系方式字段；不回填 `raw_message_text` / `extracted_phone` 等其余新增列；不改变已有 `status`；不改变分配逻辑。
- `sales_staff.sort_order` 是否回填为 id 序，放 P2-C 或 P6 前再确认。

## 主线验收口径（WAL 模式下重要）

> **结论：`.db` 文件 hash / mtime 不能作为「数据未变化」的唯一证据。**

当前 `data/auto_wechat.db` 是**开发测试库**（非生产库），SQLite 处于 **WAL 模式**（主 `.db` + `-wal` + `-shm` 三文件）。WAL 模式下：

1. 任何 `wal_checkpoint` 都可能把历史 `-wal` 帧合并进主 `.db`，导致 `.db` **文件 hash / mtime 变化**，但**业务数据和结构完全不变**（WAL 本就是 `.db` 的一部分，只是合并时机不同）。
2. 因此「迁移前后 `.db` hash 是否一致」**不能**用来证明主线是否被迁移修改——即便迁移脚本零写入，只要发生 checkpoint，hash 就会变。
3. 文件 hash **只能作为辅助参考**，不能作为唯一判断依据。

**可靠的验收指标（必须以此为主）**：

- `PRAGMA table_info(douyin_leads)` —— 新增列是否存在、类型 / 可空性正确
- `PRAGMA table_info(sales_staff)` —— 同上
- `schema_migrations` 是否存在、`version_num` 版本记录是否正确
- 关键表行数迁移前后是否一致（`COUNT(*)`，ADD COLUMN 不应改行数）
- 旧数据关键字段抽样是否一致（如 `status`、`source_id`、`customer_name` 未被改动）
- `reassign_count` 默认值是否符合预期（旧行自动为 0）
- 新增列旧数据是否为预期值（联系方式类列应为 NULL，符合 P2-A 不回填边界）

P2-C 主线迁移前如需处理 WAL（如收缩 4MB `-wal`），应**单独确认后再执行 checkpoint**，迁移骨架阶段不执行 checkpoint。

## 副本验证流程（推荐）

```bash
# 0. 记录主线结构基线（不是 hash，是结构 + 数据）——只读，不执行 DDL / checkpoint
python -c "import sqlite3; c=sqlite3.connect('file:data/auto_wechat.db?mode=ro',uri=True); print([r[1] for r in c.execute('PRAGMA table_info(douyin_leads)')]); print(c.execute('SELECT count(*) FROM douyin_leads').fetchone()[0]); c.close()"

# 1. 用 backup API 生成一致性副本（WAL 安全，不依赖 copy2）
python migrations/migrate_sqlite.py --backup-src data/auto_wechat.db --backup-dst data/auto_wechat.db.migtest

# 2. 副本 dry-run（只打印，不写库）
python migrations/migrate_sqlite.py --db-path data/auto_wechat.db.migtest --dry-run

# 3. 副本 apply（单一事务写库）
python migrations/migrate_sqlite.py --db-path data/auto_wechat.db.migtest --apply

# 4. 副本验证（结构 + 版本 + 行数 + 默认值）
python migrations/migrate_sqlite.py --db-path data/auto_wechat.db.migtest --verify

# 5. 幂等验证：再次 apply 不报错、不重复加字段
python migrations/migrate_sqlite.py --db-path data/auto_wechat.db.migtest --apply

# 6. 主线结构复核：重跑步骤 0 的只读查询，列清单 / 行数应与基线一致
#    （注：.db 文件 hash 可能因 WAL checkpoint 变化，不作为主线是否被改的判据）
```

> 直接 `--db-path data/auto_wechat.db` 会被拒绝（主线防护），除非加 `--allow-mainline`（P2-C 阶段才用）。

## 阶段定位

- **P2-A**：迁移脚本骨架 + 副本 dry-run / apply 验证（已完成 ✅）。
- **P2-A-END**：WAL/hash 验收口径修正（已完成 ✅）。
- **P2-C**（下一步）：确认 P2-A 安全后，对主线 `data/auto_wechat.db` 执行正式迁移（`--allow-mainline`）。**先于 P2-B**。
- **P2-B**：确认 P2-C 主线库已迁出新列后，才允许 `models.py` 字段补齐。**后于 P2-C**。

> **顺序说明**：P2-C 先于 P2-B。原因：若先改 `models.py` 而主线库未迁移，SQLAlchemy 模型会认为新字段已存在但实际表无此列，运行时缺列报错。先迁库再补模型，确保数据库结构与模型同步。
