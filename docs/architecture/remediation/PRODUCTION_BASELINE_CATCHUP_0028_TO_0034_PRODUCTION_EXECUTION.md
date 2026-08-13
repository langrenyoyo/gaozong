# PRODUCTION-BASELINE-CATCHUP-0028-TO-0034 — PRODUCTION-EXECUTION

> 窗口：`PRODUCTION-BASELINE-CATCHUP-0028-TO-0034 / PRODUCTION-EXECUTION`
> 窗口性质：独立 Production Execution 执行窗口（fail-closed）
> 执行载体：**本地 Windows 开发机**（`e:\work\project\auto_wechat`，git HEAD=`36fe68a`，Docker 29.6.1 / Compose v5.3.0 / Python 3.14 + alembic 1.18.5）
> 执行日期：2026-08-13
> 前序授权：`..._FOCUSED_PRODUCTION_AUTHORIZATION_R1.md`（`PRODUCTION_AUTHORIZATION = APPROVED / GO_WITH_NON_BLOCKING_FINDINGS`）
> 本窗口职责：按已批准 Production Runbook fail-closed 执行 Merchant 9000 PostgreSQL 0028→0034 并部署冻结 target 9000 release。

---

## 0. 继承授权状态（本窗口不重新审批）

```text
PRODUCTION_AUTHORIZATION        = APPROVED / GO_WITH_NON_BLOCKING_FINDINGS（继承 R1）
BLOCKER-1 RELEASE_ENGINEERING   = CLOSED
BLOCKER-2 EXTERNAL_AUTOHEAL     = CLOSED
BLOCKER-3 MERCHANT_REALITY      = CLOSED
PRODUCTION_MIGRATION_AUTHORIZED = YES
PRODUCTION_EXECUTION_ENTRY      = OPEN
PRODUCTION_MIGRATION_EXECUTED   = NO（授权 ≠ 已执行）
```

## 1. Frozen Boundaries（全程锁死，未改变）

```text
CURRENT_PRODUCTION_CODE = f453f44e6a70de3eb5fa8f808cf4b6a9d72ea6c1
APPLICATION_BASE        = 9db3f5854095e483a55724e66d452792b354ff53
RELEASE_TREE            = a633b4860b818ab48fda5e22f39aa311eb96e9eb
TARGET_9000_ALEMBIC     = 0034
严禁 target = 36fe68a（含 0035 / P2 M04）
9100 CODE UPGRADE = NO / DB MIGRATION = NO / RECREATE = NO / TARGET DB = 0003
0035 = NOT APPLIED（0031 为 intentional gap）
RB-10 CLEANUP = NOT AUTHORIZED
```

## 2. 环境能力边界（★本窗口决定性事实）

本 Production Execution 窗口运行在**本地开发机**，不是 Merchant 生产服务器：

```text
- 可访问 Merchant 生产网关只读端点（远程 /ready 探测 = 200，见 §5 M0-01）
- 无 Merchant 主机 /www/wwwroot/XG_AI_System 文件系统访问
- 无 SSH 通道（M-AUTH 只读窗口已确认；本窗口复核无 ~/.ssh 生产凭据）
- 无法执行生产 docker compose / 迁移 / 部署 / 备份 / 回滚 等任何 mutation
- 生产验证（PV-01~17）所需的生产容器 / 生产 DB / 生产 /ready 内网端点无法由本机真实执行
```

**因此本窗口对以下阶段如实判定为 `NOT_EXECUTABLE_FROM_LOCAL_DEV`（无 Merchant 通道），不执行、不伪造：M1~M11、PV-01~PV-17、rollback 实演。**

本窗口真实完成的部分：M0 中本机可验证的 artifact gate / target content gate / S10-B resolution / rollback readiness 核实，全部给出真实命令输出与结果。

---

## 3. Pre-execution Reality（本机侧）

| 项 | 期望 | 本机实测 | Verdict |
| --- | --- | --- | --- |
| 本机 git HEAD | 主工作区 `36fe68a`（开发主线） | `36fe68a3f5c933d6bc2b50dd7c0bfcacfdb70ce2` | MATCH（开发机现实，非生产） |
| release commit 存在性 | `a633b48` | `git cat-file -t` = commit | MATCH |
| release parent | `9db3f58` | `a633b48` parent = `9db3f5854095e483a55724e66d452792b354ff53` | MATCH |
| release worktree | release/b7-0034-s10b-freeze | `.worktrees/release-0034-s10b-freeze` @ a633b48 | MATCH |
| Docker/Compose | rehearsal 同版本 | Docker 29.6.1 / Compose v5.3.0 / Python 3.14 + alembic 1.18.5 | MATCH |

## 4. M0 Evidence（本机真实执行）

### M0-04 Release Artifact Hard Gate — ✅ PASS（本机验证）

**COMMAND（release tree blob SHA256 计算）**：

```text
git show a633b486...:<path> | sha256sum（8 个 S10-B 冻结文件）
```

**AFTER（全部与 Manifest §3 一致）**：

| 路径 | 实测 SHA256 | Manifest | 结果 |
| --- | --- | --- | --- |
| `.env.production.example` | `9981c2cd...203e69` | `9981c2cd...203e69` | MATCH |
| `docker-compose.yml` | `bde9d833...9e6425d` | `bde9d833...9e6425d` | MATCH |
| `docs/config/ENV_VARIABLE_REFERENCE.md` | `4b2804fe...baf10d` | `4b2804fe...baf10d` | MATCH |
| `scripts/release_9000_s10b.py` | `38a65f27...5fa399c` | `38a65f27...5fa399c` | MATCH |
| `tests/test_s10_b_image_identity_isolation.py` | `f7c278b6...3140d` | `f7c278b6...3140d` | MATCH |
| `S10_B_..._APPROVAL.md` | `6a5781ac...614650` | `6a5781ac...614650` | MATCH |
| `S10_B_..._IMPLEMENTATION.md` | `4cdb5cde...19fb5` | `4cdb5cde...19fb5` | MATCH |
| `S10_B_..._CORRECTION_APPROVAL.md` | `91f4fe6a...d33a0` | `91f4fe6a...d33a0` | MATCH |

**compose S10-B RE-B 身份验证**（release tree `docker-compose.yml`）：

```text
38: image: ${AUTO_WECHAT_API_IMAGE:-xg-ai-system-backend:latest}
73: image: ${XG_DOUYIN_AI_CS_IMAGE:-xg-ai-system-backend:latest}
```

**迁移链单线性验证**（release tree，`revision → down_revision`）：

```text
0030_compute_idempotency.py        : 0030 → 0029
0032_daily_report_generations.py   : 0032 → 0030
0033_material_analysis_executions.py : 0033 → 0032
0034_preview_executions.py         : 0034 → 0033
0029_customer_profiles_jsonb_unify.py : 0029 → 0028
```

```text
RELEASE_SHA256_MATCH = 8/8 MATCH
RELEASE_TREE         = a633b48（parent=9db3f58）VERIFIED
MIGRATION_GRAPH      = 0028→0029→0030→0032→0033→0034 单线（0031 gap 符合设计）
```

### M0-07 Target Image Content Gate — ✅ PASS（迁移图级验证；生产 target image 构建见 §7 无法执行项）

**COMMAND（release worktree，alembic ScriptDirectory 只读加载，不连 DB）**：

```python
from alembic.script import ScriptDirectory
sd = ScriptDirectory.from_config(Config())  # script_location=migrations/postgres/auto_wechat
heads = sd.get_heads()
```

**AFTER**：

```text
HEAD(S) = ['0034']
全部 revision 含 0001~0034，不含 '0035'
assert heads == ['0034']  ==> PASS
ALEMBIC_HEAD = 0034 / 0035 ABSENT（release tree）
```

说明：release tree 与 9db3f58 的 `migrations/**` 零差异（Release Freeze §18 MIGRATION_DIFF=ZERO），且 rehearsal 已 CONTAINER_RUNTIME 验证 target 9db3f58 镜像 `/ready` expected=actual=0034（BR-17/18/29）。因此 release tree 构建的 target 镜像 head=0034 由证据链充分支持。生产 target image 的**实际 build/load** 本机无通道（§7）。

### M0-08 9100 Target Freeze Resolution — ✅ PASS（本机验证 wrapper 机制）

**COMMAND（release worktree，wrapper static/dry-run，未启动任何容器）**：

```text
python scripts/release_9000_s10b.py --env-file <临时测试 env>
python scripts/release_9000_s10b.py --env-file <临时测试 env> --expected-9000 <tgt> --expected-9100 <frozen>
```

（临时 env 仅测试身份 `xg-ai-system-backend:9db3f58-s10b-test` / `...:frozen-93094f0`，无任何真实 secret，用后即删。）

**AFTER（正向）**：

```text
resolved 9000 image : xg-ai-system-backend:9db3f58-s10b-test
resolved 9100 image : xg-ai-system-backend:frozen-93094f0
identity isolation PASS
canonical command : docker compose --env-file <f> -f ...docker-compose.yml up -d --no-deps --no-build auto-wechat-api
exit = 0
```

**AFTER（fail-closed 负向）**：

```text
# 9000 回落 :latest → PREFLIGHT FAILED（拒绝 P3），exit=1
# --expected-9000 WRONG-IMAGE → PREFLIGHT FAILED（拒绝 P-EXPECTED），exit=1
```

```text
RESOLVED_9000 = target immutable（可独立指定）
RESOLVED_9100 = frozen immutable（可独立指定，与 9000 解耦）
PREFLIGHT_FAIL_CLOSED = VERIFIED（拒绝 :latest / expected mismatch）
CANONICAL_9000_ONLY = VERIFIED（up -d --no-deps --no-build auto-wechat-api，不含 9100）
```

### M0-09 Rollback Procedure Hard Gate — ✅ PASS（文档核实 + rehearsal 证据链）

rollback 全程使用已批准 rehearsal/runbook 验证过的过程（非本窗口现场发明）：

```text
M3  rollback image preservation : docker tag <sha256:93094f0...> xg-ai-system-backend:rollback-0028-<ts>
                                   并 docker image inspect 确认 .Id == sha256:93094f0...（P-S02）
M4  backup                      : pg_dump -F c auto_wechat → aw_backup_<ts>.dump + sha256
                                   verification = pg_restore --list / 等价（P-S03）
M6  migration                   : alembic upgrade 0034（显式 target，9db3f58 制品，P-S09）
rollback（R2/R3 场景）           : wrapper --env-file <9000=old image> --apply（STATE C），
                                   或 M4 backup + rehearsal 验证过的 pg_restore 过程（§73/§74 任务书）
rehearsal 证据                  : BR-20/21/22/23/30 = ISOLATED_CONTAINER/POSTGRESQL_RUNTIME_VERIFIED
                                   （rollback target→old / old app 503 no auto-restart / lock-timeout 原子回滚
                                     / backup-restore dry-run / rollback9000 without touching9100）
```

### M0-01 Current Production Reality — ⚠️ PARTIAL（远程只读旁证 ✅；生产主机内证据 ❌ 本机无通道）

**COMMAND（只读，无副作用）**：

```text
curl -s -w "HTTP_CODE=%{http_code}" https://merchant.xiaogaoai.cn/api/ready
```

**AFTER（远程网关只读旁证）**：

```json
HTTP 200
{"service":"auto_wechat","status":"ok",
 "checks":[{"name":"backend","status":"pass","backend":"postgresql"},
           {"name":"db_connect","status":"pass"},
           {"name":"database_name","status":"pass","expected":"auto_wechat","actual":"auto_wechat"},
           {"name":"alembic_revision","status":"pass","expected":["0028"],"actual":["0028"]},
           {"name":"critical_tables","status":"pass"}]}
```

远程旁证显示生产 9000 仍为 **PG / auto_wechat / expected=actual=0028**，与授权冻结一致（未漂移）。但 M0-01 要求的生产主机内证据（`/www/wwwroot/XG_AI_System` 的 `git rev-parse HEAD` / `$DC ps`）本机无法执行 → 见 §7。

## 5. M0 Verdict

```text
RELEASE SHA MATCH（M0-04）        = ✅ PASS
TARGET HEAD 0034 / no 0035（M0-07） = ✅ PASS
9100 FREEZE CONTRACT（M0-08）      = ✅ PASS（wrapper 机制 + fail-closed 负向）
ROLLBACK PROCEDURE READY（M0-09）  = ✅ PASS（rehearsal 验证过程，未发明）
CURRENT REALITY（M0-01）           = ⚠️ 远程旁证 MATCH（0028），生产主机内证据 NOT_EXECUTABLE
TARGET IMAGE READY（M0-06）        = ❌ NOT_EXECUTABLE（生产侧 build/load 无通道）
STORAGE READY（M0-10）             = ❌ NOT_EXECUTABLE（生产 df -h 无通道）
```

**M0 ≠ PASS**（不满足"current reality MATCH / target image READY / storage READY"三项本机不可验证的硬条件）。

## 6. 本窗口无法执行的阶段（如实记录，不伪造）

以下阶段/验证在本执行窗口（本地开发机、无 Merchant 通道）**无法执行**，如实标注 `NOT_EXECUTABLE_FROM_LOCAL_DEV`，**不以 EXPECTED PASS 代替**：

| 阶段 | 内容 | 本窗口状态 |
| --- | --- | --- |
| M0-01（生产侧） | 生产 `git rev-parse HEAD` / `$DC ps`（f453f44 / 9000 healthy / 9100 healthy） | NOT_EXECUTABLE |
| M0-02 | 生产 9000/9100 `docker inspect`（PRE_C9000/PRE_I9000/PRE_C9100/PRE_I9100/started/restart） | NOT_EXECUTABLE |
| M0-03 | 生产 9000 app/DB=0028、9100 app/DB=0003 逐项 recheck | NOT_EXECUTABLE |
| M0-06 | 生产 target9000 immutable image build/load（TARGET9000_IMAGE_REF/ID/DIGEST） | NOT_EXECUTABLE |
| M0-10 | 生产 `df -h /` / `df -h /www` / `docker system df` | NOT_EXECUTABLE |
| M1 | 停/隔离生产 auto-wechat-api（`docker compose stop auto-wechat-api`） | NOT_EXECUTABLE |
| M2 | 生产写隔离证明（pg_stat_activity / 无持续 writer / P-S08） | NOT_EXECUTABLE |
| M3 | 生产 rollback image 固化 tag + inspect（P-S02） | NOT_EXECUTABLE |
| M4 | 生产 pg_dump backup + sha256 + pg_restore --list（P-S03） | NOT_EXECUTABLE |
| M5 | 生产 target artifact + image + S10-B final resolution re-verify | NOT_EXECUTABLE |
| M6 | 生产 `alembic upgrade 0034`（P-S09） | NOT_EXECUTABLE |
| M7 | 生产 DB=0034 schema/数据/JSONB 验证（P-S10/12） | NOT_EXECUTABLE |
| M8 | 生产 wrapper `--apply` 部署 target9000（P-S06） | NOT_EXECUTABLE |
| M9 | 生产 target9000 /ready 200 expected=actual=0034（P-S13） | NOT_EXECUTABLE |
| M10 | 生产 9100 unchanged（container/image/started/restart/DB=0003，P-S14） | NOT_EXECUTABLE |
| M11 | 退出维护 / 恢复流量 / 退出后 smoke | NOT_EXECUTABLE |
| PV-01~PV-17 | 生产最终验证矩阵 | NOT_EXECUTABLE |
| Rollback 实演 | 生产 rollback 过程 | NOT_EXECUTABLE（未发生 mutation，无回滚需求） |

## 7. Stop / 结论

### 7.1 停止判定

本窗口在 M0 阶段即判定 **无法进入 M1**：

```text
1. M0 硬条件无法本机满足：
     current reality（生产主机内）→ NOT_EXECUTABLE
     target image（生产侧 build/load）→ NOT_EXECUTABLE
     storage（生产侧）→ NOT_EXECUTABLE
2. 本窗口没有任何真实生产 mutation 能力（M1~M11 / PV 全部 NOT_EXECUTABLE）。
3. 依据任务书：
     §6  禁止现场发明执行命令 → 本窗口不发明，仅列出 approved 命令供有权限 operator 执行；
     §9  Execution Report 严禁 EXPECTED PASS 代替真实结果 → 无法执行项如实标注；
     §68 STOP 即 STOP，不得"再试一次/先继续后面"；
     执行窗口纪律"不确认即停"。
```

本窗口**不以任何方式伪造生产证据**（未伪造 /ready 200、未伪造迁移成功、未声称已部署 target 镜像）。

### 7.2 正式输出

```text
PRODUCTION_EXECUTION_STOPPED

TRIGGER                = 环境能力边界（执行窗口无 Merchant 主机访问通道，M0 生产 reality / target image / storage 硬条件无法现场核实；M1~M11 与 PV-01~17 无法真实执行；不得伪造）
PRODUCTION_MIGRATION_EXECUTED = NO
CURRENT DB             = 0028（远程 /ready 只读旁证 expected=actual=0028；未发生任何迁移）
CURRENT 9000           = 生产 f453f44 / 0028（授权冻结；本窗口未触碰）
CURRENT 9100           = 生产 0003（授权冻结；本窗口未触碰）
ROLLBACK_REQUIRED      = NO（未发生任何生产 mutation，无需 rollback）
```

### 7.3 M0 本机已完成的真实产物（供有权限 operator 延续执行）

```text
M0-04  RELEASE_SHA256_MATCH = 8/8 MATCH（release tree a633b48 / parent=9db3f58）
M0-07  ALEMBIC_HEAD = 0034 / 0035 ABSENT（release tree 迁移图验证）
M0-08  S10-B wrapper preflight = PASS（9000=target immutable / 9100=frozen / 拒绝 :latest / 拒绝 expected mismatch / canonical 9000-only）
M0-09  ROLLBACK_PROCEDURE_READY（rehearsal 验证过程：M3 tag → M4 pg_dump -F c + sha256 → M6 alembic upgrade 0034 → wrapper STATE C rollback / pg_restore）
```

### 7.4 延续执行前置条件（下一真实执行窗口 / 有 Merchant 权限 operator）

在具备以下条件的环境中重新打开 Production Execution（不必重跑本窗口 M0 已 PASS 项，但 M0 生产侧 reality / storage / target image 必须重新现场核实）：

```text
1. 可访问 Merchant /www/wwwroot/XG_AI_System（SSH 或等价受控通道）
2. 可执行生产 docker compose / alembic / pg_dump / docker tag（operator 权限）
3. M0-01/02/03 生产 reality 现场复核（HEAD=f453f44 / 9000 0028 healthy / 9100 0003 healthy）
4. M0-06 target9000 immutable image 生产侧 build/load + digest 记录（离线 pre-stage，不依赖 maintenance 期 git pull）
5. M0-10 生产存储容量现场确认
6. 按本报告 §4 + rehearsal 已验证命令顺序执行 M1~M11 → PV-01~17 → B7/B8 closure
7. 执行全程 fail-closed：任何 P-S01~P-S16 触发即 STOP；rollback 用 rehearsal 验证过程
```

## 8. Git / Merchant Discipline

```text
DO NOT COMMIT / DO NOT PUSH（本窗口）
本机主工作区未 commit、未 push
未触碰 Merchant 生产 repo / 生产 env / 生产容器 / 生产 DB
临时测试 env 文件已删除（无残留）
```

## 9. Secret Safety

本窗口记录的生产 `/ready` 响应为公开健康信息（backend/database_name/alembic_revision），**不含**任何 password / DATABASE_URL credential / API KEY / JWT secret / Douyin secret / LLM key。未输出任何 secret 值。

## 10. 文档影响检查（AI 文档自治维护）

- 本轮唯一新增：本报告 `..._PRODUCTION_EXECUTION.md`（执行窗口 STOP 报告，HISTORICAL 执行准备/能力边界记录）。
- **未修改**：`..._FOCUSED_PRODUCTION_AUTHORIZATION_R1.md`（授权 GO 结论不受影响，授权 ≠ 已执行）、Design / Rehearsal / Rehearsal Approval / Release Freeze / Release Manifest / M-AUTH 等历史窗口报告。
- `CLAUDE.md` 治理状态中 `PRODUCTION_MIGRATION_EXECUTED` 仍为 `NO`，与本报告一致，**无矛盾需修正**。
- 本窗口未改变任何生产现实，因此不产生需同步的"当前事实"变化；唯一新增状态是"Production Execution 首窗口因无 Merchant 通道在 M0 停止"，该状态已由本报告承载，无需改写 05_PROJECT_CONTEXT.md 当前结论。

---

*Production Execution 窗口结束。本窗口在本地开发机真实完成 M0 中本机可验证的全部 artifact/机制/回滚就绪核实（8/8 SHA256 MATCH、alembic head=0034 无 0035、S10-B preflight 正向+fail-closed、rollback 过程就绪），并对生产 reality 完成远程只读旁证（/ready=200 expected=actual=0028）。因执行窗口无 Merchant 主机访问通道，M0 生产侧硬条件与 M1~M11、PV-01~17 无法真实执行，本窗口 fail-closed 停止，如实输出 `PRODUCTION_EXECUTION_STOPPED`；未发生任何生产 mutation，无需 rollback；未伪造任何生产证据。*

---

