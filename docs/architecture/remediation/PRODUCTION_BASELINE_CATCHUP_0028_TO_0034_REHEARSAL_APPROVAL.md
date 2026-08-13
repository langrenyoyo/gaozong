# PRODUCTION-BASELINE-CATCHUP-0028-TO-0034 — Independent Rehearsal Approval

> 窗口：`PRODUCTION-BASELINE-CATCHUP-0028-TO-0034-INDEPENDENT-REHEARSAL-APPROVAL`
> 窗口性质：**INDEPENDENT READ / VERIFY ONLY** — 不执行 rehearsal、不执行生产迁移/部署、不构建镜像、不 commit、不 push、不改代码/迁移/compose/Dockerfile/env/wrapper。
> 审批对象：`docs/architecture/remediation/PRODUCTION_BASELINE_CATCHUP_0028_TO_0034_ISOLATED_REHEARSAL.md`
> 相关材料：`PRODUCTION_BASELINE_CATCHUP_0028_TO_0034_DESIGN.md` / `_DESIGN_APPROVAL.md` / `S10_B_*_IMPLEMENTATION.md` / `S10_B_*_APPROVAL.md` / `S10_B_*_CORRECTION_APPROVAL.md`
> 日期：2026-08-12
> 证据层级：`GIT_HISTORY_VERIFIED` / `MIGRATION_VERIFIED` / `CODE_VERIFIED` / `CONTAINER_CONFIG_VERIFIED` / `ISOLATED_RUNTIME_EVIDENCE_ACCEPTED`。本窗口未重新执行 rehearsal（任务书 §4 禁止），runtime 证据承自 Rehearsal 窗口实测并经静态交叉核实。

---

## 1. Approval Scope

独立审查 Isolated Rehearsal 报告（BR-01~BR-30 + U1/U2/U3 + A/B/C 矩阵 + backup/restore + 9100 冻结 + 9000 rollback + failure injection + host pollution），判断该 rehearsal 是否足以打开 **Production Authorization Entry**。

本窗口不授权生产迁移、不授权生产部署、不审批 0035、不审批 P3a、不审批 RB-10。只裁定：Rehearsal 是否 correct、Hard gates 是否 runtime-addressed、是否可进入 Production Authorization 阶段。

## 2. Governance Baseline

承自 Design Approval（`APPROVED_WITH_CORRECTIONS`，C1~C5 CLOSED），本窗口不重开：

```text
PREFERRED_STRATEGY                 = SCHEMA_FIRST_WITH_MAINTENANCE_WINDOW（冻结，本窗口只验证不重新设计）
CURRENT_PRODUCTION_9000_CODE       = f453f44e6a70de3eb5fa8f808cf4b6a9d72ea6c1
TARGET_0034_CODE_COMMIT            = 9db3f5854095e483a55724e66d452792b354ff53
PRODUCTION_9100_DB                 = 0003
0035                               = OUT OF CURRENT CATCH-UP
9100 0003→0005                     = OUT OF CURRENT CATCH-UP
S10-B C3                           = CLOSED
S10_SHARED_IMAGE_COUPLING          = MITIGATION_IMPLEMENTED_AND_APPROVED
ISOLATED_REHEARSAL_ENTRY           = AUTHORIZED
PRODUCTION_MIGRATION_AUTHORIZED    = NO
```

## 3. Rehearsal Candidate Verdict

Rehearsal 窗口自述：

```text
ISOLATED_REHEARSAL = PASSED_WITH_NON_BLOCKING_FINDINGS
BR-01~BR-30        = ALL PASS（BR-01 = PASS_WITH_FINDING）
R-S1~R-S13         = NOT TRIGGERED
PRODUCTION_MIGRATION_AUTHORIZED = NO
```

本窗口**不采信**上述自述作为最终结论，独立核实证据后裁定（见 §55~§58）。

## 4. Evidence Sources

本窗口独立执行（只读 / 静态交叉核实）：

```text
git cat-file / git rev-parse / git ls-tree / git show / git grep （f453f44 / 9db3f58 / 36fe68a / eb9f182 树）
migrations/postgres/auto_wechat/versions/ 逐文件 revision/down_revision 头 + schema 对象
0026 / 0008 / 0025 / 0029 / 0030 / 0032 / 0033 / 0034 迁移全文交叉核实
scripts/release_9000_s10b.py wrapper canonical 命令 + compose_env sanitization + preflight
docker-compose.yml restart/healthcheck/image 字段（9db3f58 树）
app/db_readiness.py + app/routers/health.py readiness 契约（承自 Design Approval §14）
P1 artifact 代码身份（record_usage / _create_preview_execution / FC-F1 / 三模型）
rehearsal harness 边界 e:/work/tmp/rehearsal-b7/（worktree detached checkout + evidence_notes）
Rehearsal 报告 §1~§62 逐节
```

runtime 证据（容器 /ready / docker inspect / pg_restore）承自 Rehearsal 窗口实测；本窗口对可静态交叉核实的部分（迁移语义、代码身份、wrapper、compose、revision 链、finding 机制）独立验证一致，对纯 runtime 观测值（container ID / image ID / 计数）接受 Rehearsal 证据并检查内部自洽性。

## 5. Source Identity Review（第一 Hard Gate）

独立核实（`GIT_HISTORY_VERIFIED`）：

```text
OLD_SOURCE    = f453f44e6a70de3eb5fa8f808cf4b6a9d72ea6c1   → git cat-file -t = commit ✅
TARGET_SOURCE = 9db3f5854095e483a55724e66d452792b354ff53   → git cat-file -t = commit ✅
当前 repo HEAD = 36fe68a（≠ 9db3f58，≠ f453f44）
```

- Rehearsal target worktree = `e:/work/tmp/rehearsal-b7/target-9db3f58`（`git worktree add --detach 9db3f58`），HEAD 严格 = 9db3f58（报告 §8 + evidence_notes §源身份一致）。
- target 镜像 `auto-wechat-rehearsal:target-9db3f58` 由该 worktree 经 `docker build -f Dockerfile.backend.dev` 构建（报告 §9）。
- → **target9000 runtime artifact ← source 9db3f58**，而非当前 repo HEAD 或 36fe68a。`VERIFIED`。

Rehearsal 如实声明 rehearsal 镜像为 isolated production-equivalent fixture，**不声称**等于生产 `sha256:93094f0...`（provenance debt，§27/§46 NON_BLOCKING）。未过度宣称。

## 6. Migration Artifact Review

独立核实（`MIGRATION_VERIFIED` + `GIT_HISTORY_VERIFIED`）：

```text
9db3f58 树 postgres alembic versions（migrations/postgres/auto_wechat/versions/）：
  最高 = 0034_preview_executions.py
  无 0035（ls-tree 9db3f58 -- migrations/postgres/auto_wechat/versions/ 确认）
TARGET ALEMBIC HEAD = 0034 ✅
0035 NOT PRESENT in alembic path ✅
```

补充事实：`migrations/versions/0035_douyin_webhook_event_merchant_scope.sql` 存在于 **legacy SQL 目录**（非 alembic PG 路径），不参与 `alembic upgrade`。Rehearsal §25 措辞"ls-tree 无 0035"略不精确（legacy SQL 目录实有 0035.sql），但其语义目标（alembic head=0034、0035 revision 未应用）正确。报告 BR-14 用 `to_regclass('public.wechat_tasks')=NULL` 作为 0035 对象未应用的 runtime 探针，与 9db3f58 树无 alembic 0035 一致。`VERIFIED`。

