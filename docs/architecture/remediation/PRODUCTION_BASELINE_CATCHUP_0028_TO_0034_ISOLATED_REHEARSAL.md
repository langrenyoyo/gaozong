# PRODUCTION-BASELINE-CATCHUP-0028-TO-0034-ISOLATED-REHEARSAL

> 窗口：`PRODUCTION-BASELINE-CATCHUP-0028-TO-0034-ISOLATED-REHEARSAL`
> 执行日期：2026-08-12
> 载体：完全隔离、可销毁的本地 Docker + PostgreSQL 16 环境
> 性质：**REHEARSAL / VERIFICATION ONLY** —— 未操作 Merchant、未做生产迁移/部署、未 commit/push。
> 依据：`PRODUCTION_BASELINE_CATCHUP_0028_TO_0034_DESIGN.md`（APPROVED_WITH_CORRECTIONS + C1~C5 CLOSED）
> 编排机制：`S10_B_9000_9100_IMAGE_IDENTITY_ISOLATION_IMPLEMENTATION.md`（RE-B per-service image env var）+ `scripts/release_9000_s10b.py`（canonical wrapper，只读使用，未修改）
> 证据层级：`ISOLATED_POSTGRESQL_RUNTIME_VERIFIED` / `ISOLATED_CONTAINER_RUNTIME_VERIFIED` / `COMPOSE_RUNTIME_VERIFIED` / `MIGRATION_VERIFIED` / `CODE_VERIFIED`

---

## 1. Rehearsal Scope

本窗口真实执行 `0028→0034` Production Baseline Catch-up 的隔离演练，覆盖 BR-01~BR-30 全矩阵：

```text
PG 迁移层：  drifted-0028 → 0029 → 0030 → 0032 → 0033 → 0034（逐 revision，target 制品）
应用层：    old9000 + 0034 runtime / target9000 + 0034 / rollback
S10 部署层： 9000/9100 镜像身份隔离、9000-only up、9100 冻结、A/B/C 状态矩阵
故障/恢复： failure injection（lock timeout）、backup/restore dry-run
```

**PRODUCTION_MIGRATION_AUTHORIZED = NO**（本窗口不授权任何生产动作）。

---

## 2. Governance Baseline

```text
CATCHUP_DESIGN          = APPROVED_WITH_CORRECTIONS（C1~C5 CLOSED）
SCHEMA_FIRST_WITH_MAINTENANCE_WINDOW = PREFERRED（冻结，本窗口只验证不重新设计）
S10-B 机制（RE-B + release_9000_s10b.py）= 只读使用（未修改）
ISOLATED_REHEARSAL_ENTRY = AUTHORIZED
PRODUCTION_MIGRATION_AUTHORIZED = NO
```

---

## 3. Safety Boundary

严格执行：

```text
未做：SSH production mutation / production build/tag/up/recreate/restart/env/git / DB write / migration
未做：0035 / P2 cutover / new19000 EXE / 9100 0003→0005 / P3a / P3b / RB-10 / push / commit
未做：git clean / destructive reset / checkout destructive
未触碰本地既有容器 xg-ai-postgres / auto-wechat-postgres-dev（仅只读观察）
未修改 app/** / apps/** / migrations/** / docker-compose.yml（仓库内）/ release_9000_s10b.py
```

所有 rehearsal 资源带 `REHEARSAL/S10B/B7` 标识（网络、容器、库、镜像、worktree、目录）。

---

## 4. Host Environment

```text
OS        = Windows 10 Pro 10.0.19045
Docker    = 29.6.1（build 8900f1d）
Compose   = v5.3.0
Python    = 3.14（alembic 1.18.5 / psycopg / sqlalchemy 2.0.51）
本地既有容器 = xg-ai-postgres（Up 27h healthy）、auto-wechat-postgres-dev（Up 2d healthy）—— 未触碰
```

---

## 5. Docker/PostgreSQL Versions

```text
PostgreSQL = postgres:16（rehearsal-b7-pg 主 PG）
             postgres:16-alpine（compose postgres:16-alpine，S10 层）
镜像构建   = Dockerfile.backend.dev（python:3.10-slim base）
```

---

## 6. Source Identities

```text
OLD_SOURCE    = f453f44e6a70de3eb5fa8f808cf4b6a9d72ea6c1
TARGET_SOURCE = 9db3f5854095e483a55724e66d452792b354ff53
```

- OLD 树（f453f44）：9000 迁移 head=0028；9100 迁移 head=0003。
- TARGET 树（9db3f58）：9000 迁移 head=**0034**（含 0029/0030/0032/0033/0034，**不含 0035**）；9100 迁移 head=0005。
- 已独立核实两 commit 存在且 worktree HEAD 严格等于目标。

---

## 7. Old Worktree Identity

```text
path = e:/work/tmp/rehearsal-b7/old-f453f44（git worktree add --detach f453f44）
HEAD = f453f44e6a70de3eb5fa8f808cf4b6a9d72ea6c1  ✅（rev-parse 验证）
```

---

## 8. Target Worktree Identity

```text
path = e:/work/tmp/rehearsal-b7/target-9db3f58（git worktree add --detach 9db3f58）
HEAD = 9db3f5854095e483a55724e66d452792b354ff53  ✅（rev-parse 验证）
```

---

## 9. Image Identities

```text
auto-wechat-rehearsal:old-f453f44      = sha256:22e97a46a1daf873044efcd363ac6c3137cab5a29ce32a03adfdba6e8a33ff86（f453f44 树构建）
auto-wechat-rehearsal:target-9db3f58   = sha256:9a0c3bc97049a5ce1b2ca04430842d8ddf5d883e6cf77e7e4313052b300b92b8（9db3f58 树构建）
auto-wechat-rehearsal:frozen-old-9100  = 对 old 镜像 re-tag（9100 冻结独立 immutable 身份）
```

