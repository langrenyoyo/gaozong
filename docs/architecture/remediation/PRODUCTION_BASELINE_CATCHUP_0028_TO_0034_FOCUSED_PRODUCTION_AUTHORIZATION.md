# PRODUCTION-BASELINE-CATCHUP-0028-TO-0034 — Focused Production Authorization

> 窗口：`PRODUCTION-BASELINE-CATCHUP-0028-TO-0034 / FOCUSED-PRODUCTION-AUTHORIZATION`
> 窗口性质：**AUTHORIZATION ONLY / READ-ONLY** — 只审批不执行。绝对只读纪律（任务书 §2/§51/§52/§53）。
> 前序 NO-GO：`..._PRODUCTION_AUTHORIZATION.md`（`PRODUCTION_AUTHORIZATION = NO_GO`，BLOCKER-1~3）
> 日期：2026-08-12
> 职责：独立复核 B1/B2/B3 是否可从 CANDIDATE_RESOLVED 升级为 CLOSED，确认既有 Runbook 仍有效，给出 GO / NO-GO。

---

## 0. 窗口唯一职责

此前完整 Production Authorization 裁定 `NO_GO`（BLOCKER-1/2/3）。随后三个 remediation/evidence 窗口分别声称 B1/B2/B3 = CANDIDATE_RESOLVED。本窗口独立复核三者是否可正式 CLOSED，并确认 Runbook 仍有效，最终输出 GO / GO_WITH_NON_BLOCKING_FINDINGS / NO-GO。

本窗口严格遵守：发现问题只 REPORT，不边审边修（§51）；DO NOT COMMIT / DO NOT PUSH（§52）；原则上不再需要 Merchant mutation，若必须补事实只 READ-ONLY 并说明原因（§53）。

```text
允许：read reports / read git history / inspect local release branch/commit / verify hashes
      / read Merchant read-only evidence / run safe local static verification
禁止：NO Merchant mutation / NO 迁移 / NO 备份 / NO 镜像构建/tag / NO env 编辑
      / NO restart/recreate / NO git pull/checkout on Merchant / NO new rehearsal
      / NO code fix / NO migration fix / NO wrapper fix / NO 0035 / NO 9100 升级
      / NO P2 cutover / NO P3a/P3b / NO RB-10 / NO commit / NO push
```

---

## 1. Scope

只复核 B1（RELEASE_ENGINEERING_ARTIFACT_IDENTITY）/ B2（EXTERNAL_AUTOHEAL_WATCHDOG）/ B3（MERCHANT_CURRENT_REALITY）三项 blocker 的 candidate closure，加上 Runbook/Stop-Conditions/Verification Matrix 有效性确认。不重跑 rehearsal，不重跑完整 Production Authorization。

## 2. Prior NO-GO

```text
PRODUCTION_AUTHORIZATION        = NO_GO
PRODUCTION_MIGRATION_AUTHORIZED = NO
PRODUCTION_EXECUTION_ENTRY      = BLOCKED
BLOCKER-1 RELEASE_ENGINEERING_ARTIFACT_IDENTITY = NOT_READY
BLOCKER-2 EXTERNAL_AUTOHEAL_WATCHDOG             = UNKNOWN
BLOCKER-3 MERCHANT_CURRENT_REALITY               = NOT RE-FROZEN
```

## 3. Reopened Items

本窗口不重新打开已冻结治理（ISOLATED_REHEARSAL=APPROVED_WITH_NON_BLOCKING_FINDINGS、S10-B CORE=APPROVED、C1~C5=CLOSED、carry-forward findings）。只复核三个 candidate closure 的证据是否支撑 CLOSED。

## 4. Evidence Sources

```text
PRODUCTION_BASELINE_CATCHUP_0028_TO_0034_PRODUCTION_AUTHORIZATION.md   （prior NO_GO）
PRODUCTION_BASELINE_CATCHUP_0028_TO_0034_RELEASE_PACKAGE_FREEZE.md    （B1 candidate）
PRODUCTION_BASELINE_CATCHUP_0028_TO_0034_RELEASE_MANIFEST.md          （B1 身份/哈希）
PRODUCTION_BASELINE_CATCHUP_0028_TO_0034_MERCHANT_M_AUTH_READ_ONLY.md  （B2/B3 now-gate 证据）
PRODUCTION_BASELINE_CATCHUP_0028_TO_0034_REHEARSAL_APPROVAL.md         （carry-forward）
PRODUCTION_BASELINE_CATCHUP_0028_TO_0034_ISOLATED_REHEARSAL.md         （runtime 证据）
PRODUCTION_SCHEMA_BASELINE_CATCHUP_0028_TO_0034_REALITY_AUDIT.md       （M1/M2 历史 reality）
S10_B_..._APPROVAL / CORRECTION_APPROVAL / IMPLEMENTATION              （B1 机制审批）
本地 git 只读命令（git show / git diff / git ls-tree / sha256sum）      （B1 独立核实）
```

---

# 第一 Hard Gate — BLOCKER-1 Release Artifact Identity

## 5. B1 Candidate State

```text
RELEASE_PACKAGE_FREEZE = READY
APPLICATION_BASE       = 9db3f58
RELEASE_TREE           = a633b4860b818ab48fda5e22f39aa311eb96e9eb
RELEASE_BRANCH         = release/b7-0034-s10b-freeze（LOCAL ONLY / NOT PUSHED）
ALEMBIC HEAD           = 0034
0035 ALEMBIC           = ABSENT
RF-T01~RF-T18          = ALL PASS（候选）
```

## 6. B1 Release Commit（FA-B1-01）

独立核实：