Rehearsal 使用 head=0034 制品（9db3f58）`upgrade 0028` 停在合法中间 revision（非 head=0035 制品再手动指定 0034），**无 operator contamination**（任务书 §6）。revision 链 0001→…→0028 在 target 树完整存在（down_revision 逐项核实），`upgrade 0028` 良定义。

## 7. Revision Chain Review

独立逐文件核实 down_revision（9db3f58 树，`MIGRATION_VERIFIED`）：

```text
0028 down=0027
0029 down=0028
0030 down=0029
0032 down=0030   （0031 不存在，刻意跳号）
0033 down=0032
0034 down=0033
```

单线性、无分叉、单 head=0034。Catch-up 目标链 = `0028→0029→0030→0032→0033→0034`（5 个迁移）。Rehearsal 逐 revision 执行（BR-04/06/08/10/12 各自 `upgrade <rev>`，非一次性 `upgrade 0034`），证据 level = `ISOLATED_POSTGRESQL_RUNTIME_VERIFIED`。`VERIFIED`。

## 8. BR-01 Review

Rehearsal：`PASS_WITH_FINDING`（U1）。

独立判断（任务书 §8）：

- pre-0029 标准类型证据 = `MIGRATION_VERIFIED`：f453f44 树 0026 `confirmed/inferred = sa.Text()`；9db3f58 树 0026 = `JSONB(none_as_null=True)`（本窗口 git show 交叉核实，见 §10 U2）。
- BR-01 fixture 改用 **target 制品**（9db3f58）空库 `upgrade 0028` 构造 drifted 0028 态，而非 old 树。
- 该构造路径**是否偏离批准设计**？Design Approval §35 硬门禁 = `DRIFTED_0028_PRODUCTION_FIXTURE`（alembic_version=0028 + 两列 jsonb + 1/1698/0 rows）。Rehearsal 用 target 树 `upgrade 0028` 达到的**终态正是该门禁**（revision=0028 + 物理 jsonb + 58 表）。old 树因 U1 无法空库 bootstrap 到 0028，target 树是唯一可构造该终态的路径。门禁要求的是**终态**，未强制"必须由 old 树构建"。→ fixture 路径与批准设计**一致**，非偏离。
- target 树 head=0034，`upgrade 0028` 停在合法中间 revision（§6 已证无 contamination）。

→ **BR-01 = APPROVED_PASS_WITH_FINDING**。U1 为 non-blocking（§9~§11）。不可因后续 migration PASS 就自动当 PASS——本窗口独立确认 pre-0029 类型证据 + 终态满足硬门禁 + 无 contamination，故 PASS 成立。

## 9. U1 Review（最高优先级 Unexpected Finding）

Rehearsal U1：old f453f44 树 0008 含 `ai_edit_job_artifacts.file_size_bytes` 前向声明（PREDECLARED_FUTURE_SCHEMA），空库全量跑链在 0025 触发 DuplicateColumn；target 树已由 DB-BL-2C-R2 移除。

独立验证（`MIGRATION_VERIFIED`）：

- f453f44 树 `0008_xiaogao_phase1_core.py:340`：`sa.Column("file_size_bytes", sa.BigInteger(), nullable=True)`（在 ai_edit_job_artifacts 建表时预声明）✅
- 9db3f58 树 `0008:340`：`# file_size_bytes 不在此预声明：该列由 0025_ai_edit_result_delivery 正典引入`（已移除，保留注释）✅
- 0025 `ai_edit_result_delivery.py:59`：`op.add_column("ai_edit_job_artifacts", sa.Column("file_size_bytes", ...))`（正典引入）✅
- 机制成立：old 树空库链 0008 建表已含 file_size_bytes → 0025 add_column 同列 → DuplicateColumn → 事务回滚停 0024 ✅

### U1 四问（任务书 §10）

```text
U1-Q1 问题是否只在 old f453f44 + fresh empty DB + full historical bootstrap？
       YES —— 仅当 0008 预声明 AND 0025 add_column 同时发生；target 树 0008 已移除，fresh bootstrap 正常。

U1-Q2 未来生产 catch-up 是否不需要 f453f44 migration artifact / fresh DB bootstrap？
       YES —— 生产起点 = 已有 DB revision 0028，catch-up 跑 0029→0034（target 树）。fresh DB bootstrap 非生产 catch-up 路径。

U1-Q3 真实生产起点（existing DB revision 0028）是否完全绕过 0025 问题？
       YES —— 0025 已在历史 SQLite→PG cutover 演进中应用；catch-up 从 0028 起，不重跑 0025。

U1-Q4 未来 rollback 是否只是 old application image + schema 0034，而非用 old 树重建 DB？
       YES —— rollback = 旧应用镜像 + schema 0034 forward（BR-20/21 已验），非从 f453f44 迁移链重建 DB。
```

四问全成立 → U1 倾向 NON_BLOCKING。

### U1 Blocking 条件（任务书 §11）

核查 production execution / rollback / backup restore 是否任一步需要 f453f44 fresh migration chain：

```text
production execution : 用 9db3f58 制品跑 0029→0034，不需 old 树 fresh chain ✅
rollback             : 旧应用 IMAGE + schema 0034 forward（BR-20/21），不需 old 树迁移链 ✅
backup restore       : pg_dump restore（BR-23），不需从迁移链重建 ✅
```

三者均不需 f453f44 fresh migration chain → **U1 不阻断**。

### U1 分类

```text
U1 = OLD_BASELINE_FRESH_BOOTSTRAP_DEFECT
   = OUT_OF_PRODUCTION_CATCHUP_PATH
   = NON_BLOCKING_PRODUCTION_CAUTION
```

不删除该 finding，保留为历史 migration debt 记录（任务书 §57）。`VERIFIED`。

## 10. U2 Review

Rehearsal U2：target 树 0026 前向 JSONB → target 空库 0028 天然 = 生产 drift 态。

独立验证（`MIGRATION_VERIFIED`，§9 已交叉核实）：

- f453f44 树 0026：`sa.Text()`（TEXT）
- 9db3f58 树 0026：`JSONB(none_as_null=True)`，文件头注释"对齐 ORM _JSONStringJSONB"

属实。target 树 0026 建表即 JSONB → 空库 `upgrade 0028` 时两列物理即 jsonb（无需手工 ALTER），该态天然等价生产真实 drift（0028 + jsonb）。BR-02 drift 构造由迁移制品本身真实承载，语义与生产一致。

```text
U2 = TARGET_BASELINE_JSONB_PREDECLARATION
   = EXPECTED TARGET_BASELINE PROPERTY
   = SUPPORTING_EVIDENCE
   = NON_BLOCKING
```

正式分类为 expected baseline property，不再长期保留为模糊 unexpected risk（任务书 §12/§58）。`VERIFIED`。

## 11. U3 Review

Rehearsal U3：old 树 0025 失败事务回滚（revision 停 0024，无 partial DDL）。