构建命令：`docker build -f Dockerfile.backend.dev -t <tag> <worktree>`
说明：rehearsal 镜像为 isolated production-equivalent fixture，**不声称**等于生产 `sha256:93094f0...`（provenance 未证实，§19 设计已拆分 identity/provenance）。

---

## 10. Network/Ports

```text
网络： rehearsal-b7-net（PG 迁移层）/ s10_default（S10 部署层，compose project=s10）
PG：   rehearsal-b7-pg @127.0.0.1:15432（postgres/rehearsal_pw）
应用： old9000 @18801、target9000 @18802（BR-15~21 手动容器）
S10：  9000/9100 经 compose 绑定 127.0.0.1:9000/9100（宿主空闲，隔离 project s10）
```

---

## 11. PG9000 Topology

```text
库 auto_wechat @ rehearsal-b7-pg（迁移层主库）
  starting = DRIFTED_0028（物理 jsonb / revision=0028 / 58 表）
  target   = 0034（61 表 = 58 + daily_report_generations + ai_edit_material_analysis_executions + ai_preview_executions）
S10 层 compose PG（s10-postgres-1）：auto_wechat = 0034（target 制品迁移）
```

---

## 12. PG9100 Topology

```text
库 xg_douyin_ai_cs @ rehearsal-b7-pg = 0003（old 制品，BR-27 全程验证）
S10 层 compose PG（s10-postgres-1）：xg_douyin_ai_cs = 0003（old 制品）
0004 / 0005 = NOT APPLIED（全程验证）
```

---

## 13. Standard0028 Fixture（BR-01 相关）

**事实链**：
- `f453f44` 树 `0026_customer_profiles.py` 定义 `confirmed_fields_json/inferred_fields_json` = **TEXT**（pre-0029 标准类型，`MIGRATION_VERIFIED`）。
- `9db3f58` 树 `0026_customer_profiles.py` 前向对齐为 **JSONB**（DB-BL-2C-R2 相关，`MIGRATION_VERIFIED`）。
- **UNEXPECTED FINDING（U1）**：old `f453f44` 树 `0008_xiaogao_phase1_core.py` 含 `ai_edit_job_artifacts.file_size_bytes` 前向声明（`PREDECLARED_FUTURE_SCHEMA`），导致**空库全量跑链在 0025 触发 `DuplicateColumn`**；target 树已由 `DB-BL-2C-R2`（b4ee5aa）移除（保留注释）。实测：old 树 `upgrade 0024` 成功、`upgrade 0025` 失败 `DuplicateColumn`、事务回滚（revision 停 0024、无 partial DDL）。
- **结论**：当前仓库**无任何树能从空库干净跑出「TEXT 物理 + revision=0028」**（old 树 0025 挂；target 树 0026 前向 jsonb）。生产 0028 是历史 SQLite→PG cutover 演进，非空库全量跑。

**BR-01 裁决**：`PASS_WITH_FINDING`
- pre-0029 标准类型证据 = `MIGRATION_VERIFIED`（f453f44 0026 = TEXT；target 0026 = JSONB）。
- 运行时证据 = target 树空库 `upgrade 0028` 成功：revision=0028、58 表；物理两列 jsonb（该态即生产真实 drift，见 §14）。
- U1 记录为 non-blocking finding（不影响生产 catch-up，生产非空库全量跑路径）。

---

## 14. Drift Construction（BR-02）

**裁决**：`PASS`

target 树空库 `upgrade 0028` 直接得到 **revision=0028 + 物理 jsonb（两列）+ 58 表**，该状态**天然等价生产真实 drift**（§5 设计：`SCHEMA_DRIFT_SCOPE = 0029_JSONB_TYPE_AHEAD_ONLY`）。

```text
alembic_version = 0028
confirmed_fields_json = jsonb（物理）
inferred_fields_json  = jsonb（物理）
```

未通过手工 ALTER 制造 drift（因 target 0026 已前向 jsonb），drift 构造由迁移制品本身真实承载，语义与生产一致。

---

## 15. Synthetic Dataset（BR-03）

```text
customer_profiles    = 2 行（synthetic；覆盖 valid JSON object + NULL + JSON array）
compute_transactions = 1698 行（synthetic，确定性生成）
  - 3 merchants（merchant_rh1/rh2/rh3）
  - 4 transaction_type（consume/recharge/refund/manual_adjust）
  - 6 source（auto_reply/training/rag_query/preview/m05_analysis/daily_report）
  - nullable optional fields 覆盖（remark/model/agent_id/conversation_id/actual_tokens/
    capability_key/markup/usage_measurement_method/prompt/completion/cached/llm_call_stage）
  - 全部满足 CHECK 约束（delta<>0 / actual>0 / 非负 tokens / stage 枚举 / method 枚举）
daily_report_jobs     = 0 行
```

不含生产 PII；全部 synthetic。

---

## 16. Pre-Migration Fingerprint

```text
customer_profiles    = 2
compute_transactions = 1698
daily_report_jobs    = 0
JSONB 列：row1 confirmed=valid object + inferred=NULL；row2 confirmed=NULL + inferred=['city','budget']
物理类型：confirmed/inferred 均 jsonb（drifted 0028）
```

迁移至 0034 后：行数全保留（cp=2/ct=1698/drj=0），JSON 内容逻辑相等。

---

## 17. BR-01 — Clean Standard 0028

