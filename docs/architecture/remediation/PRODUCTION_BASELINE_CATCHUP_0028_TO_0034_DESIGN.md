# PRODUCTION-BASELINE-CATCHUP-0028-TO-0034 — Technical Design / Isolated Rehearsal Design

> 窗口：`PRODUCTION-BASELINE-CATCHUP-0028-TO-0034-DESIGN`
> 窗口性质：**DESIGN ONLY** — 不执行 isolated rehearsal、不执行生产迁移、不执行生产部署、不做生产 git 操作、不构建生产镜像、不重启服务、不应用 0035、不进入 P3a、不 RB-10、不 push、不 commit。
> 前序：`PRODUCTION_SCHEMA_BASELINE_CATCHUP_0028_TO_0034_REALITY_AUDIT.md`（M1/M2 只读取证，VERIFIED）+ `P2_M04_COORDINATED_CUTOVER_READINESS.md`（CUTOVER_NOT_READY，B7=生产 schema 落后）。
> 日期：2026-08-12
> 证据层级：`CODE_VERIFIED` / `MIGRATION_VERIFIED` / `GIT_HISTORY_VERIFIED` / `CONTAINER_CONFIG_VERIFIED` / `PRODUCTION_READ_ONLY_VERIFIED`（承自前序 M2）/ `PRODUCTION_RUNTIME_VERIFIED`（M3 docker inspect + M4 image inspect，2026-08-12）/ `UNKNOWN`。本窗口独立复核了迁移链 DDL、/ready 契约、git 树内容、镜像耦合、9100 RAG 迁移链差异，未复制前序结论。
> **CORRECTION-1（2026-08-12）**：返修 Docker restart 语义（`restart: unless-stopped` 不因 unhealthy 自动 restart）、Candidate A 裁定理由（非 restart loop）、R2/R3 rollback 结论、S10 升级为 VERIFIED HARD GATE（M3）、Rollback identity 拆分（M4）。详见 §14/§14-A/§14-B/§19/§35/§38/§51/§52/§60/§62。
> **CORRECTION-2（2026-08-12，承独立 Design Approval `PRODUCTION_BASELINE_CATCHUP_0028_TO_0034_DESIGN_APPROVAL.md` Verdict=`APPROVED_WITH_CORRECTIONS`）**：本窗口为 **DESIGN CORRECTION ONLY（READ/VERIFY ONLY）**，落实审批 correction C1/C2/C4（DOCUMENTATION + REHEARSAL_PLAN_GAP）并冻结 C3（S10-B Release Engineering Implementation Contract）。C1（§54 env）、C2（§3 FC-F1 evidence path）、C4（§47 rehearsal topology + BR-24~30 CONTAINER_RUNTIME）→ APPLIED/CLOSED；C3 → CONTRACT_FROZEN / IMPLEMENTATION_PENDING。DO NOT IMPLEMENT C3；不改代码/迁移/compose/Dockerfile/env/脚本；不 commit/push。详见 §3/§47/§52/§54/§62-A/§63/§66。

---

## 1. Governance Baseline

```text
P1 COMPUTE-IDEMPOTENCY-001       = CLOSED          （不重新打开）
P1 TECHNICAL_CLOSURE              = VERIFIED         （不重新打开）
P1 CODE_CLOSURE                  = CLOSED
P1 PRODUCTION_DEPLOYMENT_BASELINE = BEHIND / PENDING BASELINE CATCH-UP

P2 TECHNICAL_REMEDIATION          = VERIFIED
P2 M04 CLAIM/LEASE                = REMEDIATED
P2 PRODUCTION_CUTOVER             = BLOCKED_BY_BASELINE_CATCHUP

B7 PRODUCTION_SCHEMA_BASELINE_BEHIND = CONFIRMED
B8 PRODUCTION_CODE_BASELINE_BEHIND  = CONFIRMED
```

本窗口只设计"如何安全追平 0028→0034"，不重开 P1 correctness，不设计 0035，不执行任何动作。

---

## 2. Current Production Identity

```text
CURRENT_PRODUCTION_CODE_COMMIT = f453f44e6a70de3eb5fa8f808cf4b6a9d72ea6c1
PRODUCTION_APP_ALEMBIC_CURRENT = 0028     （代码树 migration head）
PRODUCTION_DB_ALEMBIC          = 0028
PRODUCTION_READY_EXPECTED      = 0028     （动态从代码树推断，见 §13）
PRODUCTION_READY_ACTUAL        = 0028
PRODUCTION_READY               = PASS
```

三态一致：`code head == DB == /ready expected == /ready actual == 0028`。这是**内部一致的旧 baseline**，不是"新代码 + 旧 DB"的 drift。`GIT_HISTORY_VERIFIED`（本窗口独立复核：f453f44 message="fix: 导出脚本兼容多版本 pymilvus 迭代 API"）。

物理 schema 非严格 0028（见 §5），但三态 revision 一致。

---

## 2-A. M3 Production Runtime Evidence（2026-08-12 只读核实）

生产侧 `docker inspect` + `alembic current/heads` 只读核实（`PRODUCTION_RUNTIME_VERIFIED`）：

```text
CURRENT_9000_IMAGE_REF  = xg-ai-system-backend:latest
CURRENT_9100_IMAGE_REF  = xg-ai-system-backend:latest
CURRENT_9000_IMAGE_ID   = sha256:93094f0a02ba3a4570160ce90625cb80fdec85076046fc314f5fe407add36c68
CURRENT_9100_IMAGE_ID   = sha256:93094f0a02ba3a4570160ce90625cb80fdec85076046fc314f5fe407add36c68
9000_9100_RUNTIME_IMAGE_SHARED = VERIFIED（同一 image ID）

9000_RESTART_POLICY  = unless-stopped    9000_RESTART_COUNT = 0    9000_HEALTH = healthy
9100_RESTART_POLICY  = unless-stopped    9100_RESTART_COUNT = 0    9100_HEALTH = healthy

9000 healthcheck = CMD python /ready:9000（Interval 30s/Timeout 10s/StartPeriod 20s/Retries 3）
9100 healthcheck = CMD python /ready:9100（同上）
```

**9100 RAG 库 alembic 三态**：
```text
PRODUCTION_9100_ALEMBIC_CURRENT = 0003
PRODUCTION_9100_ALEMBIC_HEAD     = 0003
PRODUCTION_9100_BASELINE         = INTERNALLY_CONSISTENT_0003
```

9100 迁移链：`<base>→0001_empty_baseline→0002_create_rag_metadata→0003(head)`。

**M3 证据对设计的决定性影响**：
1. `9000_9100_RUNTIME_IMAGE_SHARED = VERIFIED`（同 image ID）→ S10 升级为 VERIFIED HARD GATE（§51/§52）。
2. `restart_count=0` 且当前 `healthy` → 当前无 unhealthy restart 发生；`restart=unless-stopped` 不因 unhealthy 自动 restart（§14 语义确认）。
3. 9100 baseline = 0003 内部一致 → target 9db3f58 树 9100 head=0005 → **9100 不可在未独立 catch-up 0003→0005 前 recreate 为 9db3f58 镜像**（否则 expected=0005 ≠ actual=0003 → 9100 /ready 503 + unhealthy）。

---

## 3. Target Identity

```text
TARGET_0034_CODE_COMMIT = 9db3f58
```

本窗口独立复核（`GIT_HISTORY_VERIFIED`）：

- `9db3f58` message="设计：批准M04微信任务执行所有权方案"。
- 9db3f58 是当前 HEAD `36fe68a`（"修复：闭环M04微信任务执行所有权"）的**直接父**（`git log 9db3f58..36fe68a` 仅 36fe68a 一行）。
- 9db3f58 相对 `eb9f182`（FC-F1 并发修复"修复：闭环算力余额并发丢失更新"）= **纯文档提交**（`git diff --stat eb9f182 9db3f58` 仅 9 个 .md，零 .py / 零迁移改动）。
- 血统链（旧→新）：`cab2e96`(F-1 closure) → `4a5cd15` → `ef0897e` → `04f3fc9` → `eb9f182`(FC-F1) → `1d7f1f5`(P1 技术收口,文档) → `9db3f58`(设计批准,文档) → `36fe68a`(P2 closure)。
- **9db3f58 树含**：0029/0030/0032/0033/0034 迁移 + P1 消费者（`record_usage`/`AiPreviewExecution`/`ai_preview_execution`/`_create_preview_execution` 全命中）+ F-1（cab2e96 为祖先）+ FC-F1（eb9f182 为祖先，diff 纯文档证明代码完整保留）。
- **9db3f58 树不含 0035**（`git ls-tree 9db3f58 .../versions/` 无 0035）。

> **CORRECTION-2 / C2 — FC-F1 Evidence Path（APPLIED / CLOSED）**：FC-F1 closure 代码 `_write_transaction_balance_only` 实际位于 **`apps/compute/services.py`**（9db3f58 树 `:151` def + `:734` 调用 + `:177` `.returning()`），**不在 `app/` 目录**（`git grep -l "_write_transaction_balance_only" 9db3f58 -- app/` 零命中，本窗口独立核实 `CODE_VERIFIED`）。因此本设计所有涉及 FC-F1 的 evidence/search instruction 搜索范围一律以 **`-- app/ apps/`**（或等价准确表达）为准，避免假阴性。本次 correction 仅修 `EVIDENCE_PATH_COMPLETENESS`；**FC-F1 TECHNICAL CONCLUSION = UNCHANGED**（9db3f58 树确实包含 FC-F1 完整实现），**不重新打开 FC-F1 correctness / P1 correctness**。

```text
DO NOT USE 36fe68a AS B7/B8 TARGET  （36fe68a 含 0035 + P2 wechat_task_service/local_agent_main，超出 baseline catch-up）
DO NOT USE origin/master latest      （未来可能已超过 9db3f58）
```

---

## 4. Revision Graph

本窗口逐文件读取 `revision`/`down_revision` 头（`MIGRATION_VERIFIED`）：

```text
0028  down=0027   contact_invalid_followup_tasks（建表，生产已存在）
0029  down=0028   customer_profiles TEXT→JSONB（2 列）
0030  down=0029   compute_transactions +idempotency_key +payload_evidence +UK
      ───── 0031 不存在（刻意跳号，0032 文件头注释：避免与 SQLite 0031_compute_billing 编号混淆）─────
0032  down=0030   daily_report_generations（建表）+ daily_report_jobs.current_generation_id
0033  down=0032   ai_edit_material_analysis_executions（建表）
0034  down=0033   ai_preview_executions（建表）
0035  down=0034   wechat_tasks claim/lease 4 列（P2，OUT OF B7 TARGET）
```

**Catch-up 目标链 = `0028→0029→0030→0032→0033→0034`（5 个迁移）。** 0032.down_revision="0030" 已直接核实（`0032_daily_report_generations.py:21-22`），证实 0030→0032 跳号不断链。链单线、无分叉、无 merge、单 head=`0035`。

```text
0035 = OUT OF THIS CATCH-UP
不得设计 0028→0035 一次完成。
正式顺序：0028→0034 catch-up → verify → baseline closure → return P2 → 0035 later
```

---

## 5. Physical Drift

```text
PHYSICAL_SCHEMA_STRICT_MATCH_0028 = NO
SCHEMA_DRIFT_FOUND                = YES
SCHEMA_DRIFT_SCOPE                = 0029_JSONB_TYPE_AHEAD_ONLY
```

承自前序 M2 `PRODUCTION_READ_ONLY_VERIFIED`（READ ONLY 事务 `transaction_read_only=on`）：

- `customer_profiles.confirmed_fields_json` 物理 = `jsonb`（0028 定义 TEXT，0029 定义 JSONB）→ 0029 类型变更已提前落地物理层。
- `customer_profiles.inferred_fields_json` 同上。
- 0030~0034 touched 新对象**全部 NOT EXISTS**：3 新表（`daily_report_generations`/`ai_edit_material_analysis_executions`/`ai_preview_executions`）`to_regclass` 均 `f`；3 新增列（`compute_transactions.idempotency_key`/`payload_evidence`、`daily_report_jobs.current_generation_id`）不存在；UK `uk_compute_transactions_merchant_idempotency` 不存在；3 索引/3 CHECK 不存在。
- 父表 `daily_report_jobs` EXISTS（0032 FK 前置）。
- 公共表 58 张，与 0028 预期一致（除上述两列类型 drift）。

drift 方向与 catch-up 目标一致（ahead-of-revision 且方向正确），0029 对已-jsonb 列幂等兼容（见 §29），**非阻断**。

---

## 6. Data Preconditions

承自前序 M2 `PRODUCTION_READ_ONLY_VERIFIED`，全部 PASS：

| 迁移 | 前提 | 结果 |
| ---- | ---- | ---- |
| 0029 | 存量非 NULL JSON 须合法（`ALTER USING ::jsonb`） | invalid_confirmed=0, invalid_inferred=0 → **PASS** |
| 0030 | UK `(merchant_id,idempotency_key)` 存量无重复 | 列不存在→全 NULL，NULL 不参与唯一约束 → **PASS** |
| 0032 | FK 父表 `daily_report_jobs` 存在；child 新表无 orphan | parent_exists=t；新表无行 → **PASS** |
| 0033 | 新表无存量 | NOT EXISTS → **PASS** |
| 0034 | 新表无存量 | NOT EXISTS → **PASS** |

生产规模：`customer_profiles=1`、`compute_transactions=1698`、`daily_report_jobs=0`。

---

## 7. Lock/Runtime Risk

本窗口独立复核迁移 DDL（`MIGRATION_VERIFIED`），确认全链无 `op.execute`/无 backfill/无 `SET NOT NULL on existing table`：

| 迁移 | 操作 | 锁类型 | 行数 | 风险 |
| ---- | ---- | ------ | ---- | ---- |
| 0029 | ALTER COLUMN TYPE ×2（jsonb→jsonb 幂等重写） | ACCESS EXCLUSIVE（表重写） | customer_profiles=1 | **LOW**（1 行瞬时） |
| 0030 | ADD COLUMN ×2 nullable | 元数据级（PG11+） | compute_transactions=1698 | LOW |
| 0030 | CREATE UNIQUE CONSTRAINT | 校验期 AccessExclusive 扫表 | 1698 | **LOW**（存量全 NULL 不冲突） |
| 0032 | CREATE TABLE + ADD COLUMN nullable + INDEX(新表) | 元数据级 | daily_report_jobs=0 | LOW |
| 0033 | CREATE TABLE + INDEX(新表) | 元数据级 | 新表 0 | LOW |
| 0034 | CREATE TABLE + INDEX(新表) | 元数据级 | 新表 0 | LOW |

```text
全链 LOCK/RUNTIME RISK = LOW
```