```text
$ git rev-parse release/b7-0034-s10b-freeze
a633b4860b818ab48fda5e22f39aa311eb96e9eb
$ git show -s --format='%H%n parent=%P%n tree=%T%n subject=%s' a633b486
a633b4860b818ab48fda5e22f39aa311eb96e9eb
 parent=9db3f5854095e483a55724e66d452792b354ff53
 tree=6d23c7977da70caad545f675e2eb1e42087e28c9
 subject=release: 冻结0034生产追平发布制品
```

`FA-B1-01 release commit exists = PASS`。本地 ref 持久指向该 commit，cleanup worktree 后仍可 `git show a633b48` 访问。

## 7. B1 Base/Parent（FA-B1-02）

```text
parent(a633b486) = 9db3f5854095e483a55724e66d452792b354ff53 = 9db3f58（APPLICATION_BASE）
git merge-base 9db3f58 a633b486 = 9db3f58（直接派生于 9db3f58）
```

`FA-B1-02 parent/base=9db3f58 = PASS`。release commit 直接基于 APPLICATION_BASE，未引入 36fe68a（含 0035/P2）路径。

## 8. B1 Diff Scope（FA-B1-03 / FA-B1-04）

独立重跑 `git diff --name-status 9db3f58..a633b486`：

```text
M  .env.production.example
M  docker-compose.yml
A  docs/architecture/remediation/S10_B_9000_9100_IMAGE_IDENTITY_ISOLATION_APPROVAL.md
A  docs/architecture/remediation/S10_B_9000_9100_IMAGE_IDENTITY_ISOLATION_CORRECTION_APPROVAL.md
A  docs/architecture/remediation/S10_B_9000_9100_IMAGE_IDENTITY_ISOLATION_IMPLEMENTATION.md
M  docs/config/ENV_VARIABLE_REFERENCE.md
A  scripts/release_9000_s10b.py
A  tests/test_s10_b_image_identity_isolation.py
```

```text
UNKNOWN            = 0
app/**             ZERO DIFF
apps/**            ZERO DIFF
migrations/**      ZERO DIFF
frontend/**        ZERO DIFF
```

8 文件全部属于已批准 S10-B release-engineering 范围（3 M + 5 A），与 Freeze 报告 §12 / Manifest §2 完全一致。无未批准改动混入。

`FA-B1-03 approved diff only = PASS` / `FA-B1-04 app/migrations zero diff = PASS`。

## 9. B1 Alembic Head（FA-B1-05）

```text
release tree migrations/postgres/auto_wechat/versions/ 最高 = 0034_preview_executions.py
0034 down_revision = 0033（单线，无分叉）
git ls-tree ... versions/ | grep -E '003[5-9]|00[4-9][0-9]' → NO revision >= 0035 in alembic dir
```

`FA-B1-05 alembic head=0034 = PASS`。

## 10. B1 0035 Exclusion（FA-B1-06）

```text
0035_wechat_task_claim_lease.py（Alembic）= ABSENT（release tree 与文件系统均不存在）
SQLite 轨道 migrations/versions/0035_douyin_webhook_event_merchant_scope.sql = 非 PG Alembic revision
```

按任务书 §7"不得把 legacy SQL 0035.sql 与 Alembic revision 混淆"：`migrations/versions/` 是旧 SQLite 轨道，在 9db3f58 已存在，release tree 与 9db3f58 ZERO DIFF，**不影响** `AUTO_WECHAT POSTGRES ALEMBIC HEAD = 0034` 判断。

`FA-B1-06 no 0035 = PASS`。

## 11. B1 S10-B Mechanism Integrity（§8）

不只看文件存在，确认关键安全逻辑仍与 approved candidate 一致（SHA256 + 逻辑 grep 双重核验）：

```text
scripts/release_9000_s10b.py  逻辑核验（git show a633b486:scripts/release_9000_s10b.py | grep）：
  IMAGE_VARS = ("AUTO_WECHAT_API_IMAGE", "XG_DOUYIN_AI_CS_IMAGE")           ✓ per-service image env var
  compose_env()              → 移除宿主 IMAGE 变量（host precedence 克服，C2）        ✓
  fail-closed preflight      → P4 9000≠9100 / P-EXPECTED 不匹配即失败              ✓
  canonical up -d --no-deps --no-build auto-wechat-api                       ✓ 9000-only / 9100 保护
  --expected-9000 / --expected-9100                                           ✓ identity contract
  --dry-run / --apply                                                         ✓
  PREFLIGHT FAILED → sys.exit（fail-closed，不执行 up）                          ✓

docker-compose.yml diff：
  auto-wechat-api image: ${AUTO_WECHAT_API_IMAGE:-xg-ai-system-backend:latest}  ✓ env 化
  xg-douyin-ai-cs   image: ${XG_DOUYIN_AI_CS_IMAGE:-xg-ai-system-backend:latest} ✓ env 化
  顶部注释说明 RE-B per-service identity + RG-7 回落 + RG-8 不得共享 mutable :latest  ✓
```

机制与 S10-B APPROVAL + CORRECTION_APPROVAL（C1~C5 CLOSED）一致。

## 12. B1 Reproducibility（FA-B1-07）

独立重算 release tree blob SHA256 与 Manifest §3 比对：

```text
MATCH  scripts/release_9000_s10b.py            38a65f27...399c
MATCH  docker-compose.yml                      bde9d833...425d
MATCH  .env.production.example                 9981c2cd...3e69
MATCH  tests/test_s10_b_image_identity_isolation.py  f7c278b6...140d
```

（4 个 runtime/test/template 文件独立复算全 MATCH；其余 4 个 audit/doc 文件 Freeze 报告 RF-T15/RF-T16 已全 8 文件核验 PASS。）

`FA-B1-07 manifest/hash reproducible = PASS`。

## 13. B1 Offline Delivery

```text
本地 git commit a633b48 可 git archive / git bundle 离线转移
Manifest §3.1 SHA256SUMS 可在 Merchant 侧 sha256sum -c 本地校验
不要求 Merchant maintenance 期间 git pull / fetch / 下载依赖
```

