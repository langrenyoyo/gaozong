# PRODUCTION-BASELINE-CATCHUP-0028-TO-0034 — Focused Production Authorization R1

> 窗口：`PRODUCTION-BASELINE-CATCHUP-0028-TO-0034 / FOCUSED-PRODUCTION-AUTHORIZATION-R1`
> 窗口性质：**AUTHORIZATION ONLY / READ-ONLY** — 只审批不执行。绝对只读纪律（任务书 §2/§40/§54）。
> 前序：`..._FOCUSED_PRODUCTION_AUTHORIZATION.md`（HISTORICAL NO_GO，B2/B3 OPEN）→ `..._MERCHANT_M_AUTH_READ_ONLY.md` PART II（Evidence Consolidation，B2/B3 = CANDIDATE_RESOLVED）
> 日期：2026-08-12
> 职责：基于已归并的 NOW-GATE operator evidence，独立裁定 BLOCKER-2 / BLOCKER-3 是否正式 CLOSED，继承 BLOCKER-1，给出最终 GO / GO_WITH_NON_BLOCKING_FINDINGS / NO_GO。
>
> **本窗口不是执行窗口、不是修复窗口、不是 Merchant 取证窗口。** 原则上 `NO NEW MERCHANT ACCESS`（任务书 §46），只审核已 consolidated 的 operator evidence。

---

## 1. Scope

只审三件事（任务书 §1）：

```text
R1-1  BLOCKER-2  EXTERNAL_AUTOHEAL_WATCHDOG
R1-2  BLOCKER-3  MERCHANT_CURRENT_REALITY
R1-3  新的 NOW-GATE operator evidence 是否使既有 M0~M11 / P-S01~P-S16 / PV-01~PV-17 失效
```

禁止重新全面审批 B1 Release Freeze / S10-B / Catch-up Design / Isolated Rehearsal / 完整 Production Authorization。

## 2. Prior NO_GO

上一轮 Focused Production Authorization 裁定（`..._FOCUSED_PRODUCTION_AUTHORIZATION.md`）：

```text
PRODUCTION_AUTHORIZATION        = NO_GO
PRODUCTION_MIGRATION_AUTHORIZED = NO
PRODUCTION_EXECUTION_ENTRY      = BLOCKED
BLOCKER-1 RELEASE_ENGINEERING_ARTIFACT_IDENTITY = CLOSED   （FA-B1-01~07 全 PASS）
BLOCKER-2 EXTERNAL_AUTOHEAL_WATCHDOG             = OPEN      （FA-B2-01~07 UNSUPPORTED）
BLOCKER-3 MERCHANT_CURRENT_REALITY               = OPEN      （FA-B3-01~08 多数 UNSUPPORTED）
```

上一轮 NO_GO 的核心原因**不是发现新技术故障**，而是当时正式 M-AUTH 报告仍停留在 `M_AUTH_READ_ONLY_EVIDENCE_INCOMPLETE` / `MERCHANT_HOST_ACCESS=MISSING`（PART I 历史阶段）。随后 Evidence Consolidation（M-AUTH PART II）把有权限 operator 在 Merchant 主机真实执行的 M-AUTH-01~21 + B2-01~05 证据正式归并，得到 `CURRENT_M_AUTH_STATUS = COMPLETE` / B2·B3 = CANDIDATE_RESOLVED。本窗口负责把 CANDIDATE_RESOLVED → CLOSED / OPEN。

## 3. Why R1 Exists

Evidence Consolidation 窗口性质是"只归并不取证、不审批"（M-AUTH PART II §2N 明示：B2/B3 只能 CANDIDATE_RESOLVED 不能 CLOSED，正式 closure 留给下一 Focused Authorization R1）。需要一个独立审批窗口，在不修改 M-AUTH、不重跑 rehearsal、不重审 B1 的前提下，独立裁定 B2/B3 是否正式 CLOSED。

## 4. Evidence Refresh Provenance

```text
E1  EARLIER_HISTORICAL    = M1/M2/M3/M4 historical reality（仅作比较基线，非 now-gate）
E2  INITIAL_M_AUTH_REPORT = M-AUTH PART I：MERCHANT_HOST_ACCESS=MISSING / INCOMPLETE（HISTORICAL，保留不删）
E3  OPERATOR_EVIDENCE     = 有权限 operator 在 Merchant 主机 /www/wwwroot/XG_AI_System
                            真实执行 M-AUTH-01~21 + B2-01~05 的输出（当前 now-gate 事实源）
```

任务书 §4 Evidence Temporal Authority：对 Merchant 当前生产现实 `E3 > E2 > E1`，只要 E3 provenance 完整、未被后续事实推翻。**不得继续用"旧 M-AUTH 当时没有 SSH"否定随后真实 operator 已取得的 Merchant 证据。**

任务书 §5 Evidence Provenance Hard Gate：M-AUTH PART II §2B 明确标注 `PROVENANCE LABEL = MERCHANT_OPERATOR_EVIDENCE`（执行人 = 有权限 operator，非本 VibeCoding 窗口；本窗口未 SSH、未执行任何生产命令）。该区分是正常证据来源，**不构成降级**。

**R1 本地独立交叉核实（非 rubber-stamp）**：

```text
R1-X1  f453f44e6a70de3eb5fa8f808cf4b6a9d72ea6c1 在 git 历史（git cat-file -t = commit）
       subject = "fix: 导出脚本兼容多版本 pymilvus 迭代 API" / parent = 36d9bb2
       → 生产已知 HEAD 候选真实存在于仓库历史                              PASS
R1-X2  uk_return_visit_runs_idempotency_key 归属
       migrations/postgres/auto_wechat/versions/0011_return_visit_phase9.py（既有 0011 索引）
       → 非 0030 污染，印证 M-AUTH-14B 判定                                PASS
R1-X3  uk_compute_transactions_merchant_idempotency 归属
       migrations/postgres/auto_wechat/versions/0030_compute_idempotency.py（0030 未来目标）
       → 生产 0028 应 ABSENT，operator 报 ABSENT 一致                     PASS
R1-X4  0030 定义 idempotency_key + payload_evidence 列 + UK 约束
       → 0030~0034 目标对象在 0028 生产应全 ABSENT                         PASS
R1-X5  0034 down_revision = 0033（单线无分叉）/ PG Alembic 轨道最高 = 0034 / 无 ≥0035  PASS
R1-X6  a633b486 release commit parent=9db3f58 / tree=6d23c79 / diff=8 文件(3M+5A)         PASS
       app/** apps/** migrations/** frontend/** 全 ZERO DIFF
```

