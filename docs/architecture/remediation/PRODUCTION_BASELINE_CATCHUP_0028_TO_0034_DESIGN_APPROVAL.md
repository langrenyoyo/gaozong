# PRODUCTION-BASELINE-CATCHUP-0028-TO-0034 — Independent Design Approval

> 窗口：`PRODUCTION-BASELINE-CATCHUP-0028-TO-0034-INDEPENDENT-DESIGN-APPROVAL`
> 窗口性质：**INDEPENDENT READ / VERIFY ONLY** — 不执行 rehearsal、不执行生产迁移、不执行生产部署、不构建镜像、不 commit、不 push、不改代码/迁移/compose/Dockerfile/env。
> 审批对象：`docs/architecture/remediation/PRODUCTION_BASELINE_CATCHUP_0028_TO_0034_DESIGN.md`
> 前序：`PRODUCTION_SCHEMA_BASELINE_CATCHUP_0028_TO_0034_REALITY_AUDIT.md`（Verdict=`PRODUCTION_SCHEMA_CATCHUP_DESIGN_REQUIRED`）
> 日期：2026-08-12
> 证据层级：`CODE_VERIFIED` / `MIGRATION_VERIFIED` / `GIT_HISTORY_VERIFIED` / `CONTAINER_CONFIG_VERIFIED` / `DESIGN_VERIFIED` / `NOT_VERIFIED`。生产 runtime 证据（M3/M4 docker inspect / image inspect）承自 Design 窗口 `PRODUCTION_RUNTIME_VERIFIED`，本审批窗口未独立重新执行生产 docker inspect（任务书 §56 禁止要求用户执行写操作，§44 不要求本窗口执行 rehearsal）；承用项均显式标注"承自 Design M3/M4"。

---

## 1. Approval Scope

独立审查 Design 文档是否达到可授权 **Isolated Rehearsal** 的质量。不审批生产迁移、不审批生产部署、不审批 0035、不审批 P3a、不审批 RB-10。只裁定：Design 是否 correct、Hard gates 是否 addressed、Rehearsal plan 是否 executable。

## 2. Governance Baseline

承自 Design §1，本窗口不重开：

```text
P1 COMPUTE-IDEMPOTENCY-001 = CLOSED
P1 TECHNICAL_CLOSURE         = VERIFIED
P1 CODE_CLOSURE              = CLOSED
P1 PRODUCTION_DEPLOYMENT     = BEHIND / PENDING BASELINE CATCH-UP
P2 TECHNICAL_REMEDIATION     = VERIFIED
P2 M04 CLAIM/LEASE           = REMEDIATED
P2 PRODUCTION_CUTOVER        = BLOCKED_BY_BASELINE_CATCHUP
B7 PRODUCTION_SCHEMA_BEHIND  = CONFIRMED
B8 PRODUCTION_CODE_BEHIND    = CONFIRMED
```

## 3. Evidence Sources

本窗口独立核实（IA-DESIGN-01~14），不采信 Design 自述：

```text
git log / git ls-tree / git show / git diff / git grep （9db3f58 / f453f44 / eb9f58 / 36fe68a 树）
migrations/postgres/auto_wechat/versions/ 逐文件 revision/down_revision 头
0029_customer_profiles_jsonb_unify.py 全文
app/db_readiness.py + app/routers/health.py（f453f44 与 9db3f58 树对比）
docker-compose.yml + Dockerfile.backend.dev
.env.production.example + app/config.py + apps/xg_douyin_ai_cs/config.py 等 config diff
Design 文档 §1~§66 逐节
前序 Reality Audit §1~§40
```

## 4. Current Production Identity

承自 Design §2 + 前序 Audit §5/§6（`GIT_HISTORY_VERIFIED`）：

```text
CURRENT_PRODUCTION_CODE_COMMIT = f453f44e6a70de3eb5fa8f808cf4b6a9d72ea6c1
PRODUCTION_APP_ALEMBIC_CURRENT = 0028
PRODUCTION_DB_ALEMBIC          = 0028
PRODUCTION_READY_EXPECTED      = 0028
PRODUCTION_READY_ACTUAL        = 0028
PRODUCTION_READY               = PASS
```

本窗口独立确认 f453f44 message="fix: 导出脚本兼容多版本 pymilvus 迭代 API"，是 HEAD 36fe68a 的祖先，f453f44 树 9000 迁移最后=0028、不含 0029-0035。三态一致（内部一致旧 baseline，非"新代码+旧DB"drift）。`VERIFIED`。

## 5. Target Identity

本窗口独立核实（IA-DESIGN-01，`GIT_HISTORY_VERIFIED`）：

```text
TARGET_0034_CODE_COMMIT = 9db3f58
9db3f58 message = "设计：批准M04微信任务执行所有权方案"
9db3f58 = HEAD 36fe68a 的直接父（git log 9db3f58..36fe68a 仅 36fe68a 一行）
9db3f58 相对 eb9f182 = 纯文档（git diff --stat eb9f182 9db3f58 = 9 个 .md，零 .py）
```