生产历史 GitHub 网络不稳定（§43/§47）：release artifact 已 offline-capable，满足离线交付契约。

## 14. B1 Local-only Ref 是否阻塞

`release/b7-0034-s10b-freeze` 尚未 push。按任务书 §11：commit identity exists ✓ / manifest exists ✓ / hashes exist ✓ / offline package/export method 明确 ✓ → local-only ref 本身**不**自动是 blocker。分支 ref 已持久化，清理 worktree 后 commit 仍可经 `git show a633b48` / `git rev-parse release/b7-0034-s10b-freeze` 访问。artifact 不依赖任何临时 worktree 存在。

## 15. B1 Verdict

全部成立：

```text
BLOCKER-1 = CLOSED
RELEASE_ENGINEERING_ARTIFACT_IDENTITY = FROZEN_AND_APPROVED
```

---

# 第二 Hard Gate — BLOCKER-2 External Autoheal / Watchdog

## 16. B2 Candidate State

任务书 §3 候选事实声称：

```text
DOCKER_AUTOHEAL=NONE_DETECTED / WATCHTOWER=NONE_DETECTED / SYSTEMD_AUTOHEAL=NONE_DETECTED
SYSTEMD_TIMER_AUTOHEAL=NONE_DETECTED / CRON_AUTOHEAL=NONE_DETECTED
PROJECT_SPECIFIC_LIFECYCLE_AUTOMATION=NONE_DETECTED
BT_COMPOSE_BACKUP_RESTORE=MANUAL_ADMIN_CAPABILITY / BT_AUTOMATIC_TRIGGER=NONE_DETECTED
EXTERNAL_HEALTH_RESTART=NONE_DETECTED
```

## 17. 候选事实与 now-gate 证据矛盾

独立复核 M-AUTH 只读取证报告（`..._MERCHANT_M_AUTH_READ_ONLY.md`，2026-08-12 20:47，B2/B3 指定 now-gate 窗口）：

```text
MERCHANT_HOST_ACCESS = MISSING
  本机无 SSH 私钥 / config / agent / 凭据 / 部署密钥；/www/wwwroot/XG_AI_System 不在本机
M-AUTH-18 docker supervision      = BLOCKED / UNKNOWN
M-AUTH-19 systemd/supervisor      = BLOCKED / UNKNOWN
M-AUTH-20 cron/scheduled          = BLOCKED / UNKNOWN
M-AUTH-21 宝塔/custom watchdog    = BLOCKED / UNKNOWN
```

```text
EXTERNAL_HEALTH_RESTART = UNKNOWN_OR_UNCONTROLLABLE（截至 M-AUTH 窗口）
BLOCKER-2 = OPEN（M-AUTH §31）
```

任务书 §3 候选事实声称 B2"四层全 NONE_DETECTED"，但**指定 now-gate 证据窗口（M-AUTH）明确**：M-AUTH-18/19/20/21 全部 BLOCKED（宿主访问缺失），Docker/systemd/cron/宝塔四层**均未取证**。候选事实在 M-AUTH 报告中**找不到任何支撑**。

## 18. Docker Layer

M-AUTH-18 = BLOCKED。生产宿主侧 `docker ps -a` + label 审计未执行。仅 compose 层（9db3f58 树 docker-compose.yml，`CONTAINER_CONFIG_VERIFIED`）确认无 autoheal/watchtower 容器定义——但按任务书 §14/§25，compose 层 NONE_DETECTED **不等于**生产层 NONE_DETECTED，需宿主 docker 侧独立取证。`FA-B2-01 no Docker autoheal = UNSUPPORTED（生产宿主侧 UNKNOWN）`。

## 19. systemd Layer

M-AUTH-19 = BLOCKED。`systemctl list-unit-files/list-units/list-timers` 未执行。`[watchdogd]` 若为 kernel watchdog 线程不作为项目 lifecycle watchdog——但本窗口无证据判断（任务书 §15：证据不足标记限制，不得自行猜）。`FA-B2-02 no systemd watchdog = UNSUPPORTED` / `FA-B2-03 no systemd timer = UNSUPPORTED`。

## 20. Cron Layer

M-AUTH-20 = BLOCKED。root crontab / /etc/crontab / /etc/cron.d 均未执行。任务书 §16 要求确认无针对 XG_AI_System / auto-wechat-api / docker restart / docker start 的自动 lifecycle action——本窗口无法确认。`FA-B2-04 no cron lifecycle automation = UNSUPPORTED`。

## 21. BT Panel Hard Gate

M-AUTH-21 = BLOCKED。`/www/server/panel/data` 只读 grep 未执行。BT `docker_compose_backup.py` / `docker_compose_restore.py` 的真实行为（restore 具有 `docker-compose stop` + `docker-compose up -d` 能力）无法在宿主侧复核。`FA-B2-05 BT restore manual action = UNSUPPORTED` / `FA-B2-06 no BT scheduled trigger = UNSUPPORTED`。

## 22. composeMod Caller Review / BT Scheduled Trigger / Project-specific Automation

M-AUTH-21 = BLOCKED。`/www/server/panel/data` 对 docker_compose_backup/restore/compose_backup/compose_restore 无 schedule/task automation 证据；针对 XG_AI_System/xg-auto-wechat-api/auto-wechat-api 的 lifecycle automation 搜索均未执行。`dir_history.json` 仅作历史路径数据，不算生命周期执行器（任务书 §20）。`FA-B2-07 no XG project lifecycle automation = UNSUPPORTED`。

## 23. B2 Operator Caution（保留）

即使 B2 关闭，仍保留（任务书 §21/§38）：

```text
OPERATOR_CAUTION:
  maintenance M1~M11 期间禁止管理员主动触发 BT Compose backup/restore/start/restart/recreate
  for XG_AI_System，除非 approved runbook 显式要求。
  特别：Compose Restore（可能 stop + up -d）。
```