operator evidence 与本地可核实项全部一致；无内部矛盾。

## 5. B1 Inherited Closure

任务书 §2：BLOCKER-1 必须继承 CLOSED，R1 不重新执行完整 B1 审计。只有发现 `release commit changed / manifest changed / release artifact changed / S10-B files changed` 的新事实才允许重开 B1。

```text
APPLICATION_BASE  = 9db3f58
RELEASE_TREE      = a633b4860b818ab48fda5e22f39aa311eb96e9eb（immutable hash，未变化）
ALEMBIC_HEAD      = 0034 / 0035 ABSENT
manifest/hash     = verified（上一轮 FA-B1-07 独立复算 4 文件 SHA256 全 MATCH）
wrapper safety    = verified（上一轮 FA-B1 §11 逻辑核验）
```

新事实检查：

- release commit a633b48 = immutable，未变化；
- 本地主工作区存在 PRE_EXISTING S10-B 修改（M .env.production.example / M docker-compose.yml / M docs/config/ENV_VARIABLE_REFERENCE.md / ?? scripts/release_9000_s10b.py / ?? tests/test_s10_b_image_identity_isolation.py），但**本地工作区 ≠ Merchant 生产现实**（任务书 §18：两者是不同环境）。本地工作区 pre-existing release engineering diff 不构成 release artifact 变化，a633b48 frozen artifact 不受影响。

```text
BLOCKER-1 = CLOSED / INHERITED
```

无新事实重开 B1。

---

# 第二 Hard Gate — BLOCKER-2 External Autoheal / Watchdog

## 6. B2 Candidate State

M-AUTH PART II §2G / §2M 候选：

```text
EXTERNAL_HEALTH_RESTART = NONE_DETECTED
BLOCKER-2               = CANDIDATE_RESOLVED
```

## 7. Docker Evidence（R1-B2-01/02/03）

M-AUTH-18（PART II §2D）operator 在 Merchant 主机执行 `docker ps -a` + label 审计：

```text
autoheal container              = NONE_DETECTED
watchtower container            = NONE_DETECTED
watchdog deployment container   = NONE_DETECTED
9000 autoheal label             = NONE
9000 watchtower enable label    = NONE
（服务器存在其他普通容器 ≠ 项目 lifecycle 守护）
```

任务书 §7：不得把普通 Docker `restart_policy=unless-stopped` 误判成 external autoheal。operator 证据显示 9000/9100 restart_policy=unless-stopped、restart_count=0/0、health=healthy——rehearsal 已 runtime 证明 `health=unhealthy` 在当前 topology 下不自动触发 restart。compose 层（9db3f58 树）与宿主 docker 层（operator）双重 NONE_DETECTED。

```text
R1-B2-01 Docker autoheal        = PASS（NONE_DETECTED）
R1-B2-02 watchtower             = PASS（NONE_DETECTED）
R1-B2-03 Docker labels          = PASS（9000 relevant keys NONE）
```

## 8. systemd Evidence（R1-B2-04/05）

M-AUTH-19 operator 执行 `systemctl list-unit-files/list-units/list-timers` + `ps -ef`：

```text
XG_AI_System-specific watchdog service = NONE_DETECTED
auto-wechat lifecycle service          = NONE_DETECTED
relevant systemd timer                 = NONE_DETECTED
观察到 [watchdogd]：基于进程形态解释为 kernel watchdog thread / 非项目 lifecycle evidence
```

任务书 §8：观察到 `[watchdogd]` 不得单独据此判 `PROJECT_AUTOHEAL_PRESENT`。consolidation 已按进程形态分类为 kernel watchdog thread（只作形态解释，不作为唯一 closure 依据）。本窗口无反向证据推翻该分类。

```text
R1-B2-04 systemd service        = PASS（NONE_DETECTED）
R1-B2-05 systemd timer          = PASS（NONE_DETECTED）
```

## 9. Cron Evidence（R1-B2-06）

M-AUTH-20 operator 执行 `crontab -l` / `/etc/crontab` / `/etc/cron.d`：

```text
root crontab relevant lifecycle match     = NONE
/etc/crontab relevant lifecycle match    = NONE
/etc/cron.d relevant lifecycle match      = NONE
```

任务书 §9 要求覆盖 root crontab / /etc/crontab / /etc/cron.d 三处并支持无 XG lifecycle / 无 docker compose restart/start 匹配——operator 证据覆盖且全 NONE。

```text
R1-B2-06 cron                   = PASS（NONE_DETECTED）
```

## 10. BT Restore Capability（R1-B2-07）

M-AUTH-21 + B2-01（PART II §2D/§2H）：

```text
/www/server/panel/script/docker_compose_restore.py 确实具备 docker-compose stop + docker-compose up -d 能力
→ BT_COMPOSE_RESTORE_CAN_CHANGE_SERVICE_LIFECYCLE = YES
```

任务书 §10：不得伪装成没有这种能力。本窗口诚实确认 BT Compose Restore **真实具有** stop + up -d 能力（CAPABILITY = YES）。但任务书 §10 同时明确：Hard Gate 不是"宝塔是否拥有恢复功能"，真正问题是**是否存在 health/scheduled/watchdog 针对性 automatic lifecycle trigger**。

```text
R1-B2-07 BT restore capability  = PASS（capability YES，honestly acknowledged；trigger 性质见 R1-B2-08/09）
```

## 11. BT Caller Context（R1-B2-08）

M-AUTH B2-02/B2-04（PART II §2H）operator 审查 `/www/server/panel/mod/project/docker/composeMod.py`：

```text
Backup  : compose method 接收 path/name → 验证输入 → 构造 backup command
          → panelTask.bt_task().create_task("compose项目备份任务", ...)
Restore : compose_restore_config(get) → 要求 backup_id → 查 backup record
          → 检查 backup file → 构造 restore command
          → panelTask.bt_task().create_task("compose项目恢复任务", ...)
→ BT_COMPOSE_BACKUP_RESTORE_TRIGGER = EXPLICIT ADMIN/API ACTION
→ NOT HEALTH_TRIGGER_CALLBACK
真实 caller = composeMod.py；无 systemd/cron 直接 caller evidence
```