9db3f58 树含（`VERIFIED`）：
- 9000 迁移 0029/0030/0032/0033/0034，**不含 0035**（ls-tree 确认）。
- 9100 RAG 迁移 0001-0005（含 0004/0005）。
- P1 消费者：`record_usage`（app/ 6 文件）、`AiPreviewExecution` + `_create_preview_execution`（F-1 closure，app/）。
- FC-F1 closure：`_write_transaction_balance_only` + `.returning(ComputeAccount.balance_tokens)` —— **位于 `apps/compute/services.py`**（见 §45 C2）。

**Target 9db3f58 纯度 = VERIFIED**（含 0029-0034 + P1 消费者 + F-1 + FC-F1，不含 0035）。

## 6. Revision Graph Verification

本窗口逐文件读 revision/down_revision（IA-DESIGN-02，`MIGRATION_VERIFIED`）：

```text
0028 down=0027
0029 down=0028
0030 down=0029
0032 down=0030  （0031 不存在，刻意跳号）
0033 down=0032
0034 down=0033
0035 down=0034  （OUT OF B7 TARGET）
```

单线性、无分叉、无 merge、单 head=0035。0031 不存在（ls-tree 9db3f58 与 HEAD 均无）。`VERIFIED`。Catch-up 目标链 = `0028→0029→0030→0032→0033→0034`（5 个迁移）。

## 7. 0029 JSONB Verification

本窗口读 0029 全文（IA-DESIGN-03，`MIGRATION_VERIFIED`）：

```text
upgrade(): op.alter_column(type_=JSONB(none_as_null=True), postgresql_using="...::text::jsonb") ×2
  - 未传 nullable= → 不发 SET/DROP NOT NULL，nullable 保持原值
  - 无 op.execute / UPDATE / INSERT / backfill
downgrade(): JSONB→Text（postgresql_using="...::text"），丢 JSONB 查询能力，值保留
文件头注释：明确"对已是 JSONB 的列无副作用/幂等"
```

PostgreSQL 语义：`ALTER COLUMN TYPE JSONB USING col::text::jsonb` 对已-jsonb 列，逐行 `jsonb::text::jsonb`，合法 jsonb 值转换均合法，NULL 保持 NULL → 不报错、幂等、语义安全。

```text
0029_EXISTING_JSONB_COMPATIBILITY = VERIFIED
```

## 8. Data Preconditions

承自前序 Audit M2 `PRODUCTION_READ_ONLY_VERIFIED`（READ ONLY 事务），本窗口未独立重查生产 DB（任务书 §56 不要求用户执行写/读生产）：

```text
0029: invalid_confirmed=0, invalid_inferred=0 → PASS
0030: 列不存在→全 NULL，NULL 不参与唯一约束 → PASS
0032: parent_exists=t；child 新表无 orphan → PASS
0033: 新表无存量 → PASS
0034: 新表无存量 → PASS
```

行数：`customer_profiles=1`、`compute_transactions=1698`、`daily_report_jobs=0`。本窗口接受 M2 只读证据。

## 9. Lock Risk Review

本窗口复核迁移 DDL（IA-DESIGN-03 + Design §7，`MIGRATION_VERIFIED`）：

| 迁移 | 操作 | 锁 | 行数 | 风险 |
| ---- | ---- | -- | ---- | ---- |
| 0029 | ALTER TYPE ×2（jsonb→jsonb 幂等重写） | ACCESS EXCLUSIVE | 1 | LOW |
| 0030 | ADD COL ×2 nullable | 元数据级 | 1698 | LOW |
| 0030 | CREATE UNIQUE CONSTRAINT | AccessExclusive 扫表 | 1698 | LOW（全 NULL 不冲突）|
| 0032 | CREATE TABLE + ADD COL nullable + INDEX(新表) | 元数据级 | 0 | LOW |
| 0033 | CREATE TABLE + INDEX(新表) | 元数据级 | 0 | LOW |
| 0034 | CREATE TABLE + INDEX(新表) | 元数据级 | 0 | LOW |

全链无 `op.execute`/backfill/`SET NOT NULL on existing table`。`LOW` 评级合理。LOW 不豁免 maintenance/backup/stop/rollback 设计。

## 10. Candidate A Review

本窗口独立核实（IA-DESIGN-04/05/07，`CODE_VERIFIED` + `CONTAINER_CONFIG_VERIFIED`）：

```text
old f453f44 + schema0034:
  APPLICATION_RUNTIME_COMPATIBLE     = YES（旧代码不碰新表新列，§11）
  READINESS_CONTRACT_INCOMPATIBLE   = YES（expected=0028 ≠ actual=0034 → /ready 503）
  DOCKER_HEALTH_STATE               = UNHEALTHY（healthcheck 探测 /ready，连续 3 次失败）
  AUTO_RESTART_ON_UNHEALTHY         = NOT_PROVEN
```