人工控制边界，非 unresolved blocker。

## 24. B2 Verdict

候选事实"B2 全 NONE_DETECTED"在指定 now-gate 证据窗口（M-AUTH）中无任何支撑：四层（Docker/systemd/cron/宝塔）全部 BLOCKED。按任务书 §22/§25：仍存在无法解释的自动机制（UNKNOWN）→ `BLOCKER-2 = OPEN`，NO_GO。

```text
BLOCKER-2 = OPEN
EXTERNAL_AUTOHEAL_WATCHDOG = UNKNOWN_OR_UNCONTROLLABLE（now-gate 未取证）
FA-B2-01~07 = UNSUPPORTED（候选事实无 now-gate 证据）
```

---

# 第三 Hard Gate — BLOCKER-3 Merchant Current Reality

## 25. B3 Candidate State

任务书 §3 候选事实声称：

```text
PRODUCTION_GIT_HEAD=f453f44 / 9000 APP HEAD=0028 / 9000 DB CURRENT=0028 / 9000 /ready=200（expected=actual=0028）
JSONB drift=confirmed_fields_json jsonb / inferred_fields_json jsonb
future0030~0034 target objects=absent
customer_profiles=1 / compute_transactions=1725 / daily_report_jobs=0
9100 APP HEAD=0003 / 9100 DB CURRENT=0003 / 9100 /ready=200
9000 runtime image=sha256:93094f0... / 9100 runtime image=sha256:93094f0...
CURRENT_RUNTIME_SHARED_IMAGE=YES / MATERIAL_PRODUCTION_DRIFT=NONE_DETECTED
```

## 26. 候选事实证据来源核对

独立核对每个候选事实是否有 now-gate（M-AUTH，20:47）证据支撑：

| 候选事实 | M-AUTH now-gate | Reality Audit M2（更早） | 结论 |
|---|---|---|---|
| 9000 DB=0028 | ✅ 远程 /api/ready actual=[0028] | ✅ M2 SELECT version_num | **VERIFIED** |
| 9000 /ready=200 | ✅ 远程 /api/ready+/api/health | — | **VERIFIED** |
| 9000 DB backend=postgresql / db=auto_wechat | ✅ 远程 /api/ready | ✅ M2 | **VERIFIED** |
| PRODUCTION_GIT_HEAD=f453f44 | ❌ M-AUTH-01 BLOCKED/UNKNOWN | ⚠ GIT_HISTORY_VERIFIED（推断，非宿主 `git rev-parse`） | **UNSUPPORTED at now-gate** |
| 9000 APP HEAD=0028 | ❌ M-AUTH-09 BLOCKED（容器内 alembic） | ⚠ M1 USER_CONFIRMED_TOPOLOGY（非容器 alembic current） | **UNSUPPORTED at now-gate** |
| JSONB drift 两列=jsonb | ❌ M-AUTH-13 BLOCKED | ✅ M2 information_schema（1/1698/0 时期） | **M2 历史，非 now-gate** |
| future0030~0034 objects absent | ❌ M-AUTH-14 BLOCKED | ✅ M2 to_regclass（1/1698/0 时期） | **M2 历史，非 now-gate** |
| customer_profiles=1 | ❌ M-AUTH-15 BLOCKED | ✅ M2 count=1 | **M2 历史** |
| compute_transactions=1725 | ❌ M-AUTH-15 BLOCKED | ❌ M2 = **1698**（不一致） | **UNSUPPORTED（任何文档均无 1725）** |
| daily_report_jobs=0 | ❌ M-AUTH-15 BLOCKED | ✅ M2 count=0 | **M2 历史** |
| 9100 APP HEAD=0003 | ❌ M-AUTH-16 BLOCKED | ❌ M2 只查 auto_wechat PG，未查 9100 | **UNSUPPORTED** |
| 9100 DB CURRENT=0003 | ❌ M-AUTH-16 BLOCKED | ❌ M2 未覆盖 | **UNSUPPORTED** |
| 9100 /ready=200 | ❌ M-AUTH-17 BLOCKED | ❌ 无 | **UNSUPPORTED** |
| 9000 runtime image=93094f0 | ❌ M-AUTH-05/07 BLOCKED | ❌ 93094f0 来自 Design M3，非宿主 docker inspect | **UNSUPPORTED at now-gate** |
| 9100 runtime image=93094f0 | ❌ M-AUTH-06 BLOCKED | ❌ 同上 | **UNSUPPORTED at now-gate** |
| CURRENT_RUNTIME_SHARED_IMAGE=YES | ❌ M-AUTH-07 BLOCKED | ❌ 无 | **UNSUPPORTED at now-gate** |
| MATERIAL_PRODUCTION_DRIFT=NONE_DETECTED | ❌ 10/12 UNKNOWN | ⚠ M2 部分 | **UNSUPPORTED** |

## 27. Git Reality（FA-B3-01）

M-AUTH-01 = BLOCKED。`git rev-parse HEAD` 未在 `/www/wwwroot/XG_AI_System` 执行。Reality Audit 的 f453f44 是 `GIT_HISTORY_VERIFIED`（从 master 父链推断），**非**宿主 `git rev-parse HEAD` 实测。任务书 §24 要求 `HEAD=f453f44e6a70de3eb5fa8f808cf4b6a9d72ea6c1`——now-gate 未核实。`FA-B3-01 git=f453f44 = UNSUPPORTED at now-gate`。

## 28. Worktree Reality（FA-B3-02）

M-AUTH-02 = BLOCKED。`git status --short` 未执行。保护文件（`.env.production.local.bak.20260804_172603` / `milvus_export_full.jsonl` / `milvus_export_no_vec.jsonl`）存在性与 mtime 未复核（M-AUTH §7）。`FA-B3-02 tracked worktree clean = UNSUPPORTED`。