任务书 §11：若 caller 为 explicit admin/API action（需 backup_id / 显式 create_task），则 `BT_COMPOSE_TRIGGER = EXPLICIT ADMIN/API ACTION` 而非 `HEALTH_TRIGGER_CALLBACK`。operator 证据支持前者。

```text
R1-B2-08 BT caller context      = PASS（EXPLICIT ADMIN/API ACTION，非 health callback）
```

## 12. BT Schedule Evidence（R1-B2-09）

M-AUTH B2-05（PART II §2H）operator 搜索 `/www/server/panel/data`：

```text
搜索 docker_compose_backup / docker_compose_restore / compose_backup / compose_restore → NO OUTPUT
→ BT_SCHEDULED_COMPOSE_BACKUP_RESTORE = NONE_DETECTED
```

任务书 §12：确认 panel data 针对上述关键词搜索 NO MATCH。operator 证据支持。

```text
R1-B2-09 BT scheduled trigger   = PASS（NONE_DETECTED）
```

## 13. XG Project Automation（R1-B2-10）

M-AUTH B2-03（PART II §2H）operator 针对 `XG_AI_System / xg-auto-wechat-api / auto-wechat-api` 搜索 `/www/server/panel/script` + `/www/server/panel/data` + `/etc/systemd/system` + `/etc/cron.d`：

```text
唯一命中 /www/server/panel/data/dir_history.json
→ dir_history.json = HISTORY / METADATA，不是执行器
→ PROJECT_SPECIFIC_BT_LIFECYCLE_AUTOMATION = NONE_DETECTED
```

任务书 §13：dir_history.json 是 metadata/history，非 lifecycle executor。operator 证据支持。

```text
R1-B2-10 XG project automation  = PASS（NONE_DETECTED）
```

## 14. B2 Operator Caution（保留，进入 Execution Carry-forward）

任务书 §14/§33：即使 B2 CLOSED，仍必须保留 operator caution——因为 BT manual restore capability 真实存在，但 manual administrative capability != automatic watchdog。

```text
EXECUTION_OPERATOR_CAUTION_BT_01:
  During M1~M11, do NOT manually trigger BT Compose:
    Restore / Start / Restart / Recreate
  for XG_AI_System unless explicitly directed by approved Production Execution runbook.
  特别：BT Compose Restore 可执行 stop + up -d。
  这是 OPERATOR_CONTROL，不是 blocker。
```

进入 §40 Carry-forward Findings。

## 15. B2 Verdict

任务书 §15：只有当前证据足以支持 Docker/systemd timer/cron/BT automatic trigger/XG-specific automation 全 NONE_DETECTED，才允许 `EXTERNAL_HEALTH_RESTART = NONE_DETECTED / BLOCKER-2 = CLOSED`。

operator evidence（M-AUTH PART II §2G）覆盖全部五层且全 NONE_DETECTED：

```text
Docker automatic lifecycle mechanism        = NONE_DETECTED
systemd automatic lifecycle mechanism      = NONE_DETECTED
systemd timer                              = NONE_DETECTED
cron lifecycle automation                   = NONE_DETECTED
BT automatic trigger                       = NONE_DETECTED
XG-specific external lifecycle automation   = NONE_DETECTED
```

```text
EXTERNAL_HEALTH_RESTART = NONE_DETECTED
BLOCKER-2 = CLOSED
```

无 conditional GO。BT manual capability 以 OPERATOR_CAUTION 形式 carry-forward，非 blocker。

---

# 第三 Hard Gate — BLOCKER-3 Merchant Current Reality

## 16. B3 Candidate State

M-AUTH PART II §2F / §2M 候选：

```text
MERCHANT_CURRENT_REALITY   = RE_FROZEN
PRODUCTION_REALITY_DRIFT   = NO MATERIAL DRIFT DETECTED
BLOCKER-3                  = CANDIDATE_RESOLVED
```

## 17. Git Reality（R1-B3-01）

M-AUTH-01（PART II §2D）operator 在 `/www/wwwroot/XG_AI_System` 执行 `git rev-parse HEAD`：

```text
PRODUCTION_GIT_HEAD = f453f44e6a70de3eb5fa8f808cf4b6a9d72ea6c1
BRANCH               = master
tracked worktree     = 无新 diff；仅保留此前已知三个 production-only untracked 文件
```

R1-X1 独立核实 f453f44 真实存在于仓库历史（commit / subject / parent 一致）。

```text
R1-B3-01 production git       = PASS（f453f44，独立交叉核实存在于历史）
```

## 18. Worktree Reality（R1-B3-02）

M-AUTH-02：tracked clean（无 tracked drift）；保护文件 `.env.production.local.bak.20260804_172603` / `milvus_export_full.jsonl` / `milvus_export_no_vec.jsonl` = PRESENT / PROTECTED / NOT TRACKED。继续冻结：NO git clean / NO destructive reset。

**本地工作区 PRE_EXISTING S10-B 修改说明**（任务书 §18）：本机主工作区存在 `.env.production.example` / `docker-compose.yml` / `ENV_VARIABLE_REFERENCE.md` 等 PRE_EXISTING S10-B release engineering diff——这是本地开发工作区（master HEAD=36fe68a）的未提交修改，**不是** Merchant 生产现实 drift。两者是不同环境。本地工作区 pre-existing diff 不重开 B1（release artifact a633b48 immutable 未变），亦不构成 B3 drift。

```text
R1-B3-02 worktree              = PASS（生产 tracked clean；本地工作区 S10-B 为 PRE_EXISTING 非生产 drift）
```

## 19. Compose Topology（R1-B3-03）

M-AUTH-03：XG_AI_System 服务 = postgres / xg-douyin-ai-cs / auto-wechat-api / auto-wechat-frontend（四服务）。Merchant 主机存在其他项目容器（knowledge-train / used-car / car-project ...）。

任务书 §19：他项目容器不得据此认定 XG Compose topology drift。operator 证据区分了 XG_AI_System 与他项目。

```text
R1-B3-03 compose topology      = PASS（四服务一致；他项目容器非 drift）
```

## 20. Runtime Image Reality（R1-B3-04/05）

M-AUTH-05/06/07/08：