唯一非常规项 = 0029 ALTER TYPE（表重写，但 1 行瞬时）。唯一 existing-table NOT NULL ADD COL = 0035 `attempt_count`（server_default="0"，**OUT OF B7**，不在本链）。

LOW 风险**不豁免** maintenance / backup / stop condition / rollback / verification 设计（见 §16/§33/§38/§43）。

---

## 8. Candidate Strategies

本窗口对三种策略做完整技术设计与比较，不因前序建议直接宣告 Preferred。

### 8.1 Candidate A — Schema First（零停机）

```text
old code f453f44（expected=0028）继续服务
→ schema 升至 0034
→ verify old code still healthy
→ deploy 9db3f58
```

### 8.2 Candidate B — Code First

```text
deploy 9db3f58（expected=0034）
while DB still 0028
```

### 8.3 Candidate C — Coordinated Near-Simultaneous（维护窗口）

```text
maintenance → stop traffic → deploy migration-capable target artifact
→ migrate → start target application
```

---

## 9. Preferred Strategy

```text
PREFERRED_STRATEGY = SCHEMA_FIRST_WITH_MAINTENANCE_WINDOW
（= Candidate C 的 schema-first 迁移顺序变体）
```

**不是纯零停机 schema-first（Candidate A 原版）**，也非 code-first。理由见 §10-§12、§13-§15。迁移**顺序**仍是 schema-first（先迁移 DB 到 0034，再部署新代码），但**执行方式**是维护窗口内停机切换，以规避 Readiness Contract 问题。

冻结条件核对（§9）：

```text
old f453f44 + schema0034 = STATICALLY COMPATIBLE          ✓（§11，代码不碰新表新列）
target 9db3f58 + schema0034 = COMPATIBLE                  ✓（§12）
target 9db3f58 + schema0028 = NOT REQUIRED / MUST NOT RUN ✓（§12，缺对象→SQL 错误）
0029 drift behavior = supported                            ✓（§29，对已-jsonb 列幂等）
all intermediate migrations = safe                         ✓（§7，全 LOW）
```

**但**：old f453f44 + schema0034 = `APPLICATION_RUNTIME_COMPATIBLE` **AND** `READINESS_CONTRACT_INCOMPATIBLE`（§13）。因此纯零停机 schema-first **不优先**（§14/§15），优先维护窗口（§16）。

> **CORRECTION-1（2026-08-12）**：早期版本曾写"旧 app /ready 503 → docker `restart: unless-stopped` → restart loop → 纯零停机不可行"。该推导**错误**：Docker `restart: unless-stopped` 只对 container **exit/stop** 生效，不等同于 unhealthy → 自动 restart。healthcheck failure 仅使容器 health status = `unhealthy`，标准 restart-policy 不会因 unhealthy 自动重启容器（除非存在外部 autoheal/watchdog/systemd）。本设计已据 Docker 官方语义返修，见 §14。

---

## 10. Schema-First Rationale

迁移**顺序**采用 schema-first（先 schema 后 code）的依据：

1. target 9db3f58 代码不能在 0028 schema 运行（§12：消费者写 `idempotency_key`(0030)、`daily_report_generations`(0032表)、`ai_edit_material_analysis_executions`(0033表)、`ai_preview_executions`(0034表，含 F-1)；缺对象→INSERT/SELECT 报错）→ **不可 code-first**。
2. f453f44 旧代码对 0029~0034 全链前向兼容（§11）→ 旧代码可容忍 additive schema，理论上可先迁移。
3. 所有中间态对旧代码静态安全（`INTERMEDIATE_STATE_SAFE`，§21）。

但"可先迁移"≠"可零停机迁移"。见 §13 Readiness Contract。

---

## 11. Old Code Compatibility

本窗口独立核实 f453f44 代码树（`CODE_VERIFIED`）：

| App Code | Schema | 静态兼容? | 证据 |
| -------- | ------ | ---------- | ---- |
| f453f44 | 0028 | YES（current） | 三态一致 /ready PASS |
| f453f44 | 0029 | YES | ORM 已 `_JSONStringJSONB`（`app/models.py:15,1779`）；0029 仅修物理列对齐 |
| f453f44 | 0030 | YES | `git grep "idempotency_key" f453f44 -- app/models.py` 仅命中 `return_visit_runs`（0011 既有），**compute_transactions 无 idempotency_key**；0030 全 additive nullable |
| f453f44 | 0032 | YES | `git grep "AiPreviewExecution\|DailyReportGeneration\|AiEditMaterialAnalysisExecution\|daily_report_generations\|ai_preview_executions\|ai_edit_material_analysis_executions" f453f44 -- app/` **零命中**；新表+nullable 列 |
| f453f44 | 0033 | YES | 新表 additive，零引用 |
| f453f44 | 0034 | YES | 新表 additive，零引用 |

**结论：f453f44 旧代码对 0029~0034 全链前向兼容（业务运行时层面）。**

```text
INTERMEDIATE_STATE_SAFE (business runtime) = YES
```

---

## 12. Target Code Compatibility

本窗口独立核实 9db3f58 代码树（`CODE_VERIFIED`）：

| App Code | Schema | 兼容? | 证据 |
| -------- | ------ | ----- | ---- |
| 9db3f58 | 0028 | **NO** | 消费者写 idempotency_key(0030列)、daily_report_generations(0032表)、ai_edit_material_analysis_executions(0033表)、ai_preview_executions(0034表,含 F-1 `_create_preview_execution`)；缺对象→INSERT/SELECT 报错；F-1 fail-closed 降级但其余 identity 创建会错 |
| 9db3f58 | 0034 | YES | schema 与代码匹配 |

```text
target 9db3f58 代码必须 schema 到位后方可启用。
中间态对 target 代码均不安全。
```

---

## 13. Readiness Contract（★核心设计点）

本窗口独立核实 `/ready` 实现（`CODE_VERIFIED` + `CONTAINER_CONFIG_VERIFIED`）：

**实现位置**：`app/routers/health.py` + `app/db_readiness.py`。

**expected revision 推断方式**（`app/db_readiness.py:45-61`）：
```python
def load_alembic_heads(alembic_ini_path):
    cfg = AlembicConfig(key)
    script = ScriptDirectory.from_config(cfg)
    _alembic_head_cache[key] = sorted(script.get_heads())
```
**expected = `ScriptDirectory.get_heads()`**，从代码树 migration 目录动态扫描，**非硬编码**。文件头注释（`db_readiness.py:13-15`）："不硬编码 revision id——升级 migration 时 readiness 自动跟上。"

**关键事实**：`health.py` 与 `db_readiness.py` 在 f453f44 与 HEAD（36fe68a）之间**完全相同**（`git diff` IDENTICAL）。expected 完全随代码树迁移文件变化：

| 代码树 | `postgres/auto_wechat/versions` 最后迁移 | expected head |
|--------|------------------------------------------|---------------|
| f453f44 | 0028 | **0028** |
| 9db3f58 | 0034 | **0034** |
| 36fe68a | 0035 | **0035** |

**失败行为**（`db_readiness.py:216-223` + `health.py:85-88`）：
- `actual_revs != expected_heads` → `error_code=ALEMBIC_REVISION_MISMATCH` → `JSONResponse(status_code=503)`。

**schema-first 中间态分析**：

```text
旧 f453f44 容器（expected=0028）运行 + DB 升至 0034
  → actual=[0034] != expected=[0028]
  → /ready 返回 503 ALEMBIC_REVISION_MISMATCH
  → 但 /health（liveness，不查 DB）仍 200，进程能起，业务代码前向兼容
```

**必须区分（§22 命中）**：

```text
APPLICATION_RUNTIME_COMPATIBLE     = YES   （业务代码不碰新表新列，/health 200，DB connect OK）
READINESS_CONTRACT_INCOMPATIBLE     = YES   （/ready 503，expected 0028 != actual 0034）
```

**不得**把"`/ready` fails because expected revision 0028"简单解释成"旧代码不能跑 0034"。业务运行时与 readiness gate 是两个独立维度。但 readiness 不兼容的**运营后果**见 §14——它足以阻止零停机 schema-first。

---

## 14. Docker Healthcheck Behavior（★核心运营风险）

本窗口独立核实 `docker-compose.yml`（`CONTAINER_CONFIG_VERIFIED`）：

**auto-wechat-api（9000）**（`docker-compose.yml:28-59`）：
- `image: xg-ai-system-backend:latest`，`build.dockerfile: Dockerfile.backend.dev`
- healthcheck（`:51-59`）：
  - `test: ["CMD","python","-c","import urllib.request; urllib.request.urlopen('http://127.0.0.1:9000/ready', timeout=5)"]`
  - `interval: 30s` / `timeout: 10s` / `retries: 3` / `start_period: 20s`
  - **探测 `/ready`（非 /health）**，注释明确"alembic 不匹配 → unhealthy"
- `restart: unless-stopped`（`:50`）

**schema-first 中间态事实态（按 Docker 官方语义返修）**：

```text
旧 f453f44 容器 + DB 0034
  → /ready 503（连续 3 次失败后）
  → 容器 health status = unhealthy
  → /health（liveness，不查 DB）仍 200，进程持续运行，业务代码前向兼容
```

**关键语义纠正（CORRECTION-1）**：

```text
DOCKER_HEALTH_STATE              = UNHEALTHY
AUTO_RESTART_ON_UNHEALTHY        = NOT_PROVEN
```

依据：Docker `restart: unless-stopped` 是**容器退出/停止**时的重启策略，**不**等同于 unhealthy → 自动 restart。healthcheck failure 只使容器 health status 变为 `unhealthy`；标准 Docker restart-policy **不会**因 unhealthy 自动重启容器。除非生产存在额外 external mechanism（autoheal / watchtower / systemd health restart / 宝塔自动恢复 / external supervisor），否则不存在"unhealthy restart loop"。

本窗口只读核实仓库内 docker-compose（`Grep autoheal|watchtower|supervisor|systemd|ofelia` = 无命中）：仓库**无** autoheal/watchtower/supervisor 等 external restart mechanism。

```text
REPO_INTERNAL_AUTOHEAL_MECHANISM = NONE
PRODUCTION_EXTERNAL_AUTOHEAL     = UNKNOWN（REQUIRES_PRODUCTION_VERIFICATION）
```

生产宝塔侧是否配置"容器 unhealthy 自动重启"（宝塔 Docker 管理器或宿主 systemd watchdog）无法从仓库核实 → `PRODUCTION_EXTERNAL_AUTOHEAL = UNKNOWN`。不得在未证实前写 `DOCKER_UNHEALTHY_RESTART_LOOP = VERIFIED`。

**因此 Candidate A 的真实风险不是"restart loop"，而是**：
- `/ready` 503 暴露给生产流量与监控（§15 反代 upstream / 监控告警可能摘除节点或告警风暴）。
- `unhealthy` 容器在标准 Docker 下继续运行旧进程，业务**可能**仍能服务（application runtime compatible），但 readiness 不健康状态在生产 routing/monitoring 下的行为**未核实**（§15 `REQUIRES_PRODUCTION_VERIFICATION`）。

healthcheck 直连容器内 `127.0.0.1:9000/ready`，**不经反代**（与反代配置无关）。

**结论**：纯零停机 schema-first（Candidate A）因 `TEMPORARY_READINESS_INCOMPATIBILITY` + `UNVERIFIED_PRODUCTION_HEALTH_ROUTING/SUPERVISION` 裁定为 `NOT_PREFERRED`（而非因 restart loop REJECTED），见 §14-A。

---

## 14-A. Candidate A 重新评估（CORRECTION-1）

不得因早期错误的 restart-loop 推导直接 REJECT Candidate A。重新评估：

| 维度 | 评估 |
| ---- | ---- |
| application runtime | COMPATIBLE（§11，旧代码不碰新表新列，业务请求不报错） |
| /readiness | INCOMPATIBLE（§13，expected=0028 ≠ actual=0034 → 503） |
| Docker health state | unhealthy（连续 healthcheck 失败后） |
| container auto-restart on unhealthy | NOT_PROVEN（标准 restart-policy 不触发；仓库无 autoheal；生产外部机制 UNKNOWN） |
| reverse proxy behavior | UNKNOWN（仓库无反代配置；宝塔是否按 /ready 摘除节点未核实，§15） |
| external supervision | UNKNOWN（宝塔/systemd 自动恢复未核实） |
| operator behavior | 依赖人（可能因 unhealthy 报警介入） |
| deployment tooling | 标准docker compose（无编排层自动 heal） |

**裁定**：

```text
OLD_APP_NEW_SCHEMA_APPLICATION_RUNTIME = COMPATIBLE
OLD_APP_NEW_SCHEMA_READINESS_CONTRACT  = INCOMPATIBLE
DOCKER_HEALTH_STATE                   = UNHEALTHY
AUTO_RESTART_ON_UNHEALTHY              = NOT_PROVEN
（仓库无 autoheal；生产外部机制 UNKNOWN → 不得写 VERIFIED restart loop）

Candidate A = NOT_PREFERRED
理由 = TEMPORARY_READINESS_INCOMPATIBILITY
      + UNVERIFIED_PRODUCTION_HEALTH_ROUTING/SUPERVISION
（不再写 Docker restart loop）
```

Candidate A 在 application runtime 层**技术可行**（旧代码能跑、业务不中断），但其 `/ready` 503 + unhealthy 状态暴露给生产流量/监控，且反代摘除/外部自动恢复/告警行为未核实——不足以作为 Preferred。若生产侧证实无 external autoheal 且反代不按 /ready 摘除、监控容忍 temporary 503，则 Candidate A 可重新评估；当前证据不足。

Candidate C（维护窗口）仍是 Preferred，其核心价值见 §14-B。

---

## 15. Reverse Proxy Impact

仓库内**无反代配置**（搜索 `nginx*.conf` 无结果；yml 无 nginx/proxy_pass/upstream）。生产反代由宝塔面板管理，不在仓库内（参考 `docs/ai/05_acceptance/P3-E-9100-PRODUCTION-CUTOVER-BAOTA-RUNBOOK.md`）。

- docker healthcheck 走容器内 `127.0.0.1/ready`，**不经反代**，反代不影响容器 health 状态。
- **但**：若生产宝塔/nginx 配置了基于 `/ready`（或 `/api/ready`）的 upstream 健康检查，503 会导致节点被摘除或触发告警。这部分属生产侧配置，`REQUIRES_PRODUCTION_VERIFICATION`。
- 本设计不依赖反代行为来保障安全；维护窗口内 9000 停机，反代返回 503/维护页即可。

---

## 14-B. Candidate C 重新证明优势（CORRECTION-1）

Candidate C（SCHEMA_FIRST_WITH_MAINTENANCE_WINDOW）保持 Preferred，但其核心价值**重新表述**为：