## 29. Runtime Image Reality（FA-B3-03）

M-AUTH-05/06/07/08 = BLOCKED。9000/9100 runtime image ID、共享关系、old image 可引用性均未在宿主 docker inspect 复核。候选 `93094f0...` 来自 Design M3，非 now-gate 证据。rollback 保障（M-AUTH-08）无法在宿主侧确认。`FA-B3-03 runtime image unchanged = UNSUPPORTED at now-gate`。

## 30. 9000 Schema Reality（FA-B3-04）

```text
远程 /api/ready：expected=[0028] / actual=[0028] / PASS / backend=postgresql / db=auto_wechat（M-AUTH §15）✅
宿主容器内 alembic current/heads：M-AUTH-09 = BLOCKED（UNKNOWN）
宿主 psql SELECT version_num：M-AUTH-12 = BLOCKED（仅远程交叉，非宿主直查）
PostgreSQL version=16.14 / identity：M-AUTH-11 = BLOCKED
```

远程证据与历史一致（正信号），但不等于完整 reality re-freeze（M-AUTH §15 明示）。`FA-B3-04 9000 app/db=0028 = PARTIAL（远程 DB=0028 VERIFIED；app head UNKNOWN）`。

## 31. JSONB Drift（FA-B3-05）

M-AUTH-13 = BLOCKED。宿主 `information_schema` 未复核。Reality Audit M2 曾确认两列 jsonb（PRODUCTION_READ_ONLY_VERIFIED，1/1698/0 时期），但 M2 是更早审计阶段，**非 now-gate**。0029 迁移幂等前提未在 now-gate 重新冻结。`FA-B3-05 JSONB drift only = M2 历史支持，now-gate UNSUPPORTED`。

## 32. Future Object Audit（FA-B3-06）

M-AUTH-14 / M-AUTH-14B = BLOCKED。0030~0034 对象（daily_report_generations / ai_edit_material_analysis_executions / ai_preview_executions / compute_transactions.idempotency_key / uk_compute_transactions_merchant_idempotency 等）是否仍 absent，未在 now-gate 复核。Reality Audit M2 曾确认全 NOT EXISTS（1/1698/0 时期），但非 now-gate。

任务书 §29 提醒：不得把 `uk_return_visit_runs_idempotency_key`（0011 既有）误认成 future 0030 污染；关注的是 `uk_compute_transactions_merchant_idempotency` 与目标 migrations 相关 constraints——这些在 now-gate 未复核。`FA-B3-06 future objects absent = M2 历史支持，now-gate UNSUPPORTED`。

## 33. Data Scale

候选 `cp=1 / ct=1725 / drj=0`。M-AUTH-15 = BLOCKED（UNKNOWN）。Reality Audit M2 = `cp=1 / ct=1698 / drj=0`。**1725 在任何证据文档中均不存在**，与 M2 的 1698 不一致，系无支撑数字。1698→1725 即便为正常业务增长也不构成 drift（任务书 §30：只有 schema/precondition 变化才是 Hard Gate），但 now-gate 无法确认当前行数。`FA-B3 data scale = UNSUPPORTED at now-gate`。

## 34. 9100 Reality（FA-B3-07）

M-AUTH-16/17 = BLOCKED。9100 APP HEAD / DB CURRENT / /ready 全 UNKNOWN。本机无 9100 已知公网端点，未推测（M-AUTH §22）。Reality Audit M2 只审 auto_wechat PG，**未覆盖 9100**。候选 9100=0003 / ready=200 无任何证据支撑。`FA-B3-07 9100 app/db=0003 = UNSUPPORTED`。

## 35. Production Reality Matrix

任务书 §32 Material Reality Drift Criteria（只关注 git revision / 9000 revision / physical schema / future objects / runtime image / 9100 revision / new writer / new lifecycle automation）：

```text
PRODUCTION_REALITY_DRIFT = NOT_CONFIRMED_AND_NOT_EXCLUDED（承 M-AUTH §30）
```

- 远程证据（9000 DB=0028 / ready=200 / backend=postgresql / db=auto_wechat）与历史一致，**未发现 drift 迹象**（无反向证据）。
- 但 git HEAD / image ID / JSONB / future objects / row counts / 9100 / topology / watchdog 全部 UNKNOWN——**不能据此宣称"与 f453f44 兼容"或"NO MATERIAL DRIFT"**（任务书 §32 / M-AUTH §30：UNKNOWN 不等于 VERIFIED）。
- 候选事实 `MATERIAL_PRODUCTION_DRIFT=NONE_DETECTED` **不成立**：NONE_DETECTED 需四类证据全无（A 类），now-gate 仅 2/12 项远程核实。

## 36. B3 Verdict

任务书 §33：全部与 rehearsal 起点兼容 → RE_FROZEN。本窗口 now-gate（M-AUTH）仅能远程确认 9000 DB=0028 + ready=200 两项；git/app head/JSONB/future objects/9100/topology/runtime image/row counts 全 UNKNOWN；候选 `compute_transactions=1725` 与 M2 的 1698 不一致且无文档支撑。

候选事实对 B3 的"详细已核实"系**历史数据（Reality Audit M2）搬运 + 部分无支撑数字**，非 now-gate 重新冻结。M-AUTH（指定 now-gate 窗口）明确 `MERCHANT_CURRENT_REALITY = NOT RE-FROZEN` / `BLOCKER-3 = OPEN`。

```text
BLOCKER-3 = OPEN
MERCHANT_CURRENT_REALITY = NOT RE-FROZEN（now-gate 未完成）
FA-B3-01~08 = 多数 UNSUPPORTED at now-gate（仅 FA-B3-04/08 远程部分 VERIFIED）
```

---

# Carry-forward / Write Isolation / Strategy / Runbook