| 项 | 结果 | 证据 |
| --- | --- | --- |
| alembic current = 0028（target 制品空库） | PASS | `upgrade 0028` 成功，`SELECT version_num` = 0028 |
| 表数 | PASS | 58（与生产预期一致） |
| pre-0029 类型 | PASS（MIGRATION_VERIFIED） | f453f44 0026 = TEXT（标准）；target 0026 = JSONB（前向） |
| U1 old 树 0008 缺陷 | FINDING | old 树 `upgrade 0025` DuplicateColumn → 回滚（详见 §13） |

**Evidence level**：`ISOLATED_POSTGRESQL_RUNTIME_VERIFIED`（target 制品）+ `MIGRATION_VERIFIED`（类型定义）

---

## 18. BR-02 — Drift Construction

| 项 | 结果 | 证据 |
| --- | --- | --- |
| revision marker = 0028 | PASS | `alembic_version` = 0028 |
| physical types = jsonb/jsonb | PASS | `information_schema` data_type = jsonb |
| 不改变 revision marker 制造 drift | PASS | target 树 0026 前向 jsonb，空库 0028 即 drift，无手工 ALTER |

**Evidence level**：`ISOLATED_POSTGRESQL_RUNTIME_VERIFIED`

---

## 19. BR-03 — Synthetic Dataset

| 项 | 结果 |
| --- | --- |
| customer_profiles ≈ 1 | PASS（2 行，覆盖 object/NULL/array） |
| compute_transactions ≈ 1698 | PASS（1698 行，多 merchant/type/source/可空） |
| daily_report_jobs = 0 | PASS |
| 无生产 PII | PASS（synthetic） |

**Evidence level**：`ISOLATED_POSTGRESQL_RUNTIME_VERIFIED`

---

## 20. BR-04/05 — 0029（drifted0028 → 0029）

| 项 | 结果 | 证据 |
| --- | --- | --- |
| command succeeds | PASS | `upgrade 0029` exit 0，耗时 0.99s |
| alembic current = 0029 | PASS | `version_num` = 0029 |
| confirmed/inferred 保持 jsonb | PASS | data_type = jsonb |
| row count unchanged | PASS | cp=2 / ct=1698 |
| JSON content preserved | PASS | row1 object 完整、row2 array 完整 |
| NULL preserved | PASS | row1 inferred=NULL、row2 confirmed=NULL 均保留 |

**0029_EXISTING_JSONB_COMPATIBILITY = ISOLATED_POSTGRESQL_RUNTIME_VERIFIED**

---

## 21. BR-06/07 — 0030

| 项 | 结果 | 证据 |
| --- | --- | --- |
| command succeeds | PASS | 耗时 0.87s |
| idempotency_key | PASS | varchar nullable 新增 |
| payload_evidence | PASS | text nullable 新增 |
| uk_compute_transactions_merchant_idempotency | PASS | `UNIQUE (merchant_id, idempotency_key)` 存在 |
| 存量 1698 行 preserved | PASS | count=1698 |
| 新 nullable 列存量 → NULL | PASS | key_nonnull=0 / payload_nonnull=0 |
| 无 false uniqueness collision | PASS | 存量全 NULL，NULL 不参与唯一约束 |

**Evidence level**：`ISOLATED_POSTGRESQL_RUNTIME_VERIFIED`

---

## 22. BR-08/09 — 0032

| 项 | 结果 | 证据 |
| --- | --- | --- |
| command succeeds | PASS | 耗时 1.21s |
| daily_report_generations | PASS | id(PK)/job_id(NOT NULL)/lifecycle_status(NOT NULL, default 'pending')/created_at(NOT NULL, now()) |
| FK job_id → daily_report_jobs.id | PASS | `daily_report_generations_job_id_fkey` |
| CHECK 4 态 | PASS | `ck_daily_report_generations_status` IN (pending/running/succeeded/failed) |
| INDEX job_id | PASS | `idx_daily_report_generations_job` |
| daily_report_jobs.current_generation_id | PASS | integer nullable |

（以迁移文件 `0032_daily_report_generations.py` 与 PostgreSQL introspection 为准，未从旧报告猜 schema。）

---

## 23. BR-10/11 — 0033

| 项 | 结果 | 证据 |
| --- | --- | --- |
| command succeeds | PASS | 耗时 0.85s |
| ai_edit_material_analysis_executions | PASS | id(PK)/material_id(String64,NN)/source_sha256(String64,NN)/lifecycle_status(NN,'running')/created_at(NN,now())/completed_at(null) |
| CHECK 3 态 | PASS | `ck_ai_edit_material_analysis_executions_status` IN (running/completed/failed) |
| INDEX material_id | PASS | `idx_ai_edit_material_analysis_executions_material` |
| 无 FK | PASS | 独立持久实体 |

---

## 24. BR-12/13 — 0034

| 项 | 结果 | 证据 |
| --- | --- | --- |
| command succeeds | PASS | 耗时 0.90s |
| ai_preview_executions | PASS | id(PK)/merchant_id(String128,NN)/agent_id(String128,null)/lifecycle_status(NN,'running')/created_at(NN,now())/completed_at(null) |
| CHECK 3 态 | PASS | `ck_ai_preview_executions_status` IN (running/completed/failed) |
| INDEX merchant_id | PASS | `idx_ai_preview_executions_merchant` |
| F-1 前置 | PASS | `ai_preview_executions` 存在（`_create_preview_execution` 前置满足） |

（只验证 schema/artifact availability，不重审 F-1 correctness。）

---

## 25. BR-14 — Final Schema Baseline

| 项 | 结果 | 证据 |
| --- | --- | --- |
| DB ALEMBIC CURRENT = 0034 | PASS | `version_num` = 0034 |
| TARGET MIGRATION HEAD = 0034 | PASS | target 树 `ls-tree` 无 0035；alembic heads 复核 = 0034 |
| 0035 objects NOT APPLIED | PASS | `to_regclass('public.wechat_tasks')` = NULL |
| 表数 | PASS | 61（58 + 3 新表） |