```text
9000_RUNTIME_IMAGE_ID = sha256:93094f0a02ba3a4570160ce90625cb80fdec85076046fc314f5fe407add36c68
9100_RUNTIME_IMAGE_ID = sha256:93094f0a02ba3a4570160ce90625cb80fdec85076046fc314f5fe407add36c68
CURRENT_RUNTIME_SHARED_IMAGE = YES（now-gate Merchant docker inspect 事实，非仅历史 M3）
restart_count = 0 / 0 / health = healthy / healthy / restart_policy = unless-stopped
ROLLBACK_RUNTIME_IMAGE_AVAILABLE = YES（93094f0 本机可引用，支持未来 rollback preservation）
old runtime image = locally available
```

任务书 §20：9000/9100 runtime image 共享同一 old identity、restart_count=0、health=healthy、old image 本地可引用。

```text
R1-B3-04 9000 runtime image    = PASS（93094f0，old runtime）
R1-B3-05 9100 runtime image    = PASS（93094f0，与 9000 同 old）
```

## 21. 9000 App/DB（R1-B3-06）

M-AUTH-09/12：

```text
9000 APP CURRENT = 0028 / 9000 APP HEAD = 0028
SELECT version_num FROM alembic_version → 0028
```

任务书 §21：9000 Alembic current/head/DB alembic_version 三者均 = 0028。

```text
R1-B3-06 9000 app/db           = PASS（app=0028 / DB=0028）
```

## 22. 9000 Ready（R1-B3-07）

M-AUTH-10：

```text
/health = 200 / /ready = 200
expected revision = [0028] / actual revision = [0028]
critical_tables PASS
```

```text
R1-B3-07 9000 ready            = PASS（200，expected=actual=0028）
```

## 23. PostgreSQL Identity（R1-B3 补充）

M-AUTH-11：database = auto_wechat / user = xgairoot / PostgreSQL = 16.14（secret 不披露，任务书 §22）。

## 24. JSONB Drift（R1-B3-08）

M-AUTH-13：

```text
customer_profiles.confirmed_fields_json = jsonb
customer_profiles.inferred_fields_json  = jsonb
（与 rehearsal 输入模型一致）
```

任务书 §23：必须仍对应 approved rehearsal fixture（0028 revision marker + 0029 JSONB-type ahead drift）。operator 证据显示两列仍为 jsonb——这正是 0029 迁移幂等前提（0029 idempotent on jsonb，"ahead drift"即两列在 0029 运行前已是 jsonb）。R1-X4 独立核实 0030 目标对象定义，与 0029 幂等前提不冲突。

```text
R1-B3-08 JSONB drift           = PASS（两列 jsonb，对应 0029 幂等前提）
```

## 25. Future Object Audit（R1-B3-09）

M-AUTH-14：

```text
daily_report_generations                = ABSENT
ai_edit_material_analysis_executions     = ABSENT
ai_preview_executions                    = ABSENT
compute_transactions.idempotency_key     = ABSENT
compute_transactions.payload_evidence    = ABSENT
daily_report_jobs.current_generation_id  = ABSENT
→ PHYSICAL_SCHEMA_DRIFT_SCOPE = 0029_JSONB_TYPE_AHEAD_ONLY（drift 未扩大）
```

R1-X4 独立核实上述对象定义在 0030~0034 migration（0030 定义 idempotency_key/payload_evidence/UK；0032 daily_report_generations；0033 material_analysis；0034 preview_executions）——生产 0028 应全 ABSENT，operator 报 ABSENT 一致。

```text
R1-B3-09 future objects        = PASS（6 项全 ABSENT，无 0030+ 污染）
```

## 26. 14B Interpretation（R1-B3 补充）

M-AUTH-14B：

```text
found  : uk_return_visit_runs_idempotency_key
NOT    : uk_compute_transactions_merchant_idempotency
target migration 相关 constraints 查询 = 0 rows
→ FUTURE_0030_TARGET_SCHEMA_CONTAMINATION = NONE_DETECTED
```

R1-X2 独立核实 `uk_return_visit_runs_idempotency_key` 归属 `0011_return_visit_phase9.py`（既有 0011 索引，非 0030 污染）；R1-X3 独立核实 `uk_compute_transactions_merchant_idempotency` 归属 `0030_compute_idempotency.py`（未来目标，生产 0028 应 ABSENT）。任务书 §25 判定得到独立印证。

## 27. Data Scale（R1-B3-10）

M-AUTH-15：

```text
customer_profiles   = 1
compute_transactions = 1725
daily_report_jobs    = 0
```

历史 M2 = `cp=1 / ct=1698 / drj=0`（Reality Audit 时期）。1698 → 1725 = +27 行。

任务书 §26：必须分类为 `NORMAL_BUSINESS_GROWTH`（schema/preconditions 未改变，且 future objects 全 ABSENT、JSONB drift 仍 0029 两列）。**不是** PRODUCTION_REALITY_DRIFT。

> 上一轮 FOCUSED Authorization 曾标记 `ct=1725` 为"任何文档均无 1725 / UNSUPPORTED"——那是因为当时 PART I 无 operator 证据。现 PART II 提供 1725 为 operator 在 Merchant 主机实测行数，该矛盾已解决。1725 与 M2 的 1698 差异为正常业务增长，非 drift。

```text
R1-B3-10 data scale           = PASS（1/1725/0，1698→1725 = NORMAL_BUSINESS_GROWTH）
```

## 28. 9100 Reality（R1-B3-11/12）

M-AUTH-16/17：

```text
9100 APP CURRENT = 0003 / 9100 APP HEAD = 0003
/health = 200 / /ready = 200
Milvus : connected = true / collection_exists = true / schema_match = true / query_ok = true
容器内 curl = CMD_UNAVAILABLE / NON_BLOCKING（host endpoint 已真实通过）
```

任务书 §27：9100 Alembic current/head=0003、/ready=200、Milvus 四项 true。容器内 curl missing 仅 CMD_UNAVAILABLE / NON_BLOCKING（host endpoint 已验证）。

```text
R1-B3-11 9100 app/db           = PASS（0003 / 0003）
R1-B3-12 9100 ready            = PASS（200；Milvus 4x true；容器 curl NON_BLOCKING）
```

## 29. Merchant Reality Matrix

任务书 §28：必须独立输出至少 13 行矩阵，**不得直接复制 consolidation 的"13行 MATCH"**。R1 独立核对每行依据（见 §17~§28）：