**Docker restart 语义核实**（IA-DESIGN-07）：docker-compose.yml 两服务 `restart: unless-stopped`，healthcheck.test 探测 `/ready`（非 /health），参数 30s/10s/3/20s。仓库无 autoheal/watchtower/supervisor/ofelia（grep 零命中）。`restart: unless-stopped` 是容器 exit/stop 时的策略，不等同 unhealthy→自动 restart。Design CORRECTION-1 已正确返修此处语义（不再写"restart loop"）。

```text
Candidate A = NOT_PREFERRED
理由 = TEMPORARY_READINESS_INCOMPATIBILITY + UNVERIFIED_PRODUCTION_HEALTH_ROUTING/SUPERVISION
（非 restart loop —— 语义正确）
```

`NOT_PREFERRED` 理由成立。`VERIFIED`。

## 11. Candidate B Review

本窗口独立核实（IA-DESIGN-06，`CODE_VERIFIED`）：

target 9db3f58 消费者代码硬依赖 0030-0034 新对象：
- `compute_transactions.idempotency_key`（0030）：models.py:997 Column + record_usage 写入（apps/compute/services.py:706/725）。
- `daily_report_generations`（0032）：models.py + daily_report_job_service.py。
- `ai_edit_material_analysis_executions`（0033）：models.py + material_analysis.py。
- `ai_preview_executions`（0034）：models.py + routers/agents.py + routers/douyin_ai_cs_proxy.py。

f453f44 旧代码零引用这些对象（git grep 零命中；idempotency_key 仅命中 return_visit_runs 0011 既有）。

```text
target 9db3f58 + schema0028 = NOT COMPATIBLE（缺表/缺列 → SQL 错误）
Candidate B (code-first) = REJECTED  ✓
```

`VERIFIED`。

## 12. Candidate C Review

```text
PREFERRED = SCHEMA_FIRST_WITH_MAINTENANCE_WINDOW（Candidate C 变体）
```

迁移顺序 schema-first（先 schema 后 code），执行方式维护窗口停机切换。核心价值 = 隔离临时 readiness mismatch，避免 unhealthy 旧 9000 暴露给生产流量/监控（非"避免 restart loop"）。序列内部闭合性见 §15-§17。

## 13. Preferred Strategy Review

Design §9 冻结条件核对：

```text
old f453f44 + schema0034 = STATICALLY COMPATIBLE          ✓（§11，业务运行时）
target 9db3f58 + schema0034 = COMPATIBLE                  ✓（§12）
target 9db3f58 + schema0028 = NOT REQUIRED / MUST NOT RUN ✓（§11）
0029 drift behavior = supported                          ✓（§7，幂等）
all intermediate migrations = safe                       ✓（§9，全 LOW）
```

Preferred Strategy 选择合理。`VERIFIED`。

## 14. Readiness Contract

本窗口独立核实（IA-DESIGN-04/05，`CODE_VERIFIED`）：

- `app/db_readiness.py`：`load_alembic_heads` 用 `ScriptDirectory.from_config(cfg).get_heads()` 动态扫描代码树迁移目录，**非硬编码**。
- `app/routers/health.py`：`actual_revs != expected_heads` → `error_code=ALEMBIC_REVISION_MISMATCH` → `JSONResponse(503)`。
- `git diff f453f44 9db3f58 -- app/db_readiness.py app/routers/health.py` = **空**（两文件 IDENTICAL）。

| 代码树 | 9000 迁移链尾 | expected head |
|--------|--------------|--------------|
| f453f44 | 0028 | 0028 |
| 9db3f58 | 0034 | 0034 |
| 36fe68a | 0035 | 0035 |

```text
f453f44 容器（expected=0028）+ DB=0034 → actual=[0034] != expected=[0028] → /ready 503（必然）
```

`VERIFIED`。Design §13 正确区分 `APPLICATION_RUNTIME_COMPATIBLE=YES` 与 `READINESS_CONTRACT_INCOMPATIBLE=YES`。

## 15. Docker Restart Semantics

见 §10。`restart: unless-stopped` 不因 unhealthy 自动 restart（标准 Docker 语义）；仓库无 external autoheal。`PRODUCTION_EXTERNAL_AUTOHEAL = UNKNOWN`（生产宝塔/systemd 未核实，但 Design 未据此错误推导 restart loop）。`VERIFIED`。

## 16. Maintenance Window

Design §16/§39 定义 `CONTROLLED_DOWNTIME`，需控制：business write control / operator presence / backup ready / rollback artifacts ready / monitoring。序列见 §25。本窗口确认 maintenance 模型具体，非空标题。`VERIFIED`。

## 17. Write Traffic

Design §17：维护窗口内 9000 停机 → 无写流量到达 DB。9000 是 customer_profiles/compute_transactions/daily_report_jobs 唯一写入口（9100 写 xg_douyin_ai_cs 库）。0029/0030 的 AccessExclusive 锁在无并发写时安全。`VERIFIED`。

## 18. Compute Concurrency