**Evidence level**：`ISOLATED_POSTGRESQL_RUNTIME_VERIFIED`

---

## 26. BR-15 — Old App Runtime（f453f44 + schema0034）

容器 `rehearsal-old9000`（image `auto-wechat-rehearsal:old-f453f44`，@18801，连 auto_wechat=0034）：

| 项 | 结果 | 证据 |
| --- | --- | --- |
| process starts | PASS | 容器 running，uvicorn 启动 |
| DB connection works | PASS | /ready backend=postgresql / db_connect=pass |
| critical paths initialize | PASS | critical_tables pass（douyin_leads/sales_staff） |
| /health | PASS | HTTP 200 status=ok |

```text
APPLICATION_RUNTIME_COMPATIBLE = YES（业务层全 pass）
```

**Evidence level**：`ISOLATED_CONTAINER_RUNTIME_VERIFIED`

---

## 27. BR-16 — Old Readiness

| 项 | 结果 | 证据 |
| --- | --- | --- |
| /ready → 503 | PASS | HTTP 503 |
| reason | PASS | error_code=`ALEMBIC_REVISION_MISMATCH` |
| expected vs actual | PASS | expected=["0028"]（f453f44 代码树 head）≠ actual=["0034"] |
| APPLICATION_PROCESS_RUNNING | PASS | /health 200，进程持续运行 |
| DOCKER_HEALTH | PASS | S10 层 compose 实测：STATE A 9000（old+0034）= **unhealthy**（§34 BR-24~30） |
| CONTAINER_AUTO_RESTART | PASS | **restart_count=0**（unhealthy 不自动 restart，标准 restart-policy 环境） |
| container 证据 | — | container=384bc538fe9a...（STATE A compose）/ c92d4234b7c4...（手动容器） |

```text
APPLICATION_RUNTIME_COMPATIBLE  = YES（业务能跑）
READINESS_CONTRACT_INCOMPATIBLE = YES（/ready 503 expected 0028 != actual 0034）
DOCKER_HEALTH                   = UNHEALTHY（连续 healthcheck 失败后）
CONTAINER_AUTO_RESTART          = NO（restart_count 恒 0）
```

**DOCKER_UNHEALTHY_RESTART_LOOP 未发生** —— 以 CONTAINER_RUNTIME 实测证实设计 CORRECTION-1 的语义判断。

**Evidence level**：`ISOLATED_CONTAINER_RUNTIME_VERIFIED` + `COMPOSE_RUNTIME_VERIFIED`

---

## 28. BR-17 — Target Startup（9db3f58 + schema0034）

容器 `rehearsal-target9000`（image `auto-wechat-rehearsal:target-9db3f58`，@18802）：

| 项 | 结果 |
| --- | --- |
| process startup | PASS |
| DB connectivity | PASS |
| critical startup path | PASS |

**Evidence level**：`ISOLATED_CONTAINER_RUNTIME_VERIFIED`

---

## 29. BR-18 — Target Readiness

| 项 | 结果 | 证据 |
| --- | --- | --- |
| HTTP /ready = 200 | PASS | HTTP 200 |
| expected = 0034 | PASS | expected=["0034"] |
| actual = 0034 | PASS | actual=["0034"] |
| critical DB checks | PASS | backend/db_connect/database_name/critical_tables 全 pass |

---

## 30. BR-19 — P1 Artifact Verification

| 项 | 结果 | 证据 |
| --- | --- | --- |
| 0030 schema（idempotency_key/payload_evidence + UK） | PASS | 列 2 个 + UK 1 个存在 |
| 0032 daily_report_generations + current_generation_id | PASS | 表存在 |
| 0033 ai_edit_material_analysis_executions | PASS | 表存在 |
| 0034 ai_preview_executions | PASS | 表存在 |
| P1 consumer 代码 | PASS | record_usage/_create_preview_execution/DailyReportGeneration/AiEditMaterialAnalysisExecution/AiPreviewExecution 命中 app/ apps/ |
| FC-F1 atomic balance update | PASS | `_write_transaction_balance_only` @apps/compute/services.py:151/:734 + `.returning(ComputeAccount.balance_tokens)` @:177 |

**未真实扣算力 / 未产生客户收费**（全部 isolated synthetic environment）。

**Evidence level**：`ISOLATED_POSTGRESQL_RUNTIME_VERIFIED` + `CODE_VERIFIED`

---

## 31. BR-20/21 — Application Rollback（target → old，schema 保持 0034）

| 项 | 结果 | 证据 |
| --- | --- | --- |
| rollback 9000 target→old | PASS | 停 target 容器；old 接管 |
| old9000 process state | PASS | running=true / restart=0 |
| /ready expected 0028 vs actual 0034 | PASS | HTTP 503 ALEMBIC_REVISION_MISMATCH |
| Docker health | PASS | 不自动 restart（restart_count=0） |

```text
APPLICATION_ROLLBACK_WITH_SCHEMA_FORWARD = MAINTENANCE FALLBACK（可作维护态回滚，非 normal healthy service）
```

**Evidence level**：`ISOLATED_CONTAINER_RUNTIME_VERIFIED`

---

## 32. BR-22 — Failure Injection

方式：**数据库运行条件制造可控失败，未修改迁移源**。

```text
库 aw_fi_probe（独立 disposable）
  ALTER DATABASE aw_fi_probe SET lock_timeout = '2s'
  会话 A 后台：BEGIN; LOCK TABLE compute_transactions IN ACCESS EXCLUSIVE MODE; SELECT pg_sleep(25);
  同时执行：alembic upgrade 0030
  → psycopg.errors.LockNotAvailable: canceling statement due to lock timeout（真实失败）
```