```text
旧9000明确停止 → DB 0028→0034 → deploy 9db3f58 → new9000 startup → expected=0034=actual=0034 → /ready 200
```

核心价值 = **避免临时 readiness mismatch 暴露给生产流量/监控**（而非"避免 Docker restart loop"）。

具体优势：
1. 迁移期间旧 9000 已停 → 无 `/ready 503` 暴露给反代 upstream / 监控告警 / 运维。
2. 新 9000 启动时 schema 已就绪 → expected=actual=0034 → `/ready 200`，无中间态 unhealthy 窗口。
3. 不依赖"标准 Docker 不因 unhealthy 自动 restart"这一未证实假设——维护窗口直接消除 readiness 不一致窗口，无论生产是否有 external autoheal 都安全。
4. 不要求生产侧先核实反代 health routing / external supervision 行为即可安全执行（Candidate A 需先核实这些）。

Candidate C 的代价 = 维护窗口停机（§16/§39）。鉴于 0029/0030 锁风险 LOW（1/1698 行）、可夜间低峰执行，停机代价可接受。

---

## 16. Maintenance Model

由于 Candidate A（零停机 schema-first）的 readiness 503 + unhealthy 状态暴露给生产流量/监控且 routing/supervision 行为未核实（§14-A），采用**维护窗口内 schema-first 停机切换**：

```text
PREFERRED_MAINTENANCE_MODEL = CONTROLLED_DOWNTIME
```

维护窗口需要控制（§38）：
- business write control（业务写入暂停）
- operator presence（运维在场）
- backup ready（备份就绪）
- rollback artifacts ready（回滚制品就绪）
- monitoring（监控在场）

**不得**为绕过 ready 契约而现场改 docker-compose healthcheck / restart 策略 / 生产代码（§24，§64 禁止改 docker compose）。维护窗口是消除 readiness mismatch 窗口的合规手段。

维护窗口内序列见 §25（Deployment Sequence）。本窗口不给时间估计（§38）。

---

## 17. Write Traffic

`0028→0034` 迁移期间生产是否允许正常写流量？

**结论：不允许。** 维护窗口内 9000 停机，无写流量到达 DB。逐表分析：

| 表 | 迁移 | 写风险 | 处置 |
| ---- | ---- | ------ | ---- |
| customer_profiles | 0029 ALTER TYPE ×2 | ACCESS EXCLUSIVE 表重写锁，期间写阻塞 | 维护窗口内无写流量（9000 停机） |
| compute_transactions | 0030 ADD COL + UK | ADD COL 元数据级；UK 扫描期 AccessExclusive | 维护窗口内无写流量 |
| daily_report_jobs | 0032 ADD COL nullable | 元数据级即时 | 维护窗口内无写流量 |

9000 是 customer_profiles / compute_transactions / daily_report_jobs 的唯一写入口（9000 不直连微信、9100 写 xg_douyin_ai_cs 库）。9000 停机 → 无写流量到达 auto_wechat 库。0029/0030 的 AccessExclusive 锁在无并发写时安全。

---

## 18. Compute Concurrent Writes

`compute_transactions` 生产有 1698 行，9000 运行时可能持续新增（算力扣费）。0030 新增 unique/idempotency 字段。

**设计**：
- 维护窗口内 9000 停机 → 无新 compute write 到达。
- 0030 `CREATE UNIQUE CONSTRAINT` 扫描 1698 存量行：`idempotency_key` 对所有存量行恒为 NULL（列刚加），SQL 标准 NULL 不参与唯一约束 → 不冲突。
- 无并发写 → 无锁竞争。
- 不得仅因 1698 行小而认为无并发写风险；正确保障是"维护窗口内 9000 停机消除并发写"。

```text
COMPUTE_CONCURRENT_WRITE_DURING_MIGRATION = NONE (9000 stopped in maintenance window)
```

---

## 19. Target Source Identity / Rollback Identity

生产发布必须准确证明 `SOURCE_COMMIT = 9db3f58`。生产当前 `xg-ai-system-backend:latest`（movable tag）不能继续作为 release identity（§28-§29）。

**M3+M4 生产镜像 identity（`PRODUCTION_RUNTIME_VERIFIED`）**：
```text
CURRENT_RUNTIME_IMAGE_ID          = sha256:93094f0a02ba3a4570160ce90625cb80fdec85076046fc314f5fe407add36c68
CURRENT_RUNTIME_IMAGE_CREATED     = 2026-08-06T18:17:27+08:00
CURRENT_RUNTIME_IMAGE_REPOTAGS    = ["xg-ai-system-backend:latest"]
CURRENT_RUNTIME_IMAGE_REPODIGESTS= ["xg-ai-system-backend@sha256:93094f0a02ba3a4570160ce90625cb80fdec85076046fc314f5fe407add36c68"]
IMAGE_LABELS                      = com.docker.compose.project/service/version（无 source commit provenance label）
  不存在 org.opencontainers.image.revision / git.commit / GIT_COMMIT
```

**Rollback Identity 重新分类（C8/M4）**：
```text
ROLLBACK_RUNTIME_IMAGE_IDENTITY      = VERIFIED（image ID = 93094f0...，M3+M4 实测）
ROLLBACK_SOURCE_COMMIT_PROVENANCE    = UNVERIFIED（image 无 provenance label）
IMAGE_BUILD_PROVENANCE_DEBT           = NON_BLOCKING FOR THIS CATCH-UP
  （前提：runtime rollback image 被可靠保存为 immutable identity）
```

**不得声称** `sha256:93094f0... = f453f44`。宿主 Git HEAD=f453f44（§2，`GIT_HISTORY_VERIFIED`）与 runtime image identity（M3/M4）是**两条独立证据**，分别保存，不互相背书。当前运行镜像构建于 2026-08-06，与宿主 git HEAD f453f44 的一致性**未经 provenance 证实**（image 无 commit label）。

```text
ROLLBACK_ARTIFACT_IDENTITY_GAP（笼统）= 已拆分：
  ROLLBACK_RUNTIME_IMAGE_IDENTITY      = VERIFIED
  ROLLBACK_SOURCE_COMMIT_PROVENANCE    = UNVERIFIED (NON_BLOCKING if runtime image preserved)
```

未来生产执行前 Hard Gate（§38）：
1. **preserve current runtime image** `sha256:93094f0...` 为 immutable rollback identity（`docker tag` 固化，但本窗口不执行 docker tag）。
2. verify rollback image 在本机/仓库 registry 仍可用。
3. target 9000 image 必须用**独立 immutable identity**（如 `:9db3f58-<ts>`），不复用共享 mutable `:latest`。
4. 不得覆盖/独赖共享 mutable `:latest`。
5. 9100 在 B7/B8 catch-up 期间 pin/frozen 至当前 runtime image（§52 S10-B）。

未来 target image 从 9db3f58 构建时应增加 `org.opencontainers.image.revision=9db3f58` 等可追踪 build metadata；但不在本设计范围顺手修改业务代码/构建脚本（§64）。

未来生产执行前必须存在（§32）：
```text
CURRENT_PROD_IMAGE_ID       = 93094f0...（VERIFIED，M3）
TARGET_BACKEND_IMAGE        = 9db3f58 构建（待构建，immutable tag）
TARGET_IMAGE_ID             = 待构建
TARGET_IMAGE_DIGEST         = 待构建
SOURCE_COMMIT               = 9db3f58
BUILD_TIMESTAMP             = 待构建（若可获取）
```

---

## 20. Migration Artifact Identity

运行 Alembic 的容器/镜像必须包含 target 0034 迁移集。

```text
MIGRATION_ARTIFACT_SOURCE_COMMIT = 9db3f58
```

核实（`GIT_HISTORY_VERIFIED`）：9db3f58 树 `migrations/postgres/auto_wechat/versions/` 含 0029/0030/0032/0033/0034，**不含 0035**。9db3f58 树 alembic head = 0034。

**禁止用 36fe68a 迁移制品**（§31）：其 alembic head = 0035，即使命令指定 `upgrade 0034` 技术上可执行，仍优先 9db3f58 制品以减少 operator error（误 `upgrade head` 应用 0035）风险。

生产执行前必须验证迁移制品 `alembic heads = 0034`（§43 preflight）。

---

## 21. Intermediate Schema State

为 0029/0030/0032/0033/0034 分别评估 `OLD_PRODUCTION_CODE_COMPATIBILITY`（f453f44 × schema）：

| App Code | Schema | 业务运行时兼容? | /ready 契约 | Evidence |
| -------- | ------ | --------------- | ----------- | -------- |
| f453f44 | 0029 | YES | expected=0028 != actual=0029 → 503 | 0029 升级后 DB=0029，但 f453f44 代码树 head=0028 → mismatch |
| f453f44 | 0030 | YES | 503 | 同上，expected 0028 != actual 0030 |
| f453f44 | 0032 | YES | 503 | expected 0028 != actual 0032 |
| f453f44 | 0033 | YES | 503 | expected 0028 != actual 0033 |
| f453f44 | 0034 | YES | 503 | expected 0028 != actual 0034 |

**关键结论**：业务运行时全链前向兼容（`INTERMEDIATE_STATE_SAFE` business），但**每个中间 revision 的 /ready 都 503 → 容器 unhealthy**（因为 f453f44 代码树 head 恒=0028，DB 一旦离开 0028 即 mismatch）。

**CORRECTION-1**：早期版本写"中间态触发 docker restart 循环 → 排除旧代码继续服务"。该表述**错误**。按 Docker 官方语义（§14），unhealthy **不**自动触发 restart（除非 external autoheal，仓库无、生产未证实）。正确表述：中间态旧代码 application runtime 仍可运行（COMPATIBLE），但 `/ready 503 + unhealthy` 会暴露给生产 routing/monitoring；由于反代摘除/外部自动恢复/告警行为未核实（§15/§14-A），**不优先**让旧代码在中间 revision 继续承载正常生产流量。生产中间态优先 9000 停机（维护窗口），但这不等于"旧代码技术不可运行"。

**Rehearsal 中间态 smoke（YAGNI 判断）**：
- 静态证据已充分证明业务运行时兼容（§11），不要求每一步都重启整套应用做 smoke。
- **但最终 `f453f44 + 0034` 必须 runtime verify**（BR-15/BR-16）：在隔离 rehearsal 中验证旧 app 在 schema0034 上业务 smoke 通过 + /ready 行为符合预期（503 + unhealthy，进程不崩，区分 application runtime compatible vs readiness contract incompatible）。

---

## 22. Old Code + New Schema Hard Gate（★Rehearsal 核心场景）

这是 schema-first 能否成立的核心验证。Rehearsal 必须包含：

```text
REHEARSAL-OLD-APP-NEW-SCHEMA
  source code = f453f44
  DB schema   = 0034
```

至少验证（BR-15/BR-16）：
- application starts（进程能起）
- /ready appropriate behavior（预期 503 ALEMBIC_REVISION_MISMATCH，非崩溃）
- /health 200（liveness OK）
- core DB connect（SELECT 1 OK）
- critical table access（douyin_leads/sales_staff 可读）
- existing active production flows smoke（业务请求不因新表新列报错）

**必须区分**（任务书 §22 命中）：

```text
APPLICATION_RUNTIME_COMPATIBLE     = 验证目标（业务能跑）
READINESS_CONTRACT_INCOMPATIBLE     = 预期事实（/ready 503，不等于业务不能跑）
```

若 rehearsal 发现业务运行时**不**兼容（业务请求报错），则 R2/R3 的 schema-forward fallback 不可行（§35-§37），策略需重新评估。**注意**：readiness 503 + unhealthy **不**计入"业务运行时不兼容"（那是预期事实，非业务报错）。

---

## 23. Readiness Contract Problem（审查结论）

已审查 f453f44 `/ready` expected revision = 0028（动态从代码树推断，§13）。

schema-first 后 DB=0034：旧 app `/ready` = **FAIL（503）**，即使业务代码前向兼容。

**审查结论**：
- 这是 readiness gate（动态 head 推断）的预期行为，非 bug。f453f44 与 HEAD 的 health.py/db_readiness.py 完全相同，说明这是设计意图（"升级 migration 时 readiness 自动跟上"）。
- 旧代码的 expected 锁定在其镜像内迁移文件（0001..0028），无法在不动镜像的情况下变为 0034。

**处置**：维护窗口内 9000 停机（§16），旧 app 在 DB 升级期间不运行，不探测 /ready，避免 temporary readiness mismatch 暴露给生产流量/监控。不现场改生产代码 / healthcheck / restart 策略（§24/§64）。

> **CORRECTION-1**：早期"规避 restart 循环"措辞不准确。标准 Docker 不因 unhealthy 自动 restart；维护窗口真正规避的是"503/unhealthy 暴露给反代 upstream 与监控告警"，以及"新代码启动前 schema 已就绪"。

---

## 24. Readiness Contract 影响 Schema-First 的处置

Readiness Contract 使**纯零停机** schema-first **不优先**（§14-A：temporary readiness incompatibility + 未核实的生产 health routing/supervision）。

按任务书 §24 处置：
- **不**现场改生产代码（health.py/db_readiness.py）。
- **不**现场改 docker-compose healthcheck/restart。
- **重新比较 Candidate C**（coordinated cutover）→ 已采纳为 PREFERRED（§9/§14-B）。
- **temporary maintenance mode** → 已设计（§16）：维护窗口内停旧 9000 → 迁移 → 部署新 9000 → 启动。

任何新业务代码 / healthcheck 改动 → `SEPARATE DESIGN REQUIRED`，本窗口不顺手实施。

---

## 25. Deployment Sequence（runbook 候选，DESIGN ONLY）

```text
 1. announce maintenance（通告维护窗口，operator 停止业务操作）
 2. pause business write traffic（反代 503 或停服，9000 不再接收写入）
 3. backup DB checkpoint（§33，全量备份 + alembic_version 记录）
 3b. preserve current runtime image sha256:93094f0... 为 immutable rollback identity（docker tag 固化，§38；生产执行窗口操作，非本窗口）
 4. stop old 9000 container（docker compose stop auto-wechat-api，仅 9000，不触及 9100）
    → 旧 9000 不再运行，避免 temporary /ready 503 + unhealthy 暴露给生产流量/监控；9100 保持 frozen（S10-B）
 5. verify migration artifact head=0034（9db3f58 制品，§20/§43）
 6. apply migration set: alembic upgrade 0034（显式 target，§42）
    → DB 0028→0029→0030→0032→0033→0034
    → 0029 幂等处理已-jsonb 列；0030 ADD COL+UK；0032/0033/0034 建表
 7. verify DB current=0034（alembic current + schema 对象，§48 PV-03/PV-08~11）
 8. build/deploy target 9000 image 9db3f58（immutable tag，S10-B：仅 9000，9100 不 recreate，§51/§52）
 9. start new 9000（expected=0034 = actual 0034 → /ready 200）
10. health/readiness check（/ready HTTP 200 + expected=actual=0034）
11. P1 production baseline verification（§36，静态 + safe smoke，不真实扣费）
12. resume business traffic（撤反代 503）
13. post-catchup monitoring（日志无 migration/runtime 错误）
14. catch-up closure → return P2（不直接上 0035）
```