Design §18：维护窗口内 9000 停机 → 无新 compute write。0030 CREATE UNIQUE CONSTRAINT 扫 1698 存量行，idempotency_key 全 NULL 不冲突。不以"1698 行小"为由忽略，正确保障是"9000 停机消除并发写"。`VERIFIED`。

## 19. S10 Shared Image Evidence

本窗口独立核实（IA-DESIGN-08，`CONTAINER_CONFIG_VERIFIED` + 承自 Design M3 `PRODUCTION_RUNTIME_VERIFIED`）：

```text
docker-compose.yml:
  auto-wechat-api（9000）: image=xg-ai-system-backend:latest, build=Dockerfile.backend.dev
  xg-douyin-ai-cs（9100）: image=xg-ai-system-backend:latest, build=Dockerfile.backend.dev
  两服务靠 command 区分入口（9000=app.main:app，9100=apps.xg_douyin_ai_cs.main:app）
  无独立 9100 Dockerfile

承自 Design M3（docker inspect，本窗口未独立重核）:
  9000 Image ID = sha256:93094f0a02ba3a4570160ce90625cb80fdec85076046fc314f5fe407add36c68
  9100 Image ID = 同上
  → 9000_9100_RUNTIME_IMAGE_SHARED = VERIFIED（同 image ID）
  9100 ALEMBIC_CURRENT = 0003（INTERNALLY_CONSISTENT_0003）
```

9100 RAG 迁移链差异（`GIT_HISTORY_VERIFIED`）：`git diff --stat f453f44 9db3f58 -- migrations/postgres/xg_douyin_ai_cs/` = 0004(+68)+0005(+63)，2 文件 131 行；`-- apps/xg_douyin_ai_cs/` = 8 文件 +395/-48。9db3f58 树 9100 head=0005，f453f44 树 9100 head=0003。

`VERIFIED`。

## 20. S10 Risk Model

Design §51 CORRECTION-1（C5）正确纠正风险模型：

```text
错误表述（已返修）: rebuild :latest → 运行中 9100 即时改变
正确表述: rebuild/repoint :latest 不自动 mutate 已运行 9100 容器
         风险发生于 9100 被 recreate/redeploy 使用共享 mutable tag 时
         → 9100 expected=0005 ≠ actual=0003 → /ready 503 + unhealthy
```

`VERIFIED`。Design 不再写"即时同步升级 9100"错误。

## 21. S10-A Review

S10-A = 一起升级 9100 0003→0005（RAG catch-up + 395 行代码）。扩大范围，违反 MINIMUM_CHANGE / NO_UNAUTHORIZED_9100_CATCH_UP / YAGNI。`不首选`，裁定合理。`VERIFIED`。

## 22. S10-B Review

S10-B = 9000 immutable image from 9db3f58 + 9100 冻结 93094f0.../0003，不 recreate 不 migrate。符合 MINIMUM_CHANGE / YAGNI / NO_UNAUTHORIZED_9100_CATCH_UP。`首选`，裁定合理。`VERIFIED`。

## 23. S10-B Feasibility

本窗口独立核实（IA-DESIGN-09，`CONTAINER_CONFIG_VERIFIED`）—— **本次审批最高优先级之一**：

```text
docker-compose.yml: 9000 与 9100 是两个独立 service 定义，各有独立 image: 字段
  → Docker Compose 架构上支持 per-service image 覆盖（机制清楚）

仓库现状:
  - 无 docker-compose.override.yml
  - docker-compose.staging.yml 展示 override 模式，但两服务用相同 image tag（无 per-service 差异先例）
  - scripts/production_pg_*.sh 聚焦 PG/迁移/cutover，无一涉及 image build/tag/deploy
  - .env.production.example 无 IMAGE 变量（image 字段全硬编码字面量）
  → 仓库无现成机制支持 service-specific image identity
```

```text
S10-B = DESIGN FEASIBLE（机制清楚：per-service image override 是 Docker Compose 标准能力）
      + RELEASE_ENGINEERING_CHANGE_REQUIRED = YES（仓库无现成机制，需创建生产 compose override 或改 image 字段为 env-var 驱动）
```

Design §52/§64 **如实标注**此 gap（"改 docker-compose.yml 全局 image 字段超出本窗口，由生产执行窗口决定 override 机制"，未假装"无需修改当前部署"）。

**任务书 §19 裁定**：current production deployment 现状不能 isolate 9000/9100 image identity（确认），**但** Design 有可实施的最小方案（per-service compose override 或 env-var driven tag，机制清楚）→ **不触发 CATCHUP_DESIGN_BLOCKED**。任务书 §17 允许审批裁定 S10-B DESIGN FEASIBLE（前提机制清楚），同时要求 RELEASE_ENGINEERING_CHANGE 进入 separate implementation/approval（§18）。

`VERIFIED`。但需 C3 correction（§45）明确化最小机制与闭环时点。

## 24. 9100 Freeze Contract

若 S10-B 批准，冻结（Design §20/§52）：

```text
9100_RUNTIME_IMAGE = sha256:93094f0...（承自 M3）
9100_DB            = 0003
9100_DEPLOYMENT    = NO CHANGE
未来: DO NOT RECREATE 9100 / DO NOT MIGRATE 9100 / DO NOT RESTART 9100 UNNECESSARILY
```