独立验证：U1 机制分析（§9）已证明 0025 DuplicateColumn 是 Alembic 单事务内的失败；PostgreSQL transactional DDL 语义下，事务回滚撤销该 revision 的全部 DDL+DML，revision marker 不前进（停 0024）、无 partial DDL。Rehearsal §13/§45 实测一致（old 树 upgrade 0024 成功、upgrade 0025 失败、revision 停 0024、无 partial DDL）。与 BR-22 独立佐证。

```text
U3 = TRANSACTIONAL_DDL_ROLLBACK_SUPPORTING_EVIDENCE
   = NON_BLOCKING
```

（任务书 §13/§59）。`VERIFIED`。

## 12. Drifted0028 Review（BR-02）

独立确认（`ISOLATED_RUNTIME_EVIDENCE_ACCEPTED` + `MIGRATION_VERIFIED`）：

```text
alembic_version        = 0028
confirmed_fields_json  = jsonb（物理）
inferred_fields_json   = jsonb（物理）
表数                   = 58
```

由 target 树空库 `upgrade 0028` 天然得到（U2），非手工 ALTER 制造、非 standard clean 0028(TEXT) fixture 替代生产真实 drift。符合 Design Approval §35 硬门禁与任务书 §14。`VERIFIED`。

## 13. Synthetic Data Review（BR-03）

独立确认（`ISOLATED_RUNTIME_EVIDENCE_ACCEPTED`）：

```text
customer_profiles    = 2（覆盖 valid JSON object + NULL + JSON array）
compute_transactions  = 1698（3 merchant / 4 type / 6 source / 可空字段 / CHECK 合规）
daily_report_jobs     = 0
```

production-like scale + precondition coverage 合理（任务书 §15 重点非严格 1698，而是 scale + precondition）。无生产 PII，全 synthetic。pre-migration fingerprint 已记录（§16）。`VERIFIED`。

## 14. BR-04/05 — 0029（drifted0028 → 0029）

独立确认（`MIGRATION_VERIFIED` + `ISOLATED_RUNTIME_EVIDENCE_ACCEPTED`）：

迁移语义（git show 0029）：`op.alter_column(type_=JSONB(none_as_null=True), postgresql_using="...::text::jsonb")` ×2，无 `op.execute`/UPDATE/INSERT/backfill，未传 `nullable=`（不发 SET/DROP NOT NULL）。对已-jsonb 列，`ALTER TYPE JSONB USING col::text::jsonb` 逐行 `jsonb::text::jsonb`，合法值转换合法、NULL 保持 NULL → 幂等、不丢行、不丢内容。

Rehearsal runtime：`upgrade 0029` exit 0（0.99s）、revision=0029、jsonb 保持、cp=2/ct=1698、JSON object/array/NULL 全保留。迁移语义与 runtime 声明一致。

```text
0029_EXISTING_JSONB_COMPATIBILITY = ISOLATED_POSTGRESQL_RUNTIME_VERIFIED
```

达到任务书 §17 要求的 evidence level（非仅 MIGRATION_CODE_VERIFIED）。`VERIFIED`。

## 15. BR-06/07 — 0030

独立确认（`MIGRATION_VERIFIED` + `ISOLATED_RUNTIME_EVIDENCE_ACCEPTED`）：

```text
add_column idempotency_key     = sa.String(255), nullable ✅
add_column payload_evidence    = sa.Text(), nullable ✅
create_unique_constraint        = uk_compute_transactions_merchant_idempotency（merchant_id, idempotency_key）✅
存量 1698 行 preserved           = count=1698 ✅
新 nullable 列存量 → NULL        = key_nonnull=0 / payload_nonnull=0 ✅
无 false uniqueness collision   = 存量全 NULL，NULL 不参与唯一约束 ✅
```

以迁移文件 + PostgreSQL introspection 为准，未从旧报告字段名猜测。`VERIFIED`。

## 16. BR-08/09 — 0032

独立确认（`MIGRATION_VERIFIED`）：

```text
create_table daily_report_generations:
  id(PK, autoincrement) / job_id(Integer, NN) / lifecycle_status(String20, NN, server_default 'pending')
  / created_at(DateTime, NN, server_default now())
ForeignKeyConstraint job_id → daily_report_jobs.id ✅
CheckConstraint lifecycle_status IN (pending/running/succeeded/failed) ✅（4 态）
create_index idx_daily_report_generations_job（job_id）✅
add_column daily_report_jobs.current_generation_id（Integer, nullable）✅
存量 daily_report_jobs 行 preserved ✅
```

按实际迁移定义，FK/CHECK/INDEX 状态符合。`VERIFIED`。

## 17. BR-10/11 — 0033

独立确认（`MIGRATION_VERIFIED`）：

```text
create_table ai_edit_material_analysis_executions:
  id(PK) / material_id(String64, NN) / source_sha256(String64, NN)
  / lifecycle_status(String20, NN, server_default 'running')
  / created_at(DateTime, NN, now()) / completed_at(DateTime, null)
CheckConstraint IN (running/completed/failed) ✅（3 态）
create_index idx_ai_edit_material_analysis_executions_material（material_id）✅
无 FK（独立持久实体）✅
```

`VERIFIED`。

## 18. BR-12/13 — 0034

独立确认（`MIGRATION_VERIFIED`）：

```text
create_table ai_preview_executions:
  id(PK) / merchant_id(String128, NN) / agent_id(String128, null)
  / lifecycle_status(String20, NN, server_default 'running')
  / created_at(DateTime, NN, now()) / completed_at(DateTime, null)
CheckConstraint IN (running/completed/failed) ✅（3 态）
create_index idx_ai_preview_executions_merchant（merchant_id）✅
F-1 前置：ai_preview_executions 存在（_create_preview_execution 前置满足）✅
```

只验证 schema/artifact availability，**不重审 F-1 correctness**（任务书 §21）。`VERIFIED`。

## 19. BR-14 — Final Schema Baseline

独立确认（`MIGRATION_VERIFIED` + `GIT_HISTORY_VERIFIED` + `ISOLATED_RUNTIME_EVIDENCE_ACCEPTED`）：

```text
DB ALEMBIC CURRENT     = 0034 ✅
TARGET MIGRATION HEAD  = 0034 ✅（9db3f58 树无 alembic 0035）
0035 objects NOT APPLIED = to_regclass('public.wechat_tasks') = NULL ✅（结构上 9db3f58 树无 0035，不可能应用）
表数                   = 61（58 + daily_report_generations + ai_edit_material_analysis_executions + ai_preview_executions）✅
```

直接证据齐全。`VERIFIED`。

## 20. Data Preservation

独立审计（`ISOLATED_RUNTIME_EVIDENCE_ACCEPTED` + 迁移语义交叉核实）：

```text
迁移前（drifted 0028）：cp=2 / ct=1698 / drj=0，JSONB 内容已指纹（object + NULL + array）
迁移后（0034）：       cp=2 / ct=1698 / drj=0，JSON object/array/NULL 逻辑相等
BR-23 restore：        cp=2 / ct=1698 / drj=0，revision=0034，JSON 内容保留
```

迁移语义侧：0029 仅 alter type（无行变更）、0030 仅 add nullable col + create UK（存量全 NULL 不冲突）、0032/0033/0034 仅 create 新表 + add nullable col（不动存量行）→ 行数/内容保留由迁移语义结构保证，与 runtime 计数一致。可追溯 evidence 齐全（pre/post fingerprint + restore 验证）。`VERIFIED`。