**关键顺序约束**：
- step 4（停旧 9000）必须在 step 6（迁移）之前 → 避免 temporary /ready 503 + unhealthy 暴露给生产流量/监控（非 restart 循环，§14）。
- step 6（迁移）必须在 step 9（启动新 9000）之前 → target 代码需 schema 就绪才能运行（§12）。
- step 6 的迁移制品必须是 9db3f58（head=0034），不是 36fe68a（head=0035，§31）。
- 不得 `git pull`（§56/§57）；target = exact commit/image。

---

## 26. P1 Production Verification Matrix

Catch-up 到 0034 后，P1 production deployment **不**自动 VERIFIED。必须设计 `P1_PRODUCTION_BASELINE_VERIFICATION`，只验证"已闭环的 P1 能力是否真正部署到生产 baseline"，不重测全部 P1 correctness。

至少确认（`PV-13`，§48）：
```text
schema objects exist:
  compute_transactions.idempotency_key/payload_evidence + UK（0030）
  daily_report_generations + current_generation_id（0032）
  ai_edit_material_analysis_executions（0033）
  ai_preview_executions（0034）
target code includes P1 consumers:
  record_usage（M07 Core）
  DailyReport generation consumer
  M05 material_analysis consumer
  M01 Preview consumer + F-1 _create_preview_execution
  FC-F1 atomic balance update code（_write_transaction_balance_only / UPDATE...RETURNING；位于 apps/compute/services.py，搜索范围 -- app/ apps/，§3 CORRECTION-2/C2）
active charge paths source identity implementation present
```

优先 static deployed artifact verification + safe API/database smoke。

---

## 27. 不得真实扣算力做 Smoke

Catch-up verification 不为证明 compute 工作而真实生成账单 / 真实消耗用户 token。

可用手段：
- static code identity（grep 部署镜像内 record_usage/idempotency_key 写入点）
- isolated test（rehearsal 环境）
- read-only production schema（SELECT 对象存在性）
- safe internal/no-side-effect endpoint（/ready、/health、alembic current）

```text
NO_REAL_CHARGE_FOR_SMOKE = ENFORCED
```

---

## 28. Source Identity（镜像 identity 设计）

生产发布必须从 `f453f44` 部署到 `9db3f58`，但本窗口不执行（§56）。

**Git deployment strategy 比较**：

| 方式 | 可追踪 | 可回滚 | 风险 | 选择 |
| ---- | ------ | ------ | ---- | ---- |
| `git fetch + exact checkout 9db3f58` | YES | YES | 需生产侧 git 操作 | 备选 |
| artifact/image deployment（rebuild 镜像，tag=9db3f58） | YES | YES | 需构建 + 镜像 identity 记录 | **首选** |
| `git pull` | NO（origin/master 未来可能超过 9db3f58） | 弱 | target 不可控 | **禁止** |

```text
PRODUCTION_TARGET != origin/master latest
PRODUCTION_TARGET = exact commit 9db3f58 / exact image（tag 或 digest）
```

生产 `xg-ai-system-backend:latest` 不得继续作为 release identity（§19）。未来构建应使用明确 tag（如 `xg-ai-system-backend:9db3f58-<buildts>`），并记录 image_id/digest。但改 docker-compose.yml 的 image 字段超出本窗口（§64），生产执行窗口决定 tag 策略。

---

## 29. 0029 Drift Rehearsal（0029 对已-jsonb 列幂等）

生产物理 schema 两 JSON 列已 jsonb（§5），但 alembic_version=0028。Rehearsal **必须**构造此 drift 镜像（§10/§25 fixture），验证 0029 真实生产行为。

**0029 幂等分析**（`MIGRATION_VERIFIED`，`0029_customer_profiles_jsonb_unify.py:33-44`）：
- `op.alter_column(type_=JSONB(none_as_null=True), postgresql_using="confirmed_fields_json::text::jsonb")`
- alembic 不比较列现有类型，直接发 `ALTER TABLE ... ALTER COLUMN ... TYPE jsonb USING col::text::jsonb`。
- 列已是 jsonb 时：PG 逐行执行 `jsonb::text::jsonb`，任何合法 jsonb 值转换均合法，NULL 保持 NULL → 不报错、幂等、语义安全。
- 唯一代价：表重写（ACCESS EXCLUSIVE），但 customer_profiles=1 行 → 瞬时。
- `alter_column` 未传 `nullable=`，nullable 保持 0026 建表原值，无 `SET NOT NULL` 风险。

```text
0029_EXISTING_JSONB_COMPATIBILITY = PASS
禁止只用纯净 fresh 0028（TEXT 列）rehearsal —— 无法覆盖 0029 真实生产行为
```

---

## 30. 0030 Rehearsal

`compute_transactions` synthetic rows 覆盖（BR-06/BR-07）：
- multiple merchants
- different transaction_type
- different source
- nullable optional fields
- pre-0030 无 `idempotency_key`/`payload_evidence`

迁移后验证：
- `idempotency_key`/`payload_evidence` 新增 nullable
- `uk_compute_transactions_merchant_idempotency (merchant_id, idempotency_key)` 真实存在
- 存量 1698 synthetic rows preserved
- 新 nullable columns 对存量 = NULL
- 不制造 false conflict（存量全 NULL，NULL 不参与唯一约束）

---

## 31. 0032 Rehearsal

验证（BR-08/BR-09）：
- `daily_report_generations` 表：`id`(PK) / `job_id`(NOT NULL) / `lifecycle_status`(NOT NULL, server_default='pending') / `created_at`(NOT NULL, server_default=now())
- FK `daily_report_generations.job_id → daily_report_jobs.id`
- CHECK `ck_daily_report_generations_status lifecycle_status IN ('pending','running','succeeded','failed')`（4 态）
- INDEX `idx_daily_report_generations_job (job_id)`
- `daily_report_jobs.current_generation_id` nullable
- 按迁移真实定义验证（`0032_daily_report_generations.py:30-59`），不从历史描述猜字段

---

## 32. 0033 Rehearsal

验证（BR-10/BR-11）：
- `ai_edit_material_analysis_executions` 表：`id`(PK) / `material_id`(String64,NOT NULL) / `source_sha256`(String64,NOT NULL) / `lifecycle_status`(NOT NULL,server_default='running') / `created_at`(NOT NULL,now()) / `completed_at`(nullable)
- CHECK `ck_ai_edit_material_analysis_executions_status lifecycle_status IN ('running','completed','failed')`（3 态）
- INDEX `idx_ai_edit_material_analysis_executions_material (material_id)`
- 无 FK（独立持久实体）

---

## 33. Backup / DB Checkpoint Design

生产执行前必须存在 `DATABASE_BACKUP_CHECKPOINT`（§33）：

```text
backup method        = pg_dump（逻辑）或 PG 基础备份（物理），生产侧决定
backup identity      = 备份文件 hash / 路径
timestamp            = 备份时刻
database name        = auto_wechat
restore procedure    = pg_restore / 恢复到独立验证库验证
restore verification = 在隔离环境 restore + alembic current=0028 + 行数核对
operator             = 执行运维
```

不得只写"升级前备份数据库"。

**Backup ≠ Rollback**（§34）：DB backup 是 catastrophic recovery，正常 rollback **不**默认依赖 full database restore。

---

## 34. Backup ≠ Rollback

```text
DB backup  = catastrophic recovery（灾难恢复，全量还原）
正常 rollback = 优先 schema-forward + code rollback（§35-§37）
```

---

## 35. Rollback Strategy Layers

三级回滚：

### R1 — Abort Before Migration

```text
schema still 0028
old app still f453f44（未停或已停未迁移）
```
直接取消，无副作用。

### R2 — Schema 到 0034，Target Code 未部署

优先评估 `KEEP_SCHEMA_FORWARD + continue old code temporarily`：
- `old app + schema0034` **业务运行时兼容**（BR-15 验证 APPLICATION_RUNTIME_COMPATIBLE=YES，§11），进程能跑、业务请求不报错。
- **但** `/ready 503 + unhealthy`（§13/§14）：readiness 契约不兼容。
- **CORRECTION-1**：早期版本写"R2 旧代码继续服务不可行，因 /ready 503 触发 docker restart 循环"。该表述**错误**。标准 Docker 不因 unhealthy 自动 restart（§14）。正确分析：
  - `schema-forward + old code` 作为 **MAINTENANCE-MODE FALLBACK** 是技术可行的（旧代码能跑、不碰新表新列）。
  - 但 `/ready 503 + unhealthy` 暴露给正常生产流量/监控：反代可能摘除节点、监控告警、运维可能误判介入。**NORMAL_PRODUCTION_SERVICE** 仍不得自动宣告安全。
- R2 处置优先级：
  1. **首选** `KEEP_SCHEMA_FORWARD + 尽快部署 target 9db3f58`（继续推进到 R3 完成，让 expected=actual=0034，/ready 恢复 200）——最安全，避免 readiness mismatch 长期暴露。
  2. **次选** `KEEP_SCHEMA_FORWARD + 旧代码停机维护态`（不承载正常生产流量，等 target 就绪）——把"旧代码 + schema0034"作为维护态 fallback，而非正常服务态。
  3. **末选** `SCHEMA_DOWNGRADE 0034→0028`（§36，EMERGENCY_ONLY，新表数据丢失）。
- R2 决策依赖 rehearsal `OLD_CODE_NEW_SCHEMA_RUNTIME_VERIFIED`（BR-15/BR-16，验证业务层兼容，非 readiness 层）。

### R3 — Target Code 已部署后失败

评估 `rollback application to f453f44 + keep schema0034`：
- 依赖 rehearsal `OLD_CODE_NEW_SCHEMA_RUNTIME_VERIFIED`（BR-15/BR-20/BR-21）。
- 业务运行时兼容（§11）→ 应用层回滚 + schema 保留 forward **技术可行**（旧代码能跑）。
- **CORRECTION-1**：早期版本写"R3 回滚后 9000 会 unhealthy，因 /ready 503 → restart 循环"。该表述**错误**。正确分析：
  - R3 回滚后旧 f453f44 代码运行于 schema0034：application runtime compatible，进程能跑。
  - **但** `/ready 503 + unhealthy`（§14），与 R2 同——回滚后 9000 不得直接恢复 NORMAL_PRODUCTION_SERVICE。
  - R3 回滚后必须**进入维护态**（不承载正常流量）或**尽快重新部署 target**（让 /ready 恢复 200）。
- 若 target 已写入 0032/0033/0034 新表数据，schema downgrade 可能丢数据（§37）——故 R3 优先 schema-forward + code rollback，不优先 schema downgrade。

---

## 36. Schema Downgrade Boundary

Alembic `0034→0028` **不**作为默认 rollback。

逐 migration 审 downgrade（`MIGRATION_VERIFIED`）：
- 0034 downgrade: drop index + drop table `ai_preview_executions`（若有行→丢）
- 0033 downgrade: drop index + drop table `ai_edit_material_analysis_executions`（若有行→丢）
- 0032 downgrade: drop column `current_generation_id` + drop index + drop table `daily_report_generations`（若有行→丢）
- 0030 downgrade: drop UK + drop 2 columns（`idempotency_key`/`payload_evidence` 若有值→丢）
- 0029 downgrade: JSONB→TEXT（丢 JSONB 查询/索引能力，但值保留）

```text
SCHEMA_DOWNGRADE = EMERGENCY_ONLY
仅在无可恢复 target + 无 forward 路径时，且接受新表数据丢失
```

`APPLICATION_ROLLBACK` 与 `SCHEMA_DOWNGRADE` 必须分开设计（§37）。

---

## 37. Post-Migration Data Creation Boundary

一旦 target 9db3f58 已运行，可能写入：
- `daily_report_generations`（0032）
- `ai_edit_material_analysis_executions`（0033）
- `ai_preview_executions`（0034，含 F-1）
- `compute_transactions.idempotency_key/payload_evidence`（0030）

schema downgrade 会造成这些数据丢失。

```text
APPLICATION_ROLLBACK（code→f453f44，keep schema0034）≠ SCHEMA_DOWNGRADE（0034→0028）
优先 APPLICATION_ROLLBACK + schema forward（但受 §14 ready 契约限制）
SCHEMA_DOWNGRADE = EMERGENCY_ONLY（接受新数据丢失）
```

---

## 38. Rollback Artifacts（C8 重新分类）

生产执行前必须存在（authorization hard gate）：

```text
ROLLBACK_RUNTIME_IMAGE_IDENTITY  = VERIFIED（image ID = sha256:93094f0...，M3+M4 实测）
ROLLBACK_SOURCE_COMMIT_PROVENANCE= UNVERIFIED（image 无 provenance label；NON_BLOCKING if runtime image preserved）
DATABASE_BACKUP_CHECKPOINT       = 见 §33
ROLLBACK_IMAGE_READY             = sha256:93094f0... runtime image 可重新部署
9100_FROZEN_IMAGE                 = 9100 pin 至 93094f0...（S10-B，§52）
```

**Rollback identity 拆分**（不再笼统写 `ROLLBACK_ARTIFACT_IDENTITY_GAP = OPEN`）：

```text
ROLLBACK_RUNTIME_IMAGE_IDENTITY   = VERIFIED（M3+M4：image ID 实测，可 docker tag 固化）
ROLLBACK_SOURCE_COMMIT_PROVENANCE = UNVERIFIED（image 无 commit label；宿主 git HEAD=f453f44 为独立证据，不与 image 互相背书）
IMAGE_BUILD_PROVENANCE_DEBT       = NON_BLOCKING FOR THIS CATCH-UP
  前提：runtime rollback image 被可靠保存为 immutable identity（生产 execution 前 docker tag 固化，本窗口不执行）
```

Production Authorization 前设计 Hard Gate（C8）：
1. preserve current runtime image `sha256:93094f0...` 为 immutable rollback identity。
2. verify rollback image 仍在本机/registry 可用。
3. target 9000 image 用独立 immutable identity。
4. 不覆盖/独赖共享 mutable `:latest`。
5. 9100 pin/frozen 至当前 runtime image（§52 S10-B）。

R1/R2/R3 rollback 层级见 §35。

---

## 39. Maintenance Window

```text
CONTROLLED_MAINTENANCE_WINDOW = REQUIRED
```