| Fact | Expected | NOW-GATE (operator evidence) | Verdict |
| --- | --- | --- | --- |
| Git HEAD | f453f44 | f453f44（M-AUTH-01，R1-X1 交叉） | MATCH |
| tracked drift | none | none（M-AUTH-02） | MATCH |
| 9000 app | 0028 | 0028（M-AUTH-09） | MATCH |
| 9000 DB | 0028 | 0028（M-AUTH-12，远程+宿主 psql） | MATCH |
| 9000 ready | 200 | 200（M-AUTH-10，expected=actual=0028） | MATCH |
| JSONB drift | 2 columns jsonb | 2 columns jsonb（M-AUTH-13） | MATCH |
| future objects | absent | absent 6 项（M-AUTH-14，R1-X4 交叉） | MATCH |
| data scale | compatible | 1 / 1725 / 0（M-AUTH-15） | MATCH |
| 9000 image | old runtime | 93094f0（M-AUTH-05） | MATCH |
| 9100 image | old same | 93094f0（M-AUTH-06/07） | MATCH |
| 9100 app | 0003 | 0003（M-AUTH-16） | MATCH |
| 9100 DB | 0003 | 0003（M-AUTH-16） | MATCH |
| 9100 ready | healthy | 200（M-AUTH-17，Milvus 4x true） | MATCH |

13/13 MATCH，每行依据独立核对。

## 30. B3 Material Drift Definition

任务书 §29：真正可重开 B3 的是 git revision changed / unexpected tracked modification / 9000 revision changed / DB revision changed / physical schema drift expanded / future 0030~0034 objects present / runtime image replaced / 9100 revision changed / new XG worker/writer/service / new lifecycle automation。

逐项核查：

- Git revision：f453f44 未变；
- tracked modification：none；
- 9000 revision：0028 未变；
- DB revision：0028 未变；
- physical schema drift：仍 0029 两列 jsonb，未扩大；
- future 0030~0034 objects：全 ABSENT；
- runtime image：93094f0 未替换；
- 9100 revision：0003 未变；
- new XG worker/writer：topology 四服务，无独立 worker/scheduler（§32）；
- new lifecycle automation：B2 全 NONE_DETECTED（§15）。

正常数据行增长（1698→1725）不属于 material drift。

## 31. B3 Verdict

任务书 §30：若上述事实全部支持 approved production start model → `MERCHANT_CURRENT_REALITY = RE_FROZEN` / `PRODUCTION_REALITY_DRIFT = NO MATERIAL DRIFT DETECTED` / `BLOCKER-3 = CLOSED`。

13/13 MATCH，无 material drift触发项。

```text
MERCHANT_CURRENT_REALITY = RE_FROZEN
PRODUCTION_REALITY_DRIFT = NO MATERIAL DRIFT DETECTED
BLOCKER-3 = CLOSED
```

---

# Carry-forward / Write Isolation / Runbook

## 32. Write Isolation Model

任务书 §31：当前 Merchant topology 未发现 independent XG worker / independent scheduler / external project DB writer。

M-AUTH PART II §2L：`PRODUCTION_WRITE_ISOLATION_TOPOLOGY = CONSISTENT_WITH_STATIC_MODEL`。

任务书 §31 明示：这是 **topology evidence**；"writes already stopped" 仍属 Production Execution 的 dynamic gate（M2 / P-S08），不得写成"writes already stopped"——现在还没进入 maintenance。Runbook M1/M2 仍可在执行阶段动态证明真正 write isolation。

```text
R1-RUNBOOK-04 write isolation model = PASS（topology 与静态模型一致；actual write stop = execution-time gate）
```

## 33. Runbook Revalidation（R1-RUNBOOK-01）

任务书 §32：R1 不重审全部设计，只回答"新的 Merchant NOW-GATE evidence 是否使原 M0~M11 失效？"。

```text
M0  PRE-MAINTENANCE        reality reconfirm / protected files / storage / rollback image identity
M1  ENTER MAINTENANCE      maintenance begin
M2  VERIFY WRITE ISOLATION 9000 stopped + webhook paused + 9100 容错 + 无独立 cron writer
M3  PRESERVE ROLLBACK IMAGE Step 0~2
M4  CREATE/VERIFY DB BACKUP backup + verify
M5  VERIFY TARGET ARTIFACTS 9db3f58 source / image built / head=0034
M6  MIGRATE 0028→0034      alembic upgrade 0034
M7  VERIFY DB 0034         version_num=0034 + objects
M8  DEPLOY TARGET 9000     wrapper --apply（9000-only）
M9  VERIFY /ready 200      expected=actual=0034
M10 VERIFY 9100 UNCHANGED  container/image/DB=0003
M11 EXIT MAINTENANCE       仅 target ready 后
```

NOW-GATE evidence 显示生产现实匹配 approved model（f453f44 / 0028 / 0003 / old image / no drift / no watchdog），M0~M11 起点假设成立，未被新证据推翻。

```text
R1-RUNBOOK-01 M0~M11          = PASS（STILL VALID）
```

## 34. Stop Conditions（R1-RUNBOOK-02）

任务书 §34：确认 P-S01~P-S16 仍适用。尤其 P-S01（current reality mismatch）/ P-S02（rollback image preservation）/ P-S08（write isolation）/ P-S16（external watchdog）。

- P-S01 不触发：reality matches authorization freeze（13/13 MATCH）；
- P-S02 不触发但仍是 execution-time gate：old image 93094f0 locally available（topology），actual preservation = M3；
- P-S08 不触发但仍是 execution-time gate：topology consistent，actual write stop = M2；
- P-S16 不触发：B2 NONE_DETECTED。

```text
R1-RUNBOOK-02 P-S01~P-S16     = PASS（STILL VALID）
```

## 35. P-S04 Identity Contract

任务书 §35：继续采用 `APPLICATION_BASE=9db3f58` + `RELEASE_TREE=a633b4860b818ab48fda5e22f39aa311eb96e9eb`，不退回仅验证 9db3f58。

## 36. Verification Matrix（R1-RUNBOOK-03）

任务书 §36：PV-01~PV-17 仍足以验证 release identity / DB0034 / app0034 / /ready200 / schema objects / data preservation / JSONB / logs / P1 artifacts / 9100 unchanged / 9100 image / 9100 DB0003 / no 0035 / no unexpected drift。无新事实推翻。

```text
R1-RUNBOOK-03 PV-01~PV-17     = PASS（STILL VALID）
```

## 37. 9100 Hard Freeze（R1-RUNBOOK-05）