`VERIFIED`。

## 25. Current Runtime Image

承自 Design M3+M4（`PRODUCTION_RUNTIME_VERIFIED`，本窗口未独立重核 docker inspect）：

```text
CURRENT_RUNTIME_IMAGE_ID      = sha256:93094f0a02ba3a4570160ce90625cb80fdec85076046fc314f5fe407add36c68
CURRENT_RUNTIME_IMAGE_CREATED = 2026-08-06T18:17:27+08:00
IMAGE_LABELS                  = com.docker.compose.* （无 org.opencontainers.image.revision / git.commit）
```

## 26. Rollback Runtime Identity

Design §19/§38 拆分（C8/M4）：

```text
ROLLBACK_RUNTIME_IMAGE_IDENTITY      = VERIFIED（image ID = 93094f0...，M3+M4 实测，可 docker tag 固化）
ROLLBACK_SOURCE_COMMIT_PROVENANCE    = UNVERIFIED（image 无 provenance label）
IMAGE_BUILD_PROVENANCE_DEBT           = NON_BLOCKING FOR THIS CATCH-UP
  前提: runtime image 被可靠保存为 immutable identity
```

Design **不**声称 `93094f0...=f453f44`（宿主 git HEAD 与 image identity 为两条独立证据）。拆分正确。`VERIFIED`。

## 27. Provenance Debt

`IMAGE_BUILD_PROVENANCE_DEBT = NON_BLOCKING`，前提 runtime image preserved under immutable identity。任务书 §23 允许：只要 runtime image 可靠保留，rollback runtime capability 成立，不要求 source commit provenance 才能 rollback。`VERIFIED`。

## 28. Target Image Identity

Design §19 要求未来 target image 从 9db3f58 构建时用独立 immutable identity（如 `:9db3f58-<ts>`）+ `org.opencontainers.image.revision=9db3f58` 可追踪 metadata，不复用共享 mutable `:latest`。`VERIFIED`。

## 29. Migration Artifact Identity

Design §20：`MIGRATION_ARTIFACT_SOURCE_COMMIT = 9db3f58`，head=0034（本窗口 IA-DESIGN-10 确认 9db3f58 树 9000 链尾=0034，不含 0035）。禁止用 36fe68a 制品（head=0035，即使 `upgrade 0034` 可执行，仍优先 9db3f58 减少 operator error）。`VERIFIED`。

## 30. Backup Review

Design §33 `DATABASE_BACKUP_CHECKPOINT` 具体含：method（pg_dump/物理）/ identity（hash/路径）/ timestamp / database=auto_wechat / restore procedure / restore verification（隔离环境 restore + alembic current=0028 + 行数核对）/ operator。非空"升级前备份"。`VERIFIED`。Backup ≠ Rollback（§34）。

## 31. Rollback R1

R1（迁移前 abort，schema 仍 0028，old app 仍 f453f44）：直接取消，无副作用。简单可靠。`VERIFIED`。

## 32. Rollback R2

R2（schema 已 0034，target 未部署）：
- 依赖 rehearsal `APPLICATION_RUNTIME_COMPATIBLE=YES`（BR-15/16 待验）。
- Design 如实标注 `/ready 503 + unhealthy` 不得恢复 `NORMAL_PRODUCTION_SERVICE`。
- CORRECTION-1 正确修正早期 restart loop 推导。
- 处置优先级：首选继续推进 target（让 expected=actual=0034）/ 次选维护态 fallback / 末选 schema downgrade。

`VERIFIED`。

## 33. Rollback R3

R3（target 已部署后失败）：回滚 = 旧代码 f453f44 + schema0034，同 R2 限制（application runtime compatible 但 /ready 503+unhealthy，须进维护态或尽快重新部署 target）。优先 schema-forward + code rollback，不优先 schema downgrade。`VERIFIED`。

## 34. Schema Downgrade

Design §36：`0034→0028 = EMERGENCY_ONLY`。逐 migration downgrade 分析数据丢失（drop tables/columns）。仅在无可恢复 target + 无 forward 路径时使用。`APPLICATION_ROLLBACK ≠ SCHEMA_DOWNGRADE`。`VERIFIED`。

## 35. Drifted Fixture Review

Design §45/§46：rehearsal 必须用 `DRIFTED_0028_PRODUCTION_FIXTURE`（alembic_version=0028 + customer_profiles 两列已 jsonb），禁止只用 fresh clean 0028（TEXT 列）。fixture 含 1/1698/0 synthetic rows。`VERIFIED`，符合任务书 §26。

## 36. BR Matrix Review

本窗口独立核对（IA-DESIGN-12）：BR-01~BR-30 覆盖全生命周期——drift construction（BR-02）/ 0029 upgrade+JSON preservation（BR-04/05）/ 0030-0034 逐 revision（BR-06~13）/ final current=0034（BR-14）/ old app+new schema（BR-15/16）/ target app+new schema+/ready（BR-17/18）/ rollback（BR-20/21）/ S10 部署身份隔离（BR-24~30）/ 9100 frozen 0003（BR-26/27/28）。**无关键缺失项**。`VERIFIED`。