即使 migrations LOW risk，仍需受控维护窗口。本窗口不给时间估计，只定义所需控制（§16）：
- business write control（反代 503 / 停服）
- operator presence（运维在场）
- backup ready（§33）
- rollback artifacts ready（§38）
- monitoring（日志/指标在场）

---

## 40. Stop Conditions

```text
S1  Production DB no longer 0028                       → AUTHORIZATION_INVALIDATED
S2  Production commit changed（非 f453f44）              → AUTHORIZATION_INVALIDATED
S3  JSONB drift scope changed（非仅 2 列 jsonb）          → RE-AUDIT
S4  invalid JSON >0                                     → BLOCKED（0029 ALTER USING 失败）
S5  unexpected 0030~0034 object exists（ahead-of-rev）   → RE-AUDIT
S6  backup unavailable                                  → BLOCKED
S7  rollback image unavailable（f453f44 镜像不可重建）    → BLOCKED
S8  target migration head mismatch（制品 head != 0034）   → BLOCKED
S9  target source commit mismatch（非 9db3f58）           → BLOCKED
S10 shared 9000/9100 image coupling unresolved (VERIFIED, M3) → BLOCKED（§51/§52，VERIFIED HARD GATE，S10-B 设计已 APPROVED_WITH_CORRECTIONS + Contract FROZEN；待 S10-B implementation + 独立实施审批闭环 → C3 CLOSED）
S11 rehearsal failed                                    → BLOCKED
S12 old-code/schema0034 runtime incompatible（业务层，非 ready 层）→ BLOCKED
```

任一触发 → `PRODUCTION_AUTHORIZATION = BLOCKED`。

**S10 为真实 hard gate**（§51/§52）：9db3f58 树相比 f453f44，9100 RAG migration 链新增 `0004_knowledge_training_executions` + `0005_rag_search_executions`（`git diff --stat f453f44 9db3f58 -- migrations/postgres/xg_douyin_ai_cs/` = 2 文件 +131 行），且 `apps/xg_douyin_ai_cs/` 有 395 行代码变更。共享镜像（§51）使得部署 9db3f58 必然同步改变 9100 expected head（0003→0005），若生产 RAG 库未追平 → 9100 /ready 503 + unhealthy（按 §14 语义，不自动 restart，但 readiness mismatch 暴露给 9100 流量/监控，且 9100 代码 395 行变更本身已改变生产行为）。

**S12 限定为业务运行时不兼容**（非 readiness 层）：业务层不兼容指 BR-15 发现旧代码在 schema0034 上业务请求报错（如 ORM 反射新列失败、SQL 语法冲突）。readiness 503 属预期事实（§13），不计入 S12 阻断，但计入 R2/R3 可行性（§35）。

---

## 41. 0034 Rehearsal

验证（BR-12/BR-13）：
- `ai_preview_executions` 表：`id`(PK) / `merchant_id`(String128,NOT NULL) / `agent_id`(String128,nullable) / `lifecycle_status`(NOT NULL,server_default='running') / `created_at`(NOT NULL,now()) / `completed_at`(nullable)
- CHECK `ck_ai_preview_executions_status lifecycle_status IN ('running','completed','failed')`（3 态）
- INDEX `idx_ai_preview_executions_merchant (merchant_id)`
- F-1 durable execution identity 依赖：`ai_preview_executions` 存在是 F-1 `_create_preview_execution` 前置
- 只验证 production schema/code availability，**不**重做 F-1 technical correctness review（P1 已 RESOLVED）

---

## 42. Alembic Execution Command Design

```text
建议生产执行优先：alembic upgrade 0034
而非：           alembic upgrade head
```

即使 9db3f58 制品 head=0034，也优先显式 target，减少 operator error。本窗口**不执行**任何 alembic 命令。

**事务语义**（§7）：所有迁移默认在 Alembic 单事务内执行（无 `op.execute("COMMIT")` / `transactional_ddl` 覆盖）。失败时单事务原子回滚（DDL+DML），不留 partial DDL。但 `ALTER TYPE`（0029）表重写与 `CREATE UNIQUE CONSTRAINT`（0030）在事务内，失败回滚至 0028。

逐 revision 验证能力（§15 rehearsal）：即使 `alembic upgrade 0034` 可一次执行，rehearsal evidence 必须能定位"哪一步出错"（逐 revision upgrade + verify，BR-04~BR-13）。

---

## 43. Preflight Checklist

```text
[ ] production code still f453f44（§2，git identity）
[ ] production DB current still 0028（§2，alembic_version）
[ ] table count/fingerprint unchanged materially（58 表，§5）
[ ] 0029 JSONB drift still same scope（仅 2 列 jsonb，§5）
[ ] invalid JSON = 0（§6，0029 DATA_PRECONDITION）
[ ] compute_transactions scale checked（1698 行，§6）
[ ] backup created（§33）
[ ] target image ready（9db3f58 immutable tag，§19/§28）
[ ] rollback runtime image preserved = sha256:93094f0... tagged immutable（§38）
[ ] migration artifact head verified = 0034（9db3f58 制品，§20）
[ ] maintenance control active（§16/§39）
[ ] S10-B implementation closed + 独立实施审批通过（C3 CLOSED）：9000 immutable image + 9100 frozen 93094f0.../0003（§51/§52 C3）
```

若 baseline 在审批与执行之间变化（new git deployment / manual schema change / new Alembic revision / unexpected new tables）→ `AUTHORIZATION_INVALIDATED`，重新核实（§44）。

---

## 44. Concurrency / Baseline Drift

生产 Authorization 到真正执行之间，若出现：
```text
new git deployment / manual schema change / new Alembic revision / unexpected new tables
```
→ `AUTHORIZATION_INVALIDATED`，必须重新核实。

---

## 45. Production-Like Fixture（Hard Gate）

Rehearsal 必须使用 `DRIFTED_0028_PRODUCTION_FIXTURE`，**禁止**只用 fresh clean 0028 作为唯一起点。

Fixture 至少体现（§10）：
```text
alembic_version = 0028
customer_profiles.confirmed_fields_json = JSONB（物理 jsonb，drift）
customer_profiles.inferred_fields_json = JSONB（物理 jsonb，drift）
```
即生产真实 drift。

---

## 46. Synthetic Dataset

Fixture 数据规模（§11）：
```text
customer_profiles    ≈ 1 row
compute_transactions ≈ 1698 rows
daily_report_jobs    = 0 rows
```
synthetic/generated data，**不**导出真实 production business payload。

JSONB 字段语义（§12）：
```text
valid object
valid array（若契约允许）
NULL
```
验证 `jsonb::text::jsonb` 行为。

---

## 47. Rehearsal Topology

> **CORRECTION-2 / C4 — Rehearsal Topology 补全（APPLIED / CLOSED）**：原 topology 仅描述 isolated PostgreSQL（PG/迁移层），不足以验证 BR-24~BR-30（S10 部署身份隔离）。以下扩展为完整 `ISOLATED_REHEARSAL_TOPOLOGY`（8 项），并明确每个 BR 的真实载体与可观察证据。BR-24~30 = **CONTAINER_RUNTIME verification**（不是 STATIC_DESIGN verification），留给未来 Rehearsal 窗口真正执行。

隔离 PostgreSQL 实例（非生产），构造 drifted 0028 fixture → 逐 revision upgrade 0034 → 验证 → 旧 app smoke + 新 app smoke；并在**隔离 docker compose 环境**中验证 S10-B 服务级镜像身份隔离机制（BR-24~30）。

### ISOLATED_REHEARSAL_TOPOLOGY（8 项）

```text
1. DRIFTED_0028_POSTGRESQL_FIXTURE（非生产 PG 实例）
     alembic_version=0028 + customer_profiles 两列已物理 jsonb（drift，§45）
     synthetic rows 1/1698/0（§46）

2. OLD_9000_RUNTIME_IDENTITY
     source/tree = f453f44（旧代码运行时载体）
     载体形态 = old-image-equivalent fixture 或 locally built old source runtime
     （生产 image ID sha256:93094f0... 仅作生产事实/reference 使用，
       isolated rehearsal 不要求 copy production image bytes from Merchant）

3. TARGET_9000_RUNTIME_IDENTITY
     source/tree = 9db3f58（target 9000 运行时载体）

4. FROZEN_9100_RUNTIME_IDENTITY
     = simulated/preserved old production image identity（9100 侧冻结载体，等价 93094f0... 的旧镜像身份）
     不得在生产执行窗口外真实操作生产 9100

5. 9100_DB_FIXTURE
     = 0003（9100 RAG 库 alembic 冻结，等价生产 0003 三态一致）

6. SERVICE_SPECIFIC_IMAGE_SELECTION_MECHANISM
     = C3 冻结后的 S10-B release engineering 机制（RE-A compose override 或 RE-B per-service env var，
       实施后由独立 Implementation 窗口落地，本窗口只冻结 contract 不实现）
     rehearsal 用它来验证"9000 与 9100 可被指派不同 image ref"这一机制本身可执行

7. ISOLATED_NETWORK_AND_PORTS
     = 独立 docker network / 独立端口映射（不与生产、staging、本地 dev 冲突）

8. EXPLICIT_VERIFICATION_TARGET9000_DOES_NOT_RECREATE_MIGRATE_FROZEN9100
     = BR-28 的可观察证据契约（见下方证据定义）
```

### Rehearsal 不得依赖生产真实镜像

设计使用生产 Image ID `sha256:93094f0...` 作为生产事实/reference（§2-A/§19），但 **isolated rehearsal 不要求 copy production image bytes from Merchant** 作为唯一测试方案。可设计 `old-image-equivalent fixture` 或 `locally built old source runtime`（f453f44 源码本地构建的运行时），前提是能够验证 **service identity isolation mechanism 本身**（即：9000 与 9100 在 compose 部署层面可被指派不同 image ref，且 9000 单独 recreate 不触碰 9100）。

### BR-24~BR-30 真实载体与可观察证据

```text
BR-24  Verify deployment identities isolated
       验证 = 9000 image identity != 9100 image identity（容器运行时实测，非只检查字符串文档）
       可观察证据 = docker inspect 两容器 Image ID 不同 / compose config 解析出的两服务 image ref 不同

BR-25  Deploy/recreate target9000 only
       验证 = 9000 改变 runtime image（从 old identity 变为 target 9db3f58 identity）
       可观察证据 = docker inspect 9000 前后 Image ID 变化

BR-26  验证 9100 container/runtime image identity unchanged
       可观察证据 = docker inspect 9100 前后 Image ID 相同

BR-27  验证 9100 DB revision remains 0003
       可观察证据 = 9100 DB alembic current=0003（before/after 均=0003）

BR-28  验证 9100 container was not recreated / 9100 migration was not executed
       可观察证据 = container ID before/after + start timestamp + restart count + DB alembic current
       （9100 container ID 不变 + start time 不变 + restart_count 不变 + alembic current=0003 → 未被 recreate、未执行迁移）

BR-29  验证 target9000 + schema0034 → /ready 200（expected=0034 = actual=0034）
       可观察证据 = HTTP /ready 200 + expected_heads=[0034] + actual=[0034]

BR-30  验证 rollback9000 to preserved old image identity
       同时：9100 container unchanged + 9100 DB remains 0003
       可观察证据 = 9000 Image ID 回退到 preserved old identity + 9100 container ID/start time/restart count 不变 + 9100 alembic current=0003
```

```text
ISOLATED_REHEARSAL_TOPOLOGY_COMPLETE = YES
BR-24~BR-30 EVIDENCE TYPE           = CONTAINER_RUNTIME（非 STATIC_DESIGN；执行留给未来 Rehearsal 窗口）
```

### Rehearsal 主序列（PG 迁移层 + S10 部署层）

```text
ISOLATED_POSTGRESQL (非生产 PG 实例)
  DRIFTED_0028_FIXTURE
    → upgrade 0029 (BR-04/05)
    → upgrade 0030 (BR-06/07)
    → upgrade 0032 (BR-08/09)
    → upgrade 0033 (BR-10/11)
    → upgrade 0034 (BR-12/13)
    → BR-14 final current=0034
    → BR-15/16 old f453f44 + schema0034 runtime + /ready behavior
    → BR-17/18 target 9db3f58 + schema0034 startup + /ready
    → BR-19 P1 artifact verification
    → BR-20/21 application rollback target→old + verify（含 /ready 503 + unhealthy + 不自动 restart 预期）
    → BR-22 failure injection / stop
    → BR-23 backup/restore dry-run
ISOLATED_DOCKER_COMPOSE（S10 部署身份隔离层，BR-24~30）
    → BR-24 service identity isolated（9000 image identity != 9100）
    → BR-25 deploy/recreate target9000 only（9000 换 target image）
    → BR-26 9100 image identity unchanged
    → BR-27 9100 DB remains 0003
    → BR-28 9100 未被 recreate / 未执行迁移（container ID/start time/restart count/alembic current）
    → BR-29 target9000 + schema0034 /ready 200
    → BR-30 rollback9000 to preserved old identity，9100 untouched
```

---

## 48. BR-01~BR-30 Matrix

| ID | 测试 | Evidence Level（设计阶段标注） |
| -- | ---- | ----------------------------- |
| BR-01 | Build clean standard 0028 fixture | NOT_TESTED（待 rehearsal 执行） |
| BR-02 | Apply production JSONB drift to fixture while revision remains 0028 | NOT_TESTED |
| BR-03 | Populate production-like synthetic row counts (1/1698/0) | NOT_TESTED |
| BR-04 | 0028-drifted → 0029 | NOT_TESTED |
| BR-05 | Verify JSONB data preservation | NOT_TESTED |
| BR-06 | 0029 → 0030 | NOT_TESTED |
| BR-07 | Verify 0030 columns/UK/index/data preservation | NOT_TESTED |
| BR-08 | 0030 → 0032 | NOT_TESTED |
| BR-09 | Verify 0032 schema/FK/index | NOT_TESTED |
| BR-10 | 0032 → 0033 | NOT_TESTED |
| BR-11 | Verify 0033 schema | NOT_TESTED |
| BR-12 | 0033 → 0034 | NOT_TESTED |
| BR-13 | Verify 0034 schema | NOT_TESTED |
| BR-14 | Final Alembic current=0034 | NOT_TESTED |
| BR-15 | Old f453f44 + schema0034 runtime compatibility | NOT_TESTED |
| BR-16 | Old app /ready behavior against 0034（预期 503 ALEMBIC_REVISION_MISMATCH；APPLICATION_PROCESS_RUNNING=YES；DOCKER_HEALTH=unhealthy after retries；CONTAINER_AUTO_RESTART=NO in standard restart-policy env） | NOT_TESTED |
| BR-17 | Target 9db3f58 + schema0034 startup | NOT_TESTED |
| BR-18 | Target /ready expected=actual=0034 | NOT_TESTED |
| BR-19 | P1 production-baseline artifact verification | NOT_TESTED |
| BR-20 | Application rollback target→old while schema remains 0034 | NOT_TESTED |
| BR-21 | Verify old app after application rollback（含 /ready 503 + unhealthy 预期，进程持续运行，不自动 restart） | NOT_TESTED |
| BR-22 | Failure injection during migration / stop behavior | NOT_TESTED |
| BR-23 | Backup/restore procedure dry-run in isolated env | NOT_TESTED |
| BR-24 | Verify deployment identities isolated（9000 image identity != 9100，容器运行时实测，非字符串文档；证据契约 §47） | NOT_TESTED |
| BR-25 | Deploy/recreate target9000 only（9000 runtime image 改变；9100 不 recreate） | NOT_TESTED |
| BR-26 | Verify 9100 container/runtime image identity unchanged（docker inspect 前后 Image ID 相同） | NOT_TESTED |
| BR-27 | Verify 9100 DB revision remains 0003（alembic current before/after=0003） | NOT_TESTED |
| BR-28 | Verify 9100 container was not recreated / migration not executed（container ID + start timestamp + restart count + DB alembic current） | NOT_TESTED |
| BR-29 | Verify target9000 + schema0034 /ready 200（expected=0034 = actual=0034） | NOT_TESTED |
| BR-30 | Verify rollback9000 to preserved old image identity while 9100 container unchanged + DB remains 0003 | NOT_TESTED |