| 项 | 结果 | 证据 |
| --- | --- | --- |
| failed revision marker | PASS | 失败后 `version_num` = **0029**（回滚） |
| partial DDL 状态 | PASS | idempotency_key/payload_evidence/UK 全部不存在（无 partial DDL） |
| transaction rollback | PASS | Alembic 单事务原子回滚（DDL+DML 无残留） |
| database recoverability | PASS | 锁释放后重跑 `upgrade 0030` 成功（revision=0030、UK 存在） |
| 不修改迁移源 | PASS | 仅 lock_timeout + 锁竞争 |

**结论**：设计中对 transactional DDL 的判断得到实测确认（失败原子回滚、不留 partial DDL、可恢复）。

**Evidence level**：`ISOLATED_POSTGRESQL_RUNTIME_VERIFIED`

---

## 33. BR-23 — Backup/Restore Dry-Run

```text
backup identity = aw_backup_20260812_183121.dump（pg_dump -F c，331KB）
backup sha256   = 6f28aad4fee661a09dc8f20b98f8076d3e73b5593c1a7a37380497d27ed9b5de
backup db       = auto_wechat（@0034）
restore 目标    = aw_restore_probe（独立 disposable 库）
```

| 项 | 结果 | 证据 |
| --- | --- | --- |
| restore succeeds | PASS | pg_restore exit 0 |
| revision marker correct | PASS | `version_num` = 0034 |
| key table counts | PASS | cp=2 / ct=1698 / drj=0 / preview=0 |
| JSONB content preserved | PASS | object + array 完整 |

（备份在 0034 阶段执行；drifted0028 阶段的 JSONB 内容同样由 pre-migration fingerprint 记录，见 §16。）

**Evidence level**：`ISOLATED_POSTGRESQL_RUNTIME_VERIFIED`

---

## 34. BR-24 — Identity Isolation（S10 层）

隔离 compose 环境（`e:/work/tmp/rehearsal-b7/s10/`，project=s10，网络 s10_default）：
compose postgres `s10-postgres-1`：auto_wechat=0034（target 制品）、xg_douyin_ai_cs=0003（old 制品）。

STATE A baseline：

```text
9000 | container=384bc538fe9ac080... | image_ref=auto-wechat-rehearsal:old-f453f44    | image_id=22e97a46a1da | started=10:45:20 | restart=0
9100 | container=2e5fdd64d40bca6f... | image_ref=auto-wechat-rehearsal:frozen-old-9100 | image_id=22e97a46a1da | started=10:45:20 | restart=0
```

```text
9000 resolved image = A（old-f453f44）
9100 resolved image = B（frozen-old-9100）
A != B ✅（两个独立 immutable image ref，可分别指定）
```

**Evidence level**：`COMPOSE_RUNTIME_VERIFIED`（docker inspect 实测，非 env text）

---

## 35. BR-25 — Target9000 Only（canonical wrapper）

**§38 Host Pollution（前置）**：宿主导出 `AUTO_WECHAT_API_IMAGE=host-wrong-9000`、`XG_DOUYIN_AI_CS_IMAGE=host-wrong-9100`。

wrapper preflight：

```text
resolved 9000 image : auto-wechat-rehearsal:target-9db3f58   （env file 值，非 host-wrong）
resolved 9100 image : auto-wechat-rehearsal:frozen-old-9100
identity isolation PASS
canonical command   : docker compose --env-file .env.rehearsal-b7 -f ... up -d --no-deps --no-build auto-wechat-api
```

→ **runtime 结果来自 rehearsal env / approved identity contract，而非 hostile shell**（wrapper `compose_env()` sanitization 生效；升级为 CONTAINER_RUNTIME 级而非 config-only）。

wrapper `--apply`（hostile env 保持）执行 9000-only up：

```text
9000 before | container=384bc538fe9a... | image_ref=old-f453f44    | image_id=22e97a46a1da
9000 after  | container=4c20e3b20038... | image_ref=target-9db3f58 | image_id=9a0c3bc97049
→ 9000 发生预期 recreate/change ✅
```

**Evidence level**：`COMPOSE_RUNTIME_VERIFIED`

---

## 36. BR-26 — Frozen9100 Image Unchanged

BR-25 前后 9100：

```text
before | container=2e5fdd64d40bca6f... | image_ref=frozen-old-9100 | image_id=22e97a46a1da
after  | container=2e5fdd64d40bca6f... | image_ref=frozen-old-9100 | image_id=22e97a46a1da
→ 9100 NOT RECREATED ✅（container ID 相同）
```

**Evidence level**：`COMPOSE_RUNTIME_VERIFIED`

---

## 37. BR-27 — 9100 DB Remains 0003

BR-25 前后 9100 DB（s10-postgres-1 / xg_douyin_ai_cs）：

```text
before = 0003，after = 0003
0004/0005 NOT APPLIED（count=0，全程）
```

**Evidence level**：`ISOLATED_POSTGRESQL_RUNTIME_VERIFIED`

---

## 38. BR-28 — No9100 Recreate / No Migration

```text
container ID unchanged   = 2e5fdd64d40b...（前后一致）✅
start timestamp unchanged = 2026-08-12T10:45:20（前后一致）✅
restart count unchanged   = 0 ✅
image ID unchanged        = 22e97a46a1da ✅
DB revision unchanged     = 0003 ✅
migration command in logs = 无（wrapper canonical 命令仅 target auto-wechat-api）
```

```text
9100_RECREATE  = NO
9100_MIGRATION = NO
```

**Evidence level**：`COMPOSE_RUNTIME_VERIFIED` + `ISOLATED_POSTGRESQL_RUNTIME_VERIFIED`