## 21. BR-15 — Old App Runtime（f453f44 + schema0034）

独立确认（`ISOLATED_RUNTIME_EVIDENCE_ACCEPTED` + `CODE_VERIFIED`）：

```text
process starts             = 容器 running，uvicorn 启动 ✅
DB connection works         = /ready backend=postgresql / db_connect=pass ✅
critical_tables initialize = douyin_leads / sales_staff pass ✅
/health                    = HTTP 200 ✅
```

Rehearsal 实测 old f453f44 + DB0034 启动成功 + 业务层全 pass。但**只启动成功 + /health 200 + critical_tables pass 不代表全部业务功能兼容**（任务书 §24/§25）。

采用更准确口径：

```text
OLD_APP_SCHEMA0034 = STARTUP / CORE_RUNTIME_COMPATIBLE
```

Rehearsal 验证了 startup + DB connect + critical_tables 初始化路径，未逐一验证所有 active DB paths。不过载宣称"ALL BUSINESS PATHS COMPATIBLE"。Design Approval §11 已静态确认"旧代码不碰新表新列"（target 代码硬依赖 0030-0034，旧代码零引用），与 runtime startup compat 一致。`VERIFIED`（限定口径）。

## 22. BR-16 — Old Readiness（首次 runtime closure）

独立确认（`ISOLATED_RUNTIME_EVIDENCE_ACCEPTED` + `CONTAINER_CONFIG_VERIFIED`）：

```text
/ready → 503 ✅（HTTP 503）
error_code = ALEMBIC_REVISION_MISMATCH ✅
expected = ["0028"]（f453f44 代码树 head）≠ actual = ["0034"] ✅
APPLICATION_PROCESS_RUNNING = YES（/health 200，进程持续）✅
DOCKER_HEALTH = UNHEALTHY（S10 层 STATE A 9000 连续 healthcheck 失败）✅
CONTAINER_AUTO_RESTART = NO（restart_count 恒 0）✅
```

compose 静态核实（9db3f58 树 docker-compose.yml）：9000/9100 均 `restart: unless-stopped`，healthcheck.test 探测 `/ready`（非 /health），30s/10s/3/20s；仓库无 autoheal/watchtower/ofelia（grep 零命中）。`restart: unless-stopped` 是容器 exit/stop 策略，**不因 unhealthy 自动 restart**（标准 Docker 语义）。

→ 首次真实 runtime evidence（design approval §10/§15 此前为 config-only）：unhealthy + restart_count=0 实测证实。

```text
UNHEALTHY_WITH_UNLESS_STOPPED_DOES_NOT_BY_ITSELF_AUTO_RESTART = ISOLATED_CONTAINER_RUNTIME_VERIFIED
```

**限定当前 Docker/Compose topology**，不泛化所有未来平台（任务书 §27）。生产宝塔/systemd 反代 autoheal 行为 `PRODUCTION_EXTERNAL_AUTOHEAL = UNKNOWN`（Rehearsal §49.5，需生产侧核实，非本 rehearsal 覆盖）。`VERIFIED`。

## 23. Docker Restart Runtime Closure

见 §22。本窗口接受该首次 runtime 证据升级。`UNHEALTHY_WITH_UNLESS_STOPPED_DOES_NOT_BY_ITSELF_AUTO_RESTART = ISOLATED_CONTAINER_RUNTIME_VERIFIED`（当前 topology 限定）。

## 24. Preferred Strategy Confirmation

Rehearsal 未证明 Candidate A 应重新 Preferred。old app 虽能启动但 readiness invalid（/ready 503 + unhealthy），更支持 maintenance isolation。保持：

```text
PREFERRED_STRATEGY = SCHEMA_FIRST_WITH_MAINTENANCE_WINDOW
```

本窗口不重新开启策略设计（任务书 §28）。`VERIFIED`。

## 25. BR-17/18 — Target Runtime Hard Gate

独立确认（`ISOLATED_RUNTIME_EVIDENCE_ACCEPTED` + `GIT_HISTORY_VERIFIED`）：

```text
target source = 9db3f58 ✅
target container = Rehearsal 实测（手动容器 @18802 / image 9a0c3bc9）✅
DB = 0034 ✅
/ready = 200 ✅
expected = ["0034"] = actual = ["0034"] ✅
critical DB checks = backend/db_connect/database_name/critical_tables 全 pass ✅
```

`VERIFIED`。

## 26. BR-17/18 Target Ready 来源

任务书 §30 核实：BR-18 /ready 200 来自手动 target 容器（BR-17/18 standalone runtime test）；BR-29 /ready 200 来自 **BR-25 wrapper 实际部署的 target 容器**（4c20e3b20038）。两者均为 target-9db3f58 镜像（9a0c3bc9），且 BR-29 明确在 BR-25 actual target 容器上验证（§29），非旁路容器偷换。`VERIFIED`。

## 27. BR-19 — P1 Artifact Verification

审批边界（任务书 §31）：只确认 target 0034 baseline 含 P1 部署 artifact，不重审 P1 technical correctness。

独立确认（`CODE_VERIFIED` + `MIGRATION_VERIFIED`，9db3f58 树）：

```text
schema objects:
  0030 idempotency_key/payload_evidence + UK ✅
  0032 daily_report_generations + current_generation_id ✅
  0033 ai_edit_material_analysis_executions ✅
  0034 ai_preview_executions ✅
P1 consumer 代码身份:
  record_usage                              @ apps/compute/services.py:629 ✅
  _create_preview_execution（F-1）           @ app/routers/agents.py:61 ✅
  DailyReportGeneration                     @ app/models.py:1316 ✅
  AiEditMaterialAnalysisExecution           @ app/models.py:1732 ✅
  AiPreviewExecution                        @ app/models.py:1344 ✅
  FC-F1 _write_transaction_balance_only     @ apps/compute/services.py:151 ✅
  FC-F1 .returning(ComputeAccount.balance_tokens) @ apps/compute/services.py:177 ✅
```

未真实扣算力 / 未产生客户收费（isolated synthetic environment）。`VERIFIED`。

## 28. BR-20/21 — Application Rollback

独立确认（`ISOLATED_RUNTIME_EVIDENCE_ACCEPTED`）：

```text
rollback 9000 target→old = 停 target 容器；old 接管 ✅
old9000 process state    = running=true / restart=0 ✅
/ready expected 0028 vs actual 0034 = HTTP 503 ALEMBIC_REVISION_MISMATCH ✅
Docker health            = 不自动 restart（restart_count=0）✅
```

正式分类（任务书 §32）：

```text
APPLICATION_ROLLBACK = MAINTENANCE_FALLBACK_CAPABLE
```

**非** NORMAL_HEALTHY_SERVICE_ROLLBACK（old app /ready 503+unhealthy，须进维护态或尽快重新部署 target）。`VERIFIED`。

## 29. Rollback Hard Gate（wrapper 完成）

独立确认（`CODE_VERIFIED`）：rollback 经批准的 `scripts/release_9000_s10b.py` service-specific 机制完成（STATE C env：9000=old-f453f44，wrapper `--apply`），非 manual docker replacement 偷换概念。