**BR-16 期待明细（CORRECTION-1）**：
```text
HTTP_503                 = YES
reason                   = ALEMBIC_REVISION_MISMATCH
APPLICATION_PROCESS_RUNNING = YES（/health 200，进程持续）
DOCKER_HEALTH            = unhealthy after configured retries（3 次）
CONTAINER_AUTO_RESTART   = NO（标准 Docker restart-policy 环境）
```
最后一项 `CONTAINER_AUTO_RESTART=NO` 仅在标准 Docker restart-policy 环境中如此。若存在 external watchdog（autoheal/systemd/宝塔自动恢复），则单独验证（`PRODUCTION_EXTERNAL_AUTOHEAL = UNKNOWN`，§14/§52）。

**BR-24~BR-30（M3/C9 新增 + CORRECTION-2/C4 补全，S10 部署身份隔离验证）**：rehearsal 必须验证 9000 用 target immutable image、9100 冻结当前 image/DB0003、不发生 9100 recreate/migration。不得真实操作生产。完整 ISOLATED_REHEARSAL_TOPOLOGY（8 项）、各 BR 真实载体与可观察证据（container ID/start timestamp/restart count/DB alembic current）、以及"rehearsal 不依赖生产真实镜像"的约束见 §47。**BR-24~30 = CONTAINER_RUNTIME verification**（非 STATIC_DESIGN verification），执行留给未来 Rehearsal 窗口，本设计阶段全部 NOT_TESTED。

```text
设计阶段全部 = NOT_TESTED
执行进入独立 PRODUCTION-BASELINE-CATCHUP-0028-TO-0034-REHEARSAL 窗口
不得把设计计划写成 VERIFIED
```

---

## 49. Production Verification Plan（未来升级后）

```text
PV-01 git/source identity = 9db3f58
PV-02 image identity（id/digest/tag）
PV-03 DB current=0034
PV-04 application head=0034
PV-05 /ready 200
PV-06 expected=actual=0034
PV-07 critical tables（douyin_leads/sales_staff）
PV-08 new 0030 objects（idempotency_key/payload_evidence/UK）
PV-09 new 0032 objects（daily_report_generations/current_generation_id/FK/CHECK/INDEX）
PV-10 new 0033 objects（ai_edit_material_analysis_executions/CHECK/INDEX）
PV-11 new 0034 objects（ai_preview_executions/CHECK/INDEX）
PV-12 existing row preservation（customer_profiles 1 / compute_transactions 1698）
PV-13 P1 deployed-code identity（record_usage/AiPreviewExecution/F-1/FC-F1）
PV-14 no unexpected schema drift（无 0035 对象）
PV-15 application logs no migration/runtime errors
PV-16 9100 未被 recreate（image ID 仍=93094f0...，alembic 仍=0003，S10-B）
PV-17 9000 用 immutable target image（非共享 mutable :latest）
```

---

## 50. P2 Boundary

未来只有 `BASELINE_CATCHUP_PRODUCTION_VERIFIED` 后才允许恢复 `P2-M04-CUTOVER-BLOCKER-CLOSURE`（即解除 B7/B8）。

```text
B7 = CLOSED（schema catch-up 0034 verified）
B8 = CLOSED（code catch-up 9db3f58 verified）
→ 然后继续 P2 cutover：B3 new 19000 artifact / B2 fleet / B4 reverse proxy / B1 pause control / P2 0035
```

**不得**直接因 0034 成功而 deploy 0035。0035 属独立 P2 cutover，需独立审批 + rehearsal。

---

## 51. Shared 9000/9100 Image — VERIFIED HARD GATE（★S10，M3 升级）

本窗口核实（`CONTAINER_CONFIG_VERIFIED` + M3 `PRODUCTION_RUNTIME_VERIFIED`）：

```text
docker-compose.yml:
  auto-wechat-api（9000）:  image: xg-ai-system-backend:latest, build: Dockerfile.backend.dev
  xg-douyin-ai-cs（9100）:  image: xg-ai-system-backend:latest, build: Dockerfile.backend.dev

M3 生产 docker inspect:
  9000 Image ID = sha256:93094f0a02ba3a4570160ce90625cb80fdec85076046fc314f5fe407add36c68
  9100 Image ID = sha256:93094f0a02ba3a4570160ce90625cb80fdec85076046fc314f5fe407add36c68
  → 9000_9100_RUNTIME_IMAGE_SHARED = VERIFIED（同一 image ID，不止 compose 声明）
```

两服务同一镜像 tag、同一 Dockerfile，通过 compose `command` 区分入口（9000=`app.main:app`，9100=`apps.xg_douyin_ai_cs.main:app`）。仓库内**无单独 9100 Dockerfile**。

**9100 RAG migration 链差异**（`GIT_HISTORY_VERIFIED`）：
```text
git diff --stat f453f44 9db3f58 -- migrations/postgres/xg_douyin_ai_cs/
  0004_knowledge_training_executions.py | 68 +++++++++
  0005_rag_search_executions.py         | 63 +++++++++
  2 files changed, 131 insertions(+)
git diff --stat f453f44 9db3f58 -- apps/xg_douyin_ai_cs/
  8 files changed, 395 insertions(+), 48 deletions(-)
```

9db3f58 树 9100 migration head = `0005`；f453f44 树 9100 head = `0003`。

**M3 生产 9100 实测**（§2-A）：`PRODUCTION_9100_ALEMBIC_CURRENT = 0003`，`INTERNALLY_CONSISTENT_0003`。

**★C5 关键纠正（CORRECTION-1）**：不得写"9000 升级必然即时升级 9100"。正确语义：

```text
rebuilding/repointing :latest does NOT by itself mutate an already-running 9100 container.
Risk occurs when 9100 is recreated/redeployed using the shared mutable tag.
```

即：重新 build `xg-ai-system-backend:latest` 至 9db3f58 后，**已运行的 9100 容器仍用旧 image ID `93094f0...`**（Docker 不会因 tag 重指而自动 recreate 运行中容器）。只有执行 `docker compose up -d`/`recreate` 9100 服务时，才会拉取新 `:latest`（指向 9db3f58 镜像），此时 9100 expected=0005 ≠ actual=0003 → /ready 503 + unhealthy。

```text
S10 真正问题 = MUTABLE_SHARED_IMAGE_DEPLOYMENT_IDENTITY
           ≠ IMMEDIATE_SYNCHRONOUS_9100_UPGRADE
```

---

## 52. S10 Resolution Design（★Hard Gate，C4-C11）

```text
S10_SHARED_9000_9100_IMAGE_COUPLING = VERIFIED（M3：同 image ID）
S10_RESOLUTION_DESIGN              = IMMUTABLE_SERVICE-SPECIFIC_DEPLOYMENT
                                      / DESIGN_APPROVED_WITH_CORRECTIONS
                                      / IMPLEMENTATION_REQUIRED
```

S10 保持 `PRODUCTION_AUTHORIZATION_BLOCKER`，直到 service-specific immutable deployment identity **implementation 闭环**（C3 Contract 已冻结，§52 C3.1~C3.12；实施 + 独立实施审批 → C3 CLOSED 前不解锁）。

### S10 Mitigation 比较（C6，DESIGN ONLY，不实施）

| 方案 | 内容 | 范围 | 9100 影响 | 原则契合 | 选择 |
| ---- | ---- | ---- | --------- | -------- | ---- |
| **S10-A** | 一起升级 9100 0003→0005（RAG catch-up + 395 行代码） | 扩大到 9100 RAG 库迁移 + 9100 代码审计 + rehearsal | 9100 改变 | 违反 MINIMUM_CHANGE / NO_UNAUTHORIZED_9100_CATCH_UP / YAGNI | **不首选** |
| **S10-B** | 9000/9100 image identity split；9100 冻结 0003 当前镜像，不 deploy 不 migrate | 仅 9000 immutable image 部署 | 9100 不变 | MINIMUM_CHANGE / YAGNI / NO_UNAUTHORIZED_9100_CATCH_UP | **首选** |

**S10-B 目标部署身份**（C7，未来 execution）：
```text
9000_TARGET_IMAGE_IDENTITY = IMMUTABLE / built from 9db3f58
9100_IMAGE_IDENTITY        = CURRENT PRODUCTION IMAGE = sha256:93094f0a02ba3a4570160ce90625cb80fdec85076046fc314f5fe407add36c68

未来 execution 约束：
  DO NOT RECREATE 9100
  DO NOT MIGRATE 9100
  仅对 9000 服务做 service-specific image 部署（不改 docker-compose.yml image 字段全局，需 compose override 或显式 image tag）
```

**S10-B 实现手段（候选，不实施）**：service-specific immutable image/tag（如 `xg-ai-system-backend:9db3f58-<ts>` 用于 9000）或 compose deployment override（仅 override 9000 的 image，9100 保留 `93094f0...`）。改 docker-compose.yml 全局 image 字段超出本窗口（§64），由生产执行窗口决定具体 override 机制。

**S10-B 解除条件**：S10-B **implementation 闭环**（Contract 已冻结，§52 C3.1~C3.12）+ **independent implementation approval**（证明 9000 可用 immutable image 部署而 9100 不被 recreate）→ C3 CLOSED。若实现后仍无法隔离 9000/9100 部署身份 → `CATCHUP_DESIGN_BLOCKED`（C11）。

### S10-B Release Engineering Implementation Contract（★CORRECTION-2 / C3）

> **本窗口 = DESIGN CORRECTION ONLY：C3 只冻结 Implementation Contract，DO NOT IMPLEMENT C3。** Independent Approval（`APPROVED_WITH_CORRECTIONS`）已裁定：`S10-B = DESIGN FEASIBLE` + `RELEASE_ENGINEERING_CHANGE_REQUIRED = YES`。本小节把该要求收敛为后续独立实施窗口可直接实现的**最小合同**（`S10_B_RELEASE_ENGINEERING_IMPLEMENTATION_CONTRACT = FROZEN`）。实施、构建、docker tag、rehearsal、生产变更全部留给后续窗口。

```text
RELEASE_ENGINEERING_CHANGE_REQUIRED = YES
S10_B_RELEASE_ENGINEERING_IMPLEMENTATION_CONTRACT = FROZEN
C3 = CONTRACT_FROZEN / IMPLEMENTATION_PENDING
C3_IMPLEMENTATION = NOT_STARTED
C3_INDEPENDENT_APPROVAL = NOT_STARTED
```

#### C3.1 解除的耦合本质

当前生产（`docker-compose.yml`，`CONTAINER_CONFIG_VERIFIED`）：
```text
auto-wechat-api（9000）:  image: xg-ai-system-backend:latest
xg-douyin-ai-cs（9100）:  image: xg-ai-system-backend:latest
实际运行 9000/9100 IMAGE_ID 均 = sha256:93094f0...（M3）
```

目标（未来 execution）：
```text
9000 → independent immutable image identity（built from 9db3f58）
9100 → independent frozen old image identity（preserved 93094f0... 等价身份）
```

**解除的是 `RUNTIME_DEPLOYMENT_IDENTITY_COUPLING`（部署时两个 service 指向同一 mutable image ref，导致 9000 变更必然耦合 9100 的 recreate 风险），不是 Dockerfile sharing / source repository sharing / backend build-context sharing**。共享 `Dockerfile.backend.dev` 与共享源码仓库/构建上下文是既有事实，**不要求**为 9100 建独立 Dockerfile（除非严格必要且另行单独论证，见 C3.9 FORBIDDEN）。

#### C3.2 两个最小 Candidate 比较（DESIGN 示意，本窗口不改 compose）

**RE-A — Compose Override**：新增 production service-specific override 文件（如 `docker-compose.production.yml`），仅覆盖 `auto-wechat-api.image` 与 `xg-douyin-ai-cs.image` 两个字段：
```text
# 设计示意，本窗口未创建该文件
auto-wechat-api:
  image: xg-ai-system-backend:9db3f58-<ts>     # target 9000 immutable
xg-douyin-ai-cs:
  image: xg-ai-system-backend:93094f0-immutable # 9100 frozen old identity
```
调用：`docker compose -f docker-compose.yml -f docker-compose.production.yml up -d auto-wechat-api`（仅 9000）。

**RE-B — Per-Service Image Env Variables**：把两服务 image 字段改为 env 变量驱动，默认值保持当前字面量：
```text
# 设计示意，本窗口未改 docker-compose.yml
auto-wechat-api:
  image: ${AUTO_WECHAT_API_IMAGE:-xg-ai-system-backend:latest}
xg-douyin-ai-cs:
  image: ${XG_DOUYIN_AI_CS_IMAGE:-xg-ai-system-backend:latest}
```

| 维度 | RE-A（compose override） | RE-B（per-service env var） |
| ---- | ---- | ---- |
| backward compatibility | 强（base compose 字面量不变；不带 override 即现状） | 强（env 默认值 = 现状） |
| dev environment | 无影响（dev 用 docker-compose.dev.yml，独立） | 无影响（不设 env 即默认值） |
| production explicitness | 高（override 文件显式声明两个 image ref） | 中（image ref 由 .env.production.local 变量承载） |
| operator error risk | 中（必须记得带 `-f` override；漏带=回落到 :latest 共享） | 低（显式变量，未设则默认） |
| rehearsal usability | 高（rehearsal 可构造不同 override 组合验证 BR-24~30） | 高（rehearsal 设不同 env 组合） |
| rollback usability | 高（override 中把 9000 image 改回 preserved identity 即回滚） | 高（改 env 变量即回滚） |
| 9000/9100 功能影响 | 无（仅 image 选择） | 无（仅 image 选择） |