## 37. Carry-forward Findings 不重新打开

Independent Rehearsal Approval 的 non-blocking findings 继续保持，本窗口确认无一因最新 Merchant evidence 升级为 blocking（因 M-AUTH 未产生与 carry-forward 矛盾的新证据，只产生 UNKNOWN）：

```text
U1 old fresh-bootstrap defect（CF-1, OUT_OF_PRODUCTION_PATH）
U2 JSONB predeclaration（CF-2, SUPPORTING）
U3 transactional DDL（CF-3, ACCEPTED_WITH_SCOPE_LIMIT）
BR-22 single failure mode（CF-8, scope limit）
BR-15 partial runtime scope（CF-9, MAINTENANCE_FALLBACK_ONLY）
timing caution（CF-7, OPERATOR_CAUTION）
...
```

## 38. Write Isolation 再确认

PRODUCTION_AUTHORIZATION §18~§20 已静态判：代码层（9db3f58 树，CODE_VERIFIED）所有 9000 PG writer 均在 9000 进程内（webhook ingress / compute API / 9100→9000 HTTP 回写 / LAS / 素材分析 / 微信任务 / daily report / outbox）。compose 无独立 worker/scheduler 容器。

但 M-AUTH-03（topology）/13~17/18~21 = BLOCKED：**生产宿主侧无法排除**独立 cron/systemd/宝塔定时 writer / sidecar / 外部脚本 / 直连 PG writer / 外部 lifecycle 守护。任务书 §35：若新 evidence 显示额外 writer → NO_GO。当前 `WRITE_ISOLATION_TOPOLOGY = NOT_VERIFIED（生产宿主侧）`，CF-4 生产侧 EXECUTION_PREFLIGHT 保持开放。

```text
WRITE_ISOLATION_MODEL = CODE_LEVEL_VALID / HOST_LEVEL_NOT_VERIFIED
  前提 Execution 按 maintenance Runbook 停/隔离 9000，且 M-AUTH-03/13~17/18~21 须先取证确认无独立 writer。
```

## 39. Maintenance Strategy

```text
SCHEMA_FIRST_WITH_MAINTENANCE_WINDOW（保持，不重开 zero-downtime）
```

## 40. M0~M11 Runbook（FA-RUNBOOK-01）

承 PRODUCTION_AUTHORIZATION §41，未被新证据推翻（M-AUTH 未产生矛盾证据）：

```text
M0  PRE-MAINTENANCE      reality reconfirm / protected files / storage / rollback image identity
M1  ENTER MAINTENANCE    maintenance begin
M2  VERIFY WRITE ISOLATION 9000 stopped + webhook paused + 9100 容错 + 无独立 cron writer
M3  PRESERVE ROLLBACK IMAGE STEP 0~2
M4  CREATE/VERIFY DB BACKUP backup + verify
M5  VERIFY TARGET ARTIFACTS 9db3f58 source / image built / head=0034
M6  MIGRATE 0028→0034    alembic upgrade 0034
M7  VERIFY DB 0034       version_num=0034 + objects
M8  DEPLOY TARGET 9000   wrapper --apply（9000-only）
M9  VERIFY /ready 200    expected=actual=0034
M10 VERIFY 9100 UNCHANGED container/image/DB=0003
M11 EXIT MAINTENANCE     仅 target ready 后
```

## 41. Runbook Amendment — BT Manual Control

```text
OPERATOR_CAUTION（Execution 边界，入 runbook）:
  During M1~M11: DO NOT manually trigger BT Compose backup/restore/start/restart/recreate
  for XG_AI_System unless explicitly required by approved runbook.
  特别 Compose Restore（可能 stop + up -d）。
```

## 42. P-S01~P-S16 Stop Conditions（FA-RUNBOOK-02）

原 P-S01~P-S16 仍有效（未被新证据推翻）：

```text
P-S01 current reality differs from authorization freeze
P-S02 rollback image preservation fails
P-S03 backup fails
P-S04 target source identity != 9db3f58
P-S05 migration head != 0034
P-S06 resolved 9000 image mismatch
P-S07 resolved 9100 image mismatch
P-S08 write isolation cannot be proven
P-S09 migration nonzero exit
P-S10 DB != 0034
P-S11 unexpected 0035
P-S12 schema/data verification fails
P-S13 target /ready != 200
P-S14 9100 changes
P-S15 rollback fails
P-S16 external watchdog invalidates maintenance
```

## 43. P-S04 升级使用 RELEASE_TREE（§40）

```text
Execution 不只验证 9db3f58，还须验证：
  APPLICATION_BASE = 9db3f58
  RELEASE_TREE    = a633b4860b818ab48fda5e22f39aa311eb96e9eb
future target artifact 与 Manifest 不匹配 → STOP
```

## 44. Execution-Time Dynamic Gates（§41）

Focused Authorization 不假装已执行，仍只作未来 fail-closed gate：

```text
rollback image tag/ref actual preservation（P-S02）
production DB backup actual creation（P-S03）
target image actual build/load（PV-01）
target image ID/digest verification
maintenance actual entry（M1）
write isolation actual verification（M2/P-S08）
migration actual execution（M6）
```

## 45. PV-01~PV-17 Verification Matrix（FA-RUNBOOK-03）

承 PRODUCTION_AUTHORIZATION §45，仍有效：PV-01 target identity / PV-02 DB0034 / PV-03 app head0034 / PV-04 /ready200 / PV-05~08 schema objects / PV-09 row preservation / PV-10 JSONB / PV-11 logs / PV-12 P1 artifacts / PV-13~15 9100 unchanged / PV-16 no 0035 / PV-17 no drift。

## 46. Network / Offline Boundary

生产历史 GitHub 网络不稳定。release artifact（a633b48）已 offline-capable（git archive/bundle + SHA256SUMS），Execution 可 pre-stage，**不依赖 maintenance 期 git pull**（§43/§47）。