wrapper `canonical_up_command` = `docker compose --env-file <f> -f docker-compose.yml up -d --no-deps --no-build auto-wechat-api`（只 target auto-wechat-api，--no-deps 保护 9100，--no-build 保留 prebuilt image）。`--apply` 执行 canonical up。rollback = 同 wrapper + STATE C env。`VERIFIED`。

## 30. BR-22 — Failure Injection

独立确认（`ISOLATED_RUNTIME_EVIDENCE_ACCEPTED` + `MIGRATION_VERIFIED`）：

方式：`ALTER DATABASE aw_fi_probe SET lock_timeout='2s'` + 会话 A 持 ACCESS EXCLUSIVE 锁 + `alembic upgrade 0030` → `psycopg.errors.LockNotAvailable`（真实失败），未修改迁移源。

```text
failed revision marker  = 0029（回滚，未前进）✅
partial DDL             = idempotency_key/payload_evidence/UK 全部不存在（无 partial DDL）✅
transaction rollback    = Alembic 单事务原子回滚（DDL+DML 无残留）✅
database recoverability = 锁释放后重跑 upgrade 0030 成功（revision=0030，UK 存在）✅
不修改迁移源            = 仅 lock_timeout + 锁竞争 ✅
```

revision marker before/after + partial DDL + transaction state + recovery 证据齐全。

```text
MIGRATION_FAILURE_ATOMIC_ROLLBACK = ISOLATED_POSTGRESQL_RUNTIME_VERIFIED
```

**不过度推广**（任务书 §35）：只证明 tested PostgreSQL transactional DDL failure mode（0030 lock-timeout 路径），不声称 all possible production migration failures always atomic。其他失败路径（如 DDL 语法错）未逐一注入（Rehearsal §49.4 已知限制）。`VERIFIED`。

## 31. BR-23 — Backup/Restore

独立确认（`ISOLATED_RUNTIME_EVIDENCE_ACCEPTED`）：

```text
backup   = aw_backup_20260812_183121.dump（pg_dump -F c，331KB，sha256 6f28aad4...）
backup DB = auto_wechat @0034
restore 目标 = aw_restore_probe（独立 disposable 库）
restore succeeds        = pg_restore exit 0 ✅
revision marker correct = version_num = 0034 ✅
key table counts        = cp=2 / ct=1698 / drj=0 / preview=0 ✅
JSONB content preserved = object + array 完整 ✅
```

非仅"pg_dump succeeded"，含完整 dump→restore→accessible→revision→counts→JSON 链。

**Backup checkpoint state 澄清**（任务书 §37）：backup 在 **0034 阶段**取得（restore 后 revision=0034）。drifted 0028 阶段的 JSONB 内容由 pre-migration fingerprint 记录（§16），非 0028 backup restore。本报告准确注明：backup checkpoint = post-migration 0034，不得误读为"pre-migration 0028 backup restore 后会变 0034"。`VERIFIED`。

## 32. BR-24 — Identity Isolation（S10 层）

独立确认（`ISOLATED_RUNTIME_EVIDENCE_ACCEPTED`，承自 Rehearsal docker inspect 实测）：

STATE A baseline：
```text
9000 | container=384bc538fe9ac080 | image_ref=auto-wechat-rehearsal:old-f453f44    | image_id=22e97a46a1da | started=10:45:20 | restart=0
9100 | container=2e5fdd64d40bca6f | image_ref=auto-wechat-rehearsal:frozen-old-9100 | image_id=22e97a46a1da | started=10:45:20 | restart=0
```

```text
9000 resolved image = A（old-f453f44）
9100 resolved image = B（frozen-old-9100）
A != B ✅（两独立 immutable image ref，per-service 可分别指定）
```

container ID / runtime image ID / start timestamp / restart count 证据齐全。`VERIFIED`。

## 33. BR-25 — Target9000 Only

独立确认（`CODE_VERIFIED` + `ISOLATED_RUNTIME_EVIDENCE_ACCEPTED`）：

§42 Host Pollution（前置）：宿主导出 `AUTO_WECHAT_API_IMAGE=host-wrong-9000`、`XG_DOUYIN_AI_CS_IMAGE=host-wrong-9100`。wrapper `compose_env()` 从子进程环境移除两 IMAGE 变量（代码 §65-79 核实），preflight resolved 值来自 `.env.rehearsal-b7`（rehearsal env / approved identity contract），非 host-wrong。

```text
wrapper --apply（hostile env 保持）执行 9000-only up：
9000 before | container=384bc538fe9a | image_ref=old-f453f44    | image_id=22e97a46a1da
9000 after  | container=4c20e3b20038 | image_ref=target-9db3f58 | image_id=9a0c3bc97049
→ 9000 发生预期 recreate/change ✅
```

wrapper canonical 命令实际执行 9000 A→target，container ID changed、runtime image changed。`VERIFIED`。

## 34. BR-26 — 9100 Frozen

独立确认（`ISOLATED_RUNTIME_EVIDENCE_ACCEPTED`）：

```text
before | container=2e5fdd64d40bca6f | image_ref=frozen-old-9100 | image_id=22e97a46a1da
after  | container=2e5fdd64d40bca6f | image_ref=frozen-old-9100 | image_id=22e97a46a1da
→ 9100 NOT RECREATED ✅（container ID / image ID / started / restart 全同）
```

非仅看 Compose config，有 runtime container/image/start/restart 证据。`VERIFIED`。

## 35. BR-27 — 9100 DB 0003

独立确认（`ISOLATED_RUNTIME_EVIDENCE_ACCEPTED`）：

```text
before = 0003，after 9000 deploy = 0003，after 9000 rollback = 0003
0004 / 0005 NOT APPLIED（count=0 全程）✅
```

`VERIFIED`。

## 36. BR-28 — No Recreate / No Migration

独立确认（`ISOLATED_RUNTIME_EVIDENCE_ACCEPTED`）：

```text
container ID unchanged    = 2e5fdd64d40b（前后一致）✅
start timestamp unchanged = 2026-08-12T10:45:20（前后一致）✅
restart count unchanged   = 0 ✅
image ID unchanged        = 22e97a46a1da ✅
DB revision unchanged     = 0003 ✅
migration command in logs = 无（wrapper canonical 仅 target auto-wechat-api）✅
```

```text
9100_RECREATE  = NO
9100_MIGRATION = NO
```

证据来自 container ID + started + image ID + restart + DB revision + logs/commands。`VERIFIED`。

## 37. BR-29 — Target9000 Runtime Ready

独立确认（`ISOLATED_RUNTIME_EVIDENCE_ACCEPTED`）：

在 BR-25 actual target 容器（4c20e3b20038，非旁路容器）上验证：

```text
HTTP /ready = 200 ✅
expected = ["0034"] = actual = ["0034"] ✅
critical checks = backend/db_connect/database_name/critical_tables 全 pass ✅
9000 health → healthy（catch-up 完成后 readiness 恢复）✅
actual runtime image = C（target-9db3f58 / 9a0c3bc9）✅
schema = 0034 ✅
```

/ready 200 来自 BR-25 target container + runtime image=C + schema=0034 三者一致。`VERIFIED`。

## 38. BR-30 — Rollback 9000 Without Touching 9100

独立确认（`ISOLATED_RUNTIME_EVIDENCE_ACCEPTED`）：

STATE C（env：9000=old-f453f44、9100=frozen-old-9100），wrapper `--apply`（hostile env 保持，preflight PASS）：