# ATTEMPT 2 — MERCHANT-OPERATOR-R1（协同执行窗口）

> 窗口：`PRODUCTION-EXECUTION-MERCHANT-OPERATOR-R1`
> 打开时间：2026-08-13
> 执行模型：VibeCoding 下发 → Merchant Operator 在生产主机 `/www/wwwroot/XG_AI_System` 真实执行 → 回填 stdout/stderr → VibeCoding 裁定 PASS/STOP/ROLLBACK → 逐批推进
> 本部分与 ATTEMPT 1 的关系：ATTEMPT 1 = LOCAL / STOPPED / NO MUTATION（保留，不改写）；本部分独立记录 MERCHANT-OPERATOR-R1 真实执行过程。

## A2-0 继承状态（本窗口不重新审批）

```text
PRODUCTION_AUTHORIZATION        = APPROVED / GO_WITH_NON_BLOCKING_FINDINGS
BLOCKER-1/2/3                   = CLOSED
PRODUCTION_MIGRATION_AUTHORIZED = YES
PRODUCTION_EXECUTION_ENTRY      = OPEN
PREVIOUS_LOCAL_EXECUTION_ATTEMPT = STOPPED_BEFORE_PRODUCTION_MUTATION
PRODUCTION_MIGRATION_EXECUTED   = NO
ROLLBACK_REQUIRED               = NO
```

## A2-1 Frozen Production Contract（锁死）

```text
AUTHORIZED STARTING CODE = f453f44e6a70de3eb5fa8f808cf4b6a9d72ea6c1
APPLICATION_BASE         = 9db3f5854095e483a55724e66d452792b354ff53
RELEASE_TREE             = a633b4860b818ab48fda5e22f39aa311eb96e9eb
TARGET 9000 DB           = 0034
TARGET 9000 RELEASE      = a633b486
9100 TARGET DB           = 0003（CODE UPGRADE=NO / MIGRATION=NO / RECREATE=NO）
0035                     = EXCLUDED
RB-10 CLEANUP            = NOT AUTHORIZED
严禁 target              = 36fe68a / current main HEAD / 0035
```

## A2-2 批次推进记录（实时追加，严禁 EXPECTED PASS 代替真实结果）

| 批次 | 阶段 | 状态 | 备注 |
| --- | --- | --- | --- |
| Batch 0A | M0 Current Reality Recheck | ✅ **PASS**（2026-08-13，operator 真实回填） | 只读命令；无 mutation；证据见 A2-5 |
| Batch 0B | Artifact / Rollback Readiness | 待 0A PASS | — |
| Batch 0C | Target Image + Pre-maintenance Gate | 待 0B PASS | — |
| Batch 1~11 | M1~M11 生产生命周期 | 待前序全 PASS | — |
| Batch PV | PV-01~PV-17 | 待退出维护前后完成 | — |

## A2-3 保护文件（全程不得删除/覆盖/清理）

```text
.env.production.local.bak.20260804_172603
milvus_export_full.jsonl
milvus_export_no_vec.jsonl
```

## A2-4 Git / Secret / 宝塔纪律（继承窗口硬约束）

```text
NO COMMIT / NO PUSH（Execution 完成前）
Operator 禁止：git pull / fetch / clean / reset --hard / docker prune / 手动改 DB / 手工改 production env / 宝塔 Compose Restore/Restart/Recreate（除非 approved Runbook 明确要求）
Secret：operator 回填前 REDACT（POSTGRES_PASSWORD / DATABASE_URL password / API KEY / JWT / Douyin secret / LLM key）；VibeCoding 不得要求 cat .env.production.local
```

## A2-5 阶段记录

### Batch 0A — M0 Current Production Reality（VERDICT = PASS，2026-08-13）

**COMMANDS EXECUTED（只读）**：git rev-parse HEAD / git branch --show-current / git status --porcelain=v1 / `$DC ps -a` / `docker inspect`（9000、9100、frontend、postgres）/ worker 探测 / `curl merchant.xiaogaoai.cn/api/ready` / `curl http://127.0.0.1:9100/ready` / `df -h` / `docker system df`。

**RAW OUTPUT（摘要，operator 完整回填）**：

```text
Git HEAD            = f453f44e6a70de3eb5fa8f808cf4b6a9d72ea6c1（branch=master）
git status          = 仅 3 untracked：.env.production.local.bak.20260804_172603 /
                       milvus_export_full.jsonl / milvus_export_no_vec.jsonl（无 tracked 修改）
Compose services    = auto-wechat-api / auto-wechat-frontend / xg-douyin-ai-cs / postgres（无额外 worker/scheduler）
9000                = xg-auto-wechat-api  RuntimeImage=sha256:93094f0a02ba...  RestartCount=0  healthy
9100                = xg-douyin-ai-cs    RuntimeImage=sha256:93094f0a02ba...（与 9000 同镜像）RestartCount=0  healthy
worker 探测         = NO_WORKER_MATCH
9000 /ready         = HTTP 200  backend=postgresql  database=auto_wechat  expected=["0028"] actual=["0028"]
9100 /ready         = HTTP 200  backend=postgresql  database=xg_douyin_ai_cs  expected=["0003"] actual=["0003"]
                      Milvus: connected=true / collection_exists=true / schema_match=true / query_ok=true
storage             = /dev/vda2 492G / 158G used / 315G avail（34%）；docker system df 正常
```

**VERDICT**：

```text
Git HEAD=f453f44 ✅ / 无 tracked 修改 ✅ / 拓扑 4 services 无 worker ✅ /
9000 healthy DB=0028 app=0028 ready 0028 ✅ / 9100 healthy DB=0003 app=0003 ready 0003 ✅ /
9000 与 9100 runtime 均=sha256:93094f0... restart=0 ✅ / 存储 315G 可用 ✅
BATCH 0A VERDICT = PASS（material reality 与授权起点一致，无 drift）
```

### Batch 0B — Artifact / Rollback Readiness

> Attempt 2 当时 Batch 0B STOPPED_PRE_MUTATION（stop_reason = release artifact absent，production 本机无 private remote）。
> 该 blocker 由 **ATTEMPT 3（MERCHANT-OPERATOR-R2）** 的 public-origin transport 解除并补齐；本节 verdict 由 Attempt 3 接力裁定，**不另起 active execution truth**（见下方 ATTEMPT 3）。

---

# ATTEMPT 3 — MERCHANT-OPERATOR-R2（协同执行窗口）

> 窗口：`PRODUCTION-EXECUTION-MERCHANT-OPERATOR-R2`
> 与 ATTEMPT 2 的关系：ATTEMPT 2 / R1 授权 GO，但 Batch 0B 因 release artifact absent 停在 PRE_MUTATION。
> ATTEMPT 3 不重新审批 / 不重做 Rehearsal / 不重做 Release Freeze；只在用户批准的窄范围治理覆盖下完成 transport 并补齐 Batch 0B。

## A3-0 用户窄范围治理覆盖（本窗口 ONLY，不可泛化）

```text
PUBLIC_ORIGIN_TRANSPORT_OVERRIDE = USER_APPROVED
PRIVATE_REMOTE_REQUIRED          = WAIVED FOR THIS RELEASE ONLY
AUTHORIZED_RELEASE               = a633b4860b818ab48fda5e22f39aa311eb96e9eb
APPLICATION_BASE                 = 9db3f58
PUBLIC_VISIBILITY_RISK           = ACCEPTED / NON_BLOCKING
```

覆盖**只允许**：现有 public origin → exact frozen release transport → Merchant 独立 staging → integrity verification。
**绝不授权**：production git pull / checkout release / merge/reset/rebase / deploy origin/master latest / maintenance-time remote dependency / 0035 / 9100 upgrade。

```text
RELEASE_ARTIFACT_DELIVERY_EXCEPTION_R1 = HISTORICAL NO_GO   （当时要求 private remote，保留不改写）
PUBLIC_ORIGIN_TRANSPORT_OVERRIDE       = APPROVED BY USER   （随后用户明确批准）
```

## A3-1 Frozen Contract（继承 A2-1，锁死）

```text
AUTHORIZED RELEASE = a633b4860b818ab48fda5e22f39aa311eb96e9eb
APPLICATION_BASE    = 9db3f5854095e483a55724e66d452792b354ff53
PROD HEAD (must hold)= f453f44e6a70de3eb5fa8f808cf4b6a9d72ea6c1
MIGRATION_TARGET    = 0034   /   0035 = ABSENT
TRANSPORT_REF       = release/b7-0034-s10b-freeze
STAGE               = /www/wwwroot/XG_AI_System_release_0034_a633b486
PROD                = /www/wwwroot/XG_AI_System（全程 NO git pull/fetch/checkout/reset/rebase/merge）
```

## A3-2 Transport 阶段记录（operator 真实回填，gate 全 fail-closed 比对冻结 SHA）

### R2-A 本地公开 origin transport preflight（开发机，只读）

```text
git show --no-patch a633b486  → commit=a633b486  parent=9db3f5854095e483a55724e66d452792b354ff53 ✓
git ls-remote origin refs/heads/release/b7-0034-s10b-freeze → 无输出（Case A：remote ref 不存在，允许创建；非 drift）
git fetch origin --prune --tags → 干净
git for-each-ref --contains 9db3f58 refs/remotes/origin/ → 无输出
  → PUBLIC_BASE_ANCESTRY = NOT_REMOTE_REACHABLE → R2-T01 STOP（public-history review）
```

### R2-A 公开历史只读 secret audit（origin/master..a633b486，20 个新增公开提交）

```text
PUBLIC_HISTORY_SECRET_AUDIT = PASS
SENSITIVE_HISTORY_FOUND     = NO
NEW_PUBLIC_COMMITS          = 20
PUBLIC_HISTORY_EXPANSION    = SAFE_TO_ACCEPT
```
审计项：AKLT/TOS 预签名/私钥/长 base64 = NONE；3 敏感文件（.env.production.example / 2 SQL）逐文件 = 占位默认值 + OWNER/GRANT 契约，无口令无凭据；evidence json = schema 指纹快照非行数据；release_9000_s10b.py 硬编码密钥 = NONE；PII 兜底 = NONE。
20 提交均为 P1 算力幂等 / DB-BL-2 基线 / 0032~0034 PG 验证 / F-1 幂等 / M04 claim-lease / S10-B 镜像身份隔离的治理闭环记录。

```text
R2-T01（public-history review） = 用户当场解除（PUBLIC_VISIBILITY_RISK 已预批 ACCEPTED）
```

### R2-B push exact frozen ref（唯一授权 remote mutation）

```text
git push origin a633b486:refs/heads/release/b7-0034-s10b-freeze  → [new branch] ✓
git ls-remote re-verify → a633b4860b818ab48fda5e22f39aa311eb96e9eb  ✓ exact
REMOTE_RELEASE_REF = exact a633b486  → PASS
```
未 push master / 未 --all / 未 --mirror / 未 --force / 未 current HEAD。

### R2-C Merchant isolated clone（MERCHANT_STAGING_FILESYSTEM_MUTATION=YES）

```text
SEG1_PASS prod_head=f453f44e6a70de3eb5fa8f808cf4b6a9d72ea6c1 stage_absent=YES
SEG2_PASS clone_rc=0   （git clone --no-tags --single-branch --branch release/b7-0034-s10b-freeze）
PRODUCTION_RUNTIME_MUTATION=NO / PRODUCTION_DB_MUTATION=NO / MAINTENANCE_ENTERED=NO
```

### R2-D exact SHA + parent + worktree + Manifest + 0034/no0035（全 fail-closed）

```text
SEG3_PASS head=a633b4860b818ab48fda5e22f39aa311eb96e9eb
          parent=9db3f5854095e483a55724e66d452792b354ff53
          rev=0034 down=0033 0035=ABSENT manifest=8/8
MIGRATION_SET = 0029 / 0030 / 0032 / 0033 / 0034（0031 跳号、0035 缺席，符合冻结）
Manifest 8/8：.env.production.example / docker-compose.yml / ENV_VARIABLE_REFERENCE.md /
             release_9000_s10b.py / test_s10_b_image_identity_isolation.py / S10-B 三份报告 全 OK
```

### R2-E production worktree isolation recheck（fail-closed）

```text
SEG4_PASS prod_head=f453f44e6a70de3eb5fa8f808cf4b6a9d72ea6c1 worktree_clean=YES
（仅 3 known protected untracked，无 tracked 改动，无 release 文件入侵）
```

## A3-3 Batch 0B backup-dir discovery（EXECUTION_COMMAND_GAP → 已解）

```text
DISK_CAPACITY   = /dev/vda2 492G / used 34% / avail 315G  → PASS
DOCKER_DISK     = images 69.65G(99% reclaimable) / build cache 63.15G  → 非阻断观察
BACKUP_DIR      = /www/backup  EXISTS / avail 315G  → 选定
  注：runbook 未预先冻结绝对路径，此为 filesystem 证据推断值（非 runbook 冻结值）。
HISTORICAL_TRACE = 无
```

## A3-4 Batch 0B 最终 Verdict（接力 Attempt 2 待定项）

```text
artifact    = PASS (a633b486 staged, SHA verified)
manifest    = PASS (8/8)
head0034    = PASS
no0035      = PASS
pg_dump     = PASS (16.14, Attempt2 已验)
pg_restore  = PASS (16.14, Attempt2 已验)
backup path = PASS (/www/backup EXISTS)
backup cap  = PASS (315G free)
BATCH 0B    = PASS
```

## A3-5 Transport Gate 最终裁定

```text
REMOTE_RELEASE_REF          = exact a633b486            ✓
STAGING isolated            = YES                        ✓
STAGING HEAD                = exact a633b486            ✓
STAGING WORKTREE            = clean                      ✓
PARENT                      = exact 9db3f58 full         ✓
MANIFEST                    = 8/8 MATCH                  ✓
ALEMBIC TARGET              = 0034                       ✓
0035 ALEMBIC                = ABSENT                    ✓
PRODUCTION HEAD             = still f453f44             ✓
PRODUCTION TRACKED WORKTREE = unchanged                 ✓
PUBLIC_ORIGIN_TRANSPORT     = VERIFIED
ARTIFACT_STAGED             = YES
MERCHANT_STAGING_FILESYSTEM_MUTATION = YES
PRODUCTION_RUNTIME_MUTATION / PRODUCTION_DB_MUTATION / MAINTENANCE_ENTERED = NO
ROLLBACK_REQUIRED           = NO
```

## A3-6 Public transport 风险归档（Step 21）

```text
PUBLIC_ORIGIN_TRANSPORT_OVERRIDE = USER_APPROVED
SCOPE                            = a633b486 ONLY
PUBLIC_VISIBILITY                = ACCEPTED NON_BLOCKING RISK
SECRET_AUDIT                     = PASS（此前公开历史审计 CLEAN）
PRODUCTION_GIT_PULL              = PROHIBITED
PRODUCTION_WORKTREE              = remained f453f44
MAINTENANCE_TIME_NETWORK_DEPENDENCY = PROHIBITED
```

本次例外**不可泛化**为项目规则（不得写成"production can always git pull public repo"）。
正确表述：`ONE-TIME RELEASE TRANSPORT EXCEPTION FOR a633b486 ONLY`；下一次 production release 重新评估。

## A3-7 批次推进记录（接力更新）

| 批次 | 阶段 | 状态 | 备注 |
| --- | --- | --- | --- |
| Batch 0A | M0 Current Reality Recheck | ✅ PASS（Attempt2） | 只读，无 mutation |
| Batch 0B | Artifact / Rollback Readiness | ✅ **PASS**（Attempt3 接力） | public transport + staging + backup-dir discovery 补齐 |
| Batch 0C | Target Image + Pre-maintenance Gate | ✅ **PASS**（Attempt3，2026-08-13） | target image build+content+S10-B preflight+runtime unchanged，详见 A3-9 |
| PRE-M1 | Execution Env Relocation + Runtime Snapshot | ✅ **PASS**（2026-08-13） | release-exec.env 迁出 STAGE→/root/.xg-ai-release(700/600)，SHA frozen，详见 A3-10~A3-12 |
| M1 | Enter Maintenance（9000-only stop） | ✅ **PASS**（2026-08-13） | 9000 stopped/Exited(0)，9100 逐位不变，postgres/frontend healthy，详见 A3-13~A3-16 |
| M2 | Verify Write Isolation | ✅ **PASS**（2026-08-13） | WRITE_ISOLATION=VERIFIED，DB sessions/locks/txns 全 0 rows，mutation counter 15s 稳定，详见 A3-18~A3-23 |
| M3 | Preserve Rollback Image | ✅ **PASS**（2026-08-13） | ROLLBACK_IMAGE_PRESERVATION=VERIFIED，rollback ref 指向 93094f0，runtime 不变，详见 A3-25~A3-30 |
| M4 | Create + Verify DB Backup | ✅ **PASS**（2026-08-13） | PRODUCTION_DB_BACKUP=VERIFIED/RESTORE_READINESS=VERIFIED，pg_dump -F c→/www/backup，SHA bee463c2...，pg_restore --list RC=0，详见 A3-32~A3-40 |
| M5 | Final Target Verification | ✅ **PASS**（2026-08-13） | FINAL_TARGET_VERIFICATION=VERIFIED/M6_ENTRY_GATE=OPEN，二十项全 PASS，详见 A3-42~A3-51 |
| M6 | Migrate 0028 → 0034 | ✅ **PASS**（2026-08-13） | PRODUCTION_DB=0034/PRODUCTION_MIGRATION_EXECUTED=YES，target image one-off 容器 `alembic upgrade 0034` RC=0，详见 A3-53~A3-61 |
| M7 | Verify DB0034 / Schema / Data | ✅ **PASS**（2026-08-13） | DB0034_SCHEMA/DATA/PRODUCTION_ACCEPTANCE=VERIFIED/M8_ENTRY_GATE=OPEN，十七项全 PASS，详见 A3-63~A3-73 |
| M8 | Deploy Target9000 | ✅ **PASS**（2026-08-13） | TARGET9000_DEPLOYED=YES/RUNTIME_IDENTITY=VERIFIED/M9_ENTRY_GATE=OPEN，S10-B --apply RC=0，详见 A3-75~A3-84 |
| M9 | Verify Target9000 Ready | ✅ **PASS**（2026-08-13） | TARGET9000_HEALTH/READINESS/DB_COMPATIBILITY/PUBLIC_READY=VERIFIED/M10_ENTRY_GATE=OPEN，十五项全 PASS，详见 A3-86~A3-94 |
| M10 | Final Verify 9100 Unchanged | ✅ **PASS**（2026-08-13） | 9100_FINAL_UNCHANGED_VERIFICATION=VERIFIED/M11_ENTRY_GATE=OPEN，十四项全 PASS，详见 A3-96~A3-102 |
| M11 | Exit Maintenance | ✅ **PASS**（2026-08-13） | PRODUCTION_RELEASE_COMPLETE=YES/MAINTENANCE_ENTERED=NO/PRODUCTION_BASELINE_CATCHUP_0028_TO_0034=COMPLETE，十六项全 PASS（Case B STATE_CLOSURE_ONLY，无额外 runtime mutation），详见 A3-104~A3-113 |
| **完成** | **PRODUCTION_BASELINE_CATCHUP_0028_TO_0034 = COMPLETE** | ✅ **2026-08-13T08:11:44Z** | M0/M1~M11 全 PASS，DB 0028→0034，target9000 部署+验收，9100 零影响，回滚资产冻结 |

## A3-8 STOP 边界（Transport 阶段已全部 PASS，本窗口停在 Batch 0C 入口）

```text
R2-T01 9db3f58 not remote-reachable          = 用户当场解除
R2-T02 remote release ref wrong SHA          = 未触发（Case A）
R2-T03 push/fetch network failure            = 未触发
R2-T04 stage path exists unexpectedly         = 未触发
R2-T05 stage HEAD != a633b486                 = 未触发
R2-T06 manifest mismatch                     = 未触发
R2-T07 0034 missing / unexpected 0035        = 未触发
R2-T08 production HEAD/worktree changed      = 未触发
```

```text
下一步 = BATCH 0C（target immutable image preparation）
        target 必须从 $STAGE（a633b486）构建，immutable tag，NOT :latest，
        build 命令来自已批准 Dockerfile.backend.dev / Release Freeze / Rehearsal / Production Authorization，不现场发明。
本窗口在此停止等 Operator 回填，不一次性下发到 M1/M6。
```

---

# ATTEMPT 3 — Batch 0C — Target Immutable Image Preparation（2026-08-13）

> Batch 0C 是进入维护窗口前最后一道准备门。通过后下一步才是真正具业务影响的 M1 — ENTER MAINTENANCE。
> 全段 operator 真实回填 + fail-closed gate 自动比对冻结值。Batch 0C 全程**未进入维护、未碰运行容器、未迁移 DB**。

## A3-9 Batch 0C Frozen Identity