## 37. S10 BR Review

BR-24~30 覆盖：deployment identities isolated（BR-24）/ deploy target 9000 only（BR-25）/ 9100 old image unchanged（BR-26）/ 9100 DB stays 0003（BR-27）/ no 9100 recreate/migration（BR-28）/ target 9000 /ready 200（BR-29）/ rollback 9000 without touching 9100（BR-30）。`VERIFIED`。但 BR-24~30 在隔离 PG rehearsal 中如何具体执行需明确化（见 §45 C4）。

## 38. PV Matrix Review

本窗口独立核对（IA-DESIGN-13）：PV-01~PV-17 覆盖 source/image identity / DB revision / app head / /ready / expected=actual / critical tables / 新 0030-0034 对象 / 存量行保留 / P1 部署证据 / 无意外 drift / 日志 / 9100 未变 / 9000 immutable image。**无缺失项**。`VERIFIED`。

## 39. P1 Boundary

Design §26/§36：catch-up 后只验证"P1 technical closure artifacts 已部署到生产 baseline"（schema objects exist + target code includes P1 consumers），不重做 P1 correctness review。`VERIFIED`，符合任务书 §37。

## 40. P2 Boundary

Design §50：`BASELINE_CATCHUP_PRODUCTION_VERIFIED` 后才恢复 P2 cutover（解除 B7/B8）。不直接 deploy 0035（0035 属独立 P2 cutover，需独立审批 + rehearsal）。`VERIFIED`。

## 41. Frontend Boundary

Design §53：`FRONTEND_CHANGE_REQUIRED = NO`。0028→0034 是后端 schema/code baseline 追平。`VERIFIED`，符合任务书 §39。

## 42. Env Compatibility

本窗口独立核实（IA-DESIGN-14，`CODE_VERIFIED`）：

```text
git diff --stat f453f44 9db3f58 -- app/config.py = 零变更
git diff --stat f453f44 9db3f58 -- apps/xg_douyin_ai_cs/config.py / llm/config.py / llm/embedding_config.py = 零变更
```

catch-up 链（0029~0034 schema 迁移）不引入新 required env 消费点。Design §54 标 `ENV_CONFIG_DRIFT = REQUIRES_PRODUCTION_VERIFICATION` 标注**合理但过度保守**——代码层可确定性穷举为零变更；生产 `.env.production.local` 不在仓库（.gitignore），确实需生产侧核实。见 §45 C1。

## 43. Stop Conditions

Design §40 S1-S12：Production DB!=0028 / commit 变 / JSONB drift scope 变 / invalid JSON>0 / unexpected ahead object / backup 不可用 / rollback image 不可用 / target head mismatch / target source mismatch / S10 image coupling unresolved / rehearsal failed / old-code+schema0034 业务层不兼容。`VERIFIED`，覆盖任务书 §42 最低要求。S12 正确限定为业务运行时不兼容（非 readiness 层）。

## 44. Blocking Findings

**无 CORRECTNESS_CRITICAL 阻断项。**

核心 design 正确性全部 VERIFIED：
- target 9db3f58 纯度（含 0029-0034 + P1 + F-1 + FC-F1，不含 0035）。
- revision graph 单线性。
- 0029 幂等性。
- readiness 契约动态推断 + f453f44+schema0034 必然 503。
- target 代码硬依赖 0030-0034（Candidate B 不安全）。
- docker restart 语义（CORRECTION-1 已正确返修）。
- S10-B 机制清楚（DESIGN FEASIBLE，不触发 §19 BLOCKED）。
- Rollback/BR/PV 完整。

**S10-B 不构成阻断**：机制清楚（per-service image override 是 Docker Compose 标准能力，两服务独立 image 字段），Design 如实标注 gap + RELEASE_ENGINEERING_CHANGE 进入 separate implementation/approval。任务书 §17/§18 明确允许此状态。

## 45. Required Corrections

以下 corrections 不影响核心 strategy 正确性，不改变 Preferred Strategy（SCHEMA_FIRST_WITH_MAINTENANCE_WINDOW）或 S10-B 设计选择（IMMUTABLE_SERVICE-SPECIFIC_DEPLOYMENT），可在进入 rehearsal candidate 时明确应用。`MUST_APPLY_BEFORE_REHEARSAL`。

### C1 — ENV_CONFIG_DRIFT 降级（DOCUMENTATION_CORRECTION）

Design §54 应将代码层 env diff 从 `REQUIRES_PRODUCTION_VERIFICATION` 降级为 `ENV_CONFIG_DRIFT = NONE_DETECTED`（基于 `app/config.py` + 3 个 9100 config 文件零 diff，catch-up 链不引入新 env 消费点）。仅生产 `.env.production.local` 实际配置仍需生产侧核实（变量名/required presence，非 secret）。不影响 strategy。