```text
9100 CODE UPGRADE = NO / 9100 DB MIGRATION = NO / 9100 RECREATE = NO / 9100 TARGET DB = 0003
```

任何 Execution 方案若要求顺带更新 9100 → STOP。

```text
R1-RUNBOOK-05 9100 freeze     = PASS（0003 maintained）
```

## 38. 0035 Boundary（R1-RUNBOOK-06）

```text
0035 = OUT OF THIS CATCH-UP / NOT APPLIED / FUTURE P2 CUTOVER
```

本地开发主线 HEAD=36fe68a 含 0035，但 target = 9db3f58（release tree a633b48 派生自 9db3f58，无 0035，R1-X5 核实）。不得因主线存在 0035 改变 target。

```text
R1-RUNBOOK-06 0035 exclusion   = PASS（target 9db3f58/head 0034，0035 excluded）
```

## 39. Network / Offline Boundary

任务书 §39：生产 GitHub 访问历史不稳定。release artifact（a633b48）offline-capable（git archive/bundle + Manifest SHA256SUMS），Execution 可 pre-stage/offline transfer + manifest/hash verification，**不依赖 maintenance 期 git pull/fetch**。这是 execution-time dynamic gate。

## 40. Execution-Time Dynamic Gates

任务书 §40：即使 R1 GO，以下仍是 PENDING EXECUTION-TIME（R1 只能确认 gate 定义充分且 fail-closed，不能确认已执行）：

```text
actual maintenance entry（M1）
actual write isolation（M2/P-S08）
actual rollback image preservation（M3/P-S02）
actual DB backup creation（M4/P-S03）
actual target artifact transfer + hash verification（M5/P-S04）
actual target image build/load + ID/digest verification（PV-01）
actual migration 0028→0034（M6/P-S09）
actual DB0034 verification（M7/P-S10）
actual target 9000 deployment（M8）
actual /ready 200 expected=actual=0034（M9/P-S13）
actual 9100 unchanged verification（M10/P-S14）
```

```text
EXECUTION-TIME_DYNAMIC_GATES = FAIL-CLOSED AND DEFERRED TO EXECUTION
```

## 41. Carry-forward Non-Blocking Findings

保持此前已批准的（任务书 §41），R1 未发现任一升级为 real blocker：

```text
U1  old baseline fresh-bootstrap defect（CF-1, OUT_OF_PRODUCTION_PATH）
U2  target JSONB predeclaration（CF-2, SUPPORTING）
U3  transactional DDL supporting evidence（CF-3, ACCEPTED_WITH_SCOPE_LIMIT）
image source provenance debt
production timing larger than rehearsal timing（CF-7, OPERATOR_CAUTION）
BR-22 single injected failure mode（CF-8, scope limit）
BR-15 partial old-runtime compatibility scope（CF-9, MAINTENANCE_FALLBACK_ONLY）
```

新增/确认：

```text
BT manual Compose lifecycle capability = OPERATOR CAUTION（见 §14 EXECUTION_OPERATOR_CAUTION_BT_01）
```

---

# Evidence Matrix / Findings / Verdict

## 42. R1 Evidence Matrix

```text
R1-B2-01 Docker autoheal                  = PASS（NONE_DETECTED）
R1-B2-02 watchtower                       = PASS（NONE_DETECTED）
R1-B2-03 Docker labels                    = PASS（9000 relevant keys NONE）
R1-B2-04 systemd service                  = PASS（NONE_DETECTED）
R1-B2-05 systemd timer                    = PASS（NONE_DETECTED）
R1-B2-06 cron                             = PASS（NONE_DETECTED）
R1-B2-07 BT restore capability            = PASS（capability YES, honestly acknowledged）
R1-B2-08 BT caller context                = PASS（EXPLICIT ADMIN/API ACTION）
R1-B2-09 BT scheduled trigger             = PASS（NONE_DETECTED）
R1-B2-10 XG-specific lifecycle automation = PASS（NONE_DETECTED）

R1-B3-01 production git                   = PASS（f453f44，R1-X1 交叉）
R1-B3-02 worktree                         = PASS（tracked clean；本地 S10-B PRE_EXISTING 非生产 drift）
R1-B3-03 compose topology                 = PASS（四服务；他项目非 drift）
R1-B3-04 9000 runtime image              = PASS（93094f0）
R1-B3-05 9100 runtime image              = PASS（93094f0 shared）
R1-B3-06 9000 app/db                      = PASS（0028 / 0028）
R1-B3-07 9000 ready                       = PASS（200，expected=actual=0028）
R1-B3-08 JSONB drift                      = PASS（两列 jsonb，0029 幂等前提）
R1-B3-09 future objects                   = PASS（6 项 ABSENT，R1-X4 交叉）
R1-B3-10 data scale                       = PASS（1/1725/0，normal growth）
R1-B3-11 9100 app/db                      = PASS（0003 / 0003）
R1-B3-12 9100 ready                       = PASS（200，Milvus 4x true）

R1-RUNBOOK-01 M0~M11                      = PASS（STILL VALID）
R1-RUNBOOK-02 P-S01~P-S16                 = PASS（STILL VALID）
R1-RUNBOOK-03 PV-01~PV-17                 = PASS（STILL VALID）
R1-RUNBOOK-04 write isolation model       = PASS（topology consistent；actual stop = execution gate）
R1-RUNBOOK-05 9100 freeze                 = PASS（0003 maintained）
R1-RUNBOOK-06 0035 exclusion              = PASS（target 0034，0035 excluded）
```

无 PASS 之外的模糊措辞；无 INSUFFICIENT_EVIDENCE。

## 43. Blocking Findings

```text
无。
```

B2 五层全 NONE_DETECTED（BT manual capability 以 OPERATOR_CAUTION carry-forward，非 blocker）；B3 13/13 MATCH 无 material drift；B1 继承 CLOSED 无新事实；runbook/stop/verification 未被推翻；9100 freeze / 0035 boundary 维持。

## 44. Non-Blocking Findings

