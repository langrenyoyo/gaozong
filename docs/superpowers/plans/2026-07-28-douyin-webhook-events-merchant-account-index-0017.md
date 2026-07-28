# 抖音 webhook 事件商户账号复合索引 0017 迁移实施计划

> **状态：已审批 R1-DRAFT 决策，待执行**。本计划是 Database Migration 高风险任务，按 CLAUDE.md「High Risk Areas」已完成风险分析并经用户审批 §4 决策点。
>
> **执行方式：** 本项目固定原地执行，不创建 worktree、不新建分支、不切目录（CLAUDE.md 硬约束 10）。步骤使用复选框跟踪。

**Goal:** 为 `douyin_webhook_events` 增加以 `(merchant_id, <账号列>, id)` 开头的复合索引，使抖音会话增量协议的游标查询（`merchant_id = ? AND (to_user_id = ? OR from_user_id = ?) AND id > cursor ORDER BY id ASC LIMIT N`）从全表扫描退化为索引范围扫描，闭合计划一 Task 4 的 PostgreSQL 执行计划门禁（无 `Seq Scan`、`Rows Removed by Filter <= 5000`）。

**Architecture:** 仅新增索引，不改表结构、不改业务查询逻辑。索引列顺序以等值过滤列（`merchant_id`、账号列）在前、范围/排序列（`id`）在末尾，支撑游标范围扫描。迁移须在 PostgreSQL 生产轨与 SQLite 过渡轨同步落地（若 SQLite 轨同样会触发全表扫描，否则只补 PG 轨并记录差异）。

**Tech Stack:** Alembic（PostgreSQL 生产轨）、SQL 迁移脚本（SQLite/通用轨）、PostgreSQL 15、SQLite。

---

## 0. 执行合同

- Task-ID：`DY-CS-DOUYIN-WEBHOOK-EVENTS-MERCHANT-ACCOUNT-INDEX-0017-1`
- Plan-Revision：`R1-DRAFT`
- 关联计划：计划一 `DY-CS-CONVERSATION-INCREMENTAL-PROTOCOL-1 / Task 4`（本任务是其前置依赖；Task 4 门禁失败根因见下）
- 关联根因证据：
  - 5 万行 EXPLAIN 显示 `Seq Scan on douyin_webhook_events`，`Rows Removed by Filter = 49501 > 5000`
  - 现有索引无一以 `(merchant_id, to_user_id, id)` 或 `(merchant_id, from_user_id, id)` 开头
- Execution-Base：`ebe6ab2329166bc4aca924e7bec1f54488f43a32`（计划一 Task 3 提交；待审批后更新）
- 风险等级：**HIGH**（Database Migration；CLAUDE.md High Risk Areas）

## 1. 现状事实（基于代码与迁移核实）

### 1.1 双轨迁移体系（关键，须在审批中确认策略）
项目存在两套迁移，版本号不同步：
- `migrations/versions/*.sql`（0001–0036）：SQLite/通用 SQL 轨，head=`0036_ai_auto_reply_outbox.sql`
- `migrations/postgres/auto_wechat/versions/*.py`（0001–0016，alembic）：PostgreSQL 生产轨，head=`0016_ai_auto_reply_outbox`

`douyin_webhook_events` 现有索引来源：
- 模型 `DouyinWebhookEvent`（`app/models.py:339`）`__table_args__` 为空；列级 `index=True`：`conversation_short_id`、`server_message_id`、`event_key`、`merchant_id`、`tenant_id`
- 迁移 `0003_create_leads_tasks_core_tables.py`：`idx_..._merchant_created(merchant_id, created_at)`、`idx_..._event_created(event, created_at)`、`idx_..._open_id_created(from_user_id, to_user_id, created_at)`、`idx_..._message_ids(conversation_short_id, server_message_id)`、`uk_..._event_key(event_key)`
- 迁移 `0035_douyin_webhook_event_merchant_scope.sql`：`idx_..._merchant(merchant_id)`、`idx_..._tenant(tenant_id)` 单列索引

**结论**：无任何索引以 `(merchant_id, to_user_id/from_user_id, id)` 开头，无法支撑三元组范围扫描。