```text
TARGET9000_IMAGE_REF    = xg-ai-system-backend:b7-0034-a633b486
TARGET9000_IMAGE_ID     = sha256:4b4f96fc75c63c49401d66ed9ca96bcac0d49681d68b41b88f5c948a3af1ae0f
TARGET9000_IMAGE_DIGEST = xg-ai-system-backend@sha256:4b4f96fc75c63c49401d66ed9ca96bcac0d49681d68b41b88f5c948a3af1ae0f
FROZEN9100_IMAGE_REF    = xg-ai-system-backend@sha256:93094f0a02ba3a4570160ce90625cb80fdec85076046fc314f5fe407add36c68
  （取值依据：E1b 实测老镜像 RepoDigests，老镜像现成 immutable digest 形态，非现场发明 tag）
RELEASE_EXEC_ENV        = /www/wwwroot/XG_AI_System_release_0034_a633b486/release-exec.env  (mode 600, root-only)
  （从生产 .env.production.local 派生，仅覆盖/补充两个 IMAGE 键；0C-E/M5/M8 全程复用同一文件；不修改 .env.production.local 本身）
OLD_RUNTIME_IMAGE       = sha256:93094f0a02ba3a4570160ce90625cb80fdec85076046fc314f5fe407add36c68
```

## A3-9.1 Batch 0C 分段记录

### 0C-A Pre-build Reality = PASS（只读 + fail-closed）

```text
stage_head   = a633b486  ✓ (gate)
stage        = CLEAN
prod_head    = f453f44   ✓ (gate)
prod_worktree= clean (3 known protected untracked)
9000 RuntimeImage = sha256:93094f0... | Restart=0 | Health=healthy | StartedAt=2026-08-06T15:51:36.842166568Z
9100 RuntimeImage = sha256:93094f0... | Restart=0 | Health=healthy | StartedAt=2026-08-06T15:51:36.764350664Z
target tag available（0C-S03 未触发）
PRE_0C_9000_CID = a4421aabee73d41034eef9d8ac3534c8228d1192b0775f541cc98ab2c5314c18
PRE_0C_9100_CID = 49548f1bad1abad38eecb260c6c84fe64f3616023bab7e76d2353027d1bf1373
```

### 0C-B Target Image Build = PASS

```text
BUILD_COMMAND      = docker build -f Dockerfile.backend.dev -t xg-ai-system-backend:b7-0034-a633b486 .
BUILD_EXIT_CODE    = 0
BUILD_CONTEXT      = /www/wwwroot/XG_AI_System_release_0034_a633b486（staging tree，非 production tree）
BUILD_SOURCE_HEAD  = a633b4860b818ab48fda5e22f39aa311eb96e9eb
```
未现场改 Dockerfile / 改代码 / 改 latest / 用 production tree。

### 0C-C Target Image Identity = PASS（fail-closed）

```text
TargetID      = sha256:4b4f96fc75c63c49401d66ed9ca96bcac0d49681d68b41b88f5c948a3af1ae0f
RepoTags      = ["xg-ai-system-backend:b7-0034-a633b486"]（无 :latest）
target != old = PASS (0C-S05：4b4f96fc... != 93094f0...)
tag_consistency = PASS (resolved == frozen，0C-S06 未触发)
```

### 0C-D Image Content Verification = PASS（one-off --network none 容器，不连生产 DB）

```text
AUTO_WECHAT ALEMBIC HEAD = 0034 (head)  ✓ (0C-S06/P-S05 未触发)
0034 revision = "0034" / down_revision = "0033"  ✓（file-level 双证据）
0035 ABSENT   ✓ (0C-S07/P-S11 未触发)
IMAGE_LAYOUT = /workspace/migrations/postgres/auto_wechat（与 Dockerfile WORKDIR/COPY 一致，§15 未触发）
```

### 0C-E S10-B Preflight / Dry-run = PASS

**0C-E1 Discovery**（只读）：
```text
wrapper CLI 合同 = --env-file / --expected-9000 / --expected-9100 / --dry-run / --apply
old image RepoDigests = xg-ai-system-backend@sha256:93094f0...（现成 immutable digest，9100 frozen ref 可用，S10B_9100_IMMUTABLE_REF_GAP 未命中）
env file IMAGE keys = ABSENT（生产 .env.production.local 无 S10-B 两键，预期：生产 0028 从未配过）
host env pollution = wrapper compose_env() sanitize 生效（HOST_ENV_POLLUTION_GAP = CLOSED）
python3（生产主机 python 不存在，用 python3）
```

**0C-E2 派生 Release Execution Env + concrete preflight**：
```text
RELEASE_ENV = STAGE/release-exec.env（mode 600 root-only，从 .env.production.local 派生 + 追加两 IMAGE 键）
AUTO_WECHAT_API_IMAGE = xg-ai-system-backend:b7-0034-a633b486
XG_DOUYIN_AI_CS_IMAGE = xg-ai-system-backend@sha256:93094f0...
resolved 9000 image : xg-ai-system-backend:b7-0034-a633b486  ✓ (0C-S08)
resolved 9100 image : xg-ai-system-backend@sha256:93094f0...  ✓ (0C-S09)
identity isolation PASS（均非 :latest，P3 未触发；非相同共享 mutable，P4 未触发）
WRAPPER_PREFLIGHT_RC = 0
canonical 9000-only command = docker compose --env-file <RELEASE_ENV> -f <STAGE>/docker-compose.yml up -d --no-deps --no-build auto-wechat-api
```
全程 `--dry-run`，未 `--apply`、未 up/restart、未打 tag、未写生产 env file。

### 0C-F Runtime Unchanged Recheck + /ready = PASS（fail-closed 比对 0C-A 基线）

```text
post_0c_9000_cid = a4421aabee73... = PRE_0C_9000_CID ✓ (0C-S11 逐位一致)
post_0c_9100_cid = 49548f1bad1a... = PRE_0C_9100_CID ✓ (0C-S11 逐位一致)
9000 Image=93094f0.../Restart=0/StartedAt=2026-08-06T15:51:36.842.../Health=healthy ✓
9100 Image=93094f0.../Restart=0/StartedAt=2026-08-06T15:51:36.764.../Health=healthy ✓
9000 /ready = HTTP200 expected=actual=0028 ✓（未迁移）
9100 /ready = HTTP200 expected=actual=0003 + milvus connected/schema_match/query_ok ✓（冻结）
```

## A3-9.2 Batch 0C Stop Conditions（全未触发）

```text
0C-S01 STAGE drift                    = 未触发
0C-S02 PROD drift                     = 未触发
0C-S03 target tag already exists      = 未触发
0C-S04 docker build failure           = 未触发
0C-S05 target == old runtime          = 未触发
0C-S06 target head !=0034             = 未触发
0C-S07 image contains 0035            = 未触发
0C-S08 wrapper resolve9000 失败       = 未触发
0C-S09 wrapper resolve frozen9100 失败= 未触发
0C-S10 preflight 指向 latest          = 未触发
0C-S11 容器 ID/image/restart/startedAt 变化 = 未触发
0C-S12 readiness 异常                  = 未触发
```

## A3-9.3 Batch 0C Mutation 分类（Step 33）

```text
DOCKER_IMAGE_BUILD_MUTATION              = YES
DOCKER_IMAGE_METADATA_MUTATION           = YES
PRODUCTION_APPLICATION_RUNTIME_MUTATION  = NO
PRODUCTION_DATABASE_MUTATION             = NO
PRODUCTION_WORKTREE_MUTATION             = NO
ENV_PRODUCTION_MUTATION                  = NO（仅新建派生 release-exec.env，不修改 .env.production.local）
MAINTENANCE_ENTERED                      = NO
ROLLBACK_REQUIRED                        = NO
```

## A3-9.4 Batch 0C Verdict（Step 32 全字段记录）

```text
BATCH_0C                = PASS
BUILD_CONTEXT           = /www/wwwroot/XG_AI_System_release_0034_a633b486
BUILD_SOURCE_HEAD       = a633b4860b818ab48fda5e22f39aa311eb96e9eb
TARGET9000_IMAGE_REF    = xg-ai-system-backend:b7-0034-a633b486
TARGET9000_IMAGE_ID     = sha256:4b4f96fc75c63c49401d66ed9ca96bcac0d49681d68b41b88f5c948a3af1ae0f
TARGET9000_IMAGE_DIGEST = xg-ai-system-backend@sha256:4b4f96fc75c63c49401d66ed9ca96bcac0d49681d68b41b88f5c948a3af1ae0f
TARGET_ALEMBIC_HEAD     = 0034
TARGET_0035_STATUS      = ABSENT
S10B_PREFLIGHT          = PASS (RC=0, --dry-run)
S10B_RESOLVED_9000      = xg-ai-system-backend:b7-0034-a633b486
S10B_RESOLVED_9100      = xg-ai-system-backend@sha256:93094f0a02ba3a4570160ce90625cb80fdec85076046fc314f5fe407add36c68
PRE_0C_9000_CONTAINER_ID  = a4421aabee73d41034eef9d8ac3534c8228d1192b0775f541cc98ab2c5314c18
POST_0C_9000_CONTAINER_ID = a4421aabee73d41034eef9d8ac3534c8228d1192b0775f541cc98ab2c5314c18
PRE_0C_9100_CONTAINER_ID  = 49548f1bad1abad38eecb260c6c84fe64f3616023bab7e76d2353027d1bf1373
POST_0C_9100_CONTAINER_ID = 49548f1bad1abad38eecb260c6c84fe64f3616023bab7e76d2353027d1bf1373
PRODUCTION_RUNTIME_MUTATION = NO
PRODUCTION_DATABASE_MUTATION = NO
MAINTENANCE_ENTERED         = NO
VERDICT = PASS
```

## A3-9.5 Batch 0C 冻结状态（Step 34）

```text
BATCH_0A = PASS
BATCH_0B = PASS
BATCH_0C = PASS

TARGET9000_IMAGE       = FROZEN
TARGET9000_IMAGE_REF   = xg-ai-system-backend:b7-0034-a633b486
TARGET9000_IMAGE_ID    = sha256:4b4f96fc75c63c49401d66ed9ca96bcac0d49681d68b41b88f5c948a3af1ae0f
TARGET ALEMBIC         = 0034
0035                   = ABSENT
S10B 9000 RESOLUTION   = VERIFIED
S10B 9100 FREEZE       = VERIFIED（frozen digest ref，非 :latest）
PRODUCTION 9000        = STILL OLD 0028（未迁移，runtime image 仍 93094f0）
PRODUCTION 9100        = STILL 0003（冻结，未变）
MAINTENANCE_ENTERED    = NO
```

## A3-9.6 STOP — 不进 M1（Step 35）

```text
BATCH_0C = PASS

M0_PRE_MAINTENANCE_PREPARATION = COMPLETE

NEXT_GATE   = M1 ENTER MAINTENANCE
M1_EXECUTED = NO
PRODUCTION_MIGRATION_EXECUTED = NO
```

Batch 0C PASS 后**停止**，不一次性给 M1~M6。下一次进入 M1 必须先得到用户显式确认，因为从 M1 开始第一次会真正中断/改变 production application runtime。M8 apply 届时需在 STAGE 目录执行 wrapper `--env-file <RELEASE_ENV> --apply`（canonical command 的 `-f` 指向 STAGE 树的 S10-B image-env 化 docker-compose.yml）；此为 M 阶段关注点，本批次不下发。

---

# ATTEMPT 3 — PRE-M1 Execution Env Relocation + M1 Enter Maintenance（2026-08-13）

> 用户显式授权范围：PRE-M1 execution env relocation + M1（停止/隔离 9000 write path）。**不提前进入 M2/M3/M4/M5/M6。**
> 全段 operator 真实回填 + fail-closed gate。

## A3-10 PRE-M1 Execution Env Relocation

**问题**：Batch 0C 的 release-exec.env 位于 `$STAGE/release-exec.env`（Git staging checkout 内），由生产 `.env.production.local` 派生，可能含 secret，必须迁出 staging checkout。

**冻结目标**：`/root/.xg-ai-release/b7-0034-a633b486.env`（`/root/.xg-ai-release` mode 0700，env file mode 0600，root-only）。

```text
PRE-M1 STAGE HEAD = a633b486  ✓ (gate)
PRE-M1 PROD HEAD  = f453f44   ✓ (gate)
OLD_ENV (source)  = $STAGE/release-exec.env（不重新生成，迁移的是 Batch 0C 已验证的同一文件）
NEW_DIR            = /root/.xg-ai-release  DIR_MODE=700 OWNER=root ✓
NEW_ENV            = /root/.xg-ai-release/b7-0034-a633b486.env  FILE_MODE=600 OWNER=root ✓
```

### A3-10.1 迁移方式：先安全复制后删源（防复制失败丢唯一 env）

```text
install -d -m 700 /root/.xg-ai-release
install -m 600 $OLD_ENV $NEW_ENV    （不直接 mv）
SHA equality: OLD_SHA == NEW_SHA ✓ (RELEASE_EXEC_ENV_COPY_INTEGRITY=PASS)
```

### A3-10.2 新路径 S10-B revalidation（删源前证明新路径解析等价）

```text
python3 scripts/release_9000_s10b.py --env-file /root/.xg-ai-release/b7-0034-a633b486.env \
  --expected-9000 xg-ai-system-backend:b7-0034-a633b486 \
  --expected-9100 xg-ai-system-backend@sha256:93094f0... \
  --dry-run
resolved 9000 image : xg-ai-system-backend:b7-0034-a633b486  ✓
resolved 9100 image : xg-ai-system-backend@sha256:93094f0...  ✓
identity isolation PASS
REVALIDATION_RC = 0
```

### A3-10.3 删除 STAGE secret env（授权单文件 cleanup，非 RB-10）

```text
rm -- $STAGE/release-exec.env   （范围冻结为仅此一文件，不顺手删其他 staging/production 文件）
OLD_STAGE_RELEASE_ENV = REMOVED
STAGING_WORKTREE       = CLEAN（git status porcelain 空）
PROD_WORKTREE           = clean（仅 3 known protected untracked）
PRODUCTION_ENV_EDIT_BY_THIS_STAGE = NONE（.env.production.local MTIME=2026-08-06 23:49:03 未改）
```

## A3-11 Release Execution Env Frozen Identity

```text
RELEASE_EXECUTION_ENV        = /root/.xg-ai-release/b7-0034-a633b486.env
RELEASE_EXECUTION_ENV_SHA256 = ad2efb0c4a1edf4a0734b81af30fc29b6f79f81760ac8ee2f9fd620290454973
PROD_ENV_MTIME（未改证据）    = 2026-08-06 23:49:03 +0800
```
M5/M8 必须复用此 SHA（drift 即 STOP）。env file 已在 Git staging checkout 之外，无 secret 泄露面。

### A3-11.1 PRE-M1 最终 Target Image Check

```text
TARGET_REF = xg-ai-system-backend:b7-0034-a633b486
TARGET_ID  = sha256:4b4f96fc75c63c49401d66ed9ca96bcac0d49681d68b41b88f5c948a3af1ae0f  ✓ (未 drift)
```

## A3-12 PRE-M1 Runtime Snapshot（stop 前基线）

```text
PRE_M1_9000_CONTAINER_ID  = a4421aabee73d41034eef9d8ac3534c8228d1192b0775f541cc98ab2c5314c18
PRE_M1_9000_IMAGE_ID      = sha256:93094f0a02ba3a4570160ce90625cb80fdec85076046fc314f5fe407add36c68
PRE_M1_9000_STARTED_AT    = 2026-08-06T15:51:36.842166568Z
PRE_M1_9000_RESTART_COUNT = 0
PRE_M1_9100_CONTAINER_ID  = 49548f1bad1abad38eecb260c6c84fe64f3616023bab7e76d2353027d1bf1373
PRE_M1_9100_IMAGE_ID      = sha256:93094f0a02ba3a4570160ce90625cb80fdec85076046fc314f5fe407add36c68
PRE_M1_9100_STARTED_AT     = 2026-08-06T15:51:36.764350664Z
PRE_M1_9100_RESTART_COUNT  = 0
9000 /ready = HTTP200 expected=actual=0028（维护前基线）
9100 /ready = HTTP200 expected=actual=0003 + milvus connected/schema_match/query_ok
```

```text
PRE_M1_EXECUTION_ENV_RELOCATION = PASS
M0_PRE_MAINTENANCE_PREPARATION   = COMPLETE
```

## A3-13 M1 Command（approved，非现场发明）

```text
ENTERING FIRST PRODUCTION APPLICATION RUNTIME MUTATION
M1 — ENTER MAINTENANCE

approved source = design §25 step 4：docker compose stop auto-wechat-api（仅 9000，不触及 9100）
env-file = PROD .env.production.local（M1 停的是生产运行的旧 9000；STAGE release-exec.env 是 M8 apply target 用，非 M1）
compose 依赖图 = auto-wechat-api depends_on postgres；9100/frontend 独立于 9000；
                docker compose stop <service> 不递归 stop dependencies、不处理 reverse depends_on → 只停 9000

actual command:
  docker compose --env-file .env.production.local -f docker-compose.yml stop auto-wechat-api
M1_STOP_RC = 0
```

## A3-14 M1 Service-State Evidence（compose ps -a）

```text
xg-auto-wechat-api      xg-ai-system-backend:latest   Exited (0)   ← 9000 已停
xg-douyin-ai-cs         xg-ai-system-backend:latest   Up 6 days (healthy)   ← 9100 未受影响
xg_ai_system-postgres-1 postgres:16-alpine            Up 6 days (healthy)   ← postgres 未受影响
xg-auto-wechat-frontend xg_ai_system-auto-wechat-frontend   Up 6 days (healthy)  ← frontend 未受影响
```
9000 /ready 此刻预期变 502/503/connection failure（维护态预期，非 M1 失败，Step 30）。

## A3-15 9100 Unchanged Comparison（逐位比对 PRE-M1 基线）

```text
9100_AFTER CID       = 49548f1bad1a... = PRE_M1_9100_CID       ✓
9100_AFTER Image     = sha256:93094f0... = PRE_M1_9100_IMAGE   ✓
9100_AFTER StartedAt = 2026-08-06T15:51:36.764... = PRE_M1     ✓
9100_AFTER Restart   = 0 = PRE_M1                        ✓
9100_AFTER Health    = healthy                            ✓
9100_UNCHANGED = PASS
9000_NO_AUTO_RESTART = PASS（stop 后 sleep 5s 复查，无外部 lifecycle 干扰，M1-S07/P-S16 未触发）
```

## A3-16 M1 Verdict

```text
approved 9000-only stop command rc = 0
9000 = stopped/isolated (Exited 0)
9100 = running healthy
9100 CID/Image/StartedAt/Restart = unchanged（逐位）
postgres = healthy
frontend = healthy
no unexpected service lifecycle mutation
M1-S01~S07 全未触发

M1 = PASS
MAINTENANCE_ENTERED = YES
```

```text
PRODUCTION_APPLICATION_RUNTIME_MUTATION = YES   （首次：停止 9000）
PRODUCTION_DATABASE_MUTATION             = NO
PRODUCTION_MIGRATION_EXECUTED            = NO
ROLLBACK_REQUIRED                        = NO
```

**M1 PASS 边界**（Step 31）：只证明 9000 容器已停 + 9100 逐位不变；**不**写 `WRITE_ISOLATION=VERIFIED`（那是 M2 的 dynamic gate：second 9000 audit / worker-scheduler audit / pg_stat_activity 证据）。

## A3-17 本阶段最终状态 + STOP

```text
PRE_M1_EXECUTION_ENV_RELOCATION = PASS
M0_PRE_MAINTENANCE_PREPARATION  = COMPLETE
BATCH_0A = PASS
BATCH_0B = PASS
BATCH_0C = PASS
M1      = PASS
MAINTENANCE_ENTERED = YES

9000 WRITE PATH = STOPPED / ISOLATED
9100            = UNCHANGED / DB 0003
PRODUCTION_DB   = STILL 0028
TARGET_IMAGE    = FROZEN (4b4f96fc75c6...)
RELEASE_EXECUTION_ENV = /root/.xg-ai-release/b7-0034-a633b486.env (SHA ad2efb0c...)

M2 = NOT EXECUTED
M3 = NOT EXECUTED
M4 = NOT EXECUTED
M6 = NOT EXECUTED
PRODUCTION_MIGRATION_EXECUTED = NO
```

本窗口用户仅授权 PRE-M1 relocation + M1，**不下发 M2**。M1 PASS 后保持 9000 stopped，不为"验证一下"重启（Step 35）。下一阶段 M2/M3/M4 的推进速度在维护窗口下应更快，但仍不跳过任何 Hard Gate。9000 现已正式进入维护状态，`merchant.xiaogaoai.cn/api/ready` 预期 502/503 直至 M9 启动 target 9000。

---

# ATTEMPT 3 — M2 Verify Write Isolation（2026-08-13）

> M1 已 PASS、维护窗口已开始。M2 唯一目标：证明 auto_wechat PostgreSQL 在 9000 已停止后不存在仍能继续写库的独立 writer。只有真实证据充分才允许 `WRITE_ISOLATION=VERIFIED`。
> 全段只读 + fail-closed；不 kill/terminate/stop unknown/DB mutation。

## A3-18 M2 Runtime / Process Topology（M2-A）