```text
R1-NB-1  BT manual Compose lifecycle capability 真实存在（restore 可 stop + up -d），
         但无 automatic trigger；以 EXECUTION_OPERATOR_CAUTION_BT_01 carry-forward（§14/§33）。
R1-NB-2  U1/U2/U3、image source provenance debt、production timing uncertainty、
         BR-15/BR-22 scope limits 继续保持非 blocking（§41），无一升级。
R1-NB-3  9100 容器内 curl = CMD_UNAVAILABLE / NON_BLOCKING（host endpoint 已真实通过，Milvus 4x true）。
R1-NB-4  compute_transactions 1698→1725 = NORMAL_BUSINESS_GROWTH（非 drift）。
R1-NB-5  本地工作区 PRE_EXISTING S10-B 修改（.env.production.example / docker-compose.yml /
         ENV_VARIABLE_REFERENCE.md / release_9000_s10b.py / test_s10_b...）非生产 drift，
         release artifact a633b48 immutable 未变，不重开 B1。
R1-NB-6  未输出任何 .env 内容/密码/密钥（secret 纪律）。
R1-NB-7  本窗口未操作 Merchant / 未迁移 / 未构建 / 未备份 / 未改 env / 未 restart / 未 commit / 未 push。
```

## 45. B1/B2/B3 Final State

```text
BLOCKER-1 RELEASE_ENGINEERING_ARTIFACT_IDENTITY = CLOSED / INHERITED
BLOCKER-2 EXTERNAL_AUTOHEAL_WATCHDOG             = CLOSED
BLOCKER-3 MERCHANT_CURRENT_REALITY               = CLOSED
NEW_BLOCKER                                      = NONE
```

## 46. R1 Verdict

任务书 §48 GO Hard Gate：B1=CLOSED / B2=CLOSED / B3=CLOSED / NEW_BLOCKER=NONE / M0~M11 STILL VALID / P-S01~16 STILL VALID / PV-01~17 STILL VALID / EXECUTION-TIME_DYNAMIC_GATES FAIL-CLOSED AND DEFERRED。全部成立。

任务书 §49：Hard Gates 全通过，但仍有 BT manual operator caution / U1/U2/U3 / image provenance debt / production timing uncertainty / BR-15/BR-22 limitations → `PRODUCTION_AUTHORIZATION_GO_WITH_NON_BLOCKING_FINDINGS`，明确 carry-forward findings。允许 Execution Entry 打开。

```text
PRODUCTION_AUTHORIZATION = APPROVED / GO_WITH_NON_BLOCKING_FINDINGS
```

## 47. Production Migration Authorization / Execution Entry

```text
PRODUCTION_MIGRATION_AUTHORIZED = YES
PRODUCTION_EXECUTION_ENTRY      = OPEN
PRODUCTION_MIGRATION_EXECUTED    = NO
```

**`PRODUCTION_MIGRATION_EXECUTED = NO` 至关重要：授权不等于已经迁移。**

任务书 §51：GO 时第一次允许 `PRODUCTION_MIGRATION_AUTHORIZED = YES` / `PRODUCTION_EXECUTION_ENTRY = OPEN`，但 `PRODUCTION_MIGRATION_EXECUTED = NO`。

## 48. Next Stage

```text
当前 : Focused Production Authorization R1 = GO_WITH_NON_BLOCKING_FINDINGS（B1/B2/B3 全 CLOSED）
  ↓
下一阶段唯一 = PRODUCTION-BASELINE-CATCHUP-0028-TO-0034 / PRODUCTION-EXECUTION（独立执行窗口）
届时才允许真正发生：
  maintenance（M1）/ write isolation（M2）/ rollback image preservation（M3）
  / production DB backup（M4）/ release artifact pre-stage verification（M5）
  / migration 0028→0034（M6）/ DB0034 verification（M7）/ target 9000 deployment（M8）
  / /ready verification（M9）/ 9100 unchanged verification（M10）/ exit maintenance（M11）
```

不必重跑 rehearsal（ISOLATED_REHEARSAL=APPROVED_WITH_NON_BLOCKING_FINDINGS 仍有效；target artifact 隔离 9db3f58/head=0034 仍 VERIFIED；release artifact a633b48 仍 FROZEN）。

## 49. 本窗口绝不顺手执行

任务书 §54：即使 Verdict = GO，本窗口**不** stop 9000 / backup DB / tag image / build image / load image / migrate / deploy / restart / recreate / edit env。`AUTHORIZATION != EXECUTION`。本窗口裁定 GO_WITH_NON_BLOCKING_FINDINGS 后立即 STOP，交独立 Execution 窗口。

## 50. R1 最终五问

任务书 §56：无论报告多长，最后必须明确回答五问。

```text
1. 是否接受已经 consolidation 的 Merchant operator NOW-GATE evidence 作为当前正式证据？
   → YES。E3 provenance 完整（MERCHANT_OPERATOR_EVIDENCE，operator 在 Merchant 主机真实执行
     M-AUTH-01~21 + B2-01~05，含具体算子值非仅聊天总结），未被后续事实推翻；
     R1 本地独立交叉核实（R1-X1~X6）全部一致；E3 > E2 > E1。

2. 是否能正式证明 EXTERNAL_HEALTH_RESTART = NONE_DETECTED？
   → YES。B2 五层（Docker autoheal/watchtower/labels / systemd service+timer / cron /
     BT automatic trigger / XG-specific automation）全 NONE_DETECTED。
     BT manual restore capability 真实存在但 = EXPLICIT ADMIN ACTION 非 health callback，
     以 OPERATOR_CAUTION carry-forward。

3. 是否能正式证明 MERCHANT_CURRENT_REALITY = RE_FROZEN 且 NO MATERIAL DRIFT DETECTED？
   → YES。B3 Reality Matrix 13/13 MATCH（git=f453f44 / 9000=0028 / DB=0028 / ready=200 /
     JSONB 两列 jsonb / future objects 6 项 ABSENT / data scale 1/1725/0 /
     9000+9100 image=93094f0 shared / 9100=0003 / 9100 ready=200）。
     无 §29 任一 material drift 触发项；1698→1725 = NORMAL_BUSINESS_GROWTH。

4. 新的 Merchant evidence 是否没有推翻 M0~M11 / P-S01~P-S16 / PV-01~PV-17？
   → YES。reality matches approved model → runbook 起点假设成立；P-S01/P-S02/P-S08/P-S16
     不触发（actual 验证仍为 execution-time gate）；PV-01~17 仍足以验证；9100 freeze /
     0035 boundary 维持。

5. 是否已经具备真正打开 PRODUCTION_EXECUTION_ENTRY 的条件？
   → YES。B1/B2/B3 全 CLOSED，NEW_BLOCKER=NONE，runbook/stop/verification 仍有效，
     execution-time dynamic gates fail-closed 且 deferred。
```