### C2 — FC-F1 证据路径修正（DOCUMENTATION_CORRECTION）

Design §3 断言 `_write_transaction_balance_only` 搜索路径 `-- app/` 不完整，FC-F1 closure 代码实际位于 `apps/compute/services.py`（apps/ 目录，非 app/）。Design 结论（9db3f58 含 FC-F1）正确——符号确实在 9db3f58 树存在（`apps/compute/services.py:151` def + `:734` 调用 + `:177` `.returning()`），仅证据引用搜索路径需扩展为 `-- app/ apps/` 以避免假阴性。不影响 target 纯度结论。

### C3 — S10-B Release Engineering 机制明确化（OPERATIONAL_HARD_GATE）

Design §52 应明确标 `RELEASE_ENGINEERING_CHANGE_REQUIRED = YES`（任务书 §18），并指定至少一种可实施的最小机制：
- 候选 1：创建生产 compose override 文件，仅覆盖 9000 的 `image:` 字段为 `xg-ai-system-backend:9db3f58-<ts>`，9100 保留指向 `93094f0...` 的 immutable tag。
- 候选 2：改 docker-compose.yml 两服务 image 字段为 env-var 驱动（`${BACKEND_IMAGE_9000}` / `${BACKEND_IMAGE_9100}`），生产 .env 分别指定。

该 release engineering change 进入 separate implementation/approval（任务书 §18），**但必须在生产 execution 前闭环**（S10-B 解除条件）。不改变 S10-B 设计选择（仍是 IMMUTABLE_SERVICE-SPECIFIC_DEPLOYMENT）。

### C4 — BR-24~30 Rehearsal 验证机制明确化（REHEARSAL_PLAN_GAP）

Design §47 rehearsal topology 仅描述隔离 PostgreSQL 实例（PG/迁移层），未明确 BR-24~30 的 docker compose 部署身份隔离如何在 rehearsal 环境验证。应明确：rehearsal 是否需要隔离 docker compose 环境（至少验证 service-specific image override 机制的可执行性 + 9100 不被 recreate），或明确 BR-24~30 的验证边界（如：rehearsal 验证 release engineering 机制设计可执行，生产 execution 窗口验证实际 image identity 隔离）。这是 rehearsal plan 明确化，不是 strategy 改变。

## 46. Non-Blocking Debt

```text
IMAGE_BUILD_PROVENANCE_DEBT = NON_BLOCKING（§27，前提 runtime image preserved）
MUTATING_GET_PROTOCOL_DEBT = NON_BLOCKING / FUTURE（承自 P2 cutover）
9100 RAG catch-up 0003→0005 = OUT OF THIS WINDOW（S10-A/独立 catch-up）
9000/9100 镜像分离 = OUT OF THIS WINDOW（需改 compose，YAGNI）
PRODUCTION_EXTERNAL_AUTOHEAL = UNKNOWN（不影响 Candidate A 裁定，§15）
反代 /ready upstream 健康检查 = REQUIRES_PRODUCTION_VERIFICATION（§15，维护窗口不依赖反代行为）
```

## 47. Evidence Matrix

| IA-DESIGN | 项 | 结论 | 证据层级 |
| --------- | -- | ---- | -------- |
| 01 | target 9db3f58 树内容 | VERIFIED | GIT_HISTORY_VERIFIED |
| 02 | revision graph 单线性 | VERIFIED | MIGRATION_VERIFIED |
| 03 | 0029 JSONB 幂等 | VERIFIED | MIGRATION_VERIFIED |
| 04 | f453f44 readiness expected=0028 | VERIFIED | CODE_VERIFIED |
| 05 | 9db3f58 readiness expected=0034 + 必然 503 | VERIFIED | CODE_VERIFIED |
| 06 | target 代码 schema 依赖（Candidate B 不安全）| VERIFIED | CODE_VERIFIED |
| 07 | docker health/restart 语义 | VERIFIED | CONTAINER_CONFIG_VERIFIED |
| 08 | 9000/9100 共享镜像 + 9100 head 0003→0005 | VERIFIED | CONTAINER_CONFIG_VERIFIED |
| 09 | S10-B 可落地性 | DESIGN FEASIBLE + RELEASE_ENGINEERING_CHANGE_REQUIRED | CONTAINER_CONFIG_VERIFIED |
| 10 | target 制品 head=0034 | VERIFIED | GIT_HISTORY_VERIFIED |
| 11 | rollback path R1/R2/R3 + identity 拆分 | VERIFIED | DESIGN_VERIFIED |
| 12 | BR-01~30 完整性 | VERIFIED 无缺失 | DESIGN_VERIFIED |
| 13 | PV-01~17 完整性 | VERIFIED 无缺失 | DESIGN_VERIFIED |
| 14 | env config 零变更 | VERIFIED（标注过度保守）| CODE_VERIFIED |

生产 runtime 证据（image ID / docker inspect）承自 Design M3/M4 `PRODUCTION_RUNTIME_VERIFIED`，本窗口未独立重核（任务书 §56）。