```text
M2-A1  xg-auto-wechat-api = Exited (0) 8 minutes ago（仍 stopped，未自行恢复）  ✓
M2-A2  HOST_9000_LISTENER = NONE（ss sport=:9000 无输出）                        ✓
M2-A3  运行容器无第二个 auto-wechat-api；DOCKER_WORKER_SCHEDULER_MATCH=NONE
       其他容器=独立项目（knowledge-train / used-car-* / car-project*），非 auto_wechat writer
       used-car-minio-1 显示 9000/tcp 是容器内部端口，无 0.0.0.0:9000 host 绑定（A2 已确认）    ✓
M2-A4  host 进程无 app.main:app port 9000、无 celery/rq/dramatiq/apscheduler
       命中均为 [kworker] 内核线程(ppid=2) / cloud-monitor-agent / nginx worker /
       used-car uvicorn :8790 / 9100 uvicorn / postgres io worker / grep 自身（false positive）    ✓
M2-A5  9100 CID/Image/Restart/StartedAt 逐位 = PRE-M1 基线                        ✓
M2-A = PASS
```

## A3-19 M2 PostgreSQL Session Evidence（M2-B，evidence-gathering）

```text
M2-B1  DB identity = auto_wechat / xgairoot / PostgreSQL 16.14  ✓
M2-B2  client backend sessions (WHERE datname=auto_wechat, client backend, pid<>pg_backend_pid())
       → (0 rows)   ← 9000 已停，连接池全释放，无残留 idle session，更无 writer  ✓
M2-B = PASS
```
判定依据（指令第 3 节）：DB CONNECTION != DB WRITER。此处连 connection 都为 0，无 writer session 可能。

## A3-20 M2 Write-Lock Evidence（M2-B3）

```text
M2-B3  granted write-style locks (RowExclusive/ShareRowExclusive/Exclusive/AccessExclusive)
       WHERE datname=auto_wechat, pid<>pg_backend_pid()
       → (0 rows)   ✓
M2-G8 write-style lock = NONE
```

## A3-21 M2 Transaction Evidence（M2-B4）

```text
M2-B4  open transactions (xact_start IS NOT NULL, client backend, pid<>pg_backend_pid())
       → (0 rows)   ← 无 idle-in-transaction，无 active open transaction  ✓
M2-G7 idle-in-transaction = NONE
```

## A3-22 M2 Mutation-Counter Stability（M2-C，动态第二层证据）

```text
M2-C  pg_stat_user_tables SUM(n_tup_ins/n_tup_upd/n_tup_del)
      BEFORE = 9598|7671|10
      sleep 15s
      AFTER  = 9598|7671|10
      DB_MUTATION_COUNTER_STABLE = PASS（15s 观察窗口 0 增长）  ✓
M2-G9 mutation counters = STABLE
```
短观察窗口为 corroborating evidence，须结合 M2-A/B 方可 PASS（指令第 7 节）；本窗口 A/B 已全 PASS。

## A3-23 M2 Final Port Recheck + Verdict（M2-D）

```text
M2-D  9000_LISTENER_STILL_NONE = PASS（M2 末尾再次 ss，无 9000 listener 复现）  ✓
M2-G10 final port recheck = NONE
```

### M2 Final Evidence Matrix

| Gate | 必须结果 | 证据 | 裁定 |
|---|---|---|---|
| M2-G1 9000 stopped | PASS | Exited(0)，state 非 running | PASS |
| M2-G2 host 9000 listener | NONE | A2 + D 均 NONE | PASS |
| M2-G3 second 9000 | NONE | 容器列表无第二个 auto-wechat-api | PASS |
| M2-G4 XG worker/scheduler | NONE_DETECTED | docker/host grep 全无 celery/rq/dramatiq/apscheduler/独立 uvicorn:9000 | PASS |
| M2-G5 9100 identity | UNCHANGED | CID/Image/Restart/StartedAt 逐位 = PRE-M1 | PASS |
| M2-G6 suspicious DB writer session | NONE | B2 client sessions (0 rows) | PASS |
| M2-G7 idle-in-transaction | NONE | B4 open txns (0 rows) | PASS |
| M2-G8 write-style lock | NONE | B3 write locks (0 rows) | PASS |
| M2-G9 mutation counters | STABLE | 9598/7671/10 15s 不变 | PASS |
| M2-G10 final port recheck | NONE | M2-D NONE | PASS |

```text
M2 = PASS
WRITE_ISOLATION = VERIFIED
```

```text
M1 = PASS
M2 = PASS
WRITE_ISOLATION = VERIFIED
MAINTENANCE_ENTERED = YES
9000 = STOPPED / ISOLATED
9100 = UNCHANGED / DB 0003
PRODUCTION_DB = STILL 0028
PRODUCTION_DATABASE_MUTATION_BY_MIGRATION = NO
PRODUCTION_APPLICATION_RUNTIME_MUTATION = YES（9000 仍 stopped）
PRODUCTION_DATABASE_MUTATION = NO
M3 = NOT EXECUTED
M4 = NOT EXECUTED
M6 = NOT EXECUTED
PRODUCTION_MIGRATION_EXECUTED = NO
ROLLBACK_REQUIRED = NO
```

## A3-24 M2 STOP — 不下发 M3

本窗口用户仅授权 M2。M2 PASS 后立即停止，**不顺手执行 M3/M4**。

```text
M2 = PASS
WRITE_ISOLATION = VERIFIED

NEXT = M3 PRESERVE ROLLBACK IMAGE
M3_EXECUTED = NO

PRODUCTION_MIGRATION_EXECUTED = NO
```

9000 仍处维护态（stopped），DB 仍 0028。下一阶段 M3（preserve rollback image）将按已批准 design §25 step 3b 把 old runtime image `93094f0...` 用 `docker tag` 固化为 immutable rollback ref（属 DOCKER_IMAGE_METADATA_MUTATION，非 runtime/DB mutation）。需用户显式授权才下发。维护窗口下推进速度可更快，但不跳过任何 Hard Gate。

---

# ATTEMPT 3 — M3 Preserve Rollback Image（2026-08-13）

> M2 已 PASS、WRITE_ISOLATION=VERIFIED。M3 唯一目标：把 old runtime image `93094f0...` 固化成不依赖 :latest 的 immutable rollback ref，并验证该 ref 仍指向原 Image ID。
> 唯一 mutation = `docker tag`（DOCKER_IMAGE_METADATA_MUTATION）；不启动/recreate 9000、不触 9100、不动 DB。

## A3-25 M3 Old-Image Identity（M3-A）

```text
M3-A  maintenance 未漂移：9000=Exited(0) 19min ago（state=exited）；9100=Up healthy；postgres=Up healthy
M3-G1 old image exists    = PASS
M3-G2 old image ID        = sha256:93094f0a02ba3a4570160ce90625cb80fdec85076046fc314f5fe407add36c68 ✓
OLD_IMAGE_IDENTITY = PASS
old image metadata: RepoTags=["xg-ai-system-backend:latest"] RepoDigests=["xg-ai-system-backend@sha256:93094f0..."]
  （:latest 不能作 rollback contract；frozen digest 存在但 M3 要的是显式 rollback tag，不止依赖 digest）
```

## A3-26 Rollback-Ref Collision Gate（M3-B）

```text
M3-G3 rollback ref pre-existence = NONE
ROLLBACK_REF_AVAILABLE = PASS（rollback ref 创建前不存在，可安全创建，非覆盖）
```

## A3-27 Rollback-Ref Creation（M3-C）

```text
唯一 mutation: docker tag sha256:93094f0... xg-ai-system-backend:rollback-b7-0028-f453f44-93094f0
DOCKER_TAG_RC = 0
M3-G4 docker tag = rc=0
```
tag 前再次确认 ref 未被外部占用（A/B 与 C 之间防竞争），未触发。

## A3-28 Rollback Identity Verification（M3-D，Hard Gate）

```text
M3-G5 rollback ref ID = sha256:93094f0a02ba3a4570160ce90625cb80fdec85076046fc314f5fe407add36c68 ✓
ROLLBACK_IMAGE_IDENTITY = VERIFIED
M3-G6 old/rollback cross-check: OLD_ID == ROLLBACK_ID == sha256:93094f0...  ✓
OLD_ROLLBACK_IDENTITY_MATCH = PASS
rollback metadata: RepoTags=["xg-ai-system-backend:latest","xg-ai-system-backend:rollback-b7-0028-f453f44-93094f0"]
  （rollback ref 与 :latest 共存，rollback ref 独立指向 93094f0，不再依赖 mutable :latest）
```
不只因 `docker tag rc=0` 判成功——必须 inspect rollback ref 再证 .Id==93094f0（指令第 8 节）。

## A3-29 Runtime Unchanged Evidence（M3-E）

```text
M3-E compose ps -a:
  xg-auto-wechat-api   Exited (0) 20min ago   ← tag 未唤醒 9000
  xg-douyin-ai-cs      Up 6 days (healthy)
  postgres             Up 6 days (healthy)
  frontend             Up 6 days (healthy)
M3-G7 9000 = still stopped (state=exited)  ✓
M3-G8 9100 = unchanged: CID=49548f1bad1a.../Image=93094f0.../Restart=0/StartedAt=2026-08-06T15:51:36.764... 逐位 = PRE-M1  ✓
M3-G9 DB mutation = NONE（tag 不触 DB）
```

## A3-30 M3 Final Evidence Matrix + Verdict

| Gate | Expected | 证据 | 裁定 |
|---|---|---|---|
| M3-G1 old image exists | PASS | inspect 成功 | PASS |
| M3-G2 old image ID | exact 93094f0... | sha256:93094f0... | PASS |
| M3-G3 rollback ref pre-existence | NONE | ROLLBACK_REF_AVAILABLE | PASS |
| M3-G4 docker tag | rc=0 | DOCKER_TAG_RC=0 | PASS |
| M3-G5 rollback ref ID | exact 93094f0... | ROLLBACK_ID=93094f0... | PASS |
| M3-G6 old/rollback cross-check | MATCH | OLD_ID==ROLLBACK_ID | PASS |
| M3-G7 9000 | still stopped | exited | PASS |
| M3-G8 9100 | unchanged | 逐位 = PRE-M1 | PASS |
| M3-G9 DB mutation | NONE | tag 不触 DB | PASS |

```text
M3 = PASS
ROLLBACK_IMAGE_PRESERVATION = VERIFIED
```

### M3 冻结 rollback identity（rollback procedure 必须复用，不得用 :latest）

```text
ROLLBACK9000_IMAGE_REF = xg-ai-system-backend:rollback-b7-0028-f453f44-93094f0
ROLLBACK9000_IMAGE_ID  = sha256:93094f0a02ba3a4570160ce90625cb80fdec85076046fc314f5fe407add36c68
```

### M3 mutation 分类

```text
DOCKER_IMAGE_METADATA_MUTATION              = YES   (docker tag)
ROLLBACK_IMAGE_REF_CREATED                   = YES
PRODUCTION_APPLICATION_RUNTIME_MUTATION_IN_M3 = NO
PRODUCTION_DATABASE_MUTATION                 = NO
PRODUCTION_MIGRATION_EXECUTED                = NO
MAINTENANCE_ENTERED                          = YES   (继承自 M1，非 M3 新触发)
ROLLBACK_REQUIRED                            = NO
```

## A3-31 M3 STOP — 不下发 M4

本窗口用户仅授权 M3。M3 PASS 后立即停止，**本轮不下发 M4 的 pg_dump 命令**。

```text
M1 = PASS
M2 = PASS
M3 = PASS
WRITE_ISOLATION           = VERIFIED
ROLLBACK_IMAGE_PRESERVATION = VERIFIED
9000 = STOPPED
9100 = UNCHANGED / DB 0003
PRODUCTION_DB = STILL 0028
M4 = NOT EXECUTED
PRODUCTION_MIGRATION_EXECUTED = NO
```

下一步唯一 = M4 — CREATE + VERIFY PRODUCTION DB BACKUP（pg_dump -F c auto_wechat → /www/backup，SHA256 + pg_restore --list verify）。需用户显式授权才下发。现同时拥有 WRITE_ISOLATION=VERIFIED 与 old runtime rollback image，下一道 M4 才创建真正的生产数据库回滚资产。

---

# ATTEMPT 3 — M4 Create + Verify Production DB Backup（2026-08-13）

> M3 已 PASS、ROLLBACK_IMAGE_PRESERVATION=VERIFIED。M4 唯一目标：在 WRITE_ISOLATION=VERIFIED 维护态下，为生产 auto_wechat@0028 创建可识别、可校验、可用于 approved rollback 的 PostgreSQL custom-format backup。
> 唯一 mutation = pg_dump 写 backup 文件（DB 读取，非 content/schema mutation）。不 restore 进 production、不 scratch DB、不 start9000。

## A3-32 M4 Pre-Backup Reality（M4-A）

```text
M4-A1 maintenance: 9000=Exited(0) 27min(state=exited)；9100=Up healthy；postgres=Up healthy
M4-A2 host :9000 listener = NONE
M4-A3 DB revision = 0028 ✓
M4-A4 backup dir = /www/backup, MODE=600 OWNER=root, df avail=314G
```

## A3-33 M4 Snapshot Identity（M4-A5）

```text
database_name=auto_wechat / db_user=xgairoot / server_version=16.14
alembic_revision = 0028
M4_BACKUP_SNAPSHOT_COUNTS:
  compute_transactions = 1740
  customer_profiles    = 1
  daily_report_jobs    = 0
```
（现场实测值，非历史 1/1725/0；compute_transactions 1740 为维护窗口前正常业务增长累计；M2 mutation counter 15s 内稳定，write isolation 仍 VERIFIED。）

## A3-34 M4 pg_dump Execution（M4-B）

```text
BACKUP_FILE = /www/backup/aw_backup_20260813T062217Z_pre0034.dump
  （TS=$(date -u +%Y%m%dT%H%M%SZ) 自动生成，非手写）
BACKUP_FILE_COLLISION = NONE（创建前不存在，非覆盖）
umask 077（root-readable only）
command: docker exec xg_ai_system-postgres-1 sh -lc 'exec pg_dump -U "$POSTGRES_USER" -d auto_wechat -F c' > $BACKUP_FILE
PG_DUMP_RC = 0
PG_DUMP = COMPLETE
```
已批准 custom format，未临时改 format/compression/ownership/schema filtering/table filtering。

## A3-35 M4 Backup File Identity（M4-C1）

```text
BACKUP_SIZE_BYTES = 1073194（~1MB，非空）
MODE=600 OWNER=root GROUP=root
```

## A3-36 M4 SHA256（M4-C2）

```text
BACKUP_SHA256 = bee463c2a061d49650372d0f0da7c271f067acb031d568e198feafdc09864ee1
```

## A3-37 M4 pg_restore --list Verification（M4-C3）

```text
pg_restore --list RC = 0
TOC 行数 = 637（non-empty，archive 可解析）
PG_RESTORE_LIST = PASS
```
注：原 `sh -lc 'exec pg_restore --list -'` 中 `-` 被 sh 误解析为文件名（`could not open input file "-"`），修正为无文件参数（pg_restore 默认读 stdin）后 RC=0。backup 文件未受损，SHA 仍冻结——这是 verify 命令语法修正，非重跑 pg_dump。
三表 grep 无命中属 TOC 格式差异（TABLE 行带 schema 前缀），不单独判 FAIL；主 gate 是 pg_restore --list RC=0（指令第 15 节）。

## A3-38 M4 Restore Readiness（M4-D，restore procedure source）

```text
RESTORE_PROCEDURE_SOURCE = approved isolated rehearsal §33 BR-23
  （rehearsal 验证 pg_dump -F c → pg_restore exit 0，独立 disposable 库 aw_restore_probe，非生产）
backup format = pg_dump -F c (custom archive)
pg_restore = PostgreSQL 16.14（容器内，exit 0 验证过）
rollback image = preserved 93094f0（M3 frozen ref: xg-ai-system-backend:rollback-b7-0028-f453f44-93094f0）
full rollback flow = KEEP MAINTENANCE → stop/remove target9000 → pg_restore auto_wechat from M4 backup → DB 回 0028 → deploy rollback image → /ready 0028 → 9100 仍 0003
M4 不在 production 真正 restore（指令第 19 节）；restore readiness = rehearsal procedure + 本轮 archive validity + 工具可用
```

## A3-39 M4 Runtime/Revision Recheck（M4-D1~D3）

```text
M4-D1 9000 = still stopped (state=exited, Exited 0 31min)   ← backup 未唤醒 9000
M4-D2 9100 = unchanged: CID=49548f1bad1a.../Image=93094f0.../Restart=0/StartedAt=2026-08-06T15:51:36.764... 逐位 = PRE-M1
M4-D3 DB revision = 0028（M4 无 schema migration）
```

## A3-40 M4 Final Evidence Matrix + Verdict

| Gate | Required | 证据 | 裁定 |
|---|---|---|---|
| M4-G1 maintenance reality | PASS | 9000 exited, 9100/postgres healthy | PASS |
| M4-G2 DB before backup | 0028 | DB_REVISION=0028 | PASS |
| M4-G3 backup dir | /www/backup writable | mode 600 root | PASS |
| M4-G4 disk capacity | sufficient | 314G avail | PASS |
| M4-G5 pg_dump | rc=0 | PG_DUMP_RC=0 | PASS |
| M4-G6 backup file | exists + non-empty | 1073194 bytes | PASS |
| M4-G7 SHA256 | frozen | bee463c2... | PASS |
| M4-G8 pg_restore --list | rc=0 | RC=0, TOC 637 | PASS |
| M4-G9 SHA after verification | unchanged | bee463c2... == frozen | PASS |
| M4-G10 restore procedure | READY/approved | rehearsal §33 BR-23 | PASS |
| M4-G11 rollback image | preserved | M3 frozen ref | PASS |
| M4-G12 9000 | still stopped | exited | PASS |
| M4-G13 9100 | unchanged | 逐位 = PRE-M1 | PASS |
| M4-G14 DB after M4 | still 0028 | 0028 | PASS |

```text
M4 = PASS
PRODUCTION_DB_BACKUP = VERIFIED
RESTORE_READINESS = VERIFIED
```

### M4 冻结 backup identity

```text
PRODUCTION_BACKUP_FILE        = /www/backup/aw_backup_20260813T062217Z_pre0034.dump
PRODUCTION_BACKUP_SHA256      = bee463c2a061d49650372d0f0da7c271f067acb031d568e198feafdc09864ee1
PRODUCTION_BACKUP_SIZE_BYTES  = 1073194
PRODUCTION_BACKUP_FORMAT      = PostgreSQL custom archive (-F c)
PRODUCTION_BACKUP_REVISION    = 0028
PRODUCTION_BACKUP_VERIFICATION = pg_restore --list PASS
RESTORE_READINESS             = VERIFIED
```

### M4 mutation 分类

```text
PRODUCTION_BACKUP_FILE_CREATION          = YES   (pg_dump 写文件)
PRODUCTION_DATABASE_CONTENT_MUTATION      = NO    (pg_dump 是读取)
PRODUCTION_SCHEMA_MUTATION                = NO
PRODUCTION_MIGRATION_EXECUTED             = NO
PRODUCTION_APPLICATION_RUNTIME_MUTATION_IN_M4 = NO
MAINTENANCE_ENTERED                       = YES   (继承自 M1)
ROLLBACK_REQUIRED                         = NO
```

### M4 安全边界记录

```text
backup 留在 /www/backup，不 git add / 不 copy 进 STAGE / 不 copy 进 repo / 不 upload public origin
BACKUP_STORAGE = /www/backup，PRODUCTION_STORAGE = same /dev/vda2
SAME_FILESYSTEM_BACKUP_LIMITATION = ACCEPTED / NON_BLOCKING FOR THIS SCHEMA MIGRATION
  能应对：bad migration / target deployment failure / logical DB rollback
  不能应对：host disk catastrophic loss（M4 非完整灾备）
/tmp/aw_backup_restore_list.txt = verify side artifact，本轮不清理（RB-10 未授权）
```

## A3-41 M4 STOP — 不下发 M5

本窗口用户仅授权 M4。M4 PASS 后立即停止，**本轮不得提前执行 M5/M6**。

```text
M1 = PASS
M2 = PASS
M3 = PASS
M4 = PASS
WRITE_ISOLATION             = VERIFIED
ROLLBACK_IMAGE_PRESERVATION = VERIFIED
PRODUCTION_DB_BACKUP        = VERIFIED
RESTORE_READINESS           = VERIFIED
9000 = STOPPED
9100 = UNCHANGED / DB 0003
PRODUCTION_DB = STILL 0028
M5 = NOT EXECUTED
M6 = NOT EXECUTED
PRODUCTION_MIGRATION_EXECUTED = NO
```

下一步唯一 = M5 — FINAL TARGET VERIFICATION。需用户显式授权才下发。现同时拥有三块安全资产：WRITE_ISOLATION=VERIFIED + rollback image（rollback-b7-0028-f453f44-93094f0）+ 生产 DB backup（aw_backup_20260813T062217Z_pre0034.dump, SHA bee463c2...）。`PRODUCTION_DB_BACKUP != VERIFIED → DO NOT MIGRATE` 现已满足，0028→0034 migration 具备真正回滚基础。

---

# ATTEMPT 3 — M5 Final Target Verification（2026-08-13）

> M4 已 PASS。M5 是 M6 前最后一道 Hard Gate：不创造新资产，只在同一时间点重新对齐所有迁移输入（release tree/target image/migration graph/env SHA）与回滚资产（rollback image/backup），并复验生产起点（9000 stopped/DB0028/write isolation/9100 不变）。
> 全程无 mutation（无 DB mutation/image build/docker tag/apply/start9000）。M5-G1~G20 二十项全 PASS。