五项全部 `YES` → `BLOCKER-2 = CLOSED` / `BLOCKER-3 = CLOSED` / `PRODUCTION_AUTHORIZATION = APPROVED / GO_WITH_NON_BLOCKING_FINDINGS`。立即停止。

---

## 51. 最终输出

```text
PRODUCTION_AUTHORIZATION_GO_WITH_NON_BLOCKING_FINDINGS
```

```text
BLOCKER-1 RELEASE_ENGINEERING_ARTIFACT_IDENTITY = CLOSED / INHERITED
BLOCKER-2 EXTERNAL_AUTOHEAL_WATCHDOG             = CLOSED
BLOCKER-3 MERCHANT_CURRENT_REALITY               = CLOSED

PRODUCTION_MIGRATION_AUTHORIZED = YES
PRODUCTION_EXECUTION_ENTRY      = OPEN
PRODUCTION_MIGRATION_EXECUTED   = NO
```

---

## 52. Git / Merchant Discipline

```text
DO NOT COMMIT
DO NOT PUSH
DO NOT MODIFY MERCHANT
DO NOT MODIFY M-AUTH（任务书 §45：READ M-AUTH / DO NOT MODIFY；本窗口未发现需 NO_GO 的事实错误）
DO NOT MIGRATE / RESTART / BUILD / TAG / BACKUP / EDIT ENV
未在 Merchant repository 写任何文件（本报告仅存于本地开发工作区）
```

## 53. 文档影响检查（AI 文档自治维护）

- 本轮唯一新增：本报告 `..._FOCUSED_PRODUCTION_AUTHORIZATION_R1.md`（R1_APPROVAL_REPORT）。
- **未修改** `..._FOCUSED_PRODUCTION_AUTHORIZATION.md`（任务书 §44：历史 NO_GO 保留为 HISTORICAL，不改成 GO；那是当时基于旧 evidence package 的正确历史决策）。
- **未修改** `..._MERCHANT_M_AUTH_READ_ONLY.md`（任务书 §45：READ M-AUTH / DO NOT MODIFY）。
- Design / Rehearsal / Rehearsal Approval / Production Authorization / Release Freeze / Release Manifest / S10-B 系列 / PRODUCTION_AUTHORIZATION 原始 NO_GO 结论**不受影响**。
- `CLAUDE.md` 治理状态：阶段 3A 的 P2/P3 优先级与 catch-up 链状态由后续窗口按需更新；本授权窗口不改动治理规则文件。
- 无其他活动文档结论因本轮而过期。

---

## 54. 工作区 Git 分类（任务书 §47）

结束前执行 `git status --short` / `git diff --name-only` / `git diff --stat`，分类 PRE_EXISTING / R1_APPROVAL_REPORT / UNKNOWN，要求 UNKNOWN=0。（实际命令输出见本窗口执行记录；分类如下。）

```text
PRE_EXISTING（S10-B release engineering + 前序 remediation 报告，均未提交，非本轮产生）:
  M  .env.production.example
  M  docker-compose.yml
  M  docs/config/ENV_VARIABLE_REFERENCE.md
  ?? docs/architecture/remediation/P2_M04_COORDINATED_CUTOVER_READINESS.md
  ?? docs/architecture/remediation/PRODUCTION_BASELINE_CATCHUP_0028_TO_0034_DESIGN.md
  ?? docs/architecture/remediation/PRODUCTION_BASELINE_CATCHUP_0028_TO_0034_DESIGN_APPROVAL.md
  ?? docs/architecture/remediation/PRODUCTION_BASELINE_CATCHUP_0028_TO_0034_FOCUSED_PRODUCTION_AUTHORIZATION.md
  ?? docs/architecture/remediation/PRODUCTION_BASELINE_CATCHUP_0028_TO_0034_ISOLATED_REHEARSAL.md
  ?? docs/architecture/remediation/PRODUCTION_BASELINE_CATCHUP_0028_TO_0034_MERCHANT_M_AUTH_READ_ONLY.md
  ?? docs/architecture/remediation/PRODUCTION_BASELINE_CATCHUP_0028_TO_0034_PRODUCTION_AUTHORIZATION.md
  ?? docs/architecture/remediation/PRODUCTION_BASELINE_CATCHUP_0028_TO_0034_REHEARSAL_APPROVAL.md
  ?? docs/architecture/remediation/PRODUCTION_BASELINE_CATCHUP_0028_TO_0034_RELEASE_MANIFEST.md
  ?? docs/architecture/remediation/PRODUCTION_BASELINE_CATCHUP_0028_TO_0034_RELEASE_PACKAGE_FREEZE.md
  ?? docs/architecture/remediation/PRODUCTION_SCHEMA_BASELINE_CATCHUP_0028_TO_0034_REALITY_AUDIT.md
  ?? docs/architecture/remediation/S10_B_9000_9100_IMAGE_IDENTITY_ISOLATION_APPROVAL.md
  ?? docs/architecture/remediation/S10_B_9000_9100_IMAGE_IDENTITY_ISOLATION_CORRECTION_APPROVAL.md
  ?? docs/architecture/remediation/S10_B_9000_9100_IMAGE_IDENTITY_ISOLATION_IMPLEMENTATION.md
  ?? scripts/release_9000_s10b.py
  ?? tests/test_s10_b_image_identity_isolation.py

R1_APPROVAL_REPORT（本轮新增）:
  ?? docs/architecture/remediation/PRODUCTION_BASELINE_CATCHUP_0028_TO_0034_FOCUSED_PRODUCTION_AUTHORIZATION_R1.md

UNKNOWN = 0
```

---

*Focused Production Authorization R1 窗口结束。仅执行本地只读 git 核实 + 报告阅读 + R1 独立交叉核实；未操作 Merchant，未修改 M-AUTH，未修改历史 FOCUSED authorization，未 commit/push，未迁移/构建/备份/改 env/restart。最终裁定 `PRODUCTION_AUTHORIZATION_GO_WITH_NON_BLOCKING_FINDINGS`：BLOCKER-1=CLOSED/INHERITED / BLOCKER-2=CLOSED / BLOCKER-3=CLOSED / PRODUCTION_MIGRATION_AUTHORIZED=YES / PRODUCTION_EXECUTION_ENTRY=OPEN / PRODUCTION_MIGRATION_EXECUTED=NO。立即停止。*