### 1.2 失败查询（来自 Task 4 门禁）
```sql
SELECT id, event, from_user_id, to_user_id, conversation_short_id, server_message_id,
       message_type, parsed_content_json, lead_id, raw_body, created_at
FROM douyin_webhook_events
WHERE event IN ('im_receive_msg','im_send_msg')
  AND is_duplicate IS false
  AND merchant_id = :merchant
  AND (to_user_id IN (:account) OR from_user_id IN (:account))
  AND id > :cursor
ORDER BY id ASC
LIMIT 101
```
计划顶层 `Limit → Sort`，底层 `Seq Scan`，过滤移除 49501 行。

## 2. 风险分析（高风险区，须逐项评估并审批）

| # | 风险 | 评估 | 待审批决策 |
|---|---|---|---|
| R1 | 写入开销：webhook 高频入库路径每次 INSERT 须维护新索引，3 个复合索引叠加可能拖慢 webhook 写入 | 中等。webhook 是高频写入表，复合索引越多写入越慢 | 是否 3 个全加，还是只加最高频 2 个？候选索引见 §3 |
| R2 | 双轨策略：sql 轨与 alembic 轨是否都加？SQLite 过渡库是否同样会全表扫？ | SQLite 无 EXPLAIN 门禁历史，但游标查询若在 SQLite 也会全扫；项目约束"不扩散 SQLite 不一致" | **待确认**：两轨都加（0037.sql + 0017.py），还是只加 PG 轨并记录 SQLite 差异 |
| R3 | `OR (to_user_id OR from_user_id)`：单个 `(merchant_id, to_user_id, id)` 索引能否覆盖 OR 两支？ | PostgreSQL 对 OR 可能各走一支索引再 Bitmap OR 合并；若优化器未选则仍可能全表 | 是否需要 `(merchant_id, to_user_id, id)` 与 `(merchant_id, from_user_id, id)` 两个索引成对，验证 EXPLAIN 实际选哪个 |
| R4 | NULL 商户行：`merchant_id IS NULL` 的历史事件，B-tree 索引默认包含 NULL 值，会增加索引体积但查询用 `merchant_id = ?` 等值不会命中 NULL | 低。等值过滤天然排除 NULL | 确认无需 `WHERE merchant_id IS NOT NULL` 部分索引 |
| R5 | 生产迁移锁：`CREATE INDEX` 默认 `ACCESS EXCLUSIVE` 锁表，阻塞 webhook 写入 | 高。生产表可能大，锁表影响在线服务 | 是否用 `CREATE INDEX CONCURRENTLY`（不锁表但耗时长、不能在事务内、失败需手动清理） |
| R6 | 列顺序论证：为何 `(merchant_id, to_user_id, id)` 而非 `(to_user_id, merchant_id, id)` | 商户隔离是首要过滤维度（每查询固定一个 merchant_id），放首列选择性最高 | 确认列顺序 |
| R7 | 既有索引冗余：新 `(merchant_id, to_user_id, id)` 是否使旧 `idx_..._open_id_created(from_user_id, to_user_id, created_at)` 或单列 `merchant_id` 冗余？ | 部分冗余可能，但旧索引服务于其他查询路径，不能仅凭本任务删除 | 本任务只加不删；冗余清理另案 |

## 3. 候选索引（计划一 Task 4 Step 4 登记）

| 索引名（拟定） | 列 | 支撑查询 |
|---|---|---|
| `idx_douyin_webhook_events_merchant_to_id` | `(merchant_id, to_user_id, id)` | merchant_id + to_user_id + id > cursor 范围扫描 |
| `idx_douyin_webhook_events_merchant_from_id` | `(merchant_id, from_user_id, id)` | merchant_id + from_user_id + id > cursor 范围扫描 |
| `idx_douyin_webhook_events_merchant_conv_id` | `(merchant_id, conversation_short_id, id)` | 会话级游标查询（conversation_key 路径） |

## 4. 审批决策（用户已确认）