## A3-42 M5 Release / Execution Env Identity（M5-A）

```text
M5-G1 Stage HEAD    = a633b4860b818ab48fda5e22f39aa311eb96e9eb ✓
M5-G2 Stage parent  = 9db3f5854095e483a55724e66d452792b354ff53 ✓
M5-G3 Stage worktree = CLEAN ✓
M5-G4 Production HEAD = f453f44e6a70de3eb5fa8f808cf4b6a9d72ea6c1 ✓（仅 3 known protected untracked）
M5-G5 Release env SHA = ad2efb0c4a1edf4a0734b81af30fc29b6f79f81760ac8ee2f9fd620290454973 = PRE-M1 frozen ✓
  env MODE=600 OWNER=root
```
完整 frozen SHA 取自 A3-11（PRE-M1 记录），非缩写；当前 SHA 与历史 frozen 自动比对一致，无 drift。

## A3-43 M5 Target Image（M5-B1）

```text
M5-G6 Target image ID = sha256:4b4f96fc75c63c49401d66ed9ca96bcac0d49681d68b41b88f5c948a3af1ae0f = frozen ✓
（未 rebuild）
```

## A3-44 M5 Migration Graph（M5-B2）

```text
M5-G7 Target Alembic HEAD = 0034 (head) ✓
M5-G8 Migration graph = 0028→0029→0030→0032→0033→0034 ✓
  （0029 customer_profiles JSONB unify / 0030 compute_idempotency / 0032 daily_report_generations /
   0033 material_analysis_executions / 0034 preview_executions）
  0032 注释明确：用 0032 非 0031 避免与 SQLite 0031_compute_billing.sql 编号混淆，0031 跳号=intentional
M5-G9 PostgreSQL Alembic 0035 = ABSENT（find 0035_* 无输出）✓
```
one-off `--network none` 容器验证 image 内容，不连生产 DB、不启动 service。

## A3-45 M5 Manifest（M5-B3）

```text
M5-G10 Manifest = 8/8 OK（复用 Batch 0B concrete SHA command，不重新生成 Manifest）
.env.production.example / docker-compose.yml / ENV_VARIABLE_REFERENCE.md /
release_9000_s10b.py / test_s10_b_image_identity_isolation.py / S10-B 三份报告 全 OK
```

## A3-46 M5 Rollback Image（M5-C1）

```text
M5-G11 Rollback image ID = sha256:93094f0a02ba3a4570160ce90625cb80fdec85076046fc314f5fe407add36c68 = M3 frozen ✓
（xg-ai-system-backend:rollback-b7-0028-f453f44-93094f0）
```

## A3-47 M5 Backup Identity（M5-C2~C4）

```text
M5-G12 Backup SHA/size = bee463c2a061d49650372d0f0da7c271f067acb031d568e198feafdc09864ee1 / 1073194 bytes = M4 frozen ✓
M5-G13 Backup archive = pg_restore --list RC=0, TOC 637 行，可解析 ✓
BACKUP_DIR_MODE  = 600 (目录 /www/backup root-only，真实权限非歧义)
BACKUP_FILE_MODE = 600
pg_restore --list 用 M4 修正后的无文件参数方式（不重蹈 - 被 sh 误解析）
```

## A3-48 M5 S10-B Final Preflight（M5-D）

```text
pre-wrapper env SHA = ad2efb0c... = frozen ✓（运行 wrapper 前再次确认 env 未 drift）
M5-G14 S10-B resolved 9000 = xg-ai-system-backend:b7-0034-a633b486（非 :latest）✓
M5-G15 S10-B resolved 9100 = xg-ai-system-backend@sha256:93094f0...（frozen old digest，非 :latest）✓
identity isolation PASS / S10B_M5_WRAPPER_RC=0
canonical 9000-only command = docker compose --env-file /root/.xg-ai-release/b7-0034-a633b486.env
  -f /www/wwwroot/XG_AI_System_release_0034_a633b486/docker-compose.yml
  up -d --no-deps --no-build auto-wechat-api（只 9000，--no-deps/--no-build，无 9100）
host env pollution = CLOSED（wrapper compose_env sanitize 生效）
全程 --dry-run，未 --apply / 未 docker compose up
```

## A3-49 M5 Runtime / Write-Isolation Recheck（M5-E）

```text
M5-G16 9000 runtime = STOPPED (state=exited, Exited 0 44min) ✓
host :9000 listener = NONE ✓
M5-G17 DB revision = 0028 ✓
M5-G18 writer sessions = client backends (0 rows) / write-style locks (0 rows) ✓
M5-G19 mutation counters = 9598|7671|10 15s 不变 ✓（WRITE_ISOLATION_RECHECK=PASS）
M5-G20 9100 = CID=49548f1bad1a.../Image=93094f0.../Restart=0/StartedAt=2026-08-06T15:51:36.764... 逐位 = PRE-M1 / healthy ✓
```
E3/E4 若出现 client backend 不自动 FAIL，复用 M2 分类口径（idle read-only 非阻断；writer/idle-in-transaction 才阻断）。本轮 0 rows，无需分类。

## A3-50 M5 Final Evidence Matrix

| Gate | 必须结果 | 证据 | 裁定 |
|---|---|---|---|
| M5-G1 Stage HEAD | a633b486... | rev-parse HEAD | PASS |
| M5-G2 Stage parent | 9db3f58... | rev-parse HEAD^ | PASS |
| M5-G3 Stage worktree | CLEAN | porcelain 空 | PASS |
| M5-G4 Production HEAD | f453f44... | rev-parse HEAD | PASS |
| M5-G5 Release env SHA | exact frozen ad2efb0c... | sha256sum | PASS |
| M5-G6 Target image ID | exact 4b4f96fc... | docker image inspect | PASS |
| M5-G7 Target Alembic HEAD | 0034 | alembic heads | PASS |
| M5-G8 Migration graph | 0028→0029→0030→0032→0033→0034 | alembic history | PASS |
| M5-G9 0035 | ABSENT | find 0035_* 无输出 | PASS |
| M5-G10 Manifest | 8/8 MATCH | sha256sum -c | PASS |
| M5-G11 Rollback image | exact 93094f0... | docker image inspect | PASS |
| M5-G12 Backup SHA/size | MATCH | bee463c2.../1073194 | PASS |
| M5-G13 Backup archive | parseable | pg_restore --list RC=0 | PASS |
| M5-G14 S10-B resolved9000 | exact target | wrapper dry-run | PASS |
| M5-G15 S10-B resolved9100 | exact frozen old | wrapper dry-run | PASS |
| M5-G16 9000 runtime | STOPPED | state=exited | PASS |
| M5-G17 DB revision | 0028 | alembic_version | PASS |
| M5-G18 writer sessions/locks | NONE | 0 rows / 0 rows | PASS |
| M5-G19 mutation counters | STABLE | 9598/7671/10 15s | PASS |
| M5-G20 9100 | UNCHANGED | 逐位 = PRE-M1 | PASS |

## A3-51 M5 Verdict

```text
M5 = PASS
FINAL_TARGET_VERIFICATION = VERIFIED
M6_ENTRY_GATE = OPEN
M6_EXECUTED = NO
```

```text
M1 = PASS / M2 = PASS / M3 = PASS / M4 = PASS / M5 = PASS
WRITE_ISOLATION             = VERIFIED
ROLLBACK_IMAGE_PRESERVATION = VERIFIED
PRODUCTION_DB_BACKUP        = VERIFIED
RESTORE_READINESS           = VERIFIED
FINAL_TARGET_VERIFICATION   = VERIFIED
PRODUCTION_DB = 0028
TARGET_DB = 0034
M6_ENTRY_GATE = OPEN
M6 = NOT EXECUTED
PRODUCTION_MIGRATION_EXECUTED = NO
```

### M5 mutation 分类

```text
PRODUCTION_DATABASE_CONTENT_MUTATION_IN_M5     = NO
PRODUCTION_SCHEMA_MUTATION_IN_M5                = NO
PRODUCTION_MIGRATION_EXECUTED                   = NO
PRODUCTION_APPLICATION_RUNTIME_MUTATION_IN_M5   = NO
MAINTENANCE_ENTERED                             = YES   (继承自 M1)
ROLLBACK_REQUIRED                               = NO
```

## A3-52 M5 STOP — 不下发 M6

本窗口用户仅授权 M5。M5 PASS 后立即停止，**不顺手 alembic upgrade 0034 / 不启动 target9000**。

```text
M5 = PASS
FINAL_TARGET_VERIFICATION = VERIFIED
M6_ENTRY_GATE = OPEN

NEXT = M6 — MIGRATE 0028 → 0034
M6_EXECUTED = NO
PRODUCTION_MIGRATION_EXECUTED = NO
```

M5 PASS 意味着迁移所需的"输入、目标、回滚资产、运行环境和写隔离"已在同一时间点全部重新对齐。下一阶段 M6 才允许第一次修改生产数据库 schema（`alembic upgrade 0028→0029→0030→0032→0033→0034`），是整条链中风险最高的 mutation。需用户再次显式授权。M6 前所有 gate 已就绪：三块安全资产齐全 + FINAL_TARGET_VERIFICATION=VERIFIED。

---

# ATTEMPT 3 — M6 Migrate 0028 → 0034（2026-08-13）

> **本次 catch-up 第一次真正修改生产数据库 schema。** migration 命令启动即 `PRODUCTION_DATABASE_MUTATION_ATTEMPTED=YES`。
> M6 只判：migration RC=0 + DB revision=0034 + runtime boundary 不变。全面 schema/data 验收属 M7（Step 14）。

## A3-53 M6 Pre-Mutation Reality（M6-A）

```text
M6-G1 9000 before migration = STOPPED (state=exited, Exited 0 58min) ✓
M6-G2 DB start revision    = 0028 ✓
M6-G3 rollback image       = sha256:93094f0... = frozen ✓ (ROLLBACK_IMAGE_BEFORE_M6=PASS)
M6-G4 backup identity      = bee463c2... = frozen ✓ (BACKUP_IDENTITY_BEFORE_M6=PASS)
9100 pre-mutation baseline = CID=49548f1bad1a.../Image=93094f0.../Restart=0/StartedAt=2026-08-06T15:51:36.764.../healthy
```

## A3-54 M6 Rollback/Backup Final Identity（M6-A3/A4）

migration 启动前最后确认回滚资产未 drift：
```text
backup SHA = bee463c2a061d49650372d0f0da7c271f067acb031d568e198feafdc09864ee1（未变）
rollback image ID = sha256:93094f0a02ba3a4570160ce90625cb80fdec85076046fc314f5fe407add36c68（未变）
→ 回滚资产在 migration 前一刻确证就绪
```

## A3-55 M6 Approved Command Provenance（M6-B）

**approved 约束核查**（design §20 line 562 + §6）：
- `production_pg_alembic_upgrade.sh` 用 `docker compose exec -T auto-wechat-api alembic ... upgrade head`，但 9000 容器 Exited 不可 exec；且其 target 硬编码 `0007`（P3-E 旧值）+ `upgrade head`（非显式 0034）+ 旧 9000 镜像 93094f0 只含 ≤0028 迁移文件 → **不可直接用于 M6**。
- design §20 line 562："运行 Alembic 的容器/镜像必须包含 target 0034 迁移集" + `MIGRATION_ARTIFACT_SOURCE_COMMIT=9db3f58` → migration code 必须来自 target image（4b4f96fc...），非旧 9000 镜像。

**三件只读核实闭合**（用户选定"先只读核实再定"）：
1. alembic.ini `script_location = %(here)s` → `-c /workspace/migrations/postgres/auto_wechat/alembic.ini` 可定位 versions ✓
2. env.py `_database_url()` 从环境变量 `DATABASE_URL` 读取（必须配置否则 raise）→ one-off 容器注入 DATABASE_URL 即可 ✓
3. 网络：postgres 容器在 `xg_ai_system_default` 网络，DNS aliases 含 `postgres` → one-off 容器 `--network xg_ai_system_default` 可通过 `postgres:5432` 连生产 PG ✓

```text
M6-G5 migration command source = APPROVED（构件复用：target image / 显式 0034 / env.py DATABASE_URL 契约）
  - 非现场发明新 runtime：production_pg_alembic_upgrade.sh 的 alembic 调用契约（-c alembic.ini upgrade <target>）被忠实复用
  - 容器形态从"compose exec 运行中 9000"改为"target image one-off 容器"是 9000-stopped 前置的必然技术后果，design §20 已规定 migration 须用 target image
M6-G6 migration target = explicit 0034（非 head，catch-up boundary）
M6_EXECUTION_COMMAND_GAP = NOT HIT
```

M6-B network discovery：
```text
PG network = xg_ai_system_default
PG container IP = 172.20.0.3
PG DNS aliases = ["postgres", "xg_ai_system-postgres-1"]（"postgres" 可解析）
pg_isready = accepting connections
```

## A3-56 M6 Migration Execution（M6-C，EXACTLY ONCE）

```
===== M6 FIRST PRODUCTION DB SCHEMA MUTATION =====
START_REVISION = 0028 / TARGET_REVISION = 0034
WRITE_ISOLATION = VERIFIED / ROLLBACK_IMAGE = VERIFIED / PRODUCTION_BACKUP = VERIFIED / FINAL_TARGET_VERIFICATION = VERIFIED
EXECUTING ALEMBIC UPGRADE 0034 EXACTLY ONCE
```

从命令启动瞬间：`PRODUCTION_DATABASE_MUTATION_ATTEMPTED = YES`

concrete command：
```text
docker run --rm \
  --network xg_ai_system_default \
  -e DATABASE_URL="postgresql+psycopg://${PG_USER}:${PG_PASSWORD}@postgres:5432/${PG_DB}" \
  --entrypoint python \
  xg-ai-system-backend:b7-0034-a633b486 \
  -m alembic -c /workspace/migrations/postgres/auto_wechat/alembic.ini upgrade 0034
```
- migration code 来源 = target image（含 0034 迁移集，design §20）
- 显式 `upgrade 0034`（非 head）
- `--network xg_ai_system_default` 连生产 PG（DNS alias postgres）
- DATABASE_URL 从生产 .env.production.local 读 PG 凭据构造（set -a; . env; set +a），注入容器环境变量，不 echo / 不落盘
- exactly once，无 retry loop，无 `|| alembic upgrade 0034`

## A3-57 M6 Migration RC/Output（M6-C）

```text
PRE_MIGRATION_REVISION = 0028（执行前最后确认，防 A 与 C 之间被改）
MIGRATION_RC = 0
M6-G7 migration executions = EXACTLY 1（无 retry loop）
M6-G8 migration RC = 0
```
RC=0 **不直接判 M6 PASS**（Step 10），进入 M6-E 用 DB revision=0034 作核心状态证据。

## A3-58 M6 Post-Revision（M6-E）

```text
END_REVISION = 0034 ✓
M6-G9 DB end revision = 0034
M6-G10 unexpected 0035 = ABSENT（END_REV=0034，非 0035）
DATABASE_REVISION_0034 = PASS
```
不把"alembic 日志看到五行 migration"作唯一成功依据；DB `alembic_version=0034` 是 M6 核心状态证据。

## A3-59 M6 Runtime/9100 Recheck（M6-F）

```text
M6-G11 9000 after migration = STILL STOPPED (state=exited, Exited 0 ~1hr)
  （DB 已 0034，old9000 expected=0028 ≠ actual=0034，若启动会 /ready 503 mismatch → 故意保持 stopped，Step 19）
M6-G12 9100 = UNCHANGED: CID=49548f1bad1a.../Image=93094f0.../Restart=0/StartedAt=2026-08-06T15:51:36.764... 逐位 = PRE-M1 / healthy ✓
M6-G13 postgres = HEALTHY ✓
```

## A3-60 M6 Final Evidence Matrix

| Gate | Required | 证据 | 裁定 |
|---|---|---|---|
| M6-G1 9000 before migration | STOPPED | exited | PASS |
| M6-G2 DB start revision | 0028 | START_REVISION=0028 | PASS |
| M6-G3 rollback image | VERIFIED | 93094f0... | PASS |
| M6-G4 backup identity | VERIFIED | bee463c2... | PASS |
| M6-G5 migration command source | APPROVED | target image 构件复用 + design §20 | PASS |
| M6-G6 migration target | explicit 0034 | upgrade 0034（非 head） | PASS |
| M6-G7 migration executions | EXACTLY 1 | 无 retry loop | PASS |
| M6-G8 migration RC | 0 | MIGRATION_RC=0 | PASS |
| M6-G9 DB end revision | 0034 | END_REVISION=0034 | PASS |
| M6-G10 unexpected 0035 | ABSENT | END_REV=0034 | PASS |
| M6-G11 9000 after migration | STILL STOPPED | exited | PASS |
| M6-G12 9100 | UNCHANGED | 逐位 = PRE-M1 | PASS |
| M6-G13 postgres | HEALTHY | healthy | PASS |

## A3-61 M6 Verdict

```text
M6 = PASS
PRODUCTION_MIGRATION_EXECUTED = YES
PRODUCTION_DATABASE_MUTATION  = YES
PRODUCTION_SCHEMA_MUTATION    = YES
PRODUCTION_DB = 0034
```

### M6 状态变化（整条链第一次）

```text
BEFORE M6: PRODUCTION_DB=0028 / PRODUCTION_DATABASE_MUTATION=NO
AFTER M6 PASS: PRODUCTION_DB=0034 / PRODUCTION_DATABASE_MUTATION=YES / PRODUCTION_SCHEMA_MUTATION=YES / PRODUCTION_MIGRATION_EXECUTED=YES
仍: 9000=STOPPED / TARGET9000=NOT DEPLOYED / 9100=UNCHANGED DB0003 / MAINTENANCE_ENTERED=YES
```

### M6 mutation 分类

```text
PRODUCTION_DATABASE_MUTATION_ATTEMPTED        = YES
PRODUCTION_DATABASE_MUTATION                   = YES
PRODUCTION_SCHEMA_MUTATION                     = YES
PRODUCTION_MIGRATION_EXECUTED                  = YES
PRODUCTION_APPLICATION_RUNTIME_MUTATION_IN_M6  = NO   (未启 9000，未碰 9100)
TARGET9000_DEPLOYED                            = NO
9100_MUTATION                                  = NO
MAINTENANCE_ENTERED                            = YES   (继承自 M1)
ROLLBACK_REQUIRED                              = NO
```

### M6 PASS ≠ migration 已最终验收（Step 17）

```text
M6 PASS = Alembic migration 执行成功并到达 0034
M7 PASS = 0034 schema/data 完整性经过生产验证（本轮未做）
```
M6 只判 migration RC=0 + revision=0034 + runtime boundary 不变；新表/字段/JSONB/constraints/indexes/P1 artifacts/row-count 全面校验属 M7（Step 14）。

## A3-62 M6 STOP — 不下发 M7、不启动 target9000

```text
M1=PASS / M2=PASS / M3=PASS / M4=PASS / M5=PASS / M6=PASS
WRITE_ISOLATION             = VERIFIED
ROLLBACK_IMAGE_PRESERVATION = VERIFIED
PRODUCTION_DB_BACKUP        = VERIFIED
RESTORE_READINESS           = VERIFIED
FINAL_TARGET_VERIFICATION   = VERIFIED
PRODUCTION_DB = 0034
PRODUCTION_MIGRATION_EXECUTED = YES
9000 = STOPPED
TARGET9000 = NOT DEPLOYED
9100 = UNCHANGED / DB 0003
M7 = NOT EXECUTED
M8 = NOT EXECUTED
```

下一步 = M7 — VERIFY DB0034 / SCHEMA / DATA。需用户显式授权才下发。
**不启动 target9000**：DB 已 0034，old9000 expected=0028≠actual=0034，若启动旧 9000 会 /ready 503 mismatch；正确维护态 = DB0034 + old9000 stopped（Step 19）。M8 才部署 target9000。

---

# ATTEMPT 3 — M7 Verify DB0034 / Schema / Data（2026-08-13）

> **核心原则**：不凭记忆猜 0034，先读冻结 migration 源码形成验收合同，再用生产只读 SQL 验证最终物理状态。M7 是独立的 0034 验收，非对已完成 migration 自证。
> 全程只读 SELECT/inspect，无 DDL/DML/runtime mutation。任一 contract 失配 → P-S12 STOP，**不现场修库**（Step 28）。

## A3-63 M7 Migration Contract Extraction（M7-A0，从冻结源码推导）

逐个阅读 0029/0030/0032/0033/0034 的 `upgrade()`，形成合同矩阵（expected state 全部来自 migration 源码，非先看生产反推）：