```text
9000 after rollback | container=c5049fce4d63 | image_ref=old-f453f44    | image_id=22e97a46a1da（回到 preserved old identity）✅
9100                | container=2e5fdd64d40b | image_ref=frozen-old-9100 | image_id=22e97a46a1da（完全不变）✅
9100 DB = 0003 ✅
回滚后 9000 /ready = 503 ALEMBIC_REVISION_MISMATCH（expected 0028 vs actual 0034）✅（维护态 fallback）
```

9000 C→A 同时 9100 container/image/start/DB 全不变。`VERIFIED`。

## 39. A/B/C Matrix Independent Review

本窗口**重建**（非复制 Rehearsal 表格，任务书 §46）。采用语义化标注避免字母歧义：

| State | 9000 container | 9000 image_ref (image_id) | 9100 container | 9100 image_ref (image_id) | 9100 DB |
| --- | --- | --- | --- | --- | --- |
| Baseline | 384bc538fe9a | old-f453f44 (22e97a46) | 2e5fdd64d40b | frozen-old-9100 (22e97a46) | 0003 |
| Target | 4c20e3b20038 | target-9db3f58 (9a0c3bc9) | 2e5fdd64d40b | frozen-old-9100 (22e97a46) | 0003 |
| Rollback | c5049fce4d63 | old-f453f44 (22e97a46) | 2e5fdd64d40b | frozen-old-9100 (22e97a46) | 0003 |

独立判断：

```text
Baseline.9100 == Target.9100   ✅（container/image/started 全同）
Target.9100   == Rollback.9100 ✅
Baseline.9000 != Target.9000    ✅（container 384bc538→4c20e3b2，image 22e97a46→9a0c3bc9）
Target.9000   != Rollback.9000  ✅（container 4c20e3b2→c5049fce，image 9a0c3bc9→22e97a46）
Rollback.9000 == Baseline.9000  ✅（image identity 均 = old-f453f44 / 22e97a46a1da；container ID 变化为 recreate 的正常语义）
```

五项条件全满足（任务书 §46）。`VERIFIED`。

> 说明：Rehearsal 报告 §41 用 A=baseline/B=target/C=rollback 标注，任务书 §46 用 A=baseline/C=target/A=rollback 标注。字母约定不同但语义等价；本窗口按语义条件独立重建，不依赖任一方字母。

## 40. Host Pollution Runtime Evidence

独立确认（`CODE_VERIFIED` + `ISOLATED_RUNTIME_EVIDENCE_ACCEPTED`）：

```text
宿主导出：AUTO_WECHAT_API_IMAGE=host-wrong-9000、XG_DOUYIN_AI_CS_IMAGE=host-wrong-9100
wrapper preflight + apply 全程在 hostile host env 下执行
resolved 值始终来自 .env.rehearsal-b7（rehearsal env / approved identity contract）：
  9000 = old-f453f44（STATE A/C）或 target-9db3f58（STATE B）
  9100 = frozen-old-9100（全程）
identity isolation PASS / expected-9000/9100 校验 PASS
```

该证据升级为 **CONTAINER_RUNTIME**（真实容器按 resolved 镜像创建），非 config-only（任务书 §43）。`compose_env()` sanitization 代码已核实（§33）。`VERIFIED`。

## 41. Maintenance Sequence

独立确认（`ISOLATED_RUNTIME_EVIDENCE_ACCEPTED`）：

Rehearsal 真实模拟维护窗口序列：
```text
maintenance begin
  → old9000（STATE A：old + 0034）被隔离/替换（/ready 503 + unhealthy，不承载正常流量）
  → schema 0028-drifted → 0034（阶段 1 逐 revision 迁移）
  → target9000 deploy（BR-25 wrapper，STATE B）
  → /ready 200（BR-29）
  → maintenance end
```

非"old app continued normal serving throughout"。`VERIFIED`。

## 42. Write Traffic Boundary

任务书 §48：migration 期间 9000 write traffic 应 stopped/isolated（针对 compute_transactions/customer_profiles/daily_report_jobs）。

Rehearsal 是 isolated synthetic 环境，无真实业务流量到达 DB；§43 模拟 old9000 隔离（不承载流量）。Rehearsal **未制造生产式并发写流量**对抗迁移（Rehearsal §45 已知限制）。

```text
WRITE_TRAFFIC_ISOLATION = REHEARSAL_PLAN_GAP（synthetic 环境无真实并发写可测）
```

严重程度评估：**NON_BLOCKING**。production 写隔离的真正保障是 design §17/§18 的维护窗口停机（9000 是 customer_profiles/compute_transactions/daily_report_jobs 唯一写入口，9100 写 xg_douyin_ai_cs 库），design approval §16/§17/§18 已 VERIFIED。Rehearsal 在 quiescent DB 上验证迁移正确性，与维护窗口 production 保证一致。production execution 窗口仍须显式落实 write pause + operator presence。`VERIFIED with NON_BLOCKING caution`。

## 43. Migration Timings

独立检查（`ISOLATED_RUNTIME_EVIDENCE_ACCEPTED`）：

```text
0029 : 0.99s
0030 : 0.87s
0032 : 1.21s
0033 : 0.85s
0034 : 0.90s
（target 制品，isolated PG，cp=2/ct=1698/drj=0）
```

不得将 isolated small-scale timing 外推为 production guaranteed runtime（任务书 §49）。

```text
PRODUCTION_LIKE_ISOLATED_RUNTIME_RISK = LOW / OBSERVED
```

`VERIFIED`（仅作 isolated risk 观测，非生产绝对锁风险保证）。

## 44. Stop Conditions

独立核实 R-S1~R-S13（任务书 §50，至少关键项可从 evidence 重建）：

```text
R-S1  target artifact head != 0034      NOT TRIGGERED（§6/§7 head=0034 已验证）✅
R-S2  unexpected 0035 applied           NOT TRIGGERED（§19 9db3f58 树无 alembic 0035，to_regclass NULL）✅
R-S3  0029 fails on JSONB drift         NOT TRIGGERED（§14 0029 幂等成功）✅
R-S4  data corruption/row loss          NOT TRIGGERED（§20 行数/内容全保留）✅
R-S7  target9000+0034 /ready failure    NOT TRIGGERED（§25/§37 /ready 200）✅
R-S9  9100 recreated during 9000 action NOT TRIGGERED（§34/§36 container/started 不变）✅
R-S10 9100 DB changes from 0003         NOT TRIGGERED（§35 恒 0003）✅
R-S11 rollback cannot restore 9000     NOT TRIGGERED（§38 回退 old identity）✅
R-S12 backup restore fails             NOT TRIGGERED（§31 restore 成功）✅
其余 R-S5/R-S6/R-S8/R-S13 = NOT TRIGGERED（Rehearsal §47，与 evidence 一致）
```

关键项可从 evidence 重建，非仅采信自述。`VERIFIED`。

## 45. Harness Integrity

独立确认（任务书 §51/§52）：

- Harness 位于 `e:/work/tmp/rehearsal-b7/`（仓库外），含 SQL fixture / backup / evidence_notes / s10 compose env / app9000.env。
- worktree = `git worktree add --detach f453f44` / `--detach 9db3f58`（纯 git checkout，未修改 business code/migrations/wrapper）。
- 迁移从 git 树运行（revision 链 + schema 对象交叉核实一致）。
- wrapper = 仓库脚本 `scripts/release_9000_s10b.py`（S10-B approved artifact，只读使用，未修改）。
- Harness 只做 fixture generation / orchestration / port injection / synthetic data / evidence capture。
- **未发现** harness 动态 patch migration/app code/health logic/wrapper 才让测试通过。