---

## 39. BR-29 — Target9000 Runtime Ready

在 BR-25 actual target 容器（4c20e3b20038...）上验证：

```text
HTTP /ready = 200
expected = ["0034"]
actual   = ["0034"]
critical checks = backend/db_connect/database_name/critical_tables 全 pass
9000 health → healthy（catch-up 完成后 readiness 恢复）
```

**Evidence level**：`COMPOSE_RUNTIME_VERIFIED`

---

## 40. BR-30 — 9000 Rollback Without Touching9100

STATE C（env：9000=old-f453f44、9100=frozen-old-9100），wrapper `--apply`（hostile env 保持，preflight PASS）：

```text
9000 after rollback | container=c5049fce4d63... | image_ref=old-f453f44    | image_id=22e97a46a1da（回到 preserved old identity）
9100                | container=2e5fdd64d40b... | image_ref=frozen-old-9100 | image_id=22e97a46a1da（完全不变）
9100 DB = 0003
```

回滚后 9000 `/ready` = 503 ALEMBIC_REVISION_MISMATCH（expected 0028 vs actual 0034）——符合预期（rollback 后进入维护态 fallback）。

**Evidence level**：`COMPOSE_RUNTIME_VERIFIED`

---

## 41. A/B/C Runtime 状态矩阵

| State | 9000 | 9100 |
| --- | --- | --- |
| A baseline | container=384bc538, image=old-f453f44(22e97a46) | container=2e5fdd64, image=frozen-old-9100(22e97a46) |
| B target | container=4c20e3b2, image=target-9db3f58(9a0c3bc9) | container=2e5fdd64, image=frozen-old-9100(22e97a46) |
| C rollback | container=c5049fce, image=old-f453f44(22e97a46) | container=2e5fdd64, image=frozen-old-9100(22e97a46) |

逐项证明（runtime image/container evidence，非 env text）：

```text
A.9100 == B.9100  ✅（container/image/started 全同）
B.9100 == C.9100  ✅
A.9000 != B.9000  ✅（container 384bc538 → 4c20e3b2，image 22e97a46 → 9a0c3bc9）
B.9000 != C.9000  ✅（container 4c20e3b2 → c5049fce，image 9a0c3bc9 → 22e97a46）
C.9000 == A.9000  ✅（image identity 均 = old-f453f44 / 22e97a46a1da；container ID 变化为 recreate 的正常语义）
```

---

## 42. Host Pollution Runtime Evidence（§38）

```text
宿主导出：AUTO_WECHAT_API_IMAGE=host-wrong-9000、XG_DOUYIN_AI_CS_IMAGE=host-wrong-9100
wrapper preflight + apply 全程在 hostile host env 下执行
resolved 值始终来自 .env.rehearsal-b7（rehearsal env / approved identity contract）：
  9000 = old-f453f44（STATE A/C）或 target-9db3f58（STATE B）
  9100 = frozen-old-9100（全程）
identity isolation PASS / expected-9000/9100 校验 PASS
```

→ 该证据升级为 **CONTAINER_RUNTIME**（真实容器按 resolved 镜像创建），而非 config-only。

---

## 43. Maintenance Sequence（§47 Dry-Run）

隔离环境真实模拟维护窗口序列：

```text
maintenance begin
  → old9000（STATE A：old + 0034）被隔离/替换（/ready 503 + unhealthy，不承载正常流量）
  → schema 0028-drifted → 0034（阶段 1 已逐 revision 迁移）
  → target9000 deploy（BR-25 wrapper，STATE B）
  → /ready 200（BR-29）
  → maintenance end
```

记录 stop condition：迁移期间 9000 应用写入 = 停/隔离（无业务流量到达 DB；synthetic 环境模拟 write traffic boundary）。

---

## 44. Migration Timings

```text
0029 : 0.99s
0030 : 0.87s
0032 : 1.21s
0033 : 0.85s
0034 : 0.90s
（target 制品，isolated PG，数据规模 cp=2/ct=1698/drj=0）
```

**证据 = PRODUCTION_LIKE_SCALE_ISOLATED_RUNTIME，非 PRODUCTION_RUNTIME**。当前规模小，不得据此宣称生产绝对无锁风险。

---

## 45. Lock/Transaction Findings

- 全链 migration 单事务（Alembic 默认），无 `op.execute("COMMIT")` 覆盖。
- BR-22 实测：0030 在锁竞争 + lock_timeout 下失败 → **原子回滚**（revision 停 0029、无 partial DDL、可恢复）。
- old 树 0025 失败同样回滚（revision 停 0024）—— 两次独立实测均证明 transactional DDL。
- 生产维护窗口内 9000 停机消除并发写（设计 §17/§18），rehearsal 未制造生产式并发流量。

---

## 46. Data Preservation

```text
迁移前（drifted 0028）：cp=2 / ct=1698 / drj=0，JSONB 内容已指纹
迁移后（0034）：       cp=2 / ct=1698 / drj=0，JSON object/array/NULL 逻辑相等
BR-23 restore：        cp=2 / ct=1698 / drj=0，revision=0034，JSON 内容保留
```

---

## 47. Stop Conditions

R-S1~R-S13 全程检查，**无一触发**：