| Revision | Object | Upgrade op | Expected final state | Data effect |
|---|---|---|---|---|
| 0029 | customer_profiles.confirmed_fields_json | alter_column TEXT→JSONB | data_type=jsonb | NULL 保持 NULL；cast 已存 JSON |
| 0029 | customer_profiles.inferred_fields_json | alter_column TEXT→JSONB | data_type=jsonb | 同上 |
| 0030 | compute_transactions.idempotency_key | add_column | varchar(255) nullable | 旧行 NULL |
| 0030 | compute_transactions.payload_evidence | add_column | text nullable | 旧行 NULL |
| 0030 | uk_compute_transactions_merchant_idempotency | create_unique_constraint | UNIQUE(merchant_id, idempotency_key) | NULL 不参与唯一约束 |
| 0032 | daily_report_generations (table) | create_table | 4 列 + PK + FK + CHECK + index | 空表合法 |
| 0032 | daily_report_jobs.current_generation_id | add_column | integer nullable | 旧行 NULL |
| 0033 | ai_edit_material_analysis_executions (table) | create_table | 6 列 + PK + CHECK + index | 空表合法 |
| 0034 | ai_preview_executions (table) | create_table | 6 列 + PK + CHECK + index | 空表合法 |

data migration 分类：0029=DATA_TRANSFORMING(type cast)；0030/0032/0033/0034=SCHEMA_ONLY。
M4 snapshot baseline（data sanity 比对，来自 A3-33）：compute_transactions=1740 / customer_profiles=1 / daily_report_jobs=0。

## A3-64 0029 Verification（M7-B2）

```text
customer_profiles.confirmed_fields_json: data_type=jsonb / udt_name=jsonb / is_nullable=YES ✓
customer_profiles.inferred_fields_json:  data_type=jsonb / udt_name=jsonb / is_nullable=YES ✓
M7-G7 JSONB physical types = PASS
```

## A3-65 0030 Verification（M7-B3）

```text
compute_transactions.idempotency_key:  character varying / varchar / is_nullable=YES ✓
compute_transactions.payload_evidence: text / text / is_nullable=YES ✓
uk_compute_transactions_merchant_idempotency: contype=u / UNIQUE (merchant_id, idempotency_key) ✓
M7-G5 column contract / M7-G8 constraints = PASS
```

## A3-66 0032 Verification（M7-B4）

```text
daily_report_generations 列: id(integer not null PK autoincrement) / job_id(integer not null) /
  lifecycle_status(varchar not null default 'pending') / created_at(timestamp not null default now()) ✓
constraints: daily_report_generations_pkey(p) / daily_report_generations_job_id_fkey(f→daily_report_jobs.id) /
  ck_daily_report_generations_status(c, IN pending/running/succeeded/failed) ✓
indexes: idx_daily_report_generations_job(non-unique btree job_id) ✓
daily_report_jobs.current_generation_id: integer / is_nullable=YES ✓
M7-G4 table / M7-G6 nullability/default / M7-G8 constraints / M7-G9 indexes = PASS
```

## A3-67 0033 Verification（M7-B5）

```text
ai_edit_material_analysis_executions 列: id(integer PK) / material_id(varchar not null) /
  source_sha256(varchar not null) / lifecycle_status(varchar not null default 'running') /
  created_at(timestamp not null default now()) / completed_at(timestamp nullable) ✓
constraints: pkey(p) / ck_ai_edit_material_analysis_executions_status(c, IN running/completed/failed) ✓
indexes: idx_ai_edit_material_analysis_executions_material(non-unique btree material_id) ✓
M7-G4/G6/G8/G9 = PASS
```

## A3-68 0034 Verification（M7-B6）

```text
ai_preview_executions 列: id(integer PK) / merchant_id(varchar not null) /
  agent_id(varchar nullable) / lifecycle_status(varchar not null default 'running') /
  created_at(timestamp not null default now()) / completed_at(timestamp nullable) ✓
constraints: ai_preview_executions_pkey(p) / ck_ai_preview_executions_status(c, IN running/completed/failed) ✓
indexes: idx_ai_preview_executions_merchant(non-unique btree merchant_id) ✓
M7-G4/G6/G8/G9 = PASS
```

## A3-69 Data-Preservation / Transformation Evidence（M7-C/D）

```text
M7-C1 unaffected critical-data sanity (vs M4 snapshot):
  compute_transactions = 1740 = M4 ✓
  customer_profiles    = 1    = M4 ✓
  daily_report_jobs    = 0    = M4 ✓
M7-G11 unaffected critical-data sanity = PASS

M7-C2 0029 JSONB invariants:
  total_rows=1 / confirmed_non_null=1 / inferred_non_null=0（该行 inferred_fields_json=NULL，NULL 保持 NULL，none_as_null 口径成立）
  confirmed_non_object_array=0 / inferred_non_object_array=0（cast 后无非法 JSON，M6 RC=0 已隐式证明）
M7-G10 data invariants = PASS

M7-D1 new tables row count: daily_report_generations=0 / ai_edit_material_analysis_executions=0 / ai_preview_executions=0（空表合法，migration 不插数据）
M7-D2 0030 idempotency NULL compat: total=1740 / idempotency_key_non_null=0 / payload_evidence_non_null=0（旧行全 NULL，backward-compatible 成立）
M7-G12 approved P1 artifacts = PASS（3 新表 + 幂等列兼容）

M7-D3 0035 DB-level exclusion: revision=0034（非 0035）✓
```

## A3-70 P1 Artifact Verification（M7-D1/D2）

```text
P1 0034 范围内 approved artifacts:
  daily_report_generations（0032）= exists + schema 正确 + 空表合法
  ai_edit_material_analysis_executions（0033）= exists + schema 正确 + 空表合法
  ai_preview_executions（0034）= exists + schema 正确 + 空表合法
  compute_transactions 幂等列（0030）= exists + nullable + 1740 旧行全 NULL（向后兼容）
0035-only artifact（P2 claim/lease schema）= 未出现（boundary 守住）
```

## A3-71 Runtime / Write-Isolation / 9100 Recheck（M7-E）

```text
M7-G13 9000 = STILL STOPPED (state=exited, Exited 0 ~1hr) ✓
host :9000 listener = NONE ✓
M7-G14 writer sessions = client backends (0 rows)（E3 初次 SQL typo 修正后重跑，0 rows）
M7-G15 write-style locks = (0 rows) ✓
M7-G16 9100 = UNCHANGED: CID=49548f1bad1a.../Image=93094f0.../Restart=0/StartedAt=2026-08-06T15:51:36.764... 逐位 = PRE-M1 / healthy ✓
M7-G17 postgres = HEALTHY ✓
```
注：E3 初次 `COALESCE(client_addr::text,' 'local')` 字符串字面量引号 typo 致语法错；修正为 `'local'` 后 0 rows。这是 verify 命令语法修正，非 DB 异常，DB/runtime 未触碰。

## A3-72 M7 Final Evidence Matrix

| Gate | Required | 证据 | 裁定 |
|---|---|---|---|
| M7-G1 DB revision | exact 0034 | row_count=1, version_num=0034 | PASS |
| M7-G2 migration files | 0029/0030/0032/0033/0034 exact | 5 文件 + 0031/0035 ABSENT | PASS |
| M7-G3 0035 PG migration | ABSENT | 0035_ABSENT + DB=0034 | PASS |
| M7-G4 table contract | PASS | 3 新表 to_regclass non-null | PASS |
| M7-G5 column/type contract | PASS | 全列 data_type/udt_name 匹配 | PASS |
| M7-G6 nullability/default | PASS | nullable/server_default 全匹配 | PASS |
| M7-G7 JSONB physical types | PASS | customer_profiles 两列 jsonb | PASS |
| M7-G8 constraints | PASS | PK/FK/UNIQUE/CHECK 全匹配 | PASS |
| M7-G9 indexes | PASS | 3 index 全匹配 | PASS |
| M7-G10 data invariants | PASS | cast 无非法 JSON；row count 不变 | PASS |
| M7-G11 unaffected data sanity | PASS | ct=1740/cp=1/drj=0 = M4 | PASS |
| M7-G12 approved P1 artifacts | PASS | 3 新表 + 幂等列兼容 | PASS |
| M7-G13 9000 | STILL STOPPED | exited | PASS |
| M7-G14 writer/open tx | NONE | client backends 0 rows | PASS |
| M7-G15 write-style locks | NONE | 0 rows | PASS |
| M7-G16 9100 | UNCHANGED | 逐位 = PRE-M1 | PASS |
| M7-G17 postgres | HEALTHY | healthy | PASS |

## A3-73 M7 Verdict

```text
M7 = PASS
DB0034_SCHEMA_VERIFICATION    = VERIFIED
DB0034_DATA_VERIFICATION       = VERIFIED
DB0034_PRODUCTION_ACCEPTANCE  = VERIFIED
M8_ENTRY_GATE = OPEN
```

### 逐 migration verdict

| Revision | Schema checks | Data checks | Verdict |
|---|---|---|---|
| 0029 | 2 列 JSONB ✓ | NULL 保持 NULL，cast 无非法 JSON | PASS |
| 0030 | 2 列 + UNIQUE ✓ | 1740 行全 NULL（backward-compatible） | PASS |
| 0032 | 新表 + PK/FK/CHECK + index + column ✓ | 空表合法；daily_report_jobs=0=M4 | PASS |
| 0033 | 新表 + PK/CHECK + index ✓ | 空表合法 | PASS |
| 0034 | 新表 + PK/CHECK + index ✓ | 空表合法 | PASS |

### M7 mutation 分类

```text
PRODUCTION_DATABASE_MUTATION_IN_M7     = NO
PRODUCTION_SCHEMA_MUTATION_IN_M7        = NO
PRODUCTION_APPLICATION_RUNTIME_MUTATION_IN_M7 = NO
PRODUCTION_MIGRATION_EXECUTED           = YES（继承自 M6）
PRODUCTION_DB                            = 0034
MAINTENANCE_ENTERED                      = YES（继承自 M1）
ROLLBACK_REQUIRED                        = NO
```
M7 是验收，非第二轮 migration。

### M6 governance note（Step 30）

```text
M6_RUNTIME = target-image one-off container
M6_RUNTIME_SELECTION = derived after read-only closure（三件只读核实：alembic.ini / env.py DATABASE_URL / PG network DNS）
SEPARATE_POST-CLOSURE_REFREEZE = NOT PERFORMED
TECHNICAL_IMPACT = NONE OBSERVED（M7 验收 schema/data 全 PASS，M6 迁移结果正确）
CLASSIFICATION = NON_BLOCKING_PROCESS_DEVIATION
```
M6 concrete procedure（target image one-off 容器 `alembic upgrade 0034`）已记录为本 release canonical evidence（A3-55~A3-56）。不触发 rollback/re-execution。

## A3-74 M7 STOP — 不下发 M8、不部署 target9000

```text
M1~M7 = PASS
WRITE_ISOLATION             = VERIFIED
ROLLBACK_IMAGE_PRESERVATION = VERIFIED
PRODUCTION_DB_BACKUP        = VERIFIED
RESTORE_READINESS           = VERIFIED
FINAL_TARGET_VERIFICATION   = VERIFIED
DB0034_SCHEMA_VERIFICATION  = VERIFIED
DB0034_DATA_VERIFICATION    = VERIFIED
DB0034_PRODUCTION_ACCEPTANCE = VERIFIED
PRODUCTION_DB = 0034
9000 = STOPPED
TARGET9000 = NOT DEPLOYED
9100 = UNCHANGED / DB 0003
M8_ENTRY_GATE = OPEN
M8 = NOT EXECUTED
```

下一步 = M8 — DEPLOY TARGET9000（old stopped container → target image 4b4f96fc...）。这是第二个重大 mutation 点：production application runtime 从 old stopped 切到 target image。需用户单独授权。本轮不 S10-B --apply / 不 docker compose up / 不启动 target9000。

---

# ATTEMPT 3 — M8 Deploy Target9000（2026-08-13）

> **第二个重大 mutation 点**：DB 已 0034，把 production 9000 runtime 从 old stopped 切到冻结 target image。
> 唯一 mutation = S10-B `--apply`（9000 recreate）。不碰 DB schema、不触 9100/postgres/frontend、不 curl /ready（属 M9）。

## A3-75 M8 Pre-Apply Identity（M8-A1~A6/A8）

```text
M8-G2 Stage identity     = a633b486 / CLEAN ✓
M8-G3 Release env SHA    = ad2efb0c4a1edf4a0734b81af30fc29b6f79f81760ac8ee2f9fd620290454973 = frozen / mode 600 root ✓
M8-G4 Target image       = sha256:4b4f96fc... = frozen ✓
M8-G5 DB pre-apply       = 0034 ✓
M8-G6 old9000            = stopped (state=exited, CID=a4421aabee73...) ✓
second-9000 gate         = 仅已知 old9000 ✓
```

Pre-apply 四服务 snapshot 冻结（供 M8-D/E 比对）：
```text
PRE_M8_9000     = CID=a4421aabee73... Image=93094f0... exited
PRE_M8_9100     = CID=49548f1bad1a... Image=93094f0... running / StartedAt=2026-08-06T15:51:36.764... / Restart=0
PRE_M8_POSTGRES = CID=2b2390531331... Image=fd1e8d0274... running / StartedAt=2026-08-06T15:51:36.375... / Restart=0
PRE_M8_FRONTEND = CID=85b175f42157... Image=79f52b6e1... running / StartedAt=2026-08-06T15:51:46.415... / Restart=0
```

## A3-76 Compose Project Identity Gate（M8-A7/A9，关键 GAP 闭合）

**GAP 发现**：生产容器 project label=`xg_ai_system`（ProjectDir=/www/wwwroot/XG_AI_System）。docker-compose.yml 无 `name:` 顶级字段，.env.production.local 无 `COMPOSE_PROJECT_NAME`。Docker Compose 默认 project name=工作目录 basename。wrapper 从 STAGE 执行（cwd=STAGE），STAGE basename=`XG_AI_System_release_0034_a633b486` → 默认会创建第二套 project `xg_ai_system_release_0034_a633b486`，不操作现有生产 project。

**只读闭合核实（M8-A9，用户选"先只读核实再定"）**：
```text
A9.1 STAGE 默认 project ps = 0 容器（证明默认建第二套，GAP 根因坐实）
A9.2 STAGE + COMPOSE_PROJECT_NAME=xg_ai_system ps = 生产 4 服务（old9000 exited / 9100+postgres+frontend running healthy），CID 与 A7/A9.4 一致
A9.3 STAGE + project binding config images = 9000=xg-ai-system-backend:b7-0034-a633b486 / 9100=xg-ai-system-backend@sha256:93094f0...
A9.4 PROD baseline ps = 4 服务与 A9.2 逐位一致
```

**闭合方法**：command-scoped `COMPOSE_PROJECT_NAME=xg_ai_system` env var 注入（wrapper subprocess 继承；compose_env() 保留 os.environ 中除两 IMAGE 变量外的所有变量）。
- 不改 wrapper 源码
- 不改 release-exec.env 文件（SHA ad2efb0c... 不变，M8-A2 已验）
- 不碰 DB/runtime
- Docker Compose 原生 project 锁定机制（env var 优先级 > 目录 basename 推断）

```text
M8_COMPOSE_PROJECT_IDENTITY_GAP = RESOLVED
M8-G7 = PASS (COMPOSE_PROJECT_NAME=xg_ai_system 是 M8 必要参数，非可选)
PROJECT_BINDING = command-scoped，preflight/dry-run/apply 三者必须完全一致
```

## A3-77 M8 S10-B Immediate Preflight / Dry-Run（M8-B）

```text
M8-G8 preflight RC = 0（command-scoped COMPOSE_PROJECT_NAME=xg_ai_system + wrapper exact M5 command）
M8-G9 dry-run: resolved 9000=xg-ai-system-backend:b7-0034-a633b486 / 9100=xg-ai-system-backend@sha256:93094f0...
  identity isolation PASS
  canonical 9000-only command = up -d --no-deps --no-build auto-wechat-api（只 9000，无 9100/postgres/frontend，无 build/pull）
host env pollution = CLOSED（wrapper compose_env sanitize 生效）
```

## A3-78 M8 S10-B Apply Execution（M8-C，EXACTLY ONCE）

```
===== M8 PRODUCTION APPLICATION RUNTIME MUTATION =====
DB=0034 / TARGET IMAGE=4b4f96fc... / S10-B PREFLIGHT=PASS / DRY-RUN=PASS / COMPOSE PROJECT IDENTITY=VERIFIED(xg_ai_system)
DEPLOYING TARGET9000 EXACTLY ONCE
```

从 apply 启动：`PRODUCTION_APPLICATION_RUNTIME_MUTATION_IN_M8=YES` / `TARGET9000_DEPLOYMENT_ATTEMPTED=YES`

concrete command（command-scoped project binding，复用 M5 exact wrapper，切到 --apply）：
```text
COMPOSE_PROJECT_NAME=xg_ai_system \
python3 scripts/release_9000_s10b.py \
  --env-file /root/.xg-ai-release/b7-0034-a633b486.env \
  --expected-9000 xg-ai-system-backend:b7-0034-a633b486 \
  --expected-9100 xg-ai-system-backend@sha256:93094f0... \
  --apply
```
```text
preflight PASS → compose up -d --no-deps --no-build auto-wechat-api
[+] Running 1/1 ✔ Container xg-auto-wechat-api Started (0.2s)
M8-G10 apply count = exactly 1（无 retry）
M8-G11 S10B_APPLY_RC = 0
```

## A3-79 M8 Target9000 Runtime Identity（M8-D，retry 修正 project binding）

```text
M8-G12 new9000 project = xg_ai_system（= 生产 project，未建第二套）✓
      new9000 service  = auto-wechat-api ✓
M8-G13 new9000 image   = sha256:4b4f96fc75c63c49401d66ed9ca96bcac0d49681d68b41b88f5c948a3af1ae0f = target ✓
M8-G14 new9000 state   = running ✓
      new9000 Health   = healthy（已 healthy，但不越权判 M9）
new9000 CID  = efa05cb59cf829bd600609f76f1678396052b43979a13353887cf4404fc74f34（≠ old a4421aabee73）
old→new transition = CONFIRMED (old != new, new_image=target)
```
注：M8-D1 初次 `$DC`（无 COMPOSE_PROJECT_NAME 前缀）查不到 new9000（`NEW_9000_MISSING`）——这是 verify 命令 project 定位 bug（与 M8-A9.1 同构：STAGE 默认 project 无容器），非部署失败。修正：verify 的所有 `compose ps` 加 command-scoped `COMPOSE_PROJECT_NAME=xg_ai_system` 前缀（与 apply 一致）。retry 后 new9000 找到且全匹配。未 retry apply、未改参数、未动 DB/runtime。

## A3-80 M8 9100 Unchanged Evidence（M8-E1）

```text
M8-G15 9100 = UNCHANGED: CID=49548f1bad1a.../Image=93094f0.../Restart=0/StartedAt=2026-08-06T15:51:36.764... 逐位 = PRE_M8 ✓
9100_UNCHANGED = PASS（collateral mutation = NONE）
```

## A3-81 M8 Postgres / Frontend Unchanged Evidence（M8-E2/E3）

```text
M8-G16 postgres = UNCHANGED: CID=2b2390531331.../Status=running/Restart=0/StartedAt=2026-08-06T15:51:36.375... 逐位 = PRE_M8 ✓
M8-G17 frontend = UNCHANGED: CID=85b175f42157.../Status=running/Restart=0/StartedAt=2026-08-06T15:51:46.415... 逐位 = PRE_M8 ✓
POSTGRES_UNCHANGED=PASS / FRONTEND_UNCHANGED=PASS
```
`--no-deps` 保证 9000 recreate 不波及 9100/postgres/frontend。三服务 CID/StartedAt/Restart 逐位不变，collateral lifecycle mutation = NONE。

## A3-82 M8 DB0034 Post-Apply Evidence（M8-E4/E5）

```text
M8-G18 POST_M8_DB_REVISION = 0034（M8 不改 DB schema）✓
M8-G19 POST_TARGET_IMAGE_ID = sha256:4b4f96fc...（target tag 自身不漂移，apply 未 rebuild/retag）✓
```

## A3-83 M8 Final Evidence Matrix

| Gate | Required | 证据 | 裁定 |
|---|---|---|---|
| M8-G1 M7 entry gate | OPEN | M7=PASS | PASS |
| M8-G2 Stage identity | a633b486 | rev-parse | PASS |
| M8-G3 Release env SHA | frozen | ad2efb0c... | PASS |
| M8-G4 Target image pre-apply | 4b4f96fc... | inspect | PASS |
| M8-G5 DB pre-apply | 0034 | alembic_version | PASS |
| M8-G6 old9000 | stopped | exited | PASS |
| M8-G7 Compose project identity | existing production project | COMPOSE_PROJECT_NAME=xg_ai_system 闭合 | PASS |
| M8-G8 S10-B preflight | PASS | RC=0 | PASS |
| M8-G9 S10-B dry-run | PASS | resolved + canonical cmd | PASS |
| M8-G10 Apply count | exactly 1 | 无 retry | PASS |
| M8-G11 Apply RC | 0 | S10B_APPLY_RC=0 | PASS |
| M8-G12 new9000 project/service | xg_ai_system / auto-wechat-api | inspect labels | PASS |
| M8-G13 new9000 image ID | 4b4f96fc... | inspect | PASS |
| M8-G14 new9000 state | running | state.Status | PASS |
| M8-G15 9100 | unchanged | 逐位 = PRE_M8 | PASS |
| M8-G16 postgres lifecycle | unchanged | 逐位 = PRE_M8 | PASS |
| M8-G17 frontend lifecycle | unchanged | 逐位 = PRE_M8 | PASS |
| M8-G18 DB after M8 | 0034 | alembic_version | PASS |
| M8-G19 target tag ID | unchanged | 4b4f96fc... | PASS |