## 48. Verdict

```text
CATCHUP_DESIGN = APPROVED_WITH_CORRECTIONS
```

依据：
- 核心 design 正确性全部 VERIFIED（target 纯度 / revision graph / 0029 幂等 / readiness 契约 / 兼容矩阵 / docker restart 语义 CORRECTION-1 已正确返修 / 回滚 / BR / PV）。
- Hard gates addressed：S10-B 机制清楚（DESIGN FEASIBLE），Design 如实标注 gap，不触发 §19 CATCHUP_DESIGN_BLOCKED；RELEASE_ENGINEERING_CHANGE 进入 separate implementation/approval（任务书 §17/§18 允许）。
- Rehearsal plan executable：BR-01~30 + PV-01~17 完整无缺失；drifted fixture hard gate 满足。
- 4 条 corrections（C1-C4）不影响核心 strategy 正确性，不改变 Preferred Strategy / S10-B 设计选择，可在进入 rehearsal candidate 时明确应用。

不裁定 APPROVED：C3（S10-B release engineering 机制明确化）+ C4（BR-24~30 rehearsal 验证机制明确化）需在进入 rehearsal 前明确，属 `MUST_APPLY_BEFORE_REHEARSAL`。不裁定 CHANGES_REQUIRED：S10-B feasibility 在 design 层面已 resolved（机制清楚、可实施、如实标注 gap），非 unresolved。

## 49. Rehearsal Authorization

```text
ISOLATED_REHEARSAL_AUTHORIZED = YES（CONDITIONAL on C1-C4 applied before rehearsal entry）
```

Rehearsal entry corrections（C1-C4）必须由 Design 窗口原位返修 Design 文档后明确应用，不由 rehearsal 窗口自行猜。Rehearsal 执行属下一独立窗口。

## 50. Production Authorization Status

```text
PRODUCTION_MIGRATION_AUTHORIZED = NO
PRODUCTION_DEPLOY_AUTHORIZED   = NO
```

生产授权仍需：C1-C4 闭环 → 独立 rehearsal 执行 → 独立 rehearsal 审批 → S1-S12 全解除（含 S10-B release engineering 闭环）→ 独立生产授权窗口。

## 51. Next Stage

```text
当前: Independent Design Approval = APPROVED_WITH_CORRECTIONS（本窗口）
  ↓
Design 窗口原位返修 C1-C4（DOCUMENTATION_CORRECTION + OPERATIONAL_HARD_GATE + REHEARSAL_PLAN_GAP）
  ↓
S10-B Release Engineering Implementation（独立实施/审批窗口，MINIMAL RELEASE_ENGINEERING_CHANGE）
  ↓
Isolated Rehearsal Execution（独立窗口，BR-01~30，含 drifted fixture + S10 部署身份隔离验证）
  ↓
Independent Rehearsal Approval（独立窗口）
  ↓
Production Authorization（独立窗口，S1-S12 全解除）
  ↓
Production Baseline Catch-up Execution（独立执行窗口）
  ↓
Production Verification（PV-01~17）
  ↓
B7/B8 Closure
  ↓
Return P2（不直接上 0035）
```

不得跨级。不得借 catch-up 执行 0035 / P3a / RB-10。

---

# 55. Git Discipline

```text
本窗口唯一新增 = docs/architecture/remediation/PRODUCTION_BASELINE_CATCHUP_0028_TO_0034_DESIGN_APPROVAL.md
DO NOT COMMIT
DO NOT PUSH
```

未修改：Design candidate / business code / migrations / compose / Dockerfile / build scripts / env / frontend / 19000 / 9100。

发现 Design 需修正处（C1-C4）→ 报告 finding，由 Design 窗口返修，本审批窗口不直接改 Design 文档。

---

# 56. Production Discipline

本窗口不要求用户执行任何写操作（`alembic upgrade` / `docker tag` / `docker build` / `docker compose *` / `git checkout` / `git pull` / DB write）。缺生产事实只提 `READ-ONLY EVIDENCE REQUEST`（本窗口生产 runtime 证据承自 Design M3/M4，未独立重核）。

---

# 57. STOP

审批报告完成。

```text
CATCHUP_DESIGN = APPROVED_WITH_CORRECTIONS

REHEARSAL_ENTRY_CORRECTIONS = C1 / C2 / C3 / C4 (MUST_APPLY_BEFORE_REHEARSAL)

ISOLATED_REHEARSAL_AUTHORIZED   = YES (CONDITIONAL on C1-C4)
PRODUCTION_MIGRATION_AUTHORIZED = NO
```

立即停止。禁止自行：

```text
run rehearsal / migrate production / deploy production / build production image
tag production image / restart Merchant / upgrade 9100 / apply 0035 / enter P3a / RB-10 / commit / push
```

---

*独立设计审批窗口结束。未执行任何迁移、未改代码/迁移/compose/Dockerfile/env、未 commit、未 push、未部署、未构建镜像。仅留下本审批报告文件。*