**实施窗口选择原则**（C3 Contract 约束，非本窗口代选）：满足 `MINIMUM DIFF / EXPLICIT PRODUCTION IDENTITY / BACKWARD COMPATIBLE DEFAULT / REHEARSABLE / ROLLBACK FRIENDLY / NO 9100 FUNCTIONAL CHANGE`。**不得因为"更工程化"选择复杂方案**。两候选均满足；若仓库现有 compose 调用习惯已带 override（staging 有先例），RE-A 更贴合仓库现状；若希望把 image 选择完全收口到 env 契约（.env.production.example 增两个 IMAGE 变量），RE-B 更显式。实施窗口二选一并给出理由，不得混合扩大范围。

#### C3.3 Runtime Guarantees（RG-1~RG-8，实施后必须保证）

```text
RG-1  9000 image identity 可被独立指定。
RG-2  9100 image identity 可被独立指定。
RG-3  变更 9000 image identity 不要求变更 9100 image identity。
RG-4  recreate 9000 不 recreate 9100。
RG-5  9000 rollback image 可被独立选择（preserved old runtime image）。
RG-6  9100 DB/migration 不被 9000 deployment 触及。
RG-7  默认 local/dev 行为保持兼容，除非显式配置。
RG-8  生产可拒绝/避免歧义的共享 mutable `:latest` 用法（catch-up 期间 production 不得依赖 ambiguous shared mutable latest）。
```

#### C3.4 Production Target Identity Contract

未来 production execution 的目标必须能够表达（本窗口不决定真实未来 target digest，因为尚未构建）：
```text
AUTO_WECHAT_API_IMAGE  = exact immutable target built from 9db3f58
XG_DOUYIN_AI_CS_IMAGE  = preserved current runtime image identity（93094f0... 等价身份）

TARGET_9000_IMAGE_DIGEST = generated during release build（构建时产生，本窗口不预写）
```

#### C3.5 9100 Freeze Contract（catch-up 全程保留）

```text
9100_CODE_CHANGE = NO
9100_DB_CHANGE   = NO
9100_MIGRATION   = NO
Catch-up 期间 9100_DB = 0003
```

#### C3.6 Existing Runtime Rollback Image + New Target Provenance

```text
ROLLBACK_RUNTIME_IMAGE_IDENTITY   = sha256:93094f0...（生产已确认，M3+M4 VERIFIED）
ROLLBACK_SOURCE_COMMIT_PROVENANCE = UNVERIFIED（image 无 provenance label）
IMAGE_BUILD_PROVENANCE_DEBT       = NON_BLOCKING
  前提：future preflight 把 old runtime image 保存为 immutable rollback reference（docker tag 固化，实施窗口执行）
```

New Target Provenance Contract：后续 C3 implementation **不一定负责 target image build**，但 release contract 必须要求未来 target image 具备至少一种：`immutable tag` / `image digest` / `OCI revision label` / `build manifest linking 9db3f58`，能够证明 `TARGET_9000_IMAGE ↔ 9db3f58`。**旧 provenance debt 不得复制到新 target**（新 target 须带 provenance，不能像旧镜像一样无 commit label）。

#### C3.7 Mutable `:latest` Boundary

`xg-ai-system-backend:latest` 可继续作为 **development/default fallback**（若 implementation 选择 backward-compatible env default）。但 **production catch-up MUST NOT rely on ambiguous shared mutable latest**（RG-8）。

#### C3.8 Implementation Scope Contract（允许 / 条件性 / 禁止）

```text
S10-B IMPLEMENTATION ALLOWED SCOPE:
- docker-compose 部署层 image 选择机制（RE-A override 或 RE-B env var，二选一）
- .env.example / .env.production.example（如 RE-B，新增两个 IMAGE 变量 + 文档；RE-A 则对应 override 文件与文档）
- 生产 env variable contract 文档
- 最小 compose/static 验证测试（RE-T01~T10）
- remediation implementation report（candidate 报告）

CONDITIONAL:
- deployment helper script：仅当当前仓库已有同类脚本（scripts/production_pg_*.sh 先例）且它是"最小安全落点"时才允许，不得为新增机制而新建复杂工具链

FORBIDDEN:
- 无业务代码（app/**）
- 无应用层代码（apps/**，含 apps/compute、apps/xg_douyin_ai_cs）
- 无数据库迁移（migrations/**）
- 无 9100 业务配置改动
- 无数据库改动
- 无前端（frontend/**）
- 无 19000
- 无新 Dockerfile，除非严格必要且单独论证（共享 Dockerfile.backend.dev 保持现状）
- 无 CI/CD 平台改动
- 无 Kubernetes
- 无新部署框架
```

具体文件由实施窗口按 repo 现实决定，**不得编造不存在的文件**。

#### C3.9 Acceptance Criteria（RE-AC01~RE-AC12）

```text
RE-AC01 无 override/env 覆盖时，现有 dev compose 行为保持有效。
RE-AC02 9000 与 9100 可被指派不同的显式 image ref。
RE-AC03 compose config 对每个 service 解析出预期 image。
RE-AC04 变更 9000 image ref 不改变 9100 ref。
RE-AC05 target9000 service 可被独立 recreate。
RE-AC06 9100 service 不被隐式 recreate。
RE-AC07 rollback9000 可选择 preserved old runtime image。
RE-AC08 image-isolation 机制不引入任何 migration 命令。
RE-AC09 不触发 9100 0003→0005 migration。
RE-AC10 无业务/API 行为变更。
RE-AC11 文档明确禁止本 catch-up 生产使用共享 mutable `:latest`。
RE-AC12 implementation 支持 BR-24~BR-30 rehearsal（§47 topology）。
```

#### C3.10 Test Contract（RE-T01~RE-T10，后续 implementation 窗口设计并执行，本窗口不执行）

```text
RE-T01 compose config 基线/默认解析（无覆盖）。
RE-T02 显式 9000 image override（RE-A）或 env 设置（RE-B）。
RE-T03 显式 9100 image override。
RE-T04 9000/9100 不同 image ref 同时生效。
RE-T05 只改 9000 后 9100 config 保持稳定。
RE-T06 service-specific recreate 命令/路径。
RE-T07 rollback9000 image 选择。
RE-T08 部署身份机制无 migration 副作用。
RE-T09 静态 scope guard：无 app/apps/migration 改动。
RE-T10 BR-24~BR-30 rehearsal 兼容契约。
```

#### C3.11 Implementation Verdict Contract

后续执行窗口最终只能输出：
```text
S10_B_IMPLEMENTATION_CANDIDATE_READY
或
S10_B_IMPLEMENTATION_BLOCKED
```
**不得自行**写 `APPROVED` / `PRODUCTION_READY`。实施后仍需独立审批。

#### C3.12 Independent Approval Contract

```text
S10-B Implementation
→ Independent Implementation Approval
→ C3 CLOSED
```

独立审批至少验证：per-service identity 实际可用 / 9000 recreate 隔离 / 9100 untouched / rollback identity 受支持 / scope 干净（RE-AC01~12 + RE-T01~10 + RG-1~8）。

### 9100 独立治理边界（C10）

若未来需要 9100 `0003→0005`，必须进入独立 `9100_RAG_PRODUCTION_BASELINE_CATCHUP` 流程（审计 0004/0005 + 395 行代码 + 设计 + rehearsal + 审批），**不得**成为当前 9000 0028→0034 catch-up 的隐式副作用。当前 catch-up 范围严格限定 9000 + auto_wechat 库 0028→0034。

**S10 解除条件总结**（任一，需独立审批）：
1. **S10-B**（首选）：设计并审批 9000 immutable image 部署 + 9100 冻结不动。
2. **S10-A**：独立完成 9100 RAG 0003→0005 审计/设计/rehearsal/审批，同维护窗口执行（扩大范围）。
3. 生产侧只读核实 RAG 库已=0005（则 9100 recreate 后 expected=actual=0005，无 mismatch）——但 9100 代码 395 行变更仍生效，需独立评估，等同 S10-A 范围。

```text
S10 本窗口 READ-ONLY EVIDENCE REQUEST 已由 M3 完成闭环：
  9000_9100_RUNTIME_IMAGE_SHARED = VERIFIED（image ID 同）
  PRODUCTION_9100_ALEMBIC_CURRENT = 0003（VERIFIED）
S10-B Design Approval = APPROVED_WITH_CORRECTIONS（独立审批 Verdict）
S10-B Release Engineering Implementation Contract = FROZEN（CORRECTION-2 / C3，见 §52 C3.1~C3.12）
剩余 = S10-B Implementation（独立实施窗口）→ Independent Implementation Approval → C3 CLOSED
```


---

## 53. Frontend Boundary

```text
FRONTEND_CHANGE_REQUIRED = NO
```

0028→0034 catch-up 是后端 schema/code baseline 追平，不要求 frontend 同步升级。frontend 不直接持有 internal token、不直连 9100/Milvus（CLAUDE.md 硬约束 #6）。不得顺手部署 frontend。

---

## 54. Environment Config Compatibility

比较 target code（9db3f58）expected env vars vs production `.env.production.local`（只比 variable names / required presence，**不**写 secret 内容）。

依据 `.env.production.example`（本窗口已读，`CODE_VERIFIED`）：
- 9000 关键 env：`DATABASE_URL`（auto_wechat 库）、`EXPECTED_DATABASE_NAME=auto_wechat`、`COMPUTE_INTERNAL_TOKEN`、`LOCAL_AGENT_AUTH_REQUIRED/TOKENS`、NewCar 鉴权、抖音 webhook。
- 9100 关键 env：`RAG_DATABASE_URL`（xg_douyin_ai_cs 库）、`RAG_EXPECTED_DATABASE_NAME`、Milvus、Embedding/LLM。
- `EXPECTED_DATABASE_NAME` 由 `/ready` 校验（`health.py:51`）。

> **CORRECTION-2 / C1 — Env Compatibility（APPLIED / CLOSED）**：Independent Approval 已确认 `app/config.py` + 3 个 9100 config 文件（`apps/xg_douyin_ai_cs/config.py` / `apps/xg_douyin_ai_cs/llm/config.py` / `apps/xg_douyin_ai_cs/llm/embedding_config.py`）在 f453f44→9db3f58 之间 required env contract **零变化**（本窗口独立核实 `git diff --stat f453f44 9db3f58 -- app/config.py` = 零变更、3 个 9100 config 零变更，`CODE_VERIFIED`）。原 `ENV_CONFIG_DRIFT = REQUIRES_PRODUCTION_VERIFICATION` 必须降级：

**潜在新增 env（9db3f58 相对 f453f44）**：本窗口已用 `git diff` 确定性核实 `app/config.py` + 3 个 9100 config 文件零 diff，catch-up 链（0029~0034 schema 迁移）**不引入新 required env 消费点**。代码层 env contract diff = **NONE_DETECTED**。

```text
TARGET_CODE_ENV_CONTRACT_DIFF = NONE_DETECTED（CODE_VERIFIED）
ENV_CONFIG_DRIFT              = NONE_DETECTED（代码层确定性穷举，替换原 REQUIRES_PRODUCTION_VERIFICATION 表述）

# 生产侧边界（不过度扩大结论）：
PRODUCTION_ENV_REQUIRED_KEY_PRESENCE = PRE_PRODUCTION_PREFLIGHT
  # target code 没有新增 required env contract，
  # 但正式 production authorization 前仍需确认当前生产 .env.production.local 满足既有 required keys。
  # 本窗口未读取/记录任何 secret value。
```

**不得**写 `PRODUCTION_ENV_VERIFIED`：本窗口没有重新读取生产 secret/config 内容，生产 `.env.production.local` 实际配置仍需 production 执行窗口按既有 keys 核实（变量名/required presence，非 secret）。

---

## 55. Production Untracked Files

生产已知 untracked：
```text
.env.production.local.bak.20260804_172603
milvus_export_full.jsonl
milvus_export_no_vec.jsonl
```

后续任何 deployment/runbook：
```text
DO NOT git clean
DO NOT destructive reset
```
不得删除这些文件。

```text
RB-10 = NOT AUTHORIZED（保持）
```

---

## 56. Git Deployment Strategy

从 f453f44 部署到 9db3f58，但**不执行**。优先 artifact/image deployment（可追踪、可回滚，§28）。**禁止 `git pull`**（origin/master 未来可能超过 9db3f58）。target = exact commit/image。

---

## 57. 禁止 git pull 作为 Targeting Mechanism

```text
PRODUCTION_TARGET != origin/master latest
PRODUCTION_TARGET = exact commit 9db3f58 / exact image
```

---

## 58. Design Alternatives（决策记录）

| 决策点 | Chosen | Rejected | Reason |
| ------ | ------ | -------- | ------ |
| 策略 | SCHEMA_FIRST_WITH_MAINTENANCE_WINDOW（Candidate C 变体） | Candidate A（纯零停机 schema-first） | TEMPORARY_READY_503 + DOCKER_UNHEALTHY + PRODUCTION_ROUTING/MONITORING_UNCERTAINTY + 不必要的运营复杂度（§14-A；非 restart loop） |
| 策略 | — | Candidate B（code-first） | target 9db3f58 不能在 0028 schema 运行（§12） |
| 迁移顺序 | schema-first（先 schema 后 code） | code-first | target 代码需 schema 就绪（§10/§12） |
| 执行方式 | 维护窗口停机切换 | 零停机 | 避免临时 readiness mismatch 暴露给生产流量/监控（§14-B/§16） |
| 部署制品 | exact commit/image tag（immutable） | `git pull` / `:latest` | target 不可控（§56/§57） |
| 迁移制品 | 9db3f58（head=0034） | 36fe68a（head=0035） | 减少 operator error（§20/§31） |
| 回滚 | schema-forward + code rollback（R3，维护态 fallback） | schema downgrade（0034→0028） | 新表数据丢失风险（§36/§37） |
| 回滚（灾难） | DB backup restore | — | catastrophic only（§33/§34） |
| 维护写策略 | 9000 停机消除写流量 | 在线迁移 | 0029/0030 AccessExclusive 锁（§17/§18） |
| 共享镜像 S10 | S10-B（9000 immutable image + 9100 冻结不动） | S10-A（一起升级 9100 0003→0005） | MINIMUM_CHANGE / YAGNI / NO_UNAUTHORIZED_9100_CATCH_UP（§52） |
| rollback identity | runtime image ID（VERIFIED）+ provenance（UNVERIFIED, NON_BLOCKING） | 笼统 ROLLBACK_ARTIFACT_IDENTITY_GAP | C8 拆分（§19/§38） |
| alembic 命令 | `upgrade 0034`（显式 target） | `upgrade head` | operator error 防护（§42） |