## A3-84 M8 Verdict

```text
M8 = PASS
TARGET9000_DEPLOYED = YES
TARGET9000_RUNTIME_IDENTITY = VERIFIED
M9_ENTRY_GATE = OPEN
```

### M8 mutation 分类

```text
PRODUCTION_APPLICATION_RUNTIME_MUTATION_IN_M8 = YES   (9000 recreate → target image)
TARGET9000_DEPLOYMENT_ATTEMPTED                = YES
TARGET9000_DEPLOYED                            = YES
PRODUCTION_DATABASE_MUTATION_IN_M8             = NO
PRODUCTION_SCHEMA_MUTATION_IN_M8               = NO
9100_MUTATION_IN_M8                            = NO
POSTGRES_RUNTIME_MUTATION_IN_M8                = NO
FRONTEND_RUNTIME_MUTATION_IN_M8                = NO
MAINTENANCE_ENTERED                            = YES   (继承自 M1，未退出)
ROLLBACK_REQUIRED                              = NO
```

### M8 冻结 new9000 identity（M9/M10 比对基线）

```text
NEW9000_CID      = efa05cb59cf829bd600609f76f1678396052b43979a13353887cf4404fc74f34
NEW9000_IMAGE_ID = sha256:4b4f96fc75c63c49401d66ed9ca96bcac0d49681d68b41b88f5c948a3af1ae0f
NEW9000_PROJECT  = xg_ai_system
NEW9000_SERVICE  = auto-wechat-api
NEW9000_STARTED  = 2026-08-13T07:32:47.736329723Z
```

### M8 关键 GAP 闭合记录（治理 lesson）

M8-G7 Compose Project Identity GAP 是本阶段最重要发现：wrapper 从 STAGE 执行默认用 STAGE basename 推断 project，会建第二套 compose project。通过 command-scoped `COMPOSE_PROJECT_NAME=xg_ai_system` 闭合（不改 wrapper/不改 release-exec.env SHA/不碰 DB）。此为 M8 必要参数，preflight/dry-run/apply 三者必须完全一致。A9 现场事实验证：注入后从 STAGE 准确选中生产 project 四服务（CID 匹配 PROD baseline）。

## A3-85 M8 STOP — 不下发 M9、不 curl /ready

```text
M1~M8 = PASS
WRITE_ISOLATION             = VERIFIED
ROLLBACK_IMAGE_PRESERVATION = VERIFIED
PRODUCTION_DB_BACKUP        = VERIFIED
RESTORE_READINESS           = VERIFIED
FINAL_TARGET_VERIFICATION   = VERIFIED
DB0034_SCHEMA_VERIFICATION  = VERIFIED
DB0034_DATA_VERIFICATION    = VERIFIED
DB0034_PRODUCTION_ACCEPTANCE = VERIFIED
TARGET9000_DEPLOYED         = YES
TARGET9000_RUNTIME_IDENTITY = VERIFIED
PRODUCTION_DB = 0034
9000 = RUNNING (target image 4b4f96fc...)
9100 = UNCHANGED / DB 0003
M9_ENTRY_GATE = OPEN
M9 = NOT EXECUTED
```

下一步 = M9 — VERIFY TARGET9000 READY（/health /ready expected=actual=0034 + container health + startup/error logs + 最小 smoke）。需用户显式授权。本轮不 curl /ready、不 curl /health、不业务 smoke、不退出 maintenance。MAINTENANCE_ENTERED 仍 YES（M11 才退出）。

---

# ATTEMPT 3 — M9 Verify Target9000 Ready（2026-08-13）

> **只读验收**：已部署的 target9000 是否真正启动成功，应用自身确认 expected DB revision = actual DB revision = 0034。不改变生产状态。
> 失败不自动修复（不 restart/recreate/rerun apply/restore/edit nginx），冻结现场 `ROLLBACK_REQUIRED=TO_BE_ADJUDICATED`。

## A3-86 M9 Target Runtime Reality（M9-A）

```text
M9-G1 target9000 CID    = efa05cb59cf829bd600609f76f1678396052b43979a13353887cf4404fc74f34 = M8 frozen ✓
M9-G2 image ID          = sha256:4b4f96fc75c63c49401d66ed9ca96bcac0d49681d68b41b88f5c948a3af1ae0f = target ✓
M9-G3 project/service   = xg_ai_system / auto-wechat-api ✓
M9-G4 container state   = running ✓
M9-G5 container health  = healthy ✓
M9-G14 restart count    = 0（无 restart instability）✓
用冻结 CID 直接 inspect（避免 STAGE project selector 错误，M8-D1 教训）
```

## A3-87 M9 Local Health（M9-B）

```text
M9-G6 local /health = HTTP200
body = {"service":"auto_wechat","status":"ok"}
LOCAL_HEALTH = PASS
```

## A3-88 M9 Local Readiness / DB Compatibility（M9-C）

```text
M9-G7 local /ready = HTTP200
ready body（exact response schema，复用 M0/M5 contract）:
  backend=postgresql / db_connect=pass / database_name=pass(expected=actual=auto_wechat)
  alembic_revision=pass / expected=["0034"] / actual=["0034"]
  critical_tables=pass(douyin_leads/sales_staff)
M9-G8 app expected revision = 0034 ✓
M9-G9 app actual revision   = 0034 ✓
M9-G10 direct DB revision   = 0034 (psql alembic_version) ✓
TARGET9000_DB_COMPATIBILITY = VERIFIED（三方一致：app expected=0034 / app actual=0034 / direct DB=0034）
```

## A3-89 M9 Public Readiness Path（M9-D）

```text
M9-G11 public /api/ready (https://merchant.xiaogaoai.cn/api/ready) = HTTP200
M9-G12 public expected/actual = 0034 / 0034
  public ready body 与 local ready 语义一致：alembic_revision expected=["0034"] actual=["0034"]
  → 反代链路已正确指向新 9000，生产用户路径已恢复
PRODUCTION_PUBLIC_READY_PATH = VERIFIED
```

## A3-90 M9 Startup / Error Log Review（M9-E）

```text
startup log（--since 2026-08-13T07:32:47Z）= 185 行
M9-G13 blocking startup errors = NONE（traceback/fatal/panic/startup failed/connection refused/revision mismatch scan 全无命中）
error/warning scan = NONE（无 error/warning 命中）
```
log 命中不自动 FAIL，需分类；本轮 0 命中，无需分类。

## A3-91 M9 Minimal Non-Destructive Smoke（M9-F）

```text
M9-G15 minimal smoke = PASS
smoke = local /health + local /ready + public /api/ready（均 HTTP200 + revision 0034）
覆盖：process / HTTP server / DB connectivity / DB revision compatibility / reverse proxy path
不创造业务数据（不 create lead / 不 send Douyin message / 不 trigger task / 不现场发明 GET endpoint）
```

## A3-92 M9 Final Runtime Recheck（M9-G）

```text
final inspect: CID=efa05cb59cf8... / Image=4b4f96fc... / Status=running / Restart=0 / Health=healthy
与 M9-A 一致：CID/Image/Status 未变，RestartCount 未增（无 restart loop），Health 仍 healthy
M9_FINAL_STABLE = PASS
```

## A3-93 M9 Final Evidence Matrix

| Gate | Required | 证据 | 裁定 |
|---|---|---|---|
| M9-G1 target9000 CID | exact efa05cb59cf8... | inspect | PASS |
| M9-G2 image ID | 4b4f96fc... | inspect | PASS |
| M9-G3 project/service | xg_ai_system / auto-wechat-api | inspect labels | PASS |
| M9-G4 container state | running | state.Status | PASS |
| M9-G5 container health | healthy | healthcheck | PASS |
| M9-G6 local /health | HTTP200 | curl | PASS |
| M9-G7 local /ready | HTTP200 | curl | PASS |
| M9-G8 app expected | 0034 | ready body | PASS |
| M9-G9 app actual | 0034 | ready body | PASS |
| M9-G10 direct DB | 0034 | psql | PASS |
| M9-G11 public /api/ready | HTTP200 | curl merchant | PASS |
| M9-G12 public expected/actual | 0034/0034 | public body | PASS |
| M9-G13 blocking errors | NONE | log scan | PASS |
| M9-G14 restart instability | NONE | RestartCount=0 | PASS |
| M9-G15 minimal smoke | PASS | health+ready+public | PASS |

## A3-94 M9 Verdict

```text
M9 = PASS
TARGET9000_HEALTH = VERIFIED
TARGET9000_READINESS = VERIFIED
TARGET9000_DB_COMPATIBILITY = VERIFIED
PRODUCTION_PUBLIC_READY_PATH = VERIFIED
M10_ENTRY_GATE = OPEN
```

### M9 核心证据——四项一致

```text
target image = sha256:4b4f96fc75c63c49401d66ed9ca96bcac0d49681d68b41b88f5c948a3af1ae0f
app expected = 0034
app actual   = 0034
direct DB    = 0034
→ 现在运行的是与已验收 DB0034 匹配的 target9000
```

### M9 mutation 分类

```text
PRODUCTION_APPLICATION_RUNTIME_MUTATION_IN_M9 = NO   (只读验收)
PRODUCTION_DATABASE_MUTATION_IN_M9            = NO
PRODUCTION_SCHEMA_MUTATION_IN_M9              = NO
M9 = READ_ONLY_ACCEPTANCE
UNEXPECTED_RUNTIME_MUTATION = NO（target9000 全程 running/healthy，RestartCount=0 未变化）
MAINTENANCE_ENTERED = YES（继承自 M1，未退出）
ROLLBACK_REQUIRED = NO
```

## A3-95 M9 STOP — 不下发 M10/M11、不退出 maintenance

```text
M1~M9 = PASS
PRODUCTION_DB = 0034
DB0034_PRODUCTION_ACCEPTANCE = VERIFIED
TARGET9000_DEPLOYED = YES
TARGET9000_RUNTIME_IDENTITY = VERIFIED
TARGET9000_HEALTH = VERIFIED
TARGET9000_READINESS = VERIFIED
TARGET9000_DB_COMPATIBILITY = VERIFIED
PRODUCTION_PUBLIC_READY_PATH = VERIFIED
9000 = TARGET / RUNNING / HEALTHY (4b4f96fc...)
9100 = UNCHANGED / DB 0003（inherited pending M10 final verification）
MAINTENANCE_ENTERED = YES
M10_ENTRY_GATE = OPEN
M10 = NOT EXECUTED
M11 = NOT EXECUTED
```

下一步 = M10 — FINAL VERIFY 9100 UNCHANGED（9100 CID/Image/DB0003 最终独立核验）。需用户显式授权。即使 M9 全 PASS，仍不退出 maintenance（M11 才正式退出）。本轮不 declare production release complete、不 M10、不 M11。

---

# ATTEMPT 3 — M10 Final Verify 9100 Unchanged（2026-08-13）

> **最后一个正式隔离验收门**：独立证明 9100 从 PRE-M1 冻结基线到现在，CID/Image/StartedAt/RestartCount/DB revision 均无变化。
> M10 最有价值的证据不是"9100 healthy"，而是完整 CID+Image+StartedAt+RestartCount 从维护前到现在一项都没变，叠加应用和数据库都仍 0003。这关闭整个 catch-up 对 9100 的"零影响"承诺。
> 全只读，无 mutation。失败绝不"修 9100"（不 restart/recreate/upgrade），冻结现场。

## A3-96 M10 Frozen 9100 Baseline Recovery（M10-A）

从执行报告 A3-12 恢复完整 PRE-M1 frozen 值（无缩写，无 placeholder）：
```text
FROZEN_9100_CID          = 49548f1bad1abad38eecb260c6c84fe64f3616023bab7e76d2353027d1bf1373
FROZEN_9100_IMAGE_ID     = sha256:93094f0a02ba3a4570160ce90625cb80fdec85076046fc314f5fe407add36c68
FROZEN_9100_STARTED_AT   = 2026-08-06T15:51:36.764350664Z
FROZEN_9100_RESTART_COUNT = 0
M10-G1 frozen baseline evidence = COMPLETE
```

## A3-97 M10 Runtime Identity Comparison（M10-B，从 PROD tree 执行）

从 PROD tree 执行（.env.production.local，避开 STAGE basename 问题）：
```text
compose ps -a 对比：9000 = 30 minutes ago Up 30 minutes（M8 刚部署）/ 9100 = 6 days ago Up 6 days → 9100 从未被 recreate/restart
M10-G2 current CID    = 49548f1bad1a... = PRE-M1 frozen ✓
M10-G3 image ID        = sha256:93094f0... = frozen ✓
M10-G4 StartedAt       = 2026-08-06T15:51:36.764350664Z = frozen ✓（逐位）
M10-G5 RestartCount    = 0 = frozen ✓
M10-G6 project/service = xg_ai_system / xg-douyin-ai-cs ✓
M10-G7 status          = running ✓
M10-G8 health          = healthy ✓
9100_FROZEN_RUNTIME_IDENTITY = PASS（四项逐位一致，非"后来恢复 healthy"）
```

## A3-98 M10 Ready Verification（M10-C）

```text
M10-G9 local /ready = HTTP200
M10-G10 ready expected = 0003 / M10-G11 ready actual = 0003
ready body（exact schema）: xg_douyin_ai_cs / backend=postgresql / db_connect=pass / alembic_revision pass expected=["0003"] actual=["0003"]
  critical_tables=pass(knowledge_documents/knowledge_chunks)
  milvus: connected=true / collection_exists=true / schema_match=true / query_ok=true（RAG 后端正常）
9100_LOCAL_READY = PASS
```

## A3-99 M10 Alembic Current/Head（M10-D）

```text
M10-D0 alembic.ini EXISTS at /workspace/migrations/postgres/xg_douyin_ai_cs/alembic.ini ✓
interpreter = /usr/local/bin/python
M10-G12 alembic current = 0003 (head) ✓
M10-G13 alembic heads   = 0003 (head) ✓
→ 9100_DATABASE_REVISION=0003 / 9100_MIGRATION_HEAD=0003
→ 证明 9000 的 0034 migration 没误作用到 9100（9100 仍 DB0003）
```
read-only current/heads，未 upgrade/downgrade/stamp。

## A3-100 M10 Final Stability Recheck（M10-E）

```text
M10-G14 final: CID=49548f1bad1a.../Image=93094f0.../Status=running/Restart=0/StartedAt=2026-08-06T15:51:36.764.../Health=healthy
四项 frozen identity 仍逐位一致，9100_FINAL_STABILITY = PASS
```

## A3-101 M10 Final Evidence Matrix

| Gate | Required | 证据 | 裁定 |
|---|---|---|---|
| M10-G1 frozen baseline | COMPLETE | 完整 4 值从报告恢复 | PASS |
| M10-G2 current CID | PRE-M1 CID | 49548f1bad1a... | PASS |
| M10-G3 image ID | 93094f0... | inspect | PASS |
| M10-G4 StartedAt | PRE-M1 value | 2026-08-06T15:51:36.764... | PASS |
| M10-G5 RestartCount | PRE-M1 value | 0 | PASS |
| M10-G6 project/service | xg_ai_system/xg-douyin-ai-cs | labels | PASS |
| M10-G7 status | running | state.Status | PASS |
| M10-G8 health | healthy | healthcheck | PASS |
| M10-G9 /ready | HTTP200 | curl | PASS |
| M10-G10 ready expected | 0003 | body | PASS |
| M10-G11 ready actual | 0003 | body | PASS |
| M10-G12 alembic current | 0003 | alembic | PASS |
| M10-G13 alembic heads | 0003 | alembic | PASS |
| M10-G14 final unchanged | unchanged | final inspect | PASS |

## A3-102 M10 Verdict

```text
M10 = PASS
9100_FINAL_UNCHANGED_VERIFICATION = VERIFIED
9100_RUNTIME_IDENTITY = UNCHANGED_FROM_PRE_M1
9100_DATABASE_REVISION = 0003
9100_MIGRATION_HEAD = 0003
M11_ENTRY_GATE = OPEN
```

### M10 mutation 分类

```text
PRODUCTION_APPLICATION_RUNTIME_MUTATION_IN_M10 = NO
PRODUCTION_DATABASE_MUTATION_IN_M10             = NO
9100_RUNTIME_MUTATION_IN_M10                     = NO
9100_DATABASE_MUTATION_IN_M10                    = NO
M10 = READ_ONLY_FINAL_ISOLATION_ACCEPTANCE
MAINTENANCE_ENTERED = YES（继承自 M1，未退出）
ROLLBACK_REQUIRED = NO
```

### M10 关键证据：9100 零影响承诺关闭

```text
compose ps 对比：9000=30min ago Up 30min（M8 部署）/ 9100=6 days ago Up 6 days → 9100 从未被 recreate/restart
9100 StartedAt=2026-08-06T15:51:36.764350664Z = PRE-M1（M1 前冻结）逐位一致
RestartCount=0：整个 catch-up（M1 stop9000 → M6 migration → M8 deploy target9000）9100 零 lifecycle 变化
alembic current/heads=0003：9000 的 0034 migration 没误作用到 9100
→ 关闭整个 catch-up 对 9100 的"零影响"承诺
```

## A3-103 M10 STOP — 不下发 M11、不退出 maintenance

```text
M1~M10 = PASS
PRODUCTION_DB = 0034
TARGET9000 = RUNNING / HEALTHY / READY (4b4f96fc...)
TARGET9000_DB_COMPATIBILITY = VERIFIED
PRODUCTION_PUBLIC_READY_PATH = VERIFIED
9100_FINAL_UNCHANGED_VERIFICATION = VERIFIED
9100 = UNCHANGED / DB 0003 / StartedAt=2026-08-06T15:51:36.764... / Restart=0
MAINTENANCE_ENTERED = YES
M11_ENTRY_GATE = OPEN
M11 = NOT EXECUTED
```

下一步 = M11 — EXIT MAINTENANCE（最终 release-state 快照 + 确认 9000/9100 均正常 + 正式 MAINTENANCE_ENTERED=NO）。需用户显式授权。本轮不退出 maintenance、不 declare production release complete。

---

# ATTEMPT 3 — M11 Exit Maintenance（2026-08-13）

> **整个 0028→0034 production catch-up 的最后一道正式门**：最终生产快照 → 确认所有 release invariants 仍成立 → 关闭 maintenance → post-exit stability check → 正式宣布 Attempt 3 / baseline catch-up COMPLETE。
> M11 不做 migration/deploy/repair。全只读。

## A3-104 M11 Final Release-State Snapshot（M11-A）

```text
M11-A1 compose ps: 9000=38min ago Up 38min healthy(target) / 9100=6 days ago Up 6 days healthy / postgres=Up 6 days healthy / frontend=Up 6 days healthy
M11-G2 target9000 CID/image = efa05cb59cf829bd600609f76f1678396052b43979a13353887cf4404fc74f34 / sha256:4b4f96fc... = frozen ✓
M11-G3 target9000 running/healthy = Up 38min, healthy ✓
M11-G4 target9000 restart stability = Restart=0（M9→M11 未增长）✓
```

## A3-105 M11 Target9000 Final Acceptance（M11-A3/A4）

```text
M11-G5 local /ready = HTTP200 / expected=["0034"] / actual=["0034"] ✓
M11-G6 public /api/ready = HTTP200 / expected=["0034"] / actual=["0034"] ✓
M11-G7 production DB = 0034 (FINAL_PRODUCTION_DB_REVISION=0034) ✓
```

## A3-106 M11 9100 Final Freeze（M11-B）

```text
M11-G8 9100 frozen runtime = CID=49548f1bad1a.../Image=93094f0.../StartedAt=2026-08-06T15:51:36.764350664Z/Restart=0 逐位 = M10 frozen ✓
M11-G9 9100 /ready = HTTP200 / expected=["0003"] / actual=["0003"] + milvus connected/collection_exists/schema_match/query_ok ✓
9100_FINAL_FREEZE = PASS
```

## A3-107 M11 Rollback Assets Final Presence（M11-C）

```text
M11-G12 rollback image = sha256:93094f0... (xg-ai-system-backend:rollback-b7-0028-f453f44-93094f0) preserved ✓
M11-G13 DB backup SHA = bee463c2a061d49650372d0f0da7c271f067acb031d568e198feafdc09864ee1 / size 1073194 preserved ✓
ROLLBACK_IMAGE_PRESERVED = PASS / BACKUP_PRESERVED = PASS
```

## A3-108 M11 Maintenance-Exit Provenance（M11-E，Case B）

核查 design §25 step 1-2/12：本次 maintenance 实际是 M1 stop9000（停服，非反代 503）→ M8 target9000 restored → M9 public path ready。design step 2"反代 503 或停服"本次选停服；step 12"撤反代 503"是 design 候选表述，本次未设反代 503 故无需撤。执行链 M1-M10 全程未执行任何 nginx/反代/maintenance-flag 操作，未设置维护页、未暂停 webhook（webhook 一直指向 9000，9000 停止期间 public 自然 503，M8 启动后恢复 200）。