```text
R-S1 target artifact head != 0034      NOT TRIGGERED（head=0034 已验证）
R-S2 unexpected 0035 applied           NOT TRIGGERED（无 wechat_tasks）
R-S3 0029 fails on JSONB drift         NOT TRIGGERED（0029 幂等成功）
R-S4 data corruption/row loss          NOT TRIGGERED（行数/内容全保留）
R-S5 unexpected uniqueness conflict    NOT TRIGGERED（存量全 NULL）
R-S6 old/target commit mismatch        NOT TRIGGERED（worktree HEAD 验证）
R-S7 target9000+0034 /ready failure    NOT TRIGGERED（/ready 200）
R-S8 wrapper preflight fail unexpected NOT TRIGGERED（PASS）
R-S9 9100 recreated during 9000 action NOT TRIGGERED（container/started 不变）
R-S10 9100 DB changes from 0003        NOT TRIGGERED（恒 0003）
R-S11 rollback cannot restore 9000     NOT TRIGGERED（回退到 22e97a46a1da）
R-S12 backup restore fails             NOT TRIGGERED（restore 成功）
R-S13 uncontrolled scope/resource collision NOT TRIGGERED（全程隔离命名）
```

---

## 48. Unexpected Findings

| ID | 发现 | 影响 | 处置 |
| --- | --- | --- | --- |
| U1 | old f453f44 树 0008 含 `ai_edit_job_artifacts.file_size_bytes` 前向声明（PREDECLARED_FUTURE_SCHEMA），空库全量跑链 0025 DuplicateColumn；target 树已由 DB-BL-2C-R2 移除 | old 树无法从空库全量跑到 0028（生产非空库全量路径，不受影响） | 记录；BR-01 fixture 改用 target 制品（与设计 §14 一致） |
| U2 | target 树 0026 前向 JSONB → target 空库 0028 天然 = 生产 drift 态 | 简化 drift 构造（BR-02 天然满足）；STANDARD_0028(TEXT) 需 MIGRATION_VERIFIED 佐证 | 记录；drift 语义与生产一致 |
| U3 | old 树 0025 失败事务回滚（revision 停 0024） | 独立佐证 transactional DDL | 记录；与 BR-22 一致 |

以上均为 non-blocking findings，不影响 0028→0034 catch-up 正确性。

---

## 49. Known Limitations

1. **PRODUCTION_LIKE ≠ PRODUCTION**：即使 1698 行 + JSONB drift + 同 revision 序列 + 容器运行时全模拟成功，也不代表生产已 VERIFIED。
2. rehearsal 镜像（f453f44/9db3f58 树构建）provenance 不等于生产 `sha256:93094f0...`（未声称）。
3. 数据规模小（cp=2/ct=1698/drj=0），迁移耗时不能外推生产绝对耗时/锁风险。
4. BR-22 只覆盖 0030 lock-timeout 失败路径；其他失败路径（如 DDL 语法错）未逐一注入。
5. 生产反代/监控/宝塔 autoheal 行为（`PRODUCTION_EXTERNAL_AUTOHEAL=UNKNOWN`）未在本 rehearsal 覆盖，需生产侧核实。
6. BR-24~30 使用 old-image-equivalent fixture（f453f44 构建），未 copy 生产镜像 bytes。

---

## 50. Evidence Matrix

| 证据 | 载体 |
| --- | --- |
| ISOLATED_POSTGRESQL_RUNTIME_VERIFIED | BR-01~14、BR-19、BR-22、BR-23、BR-27、BR-28 |
| ISOLATED_CONTAINER_RUNTIME_VERIFIED | BR-15/16、BR-17/18、BR-20/21 |
| COMPOSE_RUNTIME_VERIFIED | BR-24~30、§38 Host Pollution |
| MIGRATION_VERIFIED | 0026/0028/0029/0030/0032/0033/0034 迁移定义、old 树 0008 缺陷 |
| CODE_VERIFIED | BR-19 P1 consumer / FC-F1 代码身份 |

---

## 51. BR-01~30 Final Matrix

| BR | 测试 | 结果 | Evidence |
| --- | --- | --- | --- |
| BR-01 | Clean standard 0028 fixture | PASS_WITH_FINDING(U1) | ISOLATED_POSTGRESQL_RUNTIME_VERIFIED + MIGRATION_VERIFIED |
| BR-02 | Drift construction（revision=0028 + jsonb） | PASS | ISOLATED_POSTGRESQL_RUNTIME_VERIFIED |
| BR-03 | Production-like synthetic data（2/1698/0） | PASS | ISOLATED_POSTGRESQL_RUNTIME_VERIFIED |
| BR-04 | drifted0028 → 0029 | PASS | ISOLATED_POSTGRESQL_RUNTIME_VERIFIED |
| BR-05 | JSONB data preservation | PASS | ISOLATED_POSTGRESQL_RUNTIME_VERIFIED |
| BR-06 | 0029 → 0030 | PASS | ISOLATED_POSTGRESQL_RUNTIME_VERIFIED |
| BR-07 | 0030 columns/UK/data preservation | PASS | ISOLATED_POSTGRESQL_RUNTIME_VERIFIED |
| BR-08 | 0030 → 0032 | PASS | ISOLATED_POSTGRESQL_RUNTIME_VERIFIED |
| BR-09 | 0032 schema/FK/index | PASS | ISOLATED_POSTGRESQL_RUNTIME_VERIFIED |
| BR-10 | 0032 → 0033 | PASS | ISOLATED_POSTGRESQL_RUNTIME_VERIFIED |
| BR-11 | 0033 schema | PASS | ISOLATED_POSTGRESQL_RUNTIME_VERIFIED |
| BR-12 | 0033 → 0034 | PASS | ISOLATED_POSTGRESQL_RUNTIME_VERIFIED |
| BR-13 | 0034 schema | PASS | ISOLATED_POSTGRESQL_RUNTIME_VERIFIED |
| BR-14 | Final alembic current=0034 | PASS | ISOLATED_POSTGRESQL_RUNTIME_VERIFIED |
| BR-15 | Old f453f44 + 0034 runtime compat | PASS | ISOLATED_CONTAINER_RUNTIME_VERIFIED |
| BR-16 | Old app readiness vs 0034（503 + unhealthy + no auto-restart） | PASS | ISOLATED_CONTAINER_RUNTIME_VERIFIED + COMPOSE_RUNTIME_VERIFIED |
| BR-17 | Target 9db3f58 + 0034 startup | PASS | ISOLATED_CONTAINER_RUNTIME_VERIFIED |
| BR-18 | Target /ready expected=actual=0034 | PASS | ISOLATED_CONTAINER_RUNTIME_VERIFIED |
| BR-19 | P1 production-baseline artifact | PASS | ISOLATED_POSTGRESQL_RUNTIME_VERIFIED + CODE_VERIFIED |
| BR-20 | Application rollback target→old | PASS | ISOLATED_CONTAINER_RUNTIME_VERIFIED |
| BR-21 | Old app after rollback（503 + no auto-restart） | PASS | ISOLATED_CONTAINER_RUNTIME_VERIFIED |
| BR-22 | Failure injection / rollback / recoverability | PASS | ISOLATED_POSTGRESQL_RUNTIME_VERIFIED |
| BR-23 | Backup/restore dry-run | PASS | ISOLATED_POSTGRESQL_RUNTIME_VERIFIED |
| BR-24 | Deployment identities isolated（9000 A != 9100 B） | PASS | COMPOSE_RUNTIME_VERIFIED |
| BR-25 | Target9000 only（9000 A→C） | PASS | COMPOSE_RUNTIME_VERIFIED |
| BR-26 | 9100 image identity unchanged | PASS | COMPOSE_RUNTIME_VERIFIED |
| BR-27 | 9100 DB remains 0003 | PASS | ISOLATED_POSTGRESQL_RUNTIME_VERIFIED |
| BR-28 | 9100 not recreated / not migrated | PASS | COMPOSE_RUNTIME_VERIFIED + ISOLATED_POSTGRESQL_RUNTIME_VERIFIED |
| BR-29 | Target9000 + 0034 /ready 200 | PASS | COMPOSE_RUNTIME_VERIFIED |
| BR-30 | Rollback 9000 without touching 9100 | PASS | COMPOSE_RUNTIME_VERIFIED |