## 47. 9100 Hard Freeze

```text
9100 CODE UPGRADE = NO / 9100 DB MIGRATION = NO / 9100 RECREATE = NO / 9100 DB TARGET = 0003
```

## 48. 0035 Boundary

```text
0035 = NOT INCLUDED / NOT APPLIED / P2 FUTURE
```

---

# Evidence Matrix / Findings / Verdict

## 49. Evidence Matrix

```text
FA-B1-01 release commit exists                 = PASS（git show a633b486 独立核实）
FA-B1-02 parent/base=9db3f58                    = PASS（parent=9db3f585...ff53）
FA-B1-03 approved diff only                     = PASS（8 文件全 S10-B 范围）
FA-B1-04 app/migrations zero diff              = PASS（app/apps/migrations/frontend ZERO）
FA-B1-05 alembic head=0034                      = PASS（0034 down_revision=0033）
FA-B1-06 no 0035                                = PASS（无 >=0035 Alembic；legacy SQL 0035 非 Alembic）
FA-B1-07 manifest/hash reproducible            = PASS（4 文件独立复算 SHA256 全 MATCH）

FA-B2-01 no Docker autoheal                     = UNSUPPORTED（M-AUTH-18 BLOCKED，候选无 now-gate 证据）
FA-B2-02 no systemd watchdog                    = UNSUPPORTED（M-AUTH-19 BLOCKED）
FA-B2-03 no systemd timer                       = UNSUPPORTED（M-AUTH-19 BLOCKED）
FA-B2-04 no cron lifecycle automation           = UNSUPPORTED（M-AUTH-20 BLOCKED）
FA-B2-05 BT restore manual action               = UNSUPPORTED（M-AUTH-21 BLOCKED）
FA-B2-06 no BT scheduled trigger                = UNSUPPORTED（M-AUTH-21 BLOCKED）
FA-B2-07 no XG project lifecycle automation     = UNSUPPORTED（M-AUTH-21 BLOCKED）

FA-B3-01 git=f453f44                            = UNSUPPORTED at now-gate（M-AUTH-01 BLOCKED）
FA-B3-02 tracked worktree clean                 = UNSUPPORTED（M-AUTH-02 BLOCKED）
FA-B3-03 runtime image unchanged                = UNSUPPORTED at now-gate（M-AUTH-05~08 BLOCKED）
FA-B3-04 9000 app/db=0028                       = PARTIAL（远程 DB=0028 VERIFIED；app head UNKNOWN）
FA-B3-05 JSONB drift only                       = M2 历史支持 / now-gate UNSUPPORTED（M-AUTH-13 BLOCKED）
FA-B3-06 future objects absent                  = M2 历史支持 / now-gate UNSUPPORTED（M-AUTH-14 BLOCKED）
FA-B3-07 9100 app/db=0003                       = UNSUPPORTED（M-AUTH-16/17 BLOCKED）
FA-B3-08 /ready healthy                         = PARTIAL（9000 远程 VERIFIED；9100 UNKNOWN）

FA-RUNBOOK-01 M0~M11 valid                      = PASS（未被新证据推翻）
FA-RUNBOOK-02 P-S01~16 valid                    = PASS
FA-RUNBOOK-03 PV-01~17 valid                    = PASS
```

## 50. Blocking Findings

```text
FA-BLOCK-2（决定性）：BLOCKER-2 EXTERNAL_AUTOHEAL_WATCHDOG 无法关闭
  任务书 §3 候选事实声称 B2 四层（Docker/systemd/cron/宝塔）全 NONE_DETECTED，
  但指定 now-gate 证据窗口 M-AUTH（..._MERCHANT_M_AUTH_READ_ONLY.md，2026-08-12 20:47）
  明确 MERCHANT_HOST_ACCESS=MISSING，M-AUTH-18/19/20/21 全部 BLOCKED →
  EXTERNAL_HEALTH_RESTART=UNKNOWN_OR_UNCONTROLLABLE / BLOCKER-2=OPEN。
  候选事实在 M-AUTH 报告中无任何支撑。compose 层 NONE_DETECTED 不满足 §25 A 类（需四层全无）。
  MINIMUM NEXT ACTION : 运维/客户在 Merchant 主机执行 M-AUTH-18~21 只读命令包（附录 A 已硬化）
                        并回填结果；或提供受控 SSH 只读通道续跑。若发现不可控 lifecycle 守护 → 独立 remediation。

FA-BLOCK-3（决定性）：BLOCKER-3 MERCHANT_CURRENT_REALITY 未重新冻结
  任务书 §3 候选事实声称 B3 详细已核实（git=f453f44 / JSONB jsonb / future objects absent /
  ct=1725 / 9100=0003 / image 93094f0 / shared=YES / no drift），但：
  - 指定 now-gate 窗口 M-AUTH 仅远程核实 9000 DB=0028 + ready=200 两项，其余 10 项 UNKNOWN
    （M-AUTH-01/02/05~21 BLOCKED），明确 MERCHANT_CURRENT_REALITY=NOT RE-FROZEN / BLOCKER-3=OPEN。
  - 候选事实部分来自更早 Reality Audit M2（1/1698/0 时期，非 now-gate），部分无任何文档支撑：
    compute_transactions=1725 与 M2 的 1698 不一致且无文档来源；
    9100=0003 / ready=200 / image 93094f0 / shared=YES 在 M2 与 M-AUTH 均无 now-gate 证据。
  - 候选事实 MATERIAL_PRODUCTION_DRIFT=NONE_DETECTED 不成立：UNKNOWN ≠ VERIFIED（任务书 §32）。
  MINIMUM NEXT ACTION : 运维/客户在 Merchant 主机执行 M-AUTH-01~21 只读命令包并回填，
                        完成 now-gate reality 重新冻结；若 drift → 回 Reality Audit。
```