```text
M11-G15 exit-maintenance provenance = VERIFIED (Case B: STATE_CLOSURE_ONLY)
M11_MAINTENANCE_EXIT_ACTION = STATE_CLOSURE_ONLY
ADDITIONAL_RUNTIME_MUTATION_REQUIRED = NO
（未发明命令/未 restart nginx/未 toggle 未设过的东西——这是合法的 M11 exit）
```

## A3-109 M11 Post-Exit Stability（M11-F + G16）

M11-A3（local+public ready 0034）+ M11-B2（9100 ready 0003）+ 四服务 RestartCount 全 0 + CIDs 全 = frozen 已覆盖退出前稳定：
```text
M11-G16 post-exit stability = PASS
9000 running/healthy/ready 0034 / 9100 running/healthy/ready 0003 / postgres healthy / frontend healthy / RestartCount 全 0
```

## A3-110 M11 Final Evidence Matrix

| Gate | Required | 证据 | 裁定 |
|---|---|---|---|
| M11-G1 M10 entry gate | OPEN | M10=PASS | PASS |
| M11-G2 target9000 CID/image | frozen target | efa05cb59cf8.../4b4f96fc... | PASS |
| M11-G3 target9000 running/healthy | PASS | Up 38min healthy | PASS |
| M11-G4 target9000 restart stability | PASS | Restart=0 | PASS |
| M11-G5 local ready | 200/0034/0034 | curl | PASS |
| M11-G6 public ready | 200/0034/0034 | curl merchant | PASS |
| M11-G7 production DB | 0034 | psql | PASS |
| M11-G8 9100 frozen runtime | unchanged | 逐位=frozen | PASS |
| M11-G9 9100 ready | 200/0003/0003 | curl + milvus | PASS |
| M11-G10 postgres lifecycle | unchanged | = M8 frozen | PASS |
| M11-G11 frontend lifecycle | unchanged | = M8 frozen | PASS |
| M11-G12 rollback image | preserved | 93094f0... | PASS |
| M11-G13 DB backup SHA | preserved | bee463c2... | PASS |
| M11-G14 second STAGE project | NONE | filter=0 | PASS |
| M11-G15 exit-maintenance provenance | VERIFIED | Case B STATE_CLOSURE_ONLY | PASS |
| M11-G16 post-exit stability | PASS | ready+identity 复验 | PASS |

## A3-111 Production Execution Attempt 3 Completion

```text
M11 = PASS
MAINTENANCE_ENTERED = NO
MAINTENANCE_EXITED = YES
PRODUCTION_EXECUTION_ATTEMPT_3 = COMPLETE
COMPLETED_AT = 2026-08-13T08:11:44Z
```

## A3-112 Production Baseline Catch-up 0028→0034 Completion

```text
M0 = COMPLETE
BATCH_0A = PASS / BATCH_0B = PASS / BATCH_0C = PASS
PRE_M1 = PASS
M1~M11 = PASS

PRODUCTION_DB = 0034
PRODUCTION_MIGRATION_EXECUTED = YES
DB0034_SCHEMA_VERIFICATION = VERIFIED
DB0034_DATA_VERIFICATION = VERIFIED
DB0034_PRODUCTION_ACCEPTANCE = VERIFIED

TARGET9000_DEPLOYED = YES
TARGET9000_IMAGE_ID = sha256:4b4f96fc75c63c49401d66ed9ca96bcac0d49681d68b41b88f5c948a3af1ae0f
TARGET9000_RUNTIME_IDENTITY = VERIFIED
TARGET9000_HEALTH = VERIFIED
TARGET9000_READINESS = VERIFIED
TARGET9000_DB_COMPATIBILITY = VERIFIED
PRODUCTION_PUBLIC_READY_PATH = VERIFIED

9100_FINAL_UNCHANGED_VERIFICATION = VERIFIED
9100_DATABASE_REVISION = 0003
9100_MIGRATION_HEAD = 0003

ROLLBACK_IMAGE_PRESERVATION = VERIFIED
PRODUCTION_DB_BACKUP = VERIFIED
RESTORE_READINESS = VERIFIED

MAINTENANCE_ENTERED = NO
PRODUCTION_RELEASE_COMPLETE = YES
ROLLBACK_REQUIRED = NO

PRODUCTION_BASELINE_CATCHUP_0028_TO_0034 = COMPLETE
```

### 最终 Release Identity Snapshot

```text
APPLICATION_BASE           = 9db3f5854095e483a55724e66d452792b354ff53
RELEASE_TREE               = a633b4860b818ab48fda5e22f39aa311eb96e9eb
TARGET9000_IMAGE           = sha256:4b4f96fc75c63c49401d66ed9ca96bcac0d49681d68b41b88f5c948a3af1ae0f
TARGET9000_FINAL_CID       = efa05cb59cf829bd600609f76f1678396052b43979a13353887cf4404fc74f34
PRODUCTION_DB               = 0034
ROLLBACK9000_IMAGE_REF     = xg-ai-system-backend:rollback-b7-0028-f453f44-93094f0
ROLLBACK9000_IMAGE_ID      = sha256:93094f0a02ba3a4570160ce90625cb80fdec85076046fc314f5fe407add36c68
PRODUCTION_BACKUP_FILE     = /www/backup/aw_backup_20260813T062217Z_pre0034.dump
PRODUCTION_BACKUP_SHA256    = bee463c2a061d49650372d0f0da7c271f067acb031d568e198feafdc09864ee1
9100_FINAL_CID             = 49548f1bad1abad38eecb260c6c84fe64f3616023bab7e76d2353027d1bf1373
9100_FINAL_IMAGE           = sha256:93094f0a02ba3a4570160ce90625cb80fdec85076046fc314f5fe407add36c68
9100_DB                    = 0003
COMPLETED_AT               = 2026-08-13T08:11:44Z
```

## A3-113 Carry-forward Findings / Lessons

```text
1. public-origin transport = one-time user-approved exception (a633b486 ONLY) ≠ future default production delivery method
2. M6 migration runtime = target-image one-off container (alembic upgrade 0034 via docker run --network xg_ai_system_default) = successful canonical evidence = had NON_BLOCKING_PROCESS_DEVIATION (concrete runtime not separately refrozen after read-only closure, M7 PASS proved correct result)
3. M8 Compose project identity: STAGE default project ≠ production project; command-scoped COMPOSE_PROJECT_NAME=xg_ai_system = required execution-time binding for STAGE-based production compose operations (不改 wrapper/不改 release-exec.env SHA/不碰 DB)
4. backup /www/backup = logical rollback asset, same filesystem (/dev/vda2) ≠ host-level disaster recovery (NON_BLOCKING, 能应对 bad migration/target failure/logical rollback)
5. 9100 = zero lifecycle impact verified by CID + Image + StartedAt + RestartCount(0) + DB0003 (从未 recreate/restart, StartedAt 2026-08-06T15:51:36.764... 逐位 = PRE-M1)
```

**这些 lesson 进入 carry-forward，不因此继续改代码或 Runbook。后续治理优化另开任务。**

### RB-10 Cleanup 仍 NOT AUTHORIZED

即使 release 完成，不删除 STAGE / backup / rollback image / /tmp verify files / protected untracked files，不 docker prune。本次完成只代表 release 闭环，不代表 cleanup 获批。

---

# PRODUCTION EXECUTION ATTEMPT 3 — COMPLETE

```text
PRODUCTION_BASELINE_CATCHUP_0028_TO_0034 = COMPLETE
PRODUCTION_RELEASE_COMPLETE = YES
MAINTENANCE_ENTERED = NO
ROLLBACK_REQUIRED = NO
COMPLETED_AT = 2026-08-13T08:11:44Z
```

从 0028 到 0034 的生产数据库 baseline catch-up 已全部完成：schema migration 0028→0029→0030→0032→0033→0034 执行成功并经 M7 生产 schema/data 验收，target9000（a633b486/4b4f96fc...）部署并经 M9 ready/health 验收，9100 全程零影响（M10 最终核验 0003 未变），回滚资产（rollback image + DB backup）冻结保存，生产用户路径 merchant.xiaogaoai.cn/api/ready 已恢复 200 + revision 0034。

---

# POST-RELEASE INCIDENT — PROD-POSTRELEASE-RUNTIME-IDENTITY-RECOVERY-1

## A3-114 R0 Recovery Reality Freeze（2026-08-13，只读）

> M11 COMPLETE（08:11:44Z）后约 17 分钟（08:29:05Z），9000/9100/frontend 三服务被非计划 recreate，均换成错误 image `99122305...`（既非 target 4b4f96fc 也非 frozen 93094f0）。R0 全程只读 freeze，禁止任何 mutation。

### R0-A 两棵 tree 身份

```text
PROD tree  = f453f44e6a70de3eb5fa8f808cf4b6a9d72ea6c1（=frozen，3 known protected untracked，无 drift）
STAGE tree = a633b4860b818ab48fda5e22f39aa311eb96e9eb（=frozen，clean，无 drift）
```

### R0-B Compose 合同差异（事故根因核心）

```text
PROD compose hash  = 9d1b96ee...（f453f44 树）
STAGE compose hash = bde9d833...（a633b486 树）
PROD compose image contract  = HARDCODED_SHARED_LATEST
  line 29: image: xg-ai-system-backend:latest（9000，无 ${VAR}）
  line 62: image: xg-ai-system-backend:latest（9100，无 ${VAR}）
STAGE compose image contract = PER_SERVICE_IMAGE_ENV
  line 38: image: ${AUTO_WECHAT_API_IMAGE:-xg-ai-system-backend:latest}
  line 73: image: ${XG_DOUYIN_AI_CS_IMAGE:-xg-ai-system-backend:latest}
```

### R0-C Release Execution Env

```text
release env = /root/.xg-ai-release/b7-0034-a633b486.env mode=600 owner=root size=31430
SHA256 = ad2efb0c4a1edf4a0734b81af30fc29b6f79f81760ac8ee2f9fd620290454973 = frozen evidence ✓
RECOVERY_TARGET_9000_REF = xg-ai-system-backend:b7-0034-a633b486（≠ :latest）✓
RECOVERY_FROZEN_9100_REF = xg-ai-system-backend@sha256:93094f0a02ba3a4570160ce90625cb80fdec85076046fc314f5fe407add36c68（≠ :latest）✓
```

### R0-D 两份 .env.production.local（双入口缺陷）

```text
PROD env = EXISTS mode=600 owner=root size=31002
  auth: APP_ENV=production / NEWCAR_AUTH_ENABLED=true / NEWCAR_AUTH_MOCK_ENABLED=false
  PROD_IMAGE_VARS=ABSENT（无 AUTO_WECHAT_API_IMAGE/XG_DOUYIN_AI_CS_IMAGE）
STAGE env = MISSING（STAGE/.env.production.local 不存在）
```
**口径纠正**：PROD env 缺 image vars **不是** PROD compose 选 :latest 的原因——PROD compose 硬编码 :latest 根本不消费这两个变量。这与 STAGE（消费 ${VAR}）不同。

### R0-E Compose 最终解析（双入口缺陷确认）

```text
R0-E1 PROD compose resolve:
  9000 image=xg-ai-system-backend:latest / APP_ENV=production / NEWCAR_AUTH_ENABLED=true / NEWCAR_AUTH_MOCK_ENABLED=false
  9100 image=xg-ai-system-backend:latest / APP_ENV=production / NEWCAR_AUTH_ENABLED=true / NEWCAR_AUTH_MOCK_ENABLED=false
  → 正确 runtime env + 错误 shared mutable image contract
R0-E2 STAGE compose resolve（用 release-env）:
  9000 image=xg-ai-system-backend:b7-0034-a633b486 / APP_ENV=None / NEWCAR_AUTH_ENABLED=None / NEWCAR_AUTH_MOCK_ENABLED=None
  9100 image=xg-ai-system-backend@sha256:93094f0... / APP_ENV=None / NEWCAR_AUTH_ENABLED=None / NEWCAR_AUTH_MOCK_ENABLED=None
  → STAGE image identity CORRECT，但 service runtime env INCOMPLETE（env_file 注入行为：compose config 的 environment 字段只含显式 environment: 段，不含 env_file；非缺陷，是判定口径细节）
```

### R0-F S10-B Wrapper Preflight（dry-run，只读）

```text
RC=0 / resolved 9000=xg-ai-system-backend:b7-0034-a633b486 / resolved 9100=xg-ai-system-backend@sha256:93094f0...
identity isolation PASS / canonical command 含 --no-deps --no-build auto-wechat-api
THIS PREFLIGHT DOES NOT PROVE SERVICE_RUNTIME_ENV_IDENTITY（wrapper 只验证 image identity，不验证 auth env 完整性）
```

### R0-G 当前 runtime snapshot（事故现场）

```text
9000 = DRIFTED: CID=35f3927c8f7007845bae2abf78aa2d690bcbeb09d978bd8ec390c2d1fcb6530f
       Image=sha256:991223055c0c07098c26a7e77703899c9bdb518b5eb2c2ede7758ffeef5ea0eb
       Status=running Health=unhealthy / Restart=0 / StartedAt=2026-08-13T08:29:05.893170721Z
9100 = RECREATED: CID=a5c5c716d417625bc7b7c918d338b1520164278ca2da840bece18b5287a39177
       Image=sha256:991223055c0c07098c26a7e77703899c9bdb518b5eb2c2ede7758ffeef5ea0eb
       Status=running Health=healthy / Restart=0 / StartedAt=2026-08-13T08:29:05.892474037Z
frontend = RECREATED: CID=1f02e14b5290c2712f25319c70fd08a1552ada4b912515e08e317d6952802bb0
       Image=sha256:56a3e47de236d93147fef0f54f6c5f736011458622dfb817c1126529a420d833
       Status=running Health=healthy / StartedAt=2026-08-13T08:29:05.382406126Z
postgres = UNCHANGED: CID=2b2390531331... / StartedAt=2026-08-06T15:51:36.375... / Restart=0 / healthy
```

### R0-H DB / readiness

```text
9000 /ready = HTTP503 / alembic_revision FAIL expected=["0028"] actual=["0034"] ALEMBIC_REVISION_MISMATCH
9100 /ready = HTTP200 / expected=["0003"] actual=["0003"] + milvus connected/schema_match/query_ok
public /api/ready = HTTP503 / ALEMBIC_REVISION_MISMATCH
DB9000=0034 / DB9100=0003
```

### R0-I 9000 安全配置

```text
APP_ENV=production / NEWCAR_AUTH_ENABLED=true / NEWCAR_AUTH_MOCK_ENABLED=false
NEWCAR_AUTH_BASE_URL_SET=True / NEWCAR_AUTH_SERVICE_TOKEN_SET=False / XG_DOUYIN_AI_CS_SERVICE_TOKEN_SET=True
COMPUTE_INTERNAL_TOKEN_SET=True / LOCAL_AGENT_TOKENS_SET=True
AUTH_RUNTIME_CONFIG = CORRECT_AFTER_UNPLANNED_RECREATE（auth 本身正确，非 mock 泄漏）
```

### R0-J Recovery image assets

```text
target9000 asset  = AVAILABLE sha256:4b4f96fc75c63c49401d66ed9ca96bcac0d49681d68b41b88f5c948a3af1ae0f
frozen9100 asset  = AVAILABLE sha256:93094f0a02ba3a4570160ce90625cb80fdec85076046fc314f5fe407add36c68
rollback tag      = AVAILABLE sha256:93094f0a02ba3a4570160ce90625cb80fdec85076046fc314f5fe407add36c68（rollback-b7-0028-f453f44-93094f0）
```

### R0-K Frontend old image asset

```text
PRE_MUTATION_FRONTEND_CID=85b175f42157f2fc615d15c5f6eacb91c14ff5438ca36c84aa5e3333a96678c2
PRE_MUTATION_FRONTEND_IMAGE_ID=sha256:79f52b6e179c496614c6c593101fc0743f0d68217e3f12995305b9ceac59fd7c
PRE_MUTATION_FRONTEND_STARTED_AT=2026-08-06T15:51:46.415334552Z / RESTART=0
FRONTEND_OLD_IMAGE_ASSET = NOT_AVAILABLE（79f52b6e... 已丢失，:latest 被 99122305 覆盖，frontend 重建为 56a3e47d）
```

### R0-L Exposure window

```text
AUTH_MOCK_EXPOSURE_START ≈ 2026-08-13T07:32:47.736329723Z（M8 target9000 StartedAt）
AUTH_MOCK_EXPOSURE_END   ≈ 2026-08-13T08:29:05.893170721Z（unplanned recreate StartedAt）
AUTHORIZATION_BOUNDARY_EXPOSURE = CONFIRMED
DATA_BREACH = NOT_ESTABLISHED（需单独 audit）
MUTATION_ABUSE = NOT_ESTABLISHED（需单独 audit）
```

## A3-115 R0 Final Root-Cause Matrix + Verdict

| 问题 | 最终事实 |
|---|---|
| PROD tree | f453f44e6a70de3eb5fa8f808cf4b6a9d72ea6c1 |
| STAGE tree | a633b4860b818ab48fda5e22f39aa311eb96e9eb |
| PROD compose image contract | HARDCODED_SHARED_LATEST（line 29/62） |
| STAGE compose image contract | PER_SERVICE_IMAGE_ENV |
| PROD runtime env | CORRECT（production/true/false） |
| STAGE service runtime env | INCOMPLETE（缺 .env.production.local；env_file 注入行为细节） |
| release env image refs | 9000=b7-0034-a633b486 / 9100=@sha256:93094f0... |
| release env SHA | ad2efb0c... = frozen evidence ✓ |
| current 9000 | DRIFTED: CID=35f3927c.../Image=99122305.../unhealthy/expected0028 actual0034/StartedAt=08:29:05.893 |
| current 9100 | RECREATED: CID=a5c5c716.../Image=99122305.../healthy/DB0003 compatible/StartedAt=08:29:05.892 |
| postgres | UNCHANGED: CID=2b2390531331.../StartedAt=2026-08-06T15:51:36.375/Restart=0/healthy |
| frontend | RECREATED: CID=1f02e14b.../Image=56a3e47d.../StartedAt=08:29:05.382 |
| target9000 image asset | AVAILABLE (4b4f96fc...) |
| frozen9100 image asset | AVAILABLE (93094f0...) |
| old frontend asset | NOT_AVAILABLE (79f52b6e... 已丢失) |
| mock exposure window | 2026-08-13T07:32:47.736 → 08:29:05.893 |
| DB9000 | 0034（不可逆，M6 已迁移） |
| DB9100 | 0003 |

### 事故机制（ROOT_CAUSE CLOSED WITH EVIDENCE，HIGH_CONFIDENCE）

```text
1. PROD tree（f453f44）docker-compose.yml 是 HARDCODED image: xg-ai-system-backend:latest（无 S10-B env 化）
2. M11 COMPLETE（08:11:44Z）后 08:29:05Z 有人用 PROD tree + PROD env 执行 docker compose up（很可能带 --build，或宝塔 Compose Recreate）
3. Dockerfile.backend.dev 重新 build → 新 image 99122305 tagged :latest（覆盖原 :latest=93094f0；frontend 独立 build → 56a3e47d）
4. 9000+9100 都解析 hardcoded :latest → 都换成 99122305（f453f44 代码 = 0028-era，expected DB 0028）
5. DB 已 0034（M6 迁移不可逆）→ 9000 /ready expected=0028 != actual=0034 → unhealthy → public 503
6. 9100 expected 0003 实际 0003 → 碰巧兼容 healthy
7. postgres image 字面量 postgres:16-alpine 不在 build 范围 → 未受影响
```

Auth 配置本身正确（R0-I production/true/false + tokens SET），事故不是 auth mock 泄漏，是 image identity 丢失导致 9000 运行 0028-era 代码与 0034 DB 不兼容。

### R0 PASS

```text
RELEASE_ENV              = VERIFIED (SHA ad2efb0c...)
TARGET9000_IMAGE_ASSET   = AVAILABLE (4b4f96fc...)
FROZEN9100_IMAGE_ASSET   = AVAILABLE (93094f0...)
DB9000                   = 0034
DB9100                   = 0003
PROD_RUNTIME_ENV         = VERIFIED
ROOT_CAUSE               = CLOSED WITH EVIDENCE
```

```text
R0 = PASS
RECOVERY_REALITY_FREEZE = COMPLETE
R1_ENTRY_GATE = OPEN
R1 = NOT EXECUTED
```

## A3-116 R0 STOP — 不进入 R1

```text
DO NOT RESTORE 9000 / 9100 / frontend
DO NOT EDIT COMPOSE / ENV
R0 = PASS，但本轮只读 freeze 完成，不执行任何 recovery mutation
R1_ENTRY_GATE = OPEN（待用户显式授权 recovery 执行）
```

**恢复资产盘点**：target9000（4b4f96fc）+ frozen9100（93094f0，含 rollback tag）均可用；frontend old image（79f52b6e）已丢失不可恢复（需接受新 build frontend 或重新 build）；backup（bee463c2...）保留。recovery 方向：用 STAGE compose + release-env + COMPOSE_PROJECT_NAME=xg_ai_system 重部署 9000=target（解决 revision mismatch）+ 9100=frozen9100（恢复正确 image），但需先固化 PROD env 的两个 image vars 防 :latest 再被触发，且需考虑 frontend 处理。**全部待 R1 授权。**