1. **双轨策略**（R2）：✅ 双轨同步加 —— alembic 轨 `0017.py`（PG 生产）+ sql 轨 `0037.sql`（SQLite/通用过渡）。
2. **索引数量**（R1）：✅ 先加 2 个 —— `(merchant_id, to_user_id, id)` + `(merchant_id, from_user_id, id)`；会话级 `(merchant_id, conversation_short_id, id)` 暂不加，视 EXPLAIN 实际需要再另案补。
3. **CONCURRENTLY**（R5）：✅ 生产迁移用 `CREATE INDEX CONCURRENTLY`（不锁表、不阻塞 webhook 写入）。
   - **技术矛盾与处理（关键）**：`migrations/postgres/auto_wechat/env.py` 的 `_run_migrations_with_connection` 用 `context.begin_transaction()` 事务内执行迁移，而 `CREATE INDEX CONCURRENTLY` 不能在事务内运行，二者直接冲突。
   - 处理方案：alembic 0017 迁移**不直接用 `op.create_index(postgresql_concurrently=True)`**（会在 env.py 事务内失败），改用 **`op.execute("CREATE INDEX CONCURRENTLY ...")` 配合 `with op.get_context().autocommit_block():`** 跳出事务块执行 CONCURRENTLY；这是 alembic 官方推荐的 CONCURRENTLY 写法。若 `autocommit_block` 在当前 env.py 下不可用，则退回普通 `op.create_index`（非并发，仅在本地测试库验证，生产迁移另写独立并发脚本）。
   - 本地测试库 `auto_wechat_outbox_test` 表小，可用非并发索引创建，不影响门禁验证；CONCURRENTLY 的价值在生产，生产迁移另案审批。
4. **列顺序**（R6）：✅ `(merchant_id, 账号列, id)` —— merchant_id 首列选择性最高，id 末列支撑范围扫描与排序。
5. **NULL 行**（R4）：✅ 不加 `WHERE merchant_id IS NOT NULL` 部分索引条件 —— 等值过滤天然排除 NULL，避免部分索引维护复杂度。

## 5. 允许范围

- `migrations/postgres/auto_wechat/versions/0017_douyin_webhook_events_merchant_account_index.py`（Create）
- `migrations/versions/0037_douyin_webhook_events_merchant_account_index.sql`（Create，双轨）
- `app/models.py`（`DouyinWebhookEvent.__table_args__` 增 2 个 `Index` 声明，与迁移一致）
- `tests/test_9000_postgres_douyin_conversation_incremental.py`（Task 4 冻结门禁测试，0017 通过后解冻跑绿灯）

## 6. 验收标准（闭合 Task 4 门禁）

- A12：5 万行下构造器查询返回有界页（LIMIT 101）
- 门禁 1：EXPLAIN `douyin_webhook_events` 节点无 `Seq Scan`（应为 `Index Scan` / `Index Only Scan` / `Bitmap Index Scan`）
- 门禁 2：`max(Rows Removed by Filter) <= 5000`
- 三轮稳定性：每轮 `0 failed, 0 skipped`，清理残留 0
- alembic head 推进到 `0017`；sql 轨 head 推进到 `0037`
- 模型 `__table_args__` 与迁移索引声明一致

## 7. 禁止事项

- 不改表结构、列、业务查询逻辑（`_build_message_rows_statement` 等 Task 2/3 实现不动）
- 不改 webhook 验签、已读、发送保护、outbox、9100
- 不删除既有索引（冗余清理另案）
- 不加会话级 `(merchant_id, conversation_short_id, id)` 索引（R1 决策）
- 不连生产数据库（仅本地 `auto_wechat_outbox_test` 测试库验证）
- 不跑生产迁移（生产迁移另行审批）
- 不 amend/rebase/squash/merge/cherry-pick

---

## 8. Task 步骤

### Task 0：UNION ALL 查询改写（POC 已验证，用户授权）

**背景：** 0017 索引落地后门禁 1 通过（Index Scan），但门禁 2 失败（Rows Removed by Filter = 49401 > 5000）。根因是 `_build_message_rows_statement` 的 `or_(to_user_id.in_(...), from_user_id.in_(...))` 阻止单一复合索引范围扫描。

**POC 验证结论（已确认）：**
- UNION ALL 两个子查询（各走 `(merchant_id,to_user_id,id)` 与 `(merchant_id,from_user_id,id)` 索引）→ `Rows Removed by Filter = 0`，Merge Append 合并两个有序流，门禁 2 达标。
- 去重陷阱：`to==from` 时 UNION ALL 返回重复行，影响 `has_more` 判断。生产私信 from/to 几乎不重合，重复极罕见。

**最终方案（用户授权）：**
- **改写深度**：只改 `_query_message_row_page` 游标页路径（影响 1 点），不动 `_build_message_rows_statement` 内部、不动其他 3 个调用点（`_query_message_rows`/`_conversation_exists`/`_latest_visible_event_id`）。
- **去重策略**：Python 层按 id 去重。`_query_message_row_page` 本地构造 `union_all(子A(to_user_id), 子B(from_user_id))`，外层加 `id > cursor`/`id < before` + `order_by(id)` + `limit+1`，结果在 Python 层按 `id` 去重后再判 `has_more` 与 `scanned_event_ids`。
- **去重后 has_more 语义**：去重后唯一事件数 > limit 才 `has_more=True`，避免重复行误判。