**结果统计：BR-01~BR-30 全部 PASS（BR-01 为 PASS_WITH_FINDING，finding 为 non-blocking）。无 FAIL / BLOCKED / NOT_RUN。**

---

## 52. Rehearsal Verdict

```text
ISOLATED_REHEARSAL = PASSED_WITH_NON_BLOCKING_FINDINGS
```

依据：

- BR-01~BR-30 全部 PASS（BR-01 的 U1 finding 为 non-blocking 记录，不影响 0028→0034 catch-up 正确性；无 migration/runtime/rollback/9100 isolation correctness 问题）。
- 无 hard-stop 触发（R-S1~R-S13 全 NOT TRIGGERED）。
- target9000 + 0034 /ready 200；9100 全程冻结（container/started/image/restart/DB=0003 不变）；rollback 可用；数据保留；backup/restore 可用。
- 未发现 0035 污染、9100 recreate、9100 DB 变更、数据丢失、rollback 失败。

**仍须 Independent Rehearsal Approval（独立审批）后，才可能进入 Production Authorization。**

---

## 53. Production Authorization Status

```text
PRODUCTION_MIGRATION_AUTHORIZED = NO
```

Rehearsal 通过 ≠ 生产授权。下一步必须：

```text
PRODUCTION-BASELINE-CATCHUP-0028-TO-0034
  INDEPENDENT-REHEARSAL-APPROVAL
```

才可能进入生产授权与执行（生产侧仍需：preflight 全项、backup、rollback artifact 固化、S1-S12 设计 stop conditions、维护窗口执行）。

---

## 54. Next Stage

```text
下一阶段：PRODUCTION-BASELINE-CATCHUP-0028-TO-0034 INDEPENDENT-REHEARSAL-APPROVAL
  → 独立复核本报告（BR 矩阵 + A/B/C 矩阵 + 证据 + findings）
  → 复核通过 → 才可能 Production Authorization（PRODUCTION_MIGRATION_AUTHORIZED 仍为 NO）
  → 生产执行窗口（独立）：preflight → backup → 维护窗口 → schema 0034 → target9000 deploy → PV-01~PV-17 → B7/B8 closure → return P2
```

---

*本窗口只执行隔离 rehearsal 并产出本报告。未 commit、未 push、未操作 Merchant、未做生产迁移/部署/镜像构建（生产侧）/0035/P2/9100 升级。rehearsal 资源已按 §62 清理（见下文 Cleanup）。*

---

# Cleanup 记录（§62）

Rehearsal 完成后清理 disposable 资源（保留完整 evidence）：

```text
已清理：
  - 临时 worktree（old-f453f44 / target-9db3f58，git worktree remove）
  - rehearsal PG（rehearsal-b7-pg @15432，含 aw_old_chain_probe / aw_restore_probe / aw_fi_probe）
  - S10 compose 环境（s10 project：s10-postgres-1 / xg-auto-wechat-api / xg-douyin-ai-cs，网络 s10_default）
  - 手动应用容器（rehearsal-old9000 / rehearsal-target9000）
  - rehearsal 网络 rehearsal-b7-net
  - rehearsal 镜像（auto-wechat-rehearsal:old-f453f44 / target-9db3f58 / frozen-old-9100）
未触碰：xg-ai-postgres / auto-wechat-postgres-dev / 任何项目正常开发容器与 volume
未执行：docker prune 全局、不删除 production rollback 镜像（本地无生产镜像）
```

**Evidence 保留**：`e:/work/tmp/rehearsal-b7/`（SQL fixture、backup、evidence_notes）+ 本报告。

*Rehearsal 窗口结束。*