```text
HARNESS_INTEGRITY = VERIFIED（无被测系统修改）
```

draft evidence_notes 第 82 行"BR-25 apply 待执行"为时间戳早于最终报告的草稿；最终报告 §35 已执行 9000 A→target，非矛盾。`VERIFIED`。

## 46. Cleanup Evidence

Rehearsal §62 清理 disposable 资源（worktree / rehearsal PG / S10 compose / 手动容器 / 网络 / 镜像），保留 evidence（`e:/work/tmp/rehearsal-b7/`）。本窗口确认 evidence dir 完整（evidence_notes / sql / backup / s10 存在），未触碰 xg-ai-postgres / auto-wechat-postgres-dev / 项目正常开发容器。非 correctness hard gate，确认无环境污染。`VERIFIED`。

## 47. BR-01~30 Independent Matrix

逐项独立裁定（任务书 §55，非仅"30/30"）：

```text
BR-01  Clean standard 0028 fixture                    APPROVED_PASS_WITH_FINDING（U1 non-blocking）
BR-02  Drift construction（revision=0028 + jsonb）     APPROVED_PASS
BR-03  Production-like synthetic data（2/1698/0）      APPROVED_PASS
BR-04  drifted0028 → 0029                              APPROVED_PASS
BR-05  JSONB data preservation                         APPROVED_PASS
BR-06  0029 → 0030                                     APPROVED_PASS
BR-07  0030 columns/UK/data preservation               APPROVED_PASS
BR-08  0030 → 0032                                     APPROVED_PASS
BR-09  0032 schema/FK/index                            APPROVED_PASS
BR-10  0032 → 0033                                     APPROVED_PASS
BR-11  0033 schema                                     APPROVED_PASS
BR-12  0033 → 0034                                     APPROVED_PASS
BR-13  0034 schema                                     APPROVED_PASS
BR-14  Final alembic current=0034                      APPROVED_PASS
BR-15  Old f453f44 + 0034 runtime compat               APPROVED_PASS（限定 STARTUP/CORE_RUNTIME_COMPATIBLE 口径）
BR-16  Old app readiness vs 0034（503+unhealthy+no restart） APPROVED_PASS
BR-17  Target 9db3f58 + 0034 startup                  APPROVED_PASS
BR-18  Target /ready expected=actual=0034              APPROVED_PASS
BR-19  P1 production-baseline artifact                 APPROVED_PASS
BR-20  Application rollback target→old                 APPROVED_PASS
BR-21  Old app after rollback（503+no auto-restart）   APPROVED_PASS
BR-22  Failure injection / rollback / recoverability   APPROVED_PASS
BR-23  Backup/restore dry-run                          APPROVED_PASS
BR-24  Deployment identities isolated（9000 A != 9100 B） APPROVED_PASS
BR-25  Target9000 only（9000 A→target）               APPROVED_PASS
BR-26  9100 image identity unchanged                  APPROVED_PASS
BR-27  9100 DB remains 0003                            APPROVED_PASS
BR-28  9100 not recreated / not migrated              APPROVED_PASS
BR-29  Target9000 + 0034 /ready 200                    APPROVED_PASS
BR-30  Rollback 9000 without touching 9100            APPROVED_PASS
```

无 FAIL / NOT_VERIFIED。BR-01 为 APPROVED_PASS_WITH_FINDING。

## 48. Finding Classification

任务书 §56 分类：

```text
U1  = OLD_BASELINE_FRESH_BOOTSTRAP_DEFECT / OUT_OF_PRODUCTION_CATCHUP_PATH
      → NON_BLOCKING_PRODUCTION_CAUTION（生产非空库全量路径，不影响 catch-up；保留为历史 migration debt）
U2  = TARGET_BASELINE_JSONB_PREDECLARATION / EXPECTED
      → SUPPORTING_EVIDENCE（target 0026 前向 jsonb，drift 天然态）
U3  = TRANSACTIONAL_DDL_ROLLBACK_SUPPORTING_EVIDENCE
      → SUPPORTING_EVIDENCE（old 树 0025 失败原子回滚，与 BR-22 一致）

WRITE_TRAFFIC_ISOLATION_GAP
      → NON_BLOCKING_PRODUCTION_CAUTION（synthetic 环境无真实并发写；production 隔离由维护窗口保证）

IMAGE_BUILD_PROVENANCE_DEBT
      → NON_BLOCKING（承自 Design Approval §27，rehearsal 镜像不声称等于生产 93094f0...，前提 runtime image preserved）

PRODUCTION_EXTERNAL_AUTOHEAL_UNKNOWN
      → NON_BLOCKING_PRODUCTION_CAUTION（生产宝塔/systemd 反代 autoheal 未覆盖，需生产侧核实）

SMALL_SCALE_TIMING
      → DOCUMENTATION_ONLY（1698 行 isolated 耗时不可外推生产）

BR-22_SINGLE_FAILURE_PATH
      → DOCUMENTATION_ONLY（只覆盖 0030 lock-timeout，未逐一注入其他失败路径）

BR-15_PARTIAL_RUNTIME_SCOPE
      → DOCUMENTATION_ONLY（old+0034 只验 startup/core runtime，未逐一验所有 active DB paths）
```

## 49. Blocking Findings

**无 BLOCKING_FOR_PRODUCTION_AUTH_ENTRY 项。**

任务书 §63 CHANGES_REQUIRED 触发条件逐项核查：

```text
0029 runtime evidence 不完整         → 否（§14 ISOLATED_POSTGRESQL_RUNTIME_VERIFIED，迁移语义+runtime 一致）
target artifact 不是 9db3f58/head0034 → 否（§5/§6 已验）
0035 污染                            → 否（§19 9db3f58 树无 alembic 0035，未应用）
target /ready 200 来源不可信          → 否（§26/§37 BR-29 在 BR-25 actual target 容器验证）
9100 实际被 recreate                 → 否（§34/§36 container ID/started/image/restart 全不变）
9100 DB 实际变化                     → 否（§35 恒 0003）
rollback 不是 wrapper 完成            → 否（§29 经 release_9000_s10b.py）
backup 没有真实 restore              → 否（§31 完整 dump→restore→revision→counts→JSON）
BR-22 partial DDL 状态不明           → 否（§30 revision=0029 + 无 partial DDL + 可恢复）
U1 实际可能进入生产路径              → 否（§9 四问 + blocking 条件全成立，生产/rollback/restore 均不需 old 树 fresh chain）
harness 修改被测 migration/code      → 否（§45 worktree detached checkout，wrapper 仓库脚本只读）
```

无 CHANGES_REQUIRED 触发。

## 50. Non-Blocking Findings

见 §48。U1/U2/U3 + 4 项 caution/debt 均为 NON_BLOCKING，需 Production Authorization 明确携带（§52 carry-forward）。

## 51. Evidence Levels

本窗口使用/接受（任务书 §54 允许）：