---

## 59. YAGNI

不借 baseline catch-up 增加：
```text
new migration framework / new deployment platform / Kubernetes / new Redis
new feature flags / new observability stack / new DB HA
```
只解决 safe 0028→0034 catch-up。

唯一标记的简化 ceiling：维护窗口内 9000 停机消除并发写（§17/§18）——替代了复杂的 online migration 并发控制；upgrade path 是若未来需零停机迁移，需引入 `CREATE INDEX CONCURRENTLY` + online schema change 框架，超出本窗口。

---

## 60. Known Limitations

1. **S10 共享镜像 VERIFIED HARD GATE 未解除**（§51/§52，M3 升级）：9000/9100 同 image ID `93094f0...`（VERIFIED）；9100 baseline=0003（VERIFIED）；9db3f58 树 9100 head=0005。rebuild `:latest` 不即时 mutate 运行中 9100（C5），但 9100 recreate 会触发 expected=0005≠actual=0003 → 503+unhealthy。S10-B 设计已获独立审批 `APPROVED_WITH_CORRECTIONS`，**Release Engineering Implementation Contract 已冻结**（§52 C3.1~C3.12），剩余 = S10-B Implementation（独立实施窗口）→ Independent Implementation Approval → C3 CLOSED。若实现后仍无法隔离 9000/9100 部署身份 → `CATCHUP_DESIGN_BLOCKED`。
2. **ROLLBACK_SOURCE_COMMIT_PROVENANCE = UNVERIFIED**（§19/§38，M4）：image 无 provenance label，无法声称 `93094f0...=f453f44`。runtime image identity VERIFIED、provenance UNVERIFIED，NON_BLOCKING 前提是 runtime image 被可靠保存为 immutable（§52 C3.6 New Target Provenance Contract）。
3. **PRODUCTION_EXTERNAL_AUTOHEAL = UNKNOWN**（§14）：生产宝塔/systemd 是否对 unhealthy 容器自动 restart 未核实。这不改变 Candidate A 裁定（仍 NOT_PREFERRED，理由见 §14-A），但影响 R2/R3 fallback 后 9000 的实际命运。
4. **反代配置不在仓库**（§15）：生产宝塔/nginx 对 /ready 的 upstream 健康检查行为 `REQUIRES_PRODUCTION_VERIFICATION`。
5. **9100 代码 395 行变更未评估**（§51）：9db3f58 树 9100 代码相对 f453f44 有 395 行变更，对 9100 生产行为影响未评估（超出 9000 catch-up 范围，属 S10-A/9100 独立 catch-up）。
6. **生产 `.env.production.local` 既有 required keys 未核实**（§54，CORRECTION-2/C1 后）：代码层 env contract diff = `NONE_DETECTED`（`app/config.py` + 3 个 9100 config 零 diff，`CODE_VERIFIED`），但正式 production authorization 前仍需确认生产 `.env.production.local` 满足既有 required keys（`PRODUCTION_ENV_REQUIRED_KEY_PRESENCE = PRE_PRODUCTION_PREFLIGHT`）。不得写 `PRODUCTION_ENV_VERIFIED`。
7. **IMAGE_BUILD_PROVENANCE_DEBT**（§19/§52 C3.6）：当前 image 无 `org.opencontainers.image.revision` label。未来 target image 从 9db3f58 构建时**必须**带至少一种可追踪 provenance（immutable tag / digest / OCI revision label / build manifest），旧 provenance debt 不得复制到新 target。

---

## 61. Non-Blocking Debt

```text
MUTATING_GET_PROTOCOL_DEBT = NON_BLOCKING / FUTURE（承自 P2 cutover，与本 catch-up 无直接关联）
RB-10 = NOT AUTHORIZED（保持，§55）
9100 RAG catch-up（0003→0005）= OUT OF THIS WINDOW（S10-A/9100 独立 catch-up，需独立设计）
9000/9100 镜像分离 = C3 CONTRACT FROZEN / IMPLEMENTATION PENDING（§52 C3，实施进入 S10-B-9000-9100-IMAGE-IDENTITY-ISOLATION 窗口；本窗口不改 compose）
```

---

## 62. Design Decision

```text
CATCHUP_DESIGN_READY_FOR_APPROVAL
```

依据（CORRECTION-1 + M3/M4 已整合）：
- 迁移链 0028→0034 已独立核实（DDL/事务/锁/数据前提，全 LOW，§4/§7）。
- target 9db3f58 = 合法 0034 baseline（含 P1 消费者+F-1+FC-F1，不含 0035，§3）。
- f453f44 对 0029~0034 业务运行时前向兼容（§11）。
- Candidate A（零停机 schema-first）= NOT_PREFERRED（理由：TEMPORARY_READY_503 + DOCKER_UNHEALTHY + PRODUCTION_ROUTING/MONITORING_UNCERTAINTY + 不必要的运营复杂度，§14-A；**非** restart loop —— Docker `restart: unless-stopped` 不因 unhealthy 自动 restart，§14）。
- Preferred = SCHEMA_FIRST_WITH_MAINTENANCE_WINDOW（Candidate C 变体，§9/§25），核心价值 = 隔离临时 readiness mismatch、避免 unhealthy 旧 9000 状态暴露给生产流量/运维（§14-B）。
- Rehearsal 计划（BR-01~BR-30，drifted fixture，§45-§48）完整；BR-24~30 覆盖 S10 部署身份隔离。
- 回滚三级（R1/R2/R3）+ schema-forward 维护态 fallback + schema downgrade EMERGENCY_ONLY（§35-§37）；R2/R3 不再因"restart loop"判技术不可运行，而是因 readiness 503+unhealthy 不得恢复 NORMAL_PRODUCTION_SERVICE。
- Stop conditions 完整（S1-S12，§40），S10=VERIFIED HARD GATE（M3：同 image ID），S12 业务层。
- Rollback identity 拆分：runtime image VERIFIED（93094f0...）/ provenance UNVERIFIED（NON_BLOCKING，§19/§38）。

**S10 状态**（C11，CORRECTION-2 更新）：
```text
S10_SHARED_IMAGE_COUPLING   = VERIFIED（M3：9000/9100 同 image ID）
S10_RESOLUTION_DESIGN       = IMMUTABLE_SERVICE-SPECIFIC_DEPLOYMENT / DESIGN_APPROVED_WITH_CORRECTIONS
  （S10-B：9000 immutable image from 9db3f58 + 9100 冻结 93094f0.../0003 不 recreate 不 migrate）
S10-B RELEASE ENGINEERING IMPLEMENTATION CONTRACT = FROZEN（CORRECTION-2 / C3，§52 C3.1~C3.12）
若 S10-B 实现后仍无法隔离 9000/9100 部署身份 → CATCHUP_DESIGN_BLOCKED（不得进入 rehearsal/生产执行）
```

**同步输出**：
```text
PRODUCTION_MIGRATION_AUTHORIZED  = NO   （下一步仍需 S10-B implementation + 独立实施审批 + rehearsal 执行/审批 + 生产授权）
ISOLATED_REHEARSAL_AUTHORIZED    = NO   （独立设计审批曾写 YES-CONDITIONAL(C1-C4)，C1/C2/C4 已于本窗口 CLOSED、C3 仅 CONTRACT_FROZEN；
                                          C3 未实施前 ISOLATED_REHEARSAL_ENTRY = NOT YET OPEN，见 §62-A）
```

### 62-A. Design Correction-2 Final Status（CORRECTION-2 / 本窗口）

```text
C1 = APPLIED / CLOSED        （§54：TARGET_CODE_ENV_CONTRACT_DIFF = NONE_DETECTED，CODE_VERIFIED；
                               PRODUCTION_ENV_REQUIRED_KEY_PRESENCE = PRE_PRODUCTION_PREFLIGHT，不写 PRODUCTION_ENV_VERIFIED）
C2 = APPLIED / CLOSED        （§3：FC-F1 evidence path 扩展为 -- app/ apps/；
                               FC-F1 TECHNICAL CONCLUSION = UNCHANGED，不重开 FC-F1/P1 correctness）
C4 = APPLIED / CLOSED        （§47/§48：ISOLATED_REHEARSAL_TOPOLOGY 8 项补全；BR-24~30 = CONTAINER_RUNTIME verification，
                               可观察证据契约（container ID / start timestamp / restart count / DB alembic current）明确）

C3 = IMPLEMENTATION_CONTRACT_FROZEN   （§52 C3.1~C3.12）
C3_IMPLEMENTATION = NOT_STARTED
C3_INDEPENDENT_APPROVAL = NOT_STARTED

S10-B = DESIGN_APPROVED_WITH_CORRECTION / IMPLEMENTATION_REQUIRED
REHEARSAL_DESIGN_CORRECTIONS = PARTIALLY_CLOSED（C1/C2/C4 CLOSED，C3 pending implementation）

REHEARSAL_ENTRY_GATE = BLOCKED_BY_C3_IMPLEMENTATION
  # 即使独立设计审批写 ISOLATED_REHEARSAL_AUTHORIZED = YES（条件 C1-C4 闭环），
  # 本窗口完成后 C3 尚未实施 → ISOLATED_REHEARSAL_ENTRY = NOT YET OPEN
PRODUCTION_MIGRATION_AUTHORIZED = NO
```

不得误写 rehearsal 已可执行。Rehearsal Entry 需 `S10-B implementation` + `independent implementation approval` 通过后才开放。

## 63. Design Approval 后的正确流程（CORRECTION-2 更新）

```text
Reality Audit ✅（VERIFIED）
        ↓
Technical Design（含 CORRECTION-1 + M3/M4）✅（READY_FOR_APPROVAL）
        ↓
S10-B Design Approval（service-specific immutable deployment）✅（APPROVED_WITH_CORRECTIONS）
        ↓
Independent Design Approval ✅（APPROVED_WITH_CORRECTIONS，C1-C4 MUST_APPLY_BEFORE_REHEARSAL）
        ↓
Design Correction-2（本窗口）✅（C1/C2/C4 APPLIED/CLOSED；C3 CONTRACT_FROZEN，不实施）
        ↓
S10-B-9000-9100-IMAGE-IDENTITY-ISOLATION（独立实施窗口，唯一下一阶段）
        ↓    职责：implement minimal release-engineering mechanism（§52 C3.1~C3.12）
        ↓         + tests（RE-T01~T10）+ candidate report
        ↓         NOT run baseline rehearsal
        ↓
Independent Implementation Approval（独立窗口）→ C3 CLOSED
        ↓
Isolated Rehearsal Execution         ← 独立窗口（BR-01~BR-30，含 S10 部署身份隔离 CONTAINER_RUNTIME 验证）
        ↓
Independent Rehearsal Approval       ← 独立窗口
        ↓
Production Authorization             ← 独立窗口（S1-S12 全解除，含 S10-B 闭环）
        ↓
Production Baseline Catch-up         ← 独立执行窗口
        ↓
Production Verification（PV-01~PV-17）
        ↓
B7/B8 Closure
        ↓
Return P2（不直接上 0035）
```

**Rehearsal Entry Gate**：`S10-B implementation` + `independent implementation approval` 通过前，`ISOLATED_REHEARSAL_ENTRY = NOT YET OPEN`（§62-A）。不得跨级。

---

## 64. Candidate Diff / Git Discipline

```text
本窗口产物 = docs/architecture/remediation/PRODUCTION_BASELINE_CATCHUP_0028_TO_0034_DESIGN.md（仅此一份）
CORRECTION-1 + M3/M4 + CORRECTION-2（C1/C2/C4 APPLIED + C3 CONTRACT FROZEN）已原位返修该文件（不追加冲突报告）
DO NOT COMMIT
DO NOT PUSH
```

未修改：
```text
business code / migration / tests / docker-compose / Dockerfile / build scripts / env / frontend / 19000 / 9100
```

CORRECTION-1 仅原位替换设计文件中的错误结论（Docker restart loop 语义、Candidate A 裁定理由、R2/R3、S10 升级 VERIFIED、Rollback identity 拆分）。CORRECTION-2 仅落实独立审批 correction：C1（§54 env）、C2（§3 FC-F1 evidence path）、C4（§47/§48 rehearsal topology + BR-24~30 CONTAINER_RUNTIME）并冻结 C3（§52 Release Engineering Implementation Contract，DO NOT IMPLEMENT）。未追加互相冲突的新报告、未创建双重事实源文档（任务书 §33 禁止新增 `...DESIGN_CORRECTION_2.md`）。Approval 报告与其 Verdict 未改动（任务书 §34）。

---

## 65. Merchant Production Discipline

本设计窗口**不**要求用户在 Merchant 执行任何写操作（`alembic upgrade`/`git pull`/`git checkout`/`docker build`/`docker compose *`/`psql UPDATE/ALTER/CREATE`）。

若缺生产事实，只提 `READ-ONLY EVIDENCE REQUEST`（§52），说明：
```text
WHY REQUIRED: 裁定 S10 真实阻断程度
WHAT DECISION IT BLOCKS: 生产 catch-up 授权（S10 hard gate）
```

---

## 66. STOP

Design Correction-2 完成。

```text
C1 = APPLIED / CLOSED
C2 = APPLIED / CLOSED
C4 = APPLIED / CLOSED

C3 = IMPLEMENTATION_CONTRACT_FROZEN
C3_IMPLEMENTATION = NOT_STARTED
C3_INDEPENDENT_APPROVAL = NOT_STARTED

S10-B = DESIGN_APPROVED_WITH_CORRECTION / IMPLEMENTATION_REQUIRED

REHEARSAL_DESIGN_CORRECTIONS = PARTIALLY_CLOSED（C1/C2/C4 CLOSED，C3 pending implementation）
REHEARSAL_ENTRY_GATE         = BLOCKED_BY_C3_IMPLEMENTATION
ISOLATED_REHEARSAL_ENTRY     = NOT YET OPEN（C3 未实施前不开放）

PRODUCTION_MIGRATION_AUTHORIZED = NO
```

立即停止。禁止自行：
```text
run rehearsal / migrate Merchant / deploy Merchant / build production image
modify compose / implement image vars/override / docker tag
switch git commit / restart services / upgrade 9100 / apply 0035 / enter P3a / RB-10 / commit / push
```

---

*Design Correction-2 窗口结束。只原位修改了 DESIGN 文档（C1/C2/C4 应用 + C3 Contract 冻结）。未执行任何迁移、未改代码/迁移/compose/Dockerfile/env/脚本、未构建或 tag 镜像、未 run rehearsal、未 commit、未 push、未部署。Approval 报告与 Verdict 保持原样。*