## 51. Non-Blocking Findings

```text
FA-NB-1  B1=CLOSED：release artifact identity 已独立本地全项核实（FA-B1-01~07 全 PASS），
         RELEASE_ENGINEERING_ARTIFACT_IDENTITY=FROZEN_AND_APPROVED。本 blocker 与 Merchant 无关。
FA-NB-2  远程 /api/ready 证据（9000 DB=0028 / ready=200 / backend=postgresql / db=auto_wechat /
         critical tables PASS）与历史期望一致，是正信号；但不抵消 B2/B3 now-gate OPEN。
FA-NB-3  Reality Audit M2（PRODUCTION_READ_ONLY_VERIFIED）曾提供 schema/rows 历史证据，
         可作 Execution 时 M0 reconfirm 的比对基线，但不作 now-gate closure 依据。
FA-NB-4  未发现任何生产 drift 证据或异常；所有"未知"均为宿主访问缺失所致，非观察到的问题。
FA-NB-5  未输出任何 .env 内容/密码/密钥（遵守 secret 纪律）。
FA-NB-6  本窗口未操作 Merchant / 未迁移 / 未构建 / 未备份 / 未改 env / 未 restart / 未 commit / 未 push。
```

## 52. B1/B2/B3 Final Matrix

```text
BLOCKER-1 RELEASE_ENGINEERING_ARTIFACT_IDENTITY = CLOSED        （FA-B1-01~07 全 PASS）
BLOCKER-2 EXTERNAL_AUTOHEAL_WATCHDOG             = OPEN          （FA-B2-01~07 UNSUPPORTED）
BLOCKER-3 MERCHANT_CURRENT_REALITY               = OPEN          （FA-B3-01~08 多数 UNSUPPORTED）
```

## 53. Focused Verdict

任务书 §50：任何一个 blocker 无法关闭 → `PRODUCTION_AUTHORIZATION_NO_GO`；§51 不得使用 conditional GO 掩盖 now-gate unknown。

B1 已独立 CLOSED；但 **B2 与 B3 无法关闭**——候选事实对 B2/B3 的"CANDIDATE_RESOLVED"主张在指定 now-gate 证据窗口（M-AUTH）中无支撑，与 M-AUTH 明确的 `INCOMPLETE` / `OPEN` 裁定直接矛盾。B2 四层 watchdog 全部 UNKNOWN；B3 仅 2/12 项远程核实，其余 UNKNOWN，且候选 `ct=1725` / `9100=0003` / `image 93094f0` 等无 now-gate 证据。

```text
PRODUCTION_AUTHORIZATION = NO_GO
```

## 54. Production Migration Authorization / Execution Entry

```text
PRODUCTION_MIGRATION_AUTHORIZED = NO
PRODUCTION_EXECUTION_ENTRY      = BLOCKED
PRODUCTION_MIGRATION_EXECUTED   = NO
```

## 55. Next Stage

```text
当前 : Focused Production Authorization = NO_GO（B2/B3 OPEN）
  ↓
关闭 B2/B3 的唯一路径（承 M-AUTH §39 / PRODUCTION_AUTHORIZATION §56）：
  路径 A（推荐）：运维/客户在 Merchant 主机 /www/wwwroot/XG_AI_System 执行
                  M-AUTH 只读命令包（M-AUTH 报告附录 A，已独立审查 SAFE_AFTER_MINOR_HARDENING）
                  并回填结果 → 由 Focused Authorization 按 §16~§36 判定 B2/B3。
  路径 B：用户为本窗口提供受控 SSH 只读通道（仅任务书 §2 允许命令），续跑 M-AUTH-01~21。
  ↓
（B2/B3 全 CLOSED 后）重新 Focused Production Authorization → Production Execution
  ↓
Production Execution（独立执行窗口，第一次真正 enter maintenance / preserve rollback image /
  create backup / migrate 0028→0034 / deploy release tree target 9000 / verify）
```

不必重跑 rehearsal（ISOLATED_REHEARSAL=APPROVED_WITH_NON_BLOCKING_FINDINGS 仍有效，
target artifact 隔离 9db3f58/head=0034 仍 VERIFIED，release artifact a633b48 已 FROZEN）。

## 56. 即使 B2/B3 后续关闭也不本窗口执行

`AUTHORIZATION ≠ EXECUTION`。本窗口即使裁定 GO 也须 STOP，交独立 Execution 窗口。本窗口裁定 NO_GO，更须立即停止。

---

# 57. Git / Merchant Discipline

```text
DO NOT COMMIT
DO NOT PUSH
DO NOT MODIFY MERCHANT
DO NOT MIGRATE / RESTART / BUILD / TAG / BACKUP / EDIT ENV
未在 Merchant repository 写任何文件（本报告仅存于本地开发工作区）
```

## 58. 文档影响检查（AI 文档自治维护）

- 本轮唯一新增：本报告（`..._FOCUSED_PRODUCTION_AUTHORIZATION.md`）。未修改任何活动治理文档（CLAUDE.md / AGENTS.md / docs/ai 01~05 / Reality Map / 既有 remediation 报告）。
- `..._PRODUCTION_AUTHORIZATION.md` 的 NO_GO 结论**仍成立**（本窗口 B2/B3 保持 OPEN，未产生与之矛盾的事实；B1 虽 CLOSED，但 B2/B3 未关闭，整体仍 NO_GO）。
- 无其他活动文档结论因本轮而过期。

---

*Focused Production Authorization 窗口结束。仅执行本地只读 git 核实与报告阅读；未操作 Merchant，未 commit/push，未迁移/构建/备份/改 env/restart。最终裁定 `PRODUCTION_AUTHORIZATION_NO_GO`：BLOCKER-1=CLOSED / BLOCKER-2=OPEN / BLOCKER-3=OPEN。立即停止。*