### Task 1：复述确认与基线保护

- [ ] **Step 1：记录执行前 Git 基线**

Run:

```powershell
git rev-parse HEAD
git status --short
git diff --cached --name-only
git merge-base --is-ancestor ebe6ab2329166bc4aca924e7bec1f54488f43a32 HEAD
```

Expected:

```text
HEAD = ebe6ab2329166bc4aca924e7bec1f54488f43a32
工作区仅 3 份治理计划暂存 + 未跟踪的 Task 4 失败门禁测试文件
祖先检查退出码 0
```

确认 `tests/test_9000_postgres_douyin_conversation_incremental.py` 当前是未跟踪状态（Task 4 硬停止未提交），本任务将把它纳入并改造为绿灯。

### Task 2：创建双轨迁移文件

**Files:**
- Create: `migrations/postgres/auto_wechat/versions/0017_douyin_webhook_events_merchant_account_index.py`
- Create: `migrations/versions/0037_douyin_webhook_events_merchant_account_index.sql`

- [ ] **Step 1：创建 alembic 轨 0017 迁移（PostgreSQL 生产）**

`down_revision = "0016_ai_auto_reply_outbox"`。因 env.py 事务内执行与 CONCURRENTLY 冲突（见 §4 R5 处理方案），用 `autocommit_block` 跳出事务：

```python
"""douyin_webhook_events 商户账号复合索引

Revision ID: 0017
Revises: 0016_ai_auto_reply_outbox
Create Date: 2026-07-28
"""

from alembic import op


revision = "0017"
down_revision = "0016_ai_auto_reply_outbox"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # CONCURRENTLY 不能在事务内执行；autocommit_block 跳出 env.py 的事务块。
    # 若 autocommit_block 在当前 env.py 下不可用，退回普通 create_index（见 §4 R5）。
    with op.get_context().autocommit_block():
        op.execute(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_douyin_webhook_events_merchant_to_id "
            "ON douyin_webhook_events (merchant_id, to_user_id, id)"
        )
        op.execute(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_douyin_webhook_events_merchant_from_id "
            "ON douyin_webhook_events (merchant_id, from_user_id, id)"
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS idx_douyin_webhook_events_merchant_from_id")
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS idx_douyin_webhook_events_merchant_to_id")
```

执行窗口注意：`autocommit_block` 是 alembic 官方 CONCURRENTLY 写法，但需在执行时验证当前 env.py 是否支持。若 `alembic upgrade head` 报事务相关错误，**停下来回传审批窗口**，不得擅自改为普通 `op.create_index` 或改 env.py。

- [ ] **Step 2：创建 sql 轨 0037 迁移（SQLite/通用过渡）**

参考既有 `migrations/versions/0035_*.sql` 风格，含 head guard：

```sql
-- 0037 douyin_webhook_events 商户账号复合索引（to_user_id / from_user_id）
-- 范围：支撑会话增量协议游标查询 merchant_id + (to_user_id|from_user_id) + id > cursor 范围扫描。
-- 与 alembic 0017 同步落地，避免 SQLite 过渡库与 PostgreSQL 生产库索引不一致。

CREATE INDEX IF NOT EXISTS idx_douyin_webhook_events_merchant_to_id
    ON douyin_webhook_events(merchant_id, to_user_id, id);
CREATE INDEX IF NOT EXISTS idx_douyin_webhook_events_merchant_from_id
    ON douyin_webhook_events(merchant_id, from_user_id, id);
```

注意：SQLite 不支持 `CONCURRENTLY`，sql 轨不加该关键字。

### Task 3：模型声明同步

**Files:**
- Modify: `app/models.py`

- [ ] **Step 1：在 `DouyinWebhookEvent.__table_args__` 增 2 个 Index 声明**

```python
class DouyinWebhookEvent(Base):
    __tablename__ = "douyin_webhook_events"
    __table_args__ = (
        Index("idx_douyin_webhook_events_merchant_to_id", "merchant_id", "to_user_id", "id"),
        Index("idx_douyin_webhook_events_merchant_from_id", "merchant_id", "from_user_id", "id"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    # ... 其余列不变
```

注意：模型 `__table_args__` 当前为空（无既有复合索引），新增后不得删除列级 `index=True` 声明。`Index` 需在 `app/models.py` 顶部导入（确认 `from sqlalchemy import Index`，若已导入则复用）。