```text
ISOLATED_POSTGRESQL_RUNTIME_VERIFIED  — BR-01~14/19/22/23/27/28（承自 Rehearsal + 迁移语义交叉核实）
ISOLATED_CONTAINER_RUNTIME_VERIFIED   — BR-15/16/17/18/20/21（首次 runtime closure）
COMPOSE_RUNTIME_VERIFIED              — BR-24~30/§40 Host Pollution
GIT_HISTORY_VERIFIED                  — §5 源身份 / §6 制品 / §7 revision 链
MIGRATION_VERIFIED                    — 0026/0008/0025/0029/0030/0032/0033/0034 schema 对象
CODE_VERIFIED                         — §27 P1 artifact / §33 wrapper / §40 compose_env
CONTAINER_CONFIG_VERIFIED             — §22 compose restart/healthcheck
```

未出现禁止层级（`PRODUCTION_RUNTIME_VERIFIED` / `PRODUCTION_MIGRATION_VERIFIED`）。Rehearsal 与本窗口均未过度宣称生产 runtime。

## 52. Production Authorization Entry Gate

任务书 §60：本审批决定是否允许进入 **Production Authorization 阶段**，非直接允许生产执行。

```text
BR-01~30 independently accepted       ✅（§47）
U1 not production-path blocker       ✅（§9）
target 9db3f58 + 0034 runtime verified ✅（§5/§6/§25）
0035 absent                           ✅（§19）
data preserved                        ✅（§20）
9100 frozen                           ✅（§34/§35/§36）
9000 rollback verified                 ✅（§38）
failure stop/recovery verified         ✅（§30）
backup/restore verified                ✅（§31）
no harness cheating                    ✅（§45）
```

全部门禁满足。

## 53. PRODUCTION_AUTH_CARRY_FORWARD_FINDINGS

进入 Production Authorization 阶段必须明确携带（任务书 §62）：

```text
U1  OLD_BASELINE_FRESH_BOOTSTRAP_DEFECT — 生产不得从 f453f44 fresh chain bootstrap（生产起点必须是已有 0028 DB）
U2  TARGET_BASELINE_JSONB_PREDECLARATION — target 0026 前向 jsonb，drift 态已 rehearsal 验证
U3  TRANSACTIONAL_DDL_ROLLBACK_SUPPORTING — 迁移失败原子回滚已 rehearsal 验证（限 tested path）
WRITE_TRAFFIC_ISOLATION_GAP — production 须显式落实维护窗口 write pause + operator presence
IMAGE_BUILD_PROVENANCE_DEBT — production target image 须用独立 immutable identity + 可追踪 metadata（Design §19/§28）
PRODUCTION_EXTERNAL_AUTOHEAL_UNKNOWN — 生产反代/autoheal 行为须生产侧核实
SMALL_SCALE_TIMING — 不得据 isolated 耗时外推生产绝对锁风险
BR-22_SINGLE_FAILURE_PATH — 仅 0030 lock-timeout 路径验证，其他失败路径未注入
BR-15_PARTIAL_RUNTIME_SCOPE — old+0034 runtime compat 仅 startup/core，未逐一验所有业务路径
```

## 54. Verdict

```text
ISOLATED_REHEARSAL = APPROVED_WITH_NON_BLOCKING_FINDINGS
```

依据：
- BR-01~BR-30 全部独立 accepted（BR-01 PASS_WITH_FINDING，U1 non-blocking；无 FAIL/NOT_VERIFIED）。
- 无 hard-stop 触发（R-S1~R-S13 全 NOT TRIGGERED，关键项可从 evidence 重建）。
- target9000（9db3f58）+ 0034 /ready 200；9100 全程冻结（container/started/image/restart/DB=0003 不变）；rollback 经 wrapper 可用；数据保留；backup/restore 可用；failure injection 原子回滚可恢复。
- 无 0035 污染、9100 recreate、9100 DB 变更、数据丢失、rollback 失败、harness cheating。
- U1/U2/U3 确属 non-blocking，但须 Production Authorization 明确 carry-forward（§53）。

不裁定纯 APPROVED：U1/U2/U3 + 4 项 caution/debt 须生产授权阶段明确携带。不裁定 CHANGES_REQUIRED：无 §49 阻断项，所有硬门禁独立核实满足。

## 55. Production Authorization Entry

```text
PRODUCTION_AUTHORIZATION_ENTRY = OPEN
```

本审批**仅打开 Production Authorization 阶段入口**，不等于生产授权，更不等于生产执行（任务书 §60/§68）。下一阶段是独立的 Production Authorization 窗口。

## 56. Production Migration Authorization

```text
PRODUCTION_MIGRATION_AUTHORIZED = NO
```

Rehearsal 通过 ≠ 生产授权。生产迁移/部署仍须独立 Production Authorization 窗口裁定。

## 57. Next Stage

```text
当前: Independent Rehearsal Approval = APPROVED_WITH_NON_BLOCKING_FINDINGS（本窗口）
  ↓
Production Authorization（独立窗口，携带 §53 carry-forward findings）
  重新冻结 Merchant current reality / 生产 source/image identities / rollback image preservation
  / DB backup readiness / production env required keys / S10-B production image variables
  / 9000/9100 exact image identities / maintenance window controls / write pause
  / production command package / operator stop conditions / final GO-NO-GO
  ↓
Production Baseline Catch-up Execution（独立执行窗口）
  preflight → backup → 维护窗口 → schema 0034 → target9000 deploy → PV-01~PV-17 → B7/B8 closure → return P2
```

不得跨级。不得借 catch-up 执行 0035 / P3a / RB-10 / 9100 0003→0005 / P2 cutover。

---

# 58. Git Discipline

```text
本窗口唯一新增 = docs/architecture/remediation/PRODUCTION_BASELINE_CATCHUP_0028_TO_0034_REHEARSAL_APPROVAL.md
DO NOT COMMIT
DO NOT PUSH
```

未修改：rehearsal report / Design candidate / business code / migrations / compose / Dockerfile / wrapper / env / apps / tests。

---

# 59. Production / Merchant Discipline

本窗口未执行任何写操作（无 SSH mutation / docker / git / psql write / backup creation / production migration / production preflight mutation）。缺生产事实只提 READ-ONLY EVIDENCE REQUEST（本窗口生产 runtime 证据承自 Design M3/M4 + Rehearsal 实测，未独立重核生产 docker inspect）。

---

# 60. STOP

审批报告完成。

```text
ISOLATED_REHEARSAL              = APPROVED_WITH_NON_BLOCKING_FINDINGS
PRODUCTION_AUTHORIZATION_ENTRY   = OPEN
PRODUCTION_MIGRATION_AUTHORIZED  = NO
```

立即停止。禁止自行：

```text
run new rehearsal / migrate production / deploy production / build production image
tag production image / restart Merchant / upgrade 9100 / apply 0035 / enter P3a / RB-10 / commit / push
enter Production Authorization / enter Production Execution
```

下一阶段唯一为 PRODUCTION-BASELINE-CATCHUP-0028-TO-0034 PRODUCTION-AUTHORIZATION（独立窗口，携带 §53 findings）。

---

*独立 Rehearsal 审批窗口结束。未执行任何迁移、未改代码/迁移/compose/Dockerfile/env/wrapper、未 commit、未 push、未部署、未构建镜像、未操作 Merchant。仅留下本审批报告文件。*