### Task 4：EXPLAIN 门禁复验（解冻 Task 4）

**Files:**
- Modify: `tests/test_9000_postgres_douyin_conversation_incremental.py`

- [ ] **Step 1：将 alembic head 期望从 0016 推进到 0017**

把 `_pg_url`/`pg_engine` fixture 中 Alembic 版本校验改为 `0017`，并确保测试库已应用 0017 迁移。

- [ ] **Step 2：应用 0017 迁移到本地测试库 `auto_wechat_outbox_test`**

Run（在执行窗口会话，含 SMOKE_DATABASE_URL）:

```powershell
alembic upgrade head
```

Expected: head 推进到 `0017`，2 个索引创建成功。

- [ ] **Step 3：重跑 EXPLAIN 门禁，验证无 Seq Scan + Rows Removed <= 5000**

Run:

```powershell
pytest tests/test_9000_postgres_douyin_conversation_incremental.py -q -rs
```

Expected: `0 failed, 0 skipped`；计划节点为 `Index Scan`/`Index Only Scan`/`Bitmap Index Scan`，无 `Seq Scan`；`Rows Removed by Filter <= 5000`；清理后残留 0。

- [ ] **Step 4：三轮稳定性**

Run three times:

```powershell
pytest tests/test_9000_postgres_douyin_conversation_incremental.py -q -rs
```

Expected: 每轮 `0 failed, 0 skipped`，清理残留 0。任一轮失败即停止。

### Task 5：完整回归与候选冻结

- [ ] **Step 1：编译触及文件**

```powershell
python -m py_compile migrations/postgres/auto_wechat/versions/0017_douyin_webhook_events_merchant_account_index.py app/models.py tests/test_9000_postgres_douyin_conversation_incremental.py
```

- [ ] **Step 2：相邻只读回归（确认模型/迁移改动未破坏既有测试）**

```powershell
pytest tests/test_douyin_workbench_conversations.py tests/test_douyin_accounts_router.py tests/test_douyin_workbench_tenant_isolation_r2.py -q
```

Expected: `0 failed`。这些测试不应受索引新增影响。

- [ ] **Step 3：检查差异范围、线性、空白**

```powershell
git diff --check ebe6ab2329166bc4aca924e7bec1f54488f43a32..HEAD
git diff --name-status ebe6ab2329166bc4aca924e7bec1f54488f43a32..HEAD
git rev-list --parents --reverse ebe6ab2329166bc4aca924e7bec1f54488f43a32..HEAD
git status --short
```

Expected: 差异仅 4 个允许文件（0017.py、0037.sql、models.py、门禁测试）；单父线性；`diff --check` 干净；工作区仅 3 份治理计划暂存。

- [ ] **Step 4：文档影响检查**

0017 迁移使以下文档结论过期（业务候选阶段不改活动文档，待候选推送后另开闭环）：
- `docs/ai/05_PROJECT_CONTEXT.md`：迁移 head 状态、douyin_webhook_events 索引清单
- `docs/ai/05_acceptance/12_TEST_PLAN_AUTO_WECHAT.md`：Task 4 门禁从失败到通过
- 外部 TODO：增量协议 Task 4 闭合

- [ ] **Step 5：单父线性提交**

```powershell
git add migrations/postgres/auto_wechat/versions/0017_douyin_webhook_events_merchant_account_index.py migrations/versions/0037_douyin_webhook_events_merchant_account_index.sql app/models.py tests/test_9000_postgres_douyin_conversation_incremental.py
git commit --only migrations/postgres/auto_wechat/versions/0017_douyin_webhook_events_merchant_account_index.py migrations/versions/0037_douyin_webhook_events_merchant_account_index.sql app/models.py tests/test_9000_postgres_douyin_conversation_incremental.py -m "迁移：抖音webhook事件商户账号复合索引"
```

### Task 6：回传审批窗口

回传必须包含：

```text
CANDIDATE_READY
Task-ID / Plan-Revision
Execution-Base / Candidate-Commit / 单父提交链
4 个允许文件 name-status
EXPLAIN 三轮：节点类型 / Rows Removed by Filter / 清理残留
alembic head=0017 / sql head=0037 证据
相邻回归结果
无生产连接、无真实发送、生产迁移未执行（仅本地测试库）
未推送、未部署
```

候选冻结后 0017 闭合，回头解冻并正式完成计划一 Task 4。
