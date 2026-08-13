# PRODUCTION-BASELINE-CATCHUP-0028-TO-0034 — Merchant M-AUTH Read-Only Evidence

> 窗口：`PRODUCTION-BASELINE-CATCHUP-0028-TO-0034 / MERCHANT-M-AUTH-READ-ONLY-EVIDENCE`
> 窗口性质：**READ-ONLY ONLY / NO MUTATION** — 绝对只读纪律（任务书 §2）。发现异常=记录，不是当场修复。
> 前序：`..._PRODUCTION_AUTHORIZATION.md`（NO_GO，BLOCKER-1~3）→ `..._RELEASE_PACKAGE_FREEZE.md`（BLOCKER-1 = CANDIDATE_RESOLVED）
> 日期：2026-08-12
> 职责：只关闭 BLOCKER-2（EXTERNAL_AUTOHEAL_WATCHDOG）与 BLOCKER-3（MERCHANT_CURRENT_REALITY）所需的生产只读证据采集。
>
> **EVIDENCE REFRESH（2026-08-12）**：本报告含两大部分——**PART I**（§1~§39，初始只读取证，历史记录）与 **PART II**（Operator Evidence Refresh / Evidence Consolidation，当前 now-gate 状态）。PART I 的历史结论 `M_AUTH_READ_ONLY_EVIDENCE_INCOMPLETE` **保留为 HISTORICAL**（当时 VibeCoding 无 Merchant 执行通道，是真实历史裁决）；PART I 之后有权限 operator 已在 Merchant 主机真实执行 M-AUTH-01~21 + B2-01~05，其证据已在 **PART II** 正式归并（Evidence Synchronization Gap 消除）。**当前 now-gate 状态以 PART II 为准**；PART I 中与之冲突的状态描述均为历史阶段记录（EVIDENCE_REFRESH，非历史篡改）。

---

## 1. Scope

本窗口唯一目标：通过生产只读命令包（M-AUTH-01~21）重新冻结 Merchant 当前生产现实，关闭 BLOCKER-2 / BLOCKER-3。

BLOCKER-1 已由 Release Package Freeze 形成 candidate closure，**本窗口不重新审批**：

```text
RELEASE_PACKAGE_FREEZE = READY
RELEASE_TREE           = a633b4860b818ab48fda5e22f39aa311eb96e9eb
APPLICATION_BASE       = 9db3f58
ALEMBIC_HEAD           = 0034
```

本窗口**不执行**：迁移、构建、tag、备份、env 修改、restart/recreate、commit、push、checkout、transfer artifact。

## 2. Governance State

```text
ISOLATED_REHEARSAL            = APPROVED_WITH_NON_BLOCKING_FINDINGS
PRODUCTION_AUTHORIZATION      = NO_GO（本窗口不修改）
PRODUCTION_MIGRATION_AUTHORIZED = NO
PRODUCTION_EXECUTION_ENTRY    = BLOCKED
BLOCKER-1                     = CANDIDATE_RESOLVED_BY_FREEZE（a633b48，不重审）
BLOCKER-2                     = OPEN（本窗口前）
BLOCKER-3                     = OPEN（本窗口前）
```

## 3. Safety Boundary

本窗口遵守任务书 §2 绝对只读纪律：允许 `git`（只读）、`docker ps/inspect`、`curl GET`、`psql SELECT/SHOW`、`alembic current/heads`、`systemctl list/show/cat`、`crontab -l`、`cat/grep/find/ps/df/du/stat/ls`；禁止一切 mutation。

**本窗口实际执行**：仅 3 项命令——本地 SSH 通道核查（无网络副作用）、公网 `curl GET https://merchant.xiaogaoai.cn/api/ready`（只读 GET）、工作区只读搜索。对本窗口而言保持 `NO PRODUCTION STATE MUTATION / NO BUSINESS DATA MUTATION / NO CONFIGURATION MUTATION / NO SERVICE LIFECYCLE MUTATION`——未对 Merchant 执行任何写/改/删/重启/迁移/构建/tag/备份/env 操作。

## 4. Merchant Host Identity / 可达性判定（决定性前提）

```text
PRODUCTION_DIR        = /www/wwwroot/XG_AI_System（Merchant 主机，Linux）
本机（VibeCoding 执行环境）= Windows 10 / e:\work\project\auto_wechat（开发工作区）
```

**本窗口最重要的前置事实：本机不存在到 Merchant 主机的只读执行通道。**

- `~/.ssh/`：仅有 `known_hosts`（含 `101.96.224.224` 历史主机指纹），**无 `config`、无任何私钥**（`id_*` 均不存在）。
- `ssh-add -l`：authentication agent 不可用。
- 工作区搜索：无 `.pem` / `id_rsa*` / `id_ed25519*` / `.ppk` / 部署密钥；docs 中无任何 `ssh user@host` / `scp` 连接命令或凭据。
- 本地不存在 `/www/wwwroot/XG_AI_System`（Windows 环境）。

```text
MERCHANT_HOST_ACCESS = MISSING
```

任务书 §39 明确：Merchant access missing → **不得猜** → `M_AUTH_READ_ONLY_EVIDENCE_INCOMPLETE`。

本窗口**未**尝试盲连生产主机（无凭据下的 SSH 尝试属于未授权探测，违反纪律且无意义）。也未全盘扫描生产端口。

## 5. M-AUTH-01 — Production Git Identity

```text
状态  = BLOCKED（MERCHANT_HOST_ACCESS = MISSING）
事实  = UNKNOWN
```

需要 `git rev-parse HEAD` / `git log`，仅可在 `/www/wwwroot/XG_AI_System` 内执行。本机无法执行。历史期望 `f453f44`，**不假定仍成立**。

## 6. M-AUTH-02 — Worktree Reality

```text
状态  = BLOCKED
事实  = UNKNOWN
```

需要 `git status --short` / `git diff` 确认 tracked/untracked drift。无法执行。

## 7. Protected Files

```text
状态  = BLOCKED
事实  = UNKNOWN（存在性未复核）
```

保护文件 `.env.production.local.bak.20260804_172603` / `milvus_export_full.jsonl` / `milvus_export_no_vec.jsonl` 的存在性与 mtime 需宿主 `stat`。无法执行。**未删除任何文件**。

## 8. M-AUTH-03 — Compose Service Topology

```text
状态  = BLOCKED
事实  = UNKNOWN
```

需要 `$DC config --services` / `$DC ps` 确认四服务拓扑（postgres / auto-wechat-api / auto-wechat-frontend / xg-douyin-ai-cs）及是否存在额外 worker/scheduler/autoheal/watchtower。无法执行。**生产 topology 侧新增 writer/service 无法排除**（CF-4 生产侧待确认项保持开放）。

## 9. M-AUTH-04 — Resolved Compose Image Contract

```text
状态  = BLOCKED
事实  = UNKNOWN
```

需要 `$DC config --images`。无法执行。`.env.production.local` 内容未读取（遵守 §35 secret 纪律，即使可读也只记 PRESENT/MISSING）。

## 10. M-AUTH-05 — 9000 Runtime Container Identity

```text
状态  = BLOCKED
事实  = UNKNOWN
```

需要 `docker inspect`（container_id / image / started / health / restart_count / restart_policy）。无法执行。

## 11. M-AUTH-06 — 9100 Runtime Container Identity

```text
状态  = BLOCKED
事实  = UNKNOWN
```

同上，9100 容器身份无法复核。

## 12. M-AUTH-07 — Shared Runtime Image Reality

```text
状态  = BLOCKED
事实  = UNKNOWN
```

9000/9100 是否仍共享 old runtime image（历史 `sha256:93094f0...`）无法复核。`PRODUCTION_RUNTIME_IMAGE_DRIFT` 无法排除亦无法确认。

## 13. M-AUTH-08 — Old Runtime Image Availability

```text
状态  = BLOCKED
事实  = UNKNOWN
```

rollback 依赖的旧 runtime image 是否仍在本机可引用（M-AUTH-08）无法复核。**rollback 保障无法在宿主侧确认**（CF-5 执行前置保持待确认）。

## 14. M-AUTH-09 — 9000 Alembic Application Head / Current

```text
状态  = BLOCKED（宿主侧）
事实  = UNKNOWN（容器内 alembic current/heads 无法执行）
```

历史期望 current=0028 / head=0028。宿主侧无法执行。**远程 /api/ready 提供了 DB revision 的等价独立证据（见 §15），但不替代容器内 app head 核查。**

## 15. M-AUTH-10 — 9000 Health / Ready（✅ 唯一远程独立证据）

本机通过**公网只读 GET**（非 127.0.0.1 直连）取得等价证据：

```text
GET https://merchant.xiaogaoai.cn/api/ready → HTTP 200
{
  "service": "auto_wechat",
  "status": "ok",
  "checks": [
    { "name": "backend",             "status": "pass", "backend": "postgresql" },
    { "name": "db_connect",          "status": "pass" },
    { "name": "database_name",       "status": "pass", "expected": "auto_wechat", "actual": "auto_wechat" },
    { "name": "alembic_revision",    "status": "pass", "expected": ["0028"], "actual": ["0028"] },
    { "name": "critical_tables",     "status": "pass", "tables": [douyin_leads=pass, sales_staff=pass] }
  ]
}

GET https://merchant.xiaogaoai.cn/api/health → HTTP 200 {"service":"auto_wechat","status":"ok"}
```

```text
9000_READY_REMOTE      = HTTP 200
9000_DB_BACKEND        = postgresql
9000_DB_NAME           = auto_wechat（expected=actual）✅
9000_ALEMBIC_REVISION  = expected [0028] / actual [0028] ✅（与历史期望一致）
9000_CRITICAL_TABLES   = PASS
```

说明：
- 该证据与历史期望一致（0028 仍在），是正信号；**但不等于完整 reality re-freeze**（§39：M-AUTH-10 只是 21 项之一）。
- 该端点为公网反代暴露路径，与任务书 §10 的 `127.0.0.1:9000` 直连不完全等价，证据等级为 `MERCHANT_READ_ONLY_CONFIG_VERIFIED`（远程），非宿主直连等级。

## 16. M-AUTH-11 — PostgreSQL Identity

```text
状态  = BLOCKED
事实  = UNKNOWN
```

需要容器内 psql（current_database / current_user / server_version / inet_server_addr / port）。无法执行。**生产 PG 实例身份（merchant.xiaogaoai.cn PG，区分 callback SQLite 实例）无法在本窗口宿主侧复核**；仅远程 /api/ready 显示 backend=postgresql + db=auto_wechat。

## 17. M-AUTH-12 — 9000 Alembic Revision Direct DB Evidence

```text
状态  = BLOCKED（宿主 psql）
事实  = UNKNOWN
```

需要 `SELECT version_num FROM alembic_version`。远程 /api/ready 的 `alembic_revision actual=[0028]` 是独立交叉证据（§15），但不替代宿主 psql 直查（§15 与 §12 的一致性核对无法进行）。

## 18. M-AUTH-13 — JSONB Physical Drift

```text
状态  = BLOCKED
事实  = UNKNOWN
```

`customer_profiles.confirmed_fields_json` / `inferred_fields_json` 物理类型是否仍为 jsonb（0029 幂等前提）无法复核。**0029 迁移前提未在宿主侧冻结**。

## 19. M-AUTH-14 — Future Schema Contamination

```text
状态  = BLOCKED
事实  = UNKNOWN
```

0030~0034 对象（daily_report_generations / ai_edit_material_analysis_executions / ai_preview_executions / compute_transactions.idempotency_key 等）是否已提前落入生产 DB 无法复核。`PHYSICAL_SCHEMA_DRIFT_SCOPE_CHANGED` 无法排除。

## 20. M-AUTH-15 — Critical Production Row Counts

```text
状态  = BLOCKED
事实  = UNKNOWN
```

cp / ct / drj 行数（历史 ≈1 / ≈1698 / 0）无法复核。rehearsal 前提（数据规模兼容）无法在宿主侧确认。

## 21. M-AUTH-16 — 9100 Alembic Reality

```text
状态  = BLOCKED
事实  = UNKNOWN
```

9100 DB 是否仍 0003（冻结合约）无法复核。`PRODUCTION_9100_BASELINE_DRIFT` 无法排除。

## 22. M-AUTH-17 — 9100 Ready / Health

```text
状态  = BLOCKED
事实  = UNKNOWN
```

本机无 9100 已知公网端点；任务书 §20 要求容器内/宿主侧 GET。为遵守"不做端口扫描、不探测未知端点"，**未**尝试推测 9100 公网路径。9100 就绪未核实。

## 23. M-AUTH-18 — Docker-level Autoheal / Watchtower Audit

```text
状态  = BLOCKED
事实  = UNKNOWN（compose 层历史结论仍有效，宿主层未复核）
```

需要 `docker ps -a` + label 审计。无法执行。**BLOCKER-2 生产侧仍 UNKNOWN**。

## 24. M-AUTH-19 — systemd / supervisor / Process Watchdog

```text
状态  = BLOCKED
事实  = UNKNOWN
```

需要 `systemctl list-*` / `ps -ef`。无法执行。未对生产 systemd 做任何 stop/start/restart。

## 25. M-AUTH-20 — Cron / Scheduled Automation

```text
状态  = BLOCKED
事实  = UNKNOWN
```

需要 `crontab -l` / `/etc/crontab` / `/etc/cron.d`。无法执行。生产是否有 cron 自动重启/redeploy 未知。

## 26. M-AUTH-21 — 宝塔 / Custom Watchdog Read-Only Search

```text
状态  = BLOCKED
事实  = UNKNOWN
```

需要 `/www/server/panel` 只读 grep。无法执行。

## 27. Autoheal 最终分类

```text
compose 层（历史，CONTAINER_CONFIG_VERIFIED @ 9db3f58 树）= NONE_DETECTED
生产层（宿主，M-AUTH-18/19/20/21 均 BLOCKED）            = UNKNOWN
```

按任务书 §25 三选一：**不满足 A**（NONE_DETECTED 需四类证据全无）、**不满足 B**（PRESENT_BUT_UNDERSTOOD 需列出 mechanism/trigger/target/control/verification）。因此分类为：

```text
EXTERNAL_HEALTH_RESTART = UNKNOWN_OR_UNCONTROLLABLE（截至本窗口）
→ BLOCKER-2 = REMAINS_OPEN
```

## 28. Production Writer Topology

```text
WRITE_ISOLATION_TOPOLOGY = NOT_VERIFIED（生产宿主侧）
```

代码层（9db3f58 树，`CODE_VERIFIED`）所有 9000 PG writer 均在 9000 进程内；但 M-AUTH-03/18/19/20/21 均无法执行，无法排除生产侧独立 worker / cron writer / sidecar / 外部本地脚本。`WRITE_ISOLATION_NEW_WRITER` 无法排除亦无法确认（CF-4 生产侧 EXECUTION_PREFLIGHT 待确认项保持开放）。

## 29. Historical vs Current Matrix

任务书 §26 要求**重新建立**，不得复制历史报告。本窗口仅能重建立以下事实（其余行 UNKNOWN）：

| Fact          | Historical          | Current                            | Match |
| ------------- | ------------------- | ---------------------------------- | ----- |
| Git HEAD      | f453f44             | UNKNOWN（宿主访问缺失）            | UNKNOWN |
| 9000 app head | 0028                | UNKNOWN（宿主容器内 alembic）      | UNKNOWN |
| 9000 DB       | 0028                | 0028（远程 /api/ready actual）     | **YES（远程）** |
| JSONB drift   | two columns jsonb   | UNKNOWN                            | UNKNOWN |
| Future objects| absent              | UNKNOWN                            | UNKNOWN |
| 9000 image    | old identity        | UNKNOWN                            | UNKNOWN |
| 9000 ready    | 200                 | 200（远程 /api/ready + /api/health）| **YES（远程）** |
| 9100 app head | 0003                | UNKNOWN                            | UNKNOWN |
| 9100 DB       | 0003                | UNKNOWN                            | UNKNOWN |
| 9100 image    | old identity        | UNKNOWN                            | UNKNOWN |
| 9100 ready    | healthy             | UNKNOWN                            | UNKNOWN |
| topology      | four services       | UNKNOWN                            | UNKNOWN |

**注意**：`9000 DB=0028` 与 `9000 ready=200` 两行经公网只读核实与历史一致，是正信号；但 12 行中 10 行 UNKNOWN，**不构成 §28 的 BLOCKER-3 closure 条件**。

## 30. Production Reality Drift 分类

```text
PRODUCTION_REALITY_DRIFT = NOT_CONFIRMED_AND_NOT_EXCLUDED
```

- 远程证据显示 9000 DB revision 仍为 0028、backend=postgresql、db=auto_wechat、critical tables pass，**未发现 drift 迹象**（无反向证据）。
- 但 git HEAD / image ID / JSONB / future objects / 9100 / topology / watchdog 全部 UNKNOWN——**不能据此宣称"与 f453f44 兼容"**（§27：不是任何数字变化才算 blocker，但 UNKNOWN 不等于 VERIFIED）。

## 31. BLOCKER-2 Status

```text
BLOCKER-2 = OPEN
EXTERNAL_AUTOHEAL_WATCHDOG = UNKNOWN_OR_UNCONTROLLABLE（生产宿主侧未取证）
```

依据：M-AUTH-18/19/20/21 全部 BLOCKED（宿主访问缺失）。compose 层 NONE_DETECTED 不足以下 A 类结论。不满足 §25 C 类之外的任何判定。

## 32. BLOCKER-3 Status

```text
BLOCKER-3 = OPEN
MERCHANT_CURRENT_REALITY = NOT RE-FROZEN
```

依据：§28 closure 条件要求 8 项核心现实匹配 approved model；本窗口仅能远程确认其中 2 项（9000 DB=0028、9000 ready=200），其余 6 项（git / app head / JSONB / future objects / 9100 / topology）UNKNOWN。**不满足 BLOCKER-3 = CANDIDATE_RESOLVED**。

## 33. Supplementary Storage

```text
状态  = BLOCKED
事实  = UNKNOWN
```

`df -h /` / `df -h /www` / `docker system df` 需宿主执行。磁盘容量、备份目的地容量、Docker disk usage 未复核（§40 storage gate 保持待确认）。未执行任何 `docker prune`。

## 34. Blocking Findings

```text
B-AUTH-1（决定性，本窗口前提）：MERCHANT_HOST_ACCESS = MISSING
  本机无 SSH 私钥 / config / agent / 凭据 / 部署密钥；/www/wwwroot/XG_AI_System 不在本机。
  → M-AUTH-01~09、11~21 共 19 项宿主命令全部 BLOCKED（10 项 hard gate 全 UNKNOWN）。
  → BLOCKER-2 / BLOCKER-3 无法在本窗口关闭。
  MINIMUM NEXT ACTION : 由运维/客户在 Merchant 主机执行只读命令包（见附录 A）并回填结果；
                        或由用户为本窗口提供受控 SSH 只读通道（仅授权任务书 §2 允许的只读命令）后续跑。
```

## 35. Non-Blocking Findings

```text
NB-AUTH-1  远程 /api/ready 显示 9000 DB revision = 0028、backend=postgresql、db=auto_wechat、
          critical tables PASS → 与历史期望一致，是正信号；但非完整 re-freeze（不抵消 BLOCKER-3 OPEN）。
NB-AUTH-2  本窗口未发现任何生产 drift 证据，也未发现任何生产异常；所有"未知"均为访问缺失所致，非观察到的问题。
NB-AUTH-3  未输出任何 .env 内容、密码、密钥（遵守 §35 secret 纪律）。
```

## 36. Evidence Levels

```text
MERCHANT_READ_ONLY_CONFIG_VERIFIED  = 9000 /api/ready + /api/health（公网只读，2026-08-12）
MERCHANT_READ_ONLY_RUNTIME_VERIFIED = NOT ACHIEVED（宿主 docker inspect 未执行）
MERCHANT_READ_ONLY_DB_VERIFIED      = NOT ACHIEVED（宿主 psql 未执行；仅远程 /ready 交叉）
MERCHANT_READ_ONLY_HOST_VERIFIED    = NOT ACHIEVED（git/systemd/cron/宝塔 未执行）
PRODUCTION_TARGET_RUNTIME_VERIFIED  = NOT APPLICABLE（目标未部署，本窗口不写）
```

## 37. Verdict

```text
M_AUTH_READ_ONLY_EVIDENCE_INCOMPLETE
```

依据（任务书 §39）：Merchant host access missing → critical facts（git HEAD / docker image / DB 直查 / JSONB / future objects / row counts / 9100 / watchdog / cron / 宝塔）**无法获得**；watchdog evidence 不足；DB evidence 仅远程部分。**不得猜** → 不写 COMPLETE，不写 DRIFT_DETECTED（无 drift 证据，仅无法核实）。

> **（HISTORICAL — PART I 初始只读取证裁决）** 该结论基于当时 VibeCoding 无 Merchant 执行通道的事实，是真实历史阶段记录，**不删除、不假装未发生**。PART I 之后有权限 operator 已在 Merchant 主机真实执行 M-AUTH-01~21 + B2-01~05 并回填证据，当前 now-gate 状态为 `CURRENT_M_AUTH_STATUS = COMPLETE`，见 **PART II §2M**。

## 38. Production Authorization Status

```text
BLOCKER-1 = CANDIDATE_RESOLVED_BY_FREEZE（a633b48，本窗口未重审）
BLOCKER-2 = OPEN
BLOCKER-3 = OPEN
M_AUTH_READ_ONLY_EVIDENCE = INCOMPLETE
PRODUCTION_AUTHORIZATION  = STILL NO_GO（本窗口不修改 NO_GO）
PRODUCTION_MIGRATION_AUTHORIZED = NO
PRODUCTION_EXECUTION_ENTRY      = BLOCKED
```

> **（HISTORICAL — PART I 当时状态）** operator evidence 归并后（见 **PART II §2M**）：`BLOCKER-2 = CANDIDATE_RESOLVED` / `BLOCKER-3 = CANDIDATE_RESOLVED` / `M_AUTH_READ_ONLY_EVIDENCE = COMPLETE`；`PRODUCTION_AUTHORIZATION = STILL NO_GO` 与 `PRODUCTION_MIGRATION_AUTHORIZED = NO` / `PRODUCTION_EXECUTION_ENTRY = BLOCKED` **不变**（本窗口不修改 NO_GO，正式 closure 留给下一 Focused Authorization R1）。

## 39. Next Stage

```text
下一阶段唯一 = PRODUCTION-BASELINE-CATCHUP-0028-TO-0034 / FOCUSED-PRODUCTION-AUTHORIZATION
前置 = 本窗口 BLOCKER-2 / BLOCKER-3 必须先关闭，关闭路径二选一：
  路径 A（推荐，符合原治理设计）：运维/客户在 Merchant 主机执行附录 A 只读命令包，回填结果 →
        由本窗口（或 Focused Authorization）按 §27/§28 判定 B2/B3。
  路径 B：用户为本窗口提供受控 SSH 只读通道（仅任务书 §2 允许命令），本窗口续跑 M-AUTH-01~21。
FOCUSED-PRODUCTION-AUTHORIZATION 只复核：BLOCKER-1 frozen artifact / BLOCKER-2 watchdog /
  BLOCKER-3 current reality；不重跑完整 Production Authorization，也不重跑 rehearsal。
```

本窗口**不得**自行进入：Focused Production Authorization / Production Execution / 0035 / P2 / 9100 upgrade / P3a / P3b / RB-10（任务书 §43）。

> 本报告经 **PART II** Evidence Consolidation 后，下一阶段唯一窗口 = **FOCUSED-PRODUCTION-AUTHORIZATION-R1**（见 **PART II §2N**）。

---

# 附录 A — 运维/客户可执行的 M-AUTH-01~21 只读命令包（独立审查硬化版）

## A.0 独立审查与硬化记录

> 独立审查结论（2026-08-12）：`M-AUTH COMMAND PACKAGE = SAFE_AFTER_MINOR_HARDENING`
>
> ```text
> PRODUCTION MUTATION RISK        = NO BLOCKING FINDING
> SECRET EXPOSURE RISK            = NEEDS M-AUTH-18 / M-AUTH-20 HARDENING（已按修正二/三硬化）
> BLOCKER-3 EVIDENCE COMPLETENESS = RECOMMEND M-AUTH-14B（已新增）
> WATCHDOG EVIDENCE COMPLETENESS  = RECOMMEND SYSTEMD TIMER CHECK（已新增）
> ```

审查确认：高风险类别（`git pull/reset/clean/checkout`、`docker build/tag/pull/restart`、`compose up/down/restart`、`alembic upgrade/downgrade`、SQL write/DDL、`systemctl start/stop/restart`、cron 修改、文件写入/删除、`pg_dump/restore`）在本命令包中**均为 NONE**。DB 部分全部为 `SELECT / information_schema / to_regclass / count`；Docker 部分为 `ps / inspect / image inspect / compose config|ps|exec`；`compose exec` 仅创建临时 exec process，不 recreate/restart 容器，且 Alembic 已设 `PYTHONDONTWRITEBYTECODE=1`。

本命令包按审查意见应用硬化：

```text
修正一  GIT_OPTIONAL_LOCKS=0：禁止 git status/diff 刷新 index/stat cache（取证不扰动工作区元数据）
修正二  M-AUTH-18：只输出 supervision 相关 label key，不打印完整 labels JSON（防 metadata 泄露面）
修正三  M-AUTH-20：只输出 cron 匹配行号与相关文件，不输出 cron 内容（防 secret 泄露）
修正四  新增 M-AUTH-14B：检查 0030 index/constraint（uk_compute_transactions_merchant_idempotency 等）
补充    M-AUTH-10/17 加 --max-time 防挂起；M-AUTH-17 增加容器内 fallback；M-AUTH-19 增加 systemd timers
```

以下命令供**有权限的运维/客户**在 Merchant 主机（`/www/wwwroot/XG_AI_System`）执行，全部为任务书 §2 允许的只读命令。执行后请把各节输出回填本报告对应小节。

```bash
# 从生产目录开始
cd /www/wwwroot/XG_AI_System || exit 1

# 禁止 git 刷新 index/stat cache（取证不扰动工作区元数据）
export GIT_OPTIONAL_LOCKS=0

DC="docker compose --env-file .env.production.local -f docker-compose.yml"

echo "===== M-AUTH-01 git identity ====="
git rev-parse HEAD; git branch --show-current; git log -5 --oneline --decorate

echo "===== M-AUTH-02 worktree ====="
git status --short; git diff --name-only; git diff --stat
for f in .env.production.local.bak.20260804_172603 milvus_export_full.jsonl milvus_export_no_vec.jsonl; do
  [ -e "$f" ] && stat -c '%n | size=%s | mtime=%y' "$f" || echo "$f | NOT_PRESENT"
done

echo "===== M-AUTH-03 compose topology ====="
$DC config --services; $DC ps

echo "===== M-AUTH-04 compose images ====="
$DC config --images

echo "===== M-AUTH-05 9000 runtime ====="
C9000="$($DC ps -q auto-wechat-api)"; echo "container_id=$C9000"
docker inspect --format 'name={{.Name}} image={{.Image}} started={{.State.StartedAt}} status={{.State.Status}} health={{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}} restart_count={{.RestartCount}} restart_policy={{.HostConfig.RestartPolicy.Name}}' "$C9000"

echo "===== M-AUTH-06 9100 runtime ====="
C9100="$($DC ps -q xg-douyin-ai-cs)"; echo "container_id=$C9100"
docker inspect --format 'name={{.Name}} image={{.Image}} started={{.State.StartedAt}} status={{.State.Status}} health={{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}} restart_count={{.RestartCount}} restart_policy={{.HostConfig.RestartPolicy.Name}}' "$C9100"

echo "===== M-AUTH-07 image relationship ====="
I9000="$(docker inspect --format '{{.Image}}' "$C9000")"; I9100="$(docker inspect --format '{{.Image}}' "$C9100")"
echo "9000_image_id=$I9000"; echo "9100_image_id=$I9100"
[ "$I9000" = "$I9100" ] && echo "CURRENT_RUNTIME_SHARED_IMAGE=YES" || echo "CURRENT_RUNTIME_SHARED_IMAGE=NO"

echo "===== M-AUTH-08 image availability ====="
docker image inspect "$I9000" --format 'id={{.Id}} created={{.Created}} tags={{json .RepoTags}} digests={{json .RepoDigests}}'

echo "===== M-AUTH-09 9000 alembic ====="
$DC exec -T auto-wechat-api sh -lc 'set -eu; cd /workspace; export PYTHONPATH=/workspace; export PYTHONDONTWRITEBYTECODE=1; CFG=/workspace/migrations/postgres/auto_wechat/alembic.ini; echo "--- current ---"; python -m alembic -c "$CFG" current; echo "--- heads ---"; python -m alembic -c "$CFG" heads'

echo "===== M-AUTH-10 9000 endpoints ====="
curl --max-time 10 -sS -i http://127.0.0.1:9000/health || true; echo
curl --max-time 10 -sS -i http://127.0.0.1:9000/ready || true; echo

echo "===== M-AUTH-11 postgres identity ====="
$DC exec -T postgres sh -lc 'psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atc "SELECT current_database(), current_user, current_setting('\''server_version'\''), inet_server_addr(), inet_server_port();"'

echo "===== M-AUTH-12 alembic_version ====="
$DC exec -T postgres sh -lc 'psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atc "SELECT version_num FROM alembic_version;"'

echo "===== M-AUTH-13 JSONB drift ====="
$DC exec -T postgres sh -lc 'psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -P pager=off -c "SELECT column_name, data_type, udt_name, is_nullable FROM information_schema.columns WHERE table_schema='\''public'\'' AND table_name='\''customer_profiles'\'' AND column_name IN ('\''confirmed_fields_json'\'','\''inferred_fields_json'\'') ORDER BY column_name;"'

echo "===== M-AUTH-14 future objects ====="
$DC exec -T postgres sh -lc 'psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -P pager=off -c "SELECT to_regclass('\''public.daily_report_generations'\'') AS daily_report_generations, to_regclass('\''public.ai_edit_material_analysis_executions'\'') AS ai_edit_material_analysis_executions, to_regclass('\''public.ai_preview_executions'\'') AS ai_preview_executions; SELECT table_name, column_name FROM information_schema.columns WHERE table_schema='\''public'\'' AND ((table_name='\''compute_transactions'\'' AND column_name IN ('\''idempotency_key'\'','\''payload_evidence'\'')) OR (table_name='\''daily_report_jobs'\'' AND column_name='\''current_generation_id'\'')) ORDER BY table_name,column_name;"'

echo "===== M-AUTH-14B future index/constraint evidence ====="
$DC exec -T postgres sh -lc '
psql -v ON_ERROR_STOP=1 \
  -U "$POSTGRES_USER" \
  -d "$POSTGRES_DB" \
  -P pager=off \
  -c "
SELECT
  schemaname,
  tablename,
  indexname
FROM pg_indexes
WHERE schemaname='\''public'\''
  AND (
    indexname='\''uk_compute_transactions_merchant_idempotency'\''
    OR indexname ILIKE '\''%idempotency%'\''
  )
ORDER BY tablename,indexname;

SELECT
  tc.table_name,
  tc.constraint_name,
  tc.constraint_type
FROM information_schema.table_constraints tc
WHERE tc.table_schema='\''public'\''
  AND tc.table_name IN (
    '\''compute_transactions'\'',
    '\''daily_report_jobs'\'',
    '\''daily_report_generations'\'',
    '\''ai_edit_material_analysis_executions'\'',
    '\''ai_preview_executions'\''
  )
  AND (
    tc.constraint_name ILIKE '\''%idempotency%'\''
    OR tc.constraint_name ILIKE '\''%generation%'\''
    OR tc.constraint_name ILIKE '\''%preview%'\''
    OR tc.constraint_name ILIKE '\''%material_analysis%'\''
  )
ORDER BY tc.table_name,tc.constraint_name;
"
'
# 判断：与 9db3f58 migration 定义交叉核对——若 revision marker 仍 0028 但上述 UK index/constraint 已提前存在
# → PHYSICAL_SCHEMA_DRIFT_SCOPE_CHANGED = YES（BLOCKER-3 OPEN）

echo "===== M-AUTH-15 row counts ====="
$DC exec -T postgres sh -lc 'psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -P pager=off -c "SELECT '\''customer_profiles'\'' AS table_name, count(*) AS rows FROM customer_profiles UNION ALL SELECT '\''compute_transactions'\'', count(*) FROM compute_transactions UNION ALL SELECT '\''daily_report_jobs'\'', count(*) FROM daily_report_jobs;"'

echo "===== M-AUTH-16 9100 alembic ====="
$DC exec -T xg-douyin-ai-cs sh -lc 'set -eu; cd /workspace; export PYTHONPATH=/workspace; export PYTHONDONTWRITEBYTECODE=1; CFG=/workspace/migrations/postgres/xg_douyin_ai_cs/alembic.ini; echo "--- current ---"; python -m alembic -c "$CFG" current; echo "--- heads ---"; python -m alembic -c "$CFG" heads'

echo "===== M-AUTH-17 9100 ready ====="

echo "--- host endpoint ---"
curl --max-time 10 -sS -i http://127.0.0.1:9100/health || true
echo
curl --max-time 10 -sS -i http://127.0.0.1:9100/ready || true
echo

echo "--- container-local endpoint ---"
$DC exec -T xg-douyin-ai-cs sh -lc '
curl --max-time 10 -sS -i http://127.0.0.1:9100/ready
' || true
# 若容器内无 curl，记录 CMD_UNAVAILABLE，不安装

echo "===== M-AUTH-18 docker supervision ====="

# 只输出名称/镜像/状态，不打印完整 labels（labels 可能含任意 metadata，避免信息泄露面）
docker ps -a \
  --format 'table {{.Names}}\t{{.Image}}\t{{.Status}}'

echo "--- possible supervision containers ---"
docker ps -a \
  --format '{{.Names}}|{{.Image}}' \
  | grep -Ei 'autoheal|watchtower|watchdog|portainer|ouroboros' \
  || true

C9000="$($DC ps -q auto-wechat-api)"

echo "--- 9000 supervision-related label keys ---"
docker inspect "$C9000" \
  --format '{{range $k,$v := .Config.Labels}}{{if or (eq $k "autoheal") (eq $k "com.centurylinklabs.watchtower.enable")}}{{$k}}={{$v}}{{println}}{{end}}{{end}}'

echo "===== M-AUTH-19 system services ====="
systemctl list-unit-files --type=service --no-pager | grep -Ei 'docker|xg|wechat|auto.?wechat|douyin|watch|supervisor|bt|panel' || true
systemctl list-units --type=service --all --no-pager | grep -Ei 'xg|wechat|auto.?wechat|douyin|watch|supervisor|bt|panel' || true
ps -ef | grep -Ei 'autoheal|watchtower|watchdog|supervisord|docker compose|XG_AI_System|auto-wechat-api' | grep -v grep || true

echo "--- relevant systemd timers ---"
systemctl list-timers --all --no-pager \
  | grep -Ei 'xg|wechat|auto.?wechat|douyin|watch|docker|bt|panel' \
  || true
# 命中可疑 timer 时，只读 systemctl cat/show <timer|service>，不 disable

echo "===== M-AUTH-20 cron ====="

# 只输出匹配行号与相关文件，不输出 cron 内容（cron 可能含 token/密码/access-key）
PATTERN='XG_AI_System|auto-wechat-api|xg-auto-wechat-api|docker compose|docker restart|docker start|9000|xg-ai-system'

echo "--- root crontab relevant match locations ---"
crontab -l 2>/dev/null | grep -niE "$PATTERN" | awk -F: '{print "MATCH_LINE="$1}' || true

echo "--- /etc/crontab relevant match locations ---"
grep -niE "$PATTERN" /etc/crontab 2>/dev/null | awk -F: '{print "MATCH_LINE="$1}' || true

echo "--- /etc/cron.d relevant files ---"
grep -RIlE "$PATTERN" /etc/cron.d 2>/dev/null || true

echo "===== M-AUTH-21 BT/custom automation ====="
timeout 20s grep -RIlE 'XG_AI_System|auto-wechat-api|xg-auto-wechat-api|docker compose|docker restart|9000/ready' /www/server/panel/data /www/server/panel/script /etc/systemd/system 2>/dev/null | head -100 || true

echo "===== supplementary storage ====="
df -h /; df -h /www 2>/dev/null || true; docker system df
```

**命令包安全边界（独立审查确认的准确表述，转发给执行方）**：

```text
NO PRODUCTION STATE MUTATION
NO BUSINESS DATA MUTATION
NO CONFIGURATION MUTATION
NO SERVICE LIFECYCLE MUTATION
```

不写"物理层绝对没有任何 write"：`curl GET` 可能增加 access log、`psql SELECT` 可能更新统计/活动视图、`docker compose exec` 会创建临时 exec process——但这些均不属于上述四类 mutation，不构成生产变更。

执行方约定：
- **不要**修改任何文件、不重启/停止/迁移/删除/构建/tag。
- 输出中如包含数据库密码/密钥/token，请打码后回填；本报告只记录 PRESENT/MISSING 与身份事实。
- M-AUTH-20 命中 `MATCH_LINE` 或 `/etc/cron.d/xxx` 时，请在服务器本地查看对应行，只回填安全摘要（如 `file=... behavior=每天03:00执行docker compose restart ... secret_redacted=yes`），**不要把整份 cron 原样发回**。
- 若某条命令不可用或路径不存在（如容器内无 curl），记录 `CMD_UNAVAILABLE` 或 `PATH_NOT_PRESENT`，**不要**视为错误、不安装、不跳过其它命令。

---

# 附录 B — 文档影响检查（AI 文档自治维护）

- 本轮唯一新增：本报告（`..._MERCHANT_M_AUTH_READ_ONLY.md`）。未修改任何活动治理文档（CLAUDE.md / AGENTS.md / docs/ai 01~05 / Reality Map / 既有 remediation 报告）。
- `PRODUCTION_BASELINE_CATCHUP_0028_TO_0034_PRODUCTION_AUTHORIZATION.md` 的 NO_GO 结论**未改变**（BLOCKER-2/3 仍 OPEN，本窗口未产生与之矛盾的事实）。
- 无其他活动文档结论因本轮而过期。

# 附录 C — Git / Production Discipline

```text
DO NOT COMMIT
DO NOT PUSH
DO NOT MODIFY MERCHANT
DO NOT MIGRATE / RESTART / BUILD / TAG / BACKUP / EDIT ENV
未在 Merchant repository 写任何文件（本报告仅存于本地开发工作区）
```

---

*M-AUTH Read-Only Evidence 窗口结束。仅执行公网只读 GET 与本地只读核查；未操作 Merchant，未 commit/push。最终裁定 `M_AUTH_READ_ONLY_EVIDENCE_INCOMPLETE`，BLOCKER-2 / BLOCKER-3 保持 OPEN。*

---

# PART II — Operator Evidence Refresh / Evidence Consolidation（E3 · NOW-GATE）

> 窗口：`PRODUCTION-BASELINE-CATCHUP-0028-TO-0034 / MERCHANT-M-AUTH-EVIDENCE-CONSOLIDATION`
> 窗口性质：**EVIDENCE CONSOLIDATION / READ-ONLY** — 只归并不取证、不审批。
> 日期：2026-08-12
> 职责：把 PART I 之后、由**有权限 operator 在 Merchant 主机真实执行**的 M-AUTH-01~21 + M-AUTH-B2-01~05 只读证据，正式、可追溯地归并到本治理报告，消除 Evidence Synchronization Gap。
> **PART I 的历史结论（`M_AUTH_READ_ONLY_EVIDENCE_INCOMPLETE`）保留为 HISTORICAL 阶段记录，不由 PART II 删除或改写；当前 now-gate 状态以本 PART II 为准。**

## 2A. Evidence Source Hierarchy（E1 / E2 / E3）

```text
E1  EARLIER_HISTORICAL    = M1/M2/M3/M4 historical reality（仅作比较基线，非 now-gate）
E2  INITIAL_M_AUTH_REPORT = PART I（本文件 §1~§39）：
                            MERCHANT_HOST_ACCESS = MISSING
                            M_AUTH_READ_ONLY_EVIDENCE = INCOMPLETE（当时真实历史结论，保留）
E3  OPERATOR_EVIDENCE     = 有权限 operator 在 Merchant 主机 /www/wwwroot/XG_AI_System
                            真实执行 M-AUTH-01~21 + M-AUTH-B2-01~05 的输出（当前最重要 now-gate evidence）
```

## 2B. Operator Execution Event / Provenance（§42）

```text
EXECUTOR          = 有权限 operator（非本 VibeCoding 窗口；本窗口未 SSH、未执行任何生产命令）
EXECUTION_DIR     = /www/wwwroot/XG_AI_System（Merchant 主机，Linux）
COMMAND PACKAGE   = PART I 附录 A（独立审查 SAFE_AFTER_MINOR_HARDENING）
EVIDENCE SOURCE   = operator 经本 Consolidation 窗口传入的取证结果（含具体算子值，非仅聊天总结）
CROSS-CHECK       = 本地可核实项全部一致（已执行）：
                    f453f44e6a70de3eb5fa8f808cf4b6a9d72ea6c1 在 git 历史（生产已知 HEAD）
                    uk_return_visit_runs_idempotency_key 属 0011 既有索引（非 0030 污染）
                    uk_compute_transactions_merchant_idempotency 属 0030 未来目标（生产应 ABSENT）
                    0034 migration 存在；本地 HEAD=36fe68a（含 0035，故 target 为 9db3f58，不影响本窗口）
PROVENANCE LABEL = MERCHANT_OPERATOR_EVIDENCE
                    （不得写 "VibeCoding personally SSH verified" —— 执行人是 operator/user，不是该窗口）
```

## 2C. 阶段演进记录（EVIDENCE_REFRESH，非历史篡改，§4/§33）

```text
INITIAL_STATE : M_AUTH_READ_ONLY_EVIDENCE = INCOMPLETE
               （PART I 当时 VibeCoding 无 Merchant 执行通道 → 合法 BLOCKED → INCOMPLETE）
LATER_EVENT   : authorized operator 在 Merchant 主机执行硬化后的 M-AUTH 命令包
               （M-AUTH-01~21 + B2-01~05）
CURRENT_STATE : operator evidence 已接收并正式归并
               → M_AUTH_READ_ONLY_EVIDENCE = COMPLETE / CURRENT_M_AUTH_STATUS = COMPLETE
```

## 2D. Consolidated M-AUTH-01~21 Operator Facts（NOW-GATE）

```text
M-AUTH-01  Git Identity
           PRODUCTION_GIT_HEAD = f453f44e6a70de3eb5fa8f808cf4b6a9d72ea6c1
           BRANCH = master
           tracked worktree 无新 diff；worktree 仅保留此前已知的三个 production-only untracked 文件
M-AUTH-02  Worktree Reality
           tracked clean（无 tracked drift）
           保护文件 .env.production.local.bak.20260804_172603 / milvus_export_full.jsonl /
           milvus_export_no_vec.jsonl = PRESENT / PROTECTED / NOT TRACKED
           → 继续冻结：NO git clean / NO destructive reset
M-AUTH-03  Compose Service Topology（§10）
           XG_AI_System 服务 = postgres / xg-douyin-ai-cs / auto-wechat-api / auto-wechat-frontend
           注意：Merchant 主机存在其他项目容器（knowledge-train / used-car / car-project ...）
           → 不得误判为 XG_AI_System compose topology drift
M-AUTH-04  Resolved Compose Image Contract
           解析 image 与 S10-B per-service env 化契约一致（AUTO_WECHAT_API_IMAGE / XG_DOUYIN_AI_CS_IMAGE）
           .env.production.local 值未读取（secret 纪律，只记 PRESENT/MISSING）
M-AUTH-05  9000 Runtime Container Identity（§11）
           9000_CONTAINER_ID = a4421a...
           9000_RUNTIME_IMAGE_ID = sha256:93094f0a02ba3a4570160ce90625cb80fdec85076046fc314f5fe407add36c68
           health = healthy / restart_count = 0 / restart_policy = unless-stopped
           ROLLBACK_RUNTIME_IMAGE_AVAILABLE = YES
M-AUTH-06  9100 Runtime Container Identity（§12）
           9100_CONTAINER_ID = 49548f...
           9100_RUNTIME_IMAGE_ID = sha256:93094f0a02ba3a4570160ce90625cb80fdec85076046fc314f5fe407add36c68
           health = healthy / restart_count = 0 / restart_policy = unless-stopped
M-AUTH-07  Shared Runtime Image Reality
           CURRENT_RUNTIME_SHARED_IMAGE = YES
           （now-gate Merchant docker inspect 事实，不再以历史 M3 作为唯一依据）
M-AUTH-08  Old Runtime Image Availability
           ROLLBACK_RUNTIME_IMAGE_AVAILABLE = YES（93094f0 本机可引用）
M-AUTH-09  9000 Alembic Application Head / Current（§13）
           9000 APP CURRENT = 0028 / 9000 APP HEAD = 0028
M-AUTH-10  9000 Health / Ready（§13）
           /health = 200 / /ready = 200
           expected revision = [0028] / actual revision = [0028]
M-AUTH-11  PostgreSQL Identity（§14）
           database = auto_wechat / user = xgairoot / PostgreSQL = 16.14
           （secret 不披露）
M-AUTH-12  Alembic Revision Direct DB Evidence
           SELECT version_num FROM alembic_version → 0028
M-AUTH-13  JSONB Physical Drift（§15）
           customer_profiles.confirmed_fields_json = jsonb
           customer_profiles.inferred_fields_json  = jsonb
           （与 rehearsal 输入模型一致）
M-AUTH-14  Future Schema Contamination（§16）
           daily_report_generations = ABSENT
           ai_edit_material_analysis_executions = ABSENT
           ai_preview_executions = ABSENT
           compute_transactions.idempotency_key = ABSENT
           compute_transactions.payload_evidence = ABSENT
           daily_report_jobs.current_generation_id = ABSENT
           → PHYSICAL_SCHEMA_DRIFT_SCOPE = 0029_JSONB_TYPE_AHEAD_ONLY
           → 当前没有 evidence 表明 drift 扩大
M-AUTH-14B Future Index / Constraint Evidence（§17）
           found  : uk_return_visit_runs_idempotency_key（0011 既有索引）
           NOT    : uk_compute_transactions_merchant_idempotency
           target migration 相关 constraints 查询 = 0 rows
           → 非 0030 contamination
           → FUTURE_0030_TARGET_SCHEMA_CONTAMINATION = NONE_DETECTED
M-AUTH-15  Critical Production Row Counts（§18）
           customer_profiles = 1
           compute_transactions = 1725
           daily_report_jobs = 0
M-AUTH-16  9100 Alembic Reality（§19）
           9100 APP CURRENT = 0003 / 9100 APP HEAD = 0003
M-AUTH-17  9100 Ready / Health（§19）
           /health = 200 / /ready = 200
           Milvus : connected = true / collection_exists = true / schema_match = true / query_ok = true
           容器内 curl = CMD_UNAVAILABLE / NON_BLOCKING（host endpoint 已真实通过）
M-AUTH-18  Docker-level Autoheal / Watchtower（§21）
           autoheal container = NONE_DETECTED
           watchtower container = NONE_DETECTED
           watchdog deployment container = NONE_DETECTED
           9000 autoheal label = NONE / 9000 watchtower enable label = NONE
           （服务器存在其他普通容器 ≠ 项目 lifecycle 守护）
M-AUTH-19  systemd / supervisor / Process Watchdog（§22）
           XG_AI_System-specific watchdog service = NONE_DETECTED
           auto-wechat lifecycle service = NONE_DETECTED
           relevant systemd timer = NONE_DETECTED
           观察到 [watchdogd]：基于进程形态解释为 kernel watchdog thread / 非项目 lifecycle evidence
           （只作形态解释，不作为唯一 closure 依据）
M-AUTH-20  Cron / Scheduled Automation（§23）
           root crontab relevant lifecycle match = NONE
           /etc/crontab relevant lifecycle match = NONE
           /etc/cron.d relevant lifecycle match = NONE
M-AUTH-21  宝塔 / Custom Watchdog Read-Only Search（§24）
           命中：/www/server/panel/data/dir_history.json
                 /www/server/panel/script/docker_compose_backup.py
                 /www/server/panel/script/docker_compose_restore.py
           不得简单写 "BT automation found" —— 语义分类见 B2-01~05（§2I）
```

## 2E. Production Data Scale Refresh（§18/§44）

```text
1698 = historical M2 count（Reality Audit 时期）
1725 = current M-AUTH operator count（now-gate）
```

1698→1725 **不是** production drift；正确分类为 **NORMAL_BUSINESS_DATA_GROWTH**（schema / preconditions 未改变，且 §2D 全部 future objects 仍 ABSENT、JSONB drift 仍限定为 0029 两列）。

## 2F. BLOCKER-3 Reality Matrix（§20）

| Fact | Approved expectation | Operator evidence | Result |
| --- | --- | --- | --- |
| Git HEAD | f453f44 | f453f44 | MATCH |
| tracked worktree | no tracked drift | none | MATCH |
| 9000 app | 0028 | 0028 | MATCH |
| 9000 DB | 0028 | 0028 | MATCH |
| 9000 ready | 200 | 200 | MATCH |
| JSONB drift | two columns | two columns | MATCH |
| future objects | absent | absent | MATCH |
| data scale | compatible | 1/1725/0 | MATCH |
| 9000 image | old runtime | 93094f0 | MATCH |
| 9100 image | same old runtime | 93094f0 | MATCH |
| 9100 app | 0003 | 0003 | MATCH |
| 9100 DB | 0003 | 0003 | MATCH |
| 9100 ready | healthy | 200 | MATCH |

```text
MERCHANT_CURRENT_REALITY = RE_FROZEN
PRODUCTION_REALITY_DRIFT = NO MATERIAL DRIFT DETECTED
BLOCKER-3                = CANDIDATE_RESOLVED（正式 CLOSED 留给下一 Focused Authorization R1）
```

## 2G. BLOCKER-2 Evidence Matrix（§31）

| Layer | Evidence | Result |
| --- | --- | --- |
| Docker autoheal | container search | NONE_DETECTED |
| Watchtower | container search | NONE_DETECTED |
| Docker labels | 9000 relevant keys | NONE |
| systemd | services | NONE_DETECTED |
| systemd timer | timers | NONE_DETECTED |
| cron | root/etc/cron.d | NONE_DETECTED |
| BT scripts | backup/restore capability | PRESENT |
| BT trigger | composeMod explicit action | MANUAL/ADMIN |
| BT schedule | panel data search | NONE_DETECTED |
| project automation | XG-specific search | NONE_DETECTED |

```text
EXTERNAL_HEALTH_RESTART = NONE_DETECTED
BLOCKER-2               = CANDIDATE_RESOLVED（正式 CLOSED 留给下一 Focused Authorization R1）
```

## 2H. B2-01~05 Consolidation（§24~§30）

```text
B2-01  Backup Script Classification
       docker_compose_backup.py = Compose backup capability
       （可 copy project / backup volume / create tar / write BT backup metadata）
       current evidence 不显示 health-triggered restart / automatic autoheal
       → BT_COMPOSE_BACKUP = ADMIN_BACKUP_CAPABILITY
B2-01  Restore Script Classification
       docker_compose_restore.py 确实具备 docker-compose stop + docker-compose up -d 能力
       → BT_COMPOSE_RESTORE_CAN_CHANGE_SERVICE_LIFECYCLE = YES
       → 但 CAPABILITY != AUTOMATIC_TRIGGER
B2-02  Caller Evidence
       真实 caller = /www/server/panel/mod/project/docker/composeMod.py
       → 无 systemd/cron 直接 caller evidence
B2-04  Caller Context
       Backup  : compose method 接收 path / name → 验证输入 → 构造 backup command
                 → panelTask.bt_task().create_task("compose项目备份任务", ...)
       Restore : compose_restore_config(get) → 要求 backup_id → 查 backup record
                 → 检查 backup file → 构造 restore command
                 → panelTask.bt_task().create_task("compose项目恢复任务", ...)
       → BT_COMPOSE_BACKUP_RESTORE_TRIGGER = EXPLICIT ADMIN/API ACTION
       → NOT HEALTH_TRIGGER_CALLBACK
B2-05  Scheduled Automation
       搜索 /www/server/panel/data（docker_compose_backup / docker_compose_restore /
       compose_backup / compose_restore）→ NO OUTPUT
       → BT_SCHEDULED_COMPOSE_BACKUP_RESTORE = NONE_DETECTED
B2-03  Project-specific BT Automation
       针对 XG_AI_System / xg-auto-wechat-api / auto-wechat-api
       搜索 /www/server/panel/script + /www/server/panel/data + /etc/systemd/system + /etc/cron.d
       唯一命中 /www/server/panel/data/dir_history.json
       → PROJECT_SPECIFIC_BT_LIFECYCLE_AUTOMATION = NONE_DETECTED
       dir_history.json = HISTORY / METADATA，不是执行器
```

## 2I. Operator Caution（§32，保留）

```text
OPERATOR_CAUTION:
  During production maintenance（M1~M11）,
  DO NOT manually trigger BT Compose: Restore / Start / Restart / Recreate
  for XG_AI_System unless explicitly required by approved runbook.
  尤其 BT Compose Restore（它真实具有 stop + up -d 能力）。
  这是 OPERATOR_CONTROL，不是 blocker。
```

## 2J. Evidence Completeness Matrix（§45）

```text
M-AUTH-01  COMPLETE   git identity（f453f44 / master / tracked clean）
M-AUTH-02  COMPLETE   worktree（无 tracked drift；3 保护文件 PRESENT）
M-AUTH-03  COMPLETE   compose topology（4 服务；他项目容器非 drift）
M-AUTH-04  COMPLETE   compose images（env 化契约一致；.env 值未读）
M-AUTH-05  COMPLETE   9000 runtime（a4421a... / 93094f0 / healthy / 0 / unless-stopped）
M-AUTH-06  COMPLETE   9100 runtime（49548f... / 93094f0 / healthy / 0 / unless-stopped）
M-AUTH-07  COMPLETE   shared image = YES
M-AUTH-08  COMPLETE   rollback image available = YES
M-AUTH-09  COMPLETE   9000 alembic app = 0028 / 0028
M-AUTH-10  COMPLETE   9000 endpoints = 200 / 200（expected=actual=0028）
M-AUTH-11  COMPLETE   postgres identity = auto_wechat / xgairoot / 16.14
M-AUTH-12  COMPLETE   alembic_version = 0028
M-AUTH-13  COMPLETE   JSONB drift = 两列 jsonb
M-AUTH-14  COMPLETE   future objects = ABSENT（6 项）
M-AUTH-14B COMPLETE   index/constraint = uk_return_visit...（0011）/ uk_compute_... NOT / target 0 rows
M-AUTH-15  COMPLETE   row counts = 1 / 1725 / 0
M-AUTH-16  COMPLETE   9100 alembic app = 0003 / 0003
M-AUTH-17  COMPLETE   9100 endpoints = 200 / 200；Milvus 4x true；容器 curl CMD_UNAVAILABLE NON_BLOCKING
M-AUTH-18  COMPLETE   docker supervision = NONE_DETECTED（容器 3 项 + labels 2 项 NONE）
M-AUTH-19  COMPLETE   systemd = NONE_DETECTED（services/timers；[watchdogd] 形态解释非唯一依据）
M-AUTH-20  COMPLETE   cron = NONE（root / /etc/crontab / /etc/cron.d）
M-AUTH-21  COMPLETE   BT search = 3 命中（已由 B2-01~05 语义分类）

B2-01  COMPLETE   backup = ADMIN_BACKUP_CAPABILITY / restore 可改 lifecycle = YES 但非自动触发
B2-02  COMPLETE   caller = composeMod.py；无 systemd/cron 直接 caller
B2-03  COMPLETE   project-specific = NONE_DETECTED（dir_history.json 为 history/metadata）
B2-04  COMPLETE   caller context = EXPLICIT ADMIN/API ACTION（panelTask create_task）
B2-05  COMPLETE   scheduled = NONE_DETECTED（panel data 搜索 NO OUTPUT）
```

按真实 operator evidence，M-AUTH-01~21 与 B2-01~05 **全部 COMPLETE**；无任何一项因缺结果被强行凑完整。

## 2K. Evidence Levels（§41，升级）

```text
MERCHANT_OPERATOR_READ_ONLY_RUNTIME_VERIFIED = YES（docker inspect / image / health / restart）
MERCHANT_OPERATOR_READ_ONLY_DB_VERIFIED      = YES（psql / alembic / information_schema / counts / constraints）
MERCHANT_OPERATOR_READ_ONLY_CONFIG_VERIFIED  = YES（compose config / /health / /ready / Milvus）
MERCHANT_OPERATOR_READ_ONLY_HOST_VERIFIED    = YES（git / systemd / cron / 宝塔 / B2-01~05）

PRODUCTION_TARGET_RUNTIME_VERIFIED           = NOT APPLICABLE（target 尚未部署，本报告不写）
```

（上述等级**取代** PART I §36 中对应项的 NOT ACHIEVED 历史记录；PART I §36 保留为历史阶段状态。）

## 2L. Write Isolation Topology（§37）

```text
新的 Merchant topology 未发现 independent XG worker container / scheduler container / external local writer
PRODUCTION_WRITE_ISOLATION_TOPOLOGY = CONSISTENT_WITH_STATIC_MODEL
```

注意：这是 **topology evidence**；"writes actually stopped" 仍属 Production Execution 的 dynamic gate（M2 / P-S08）。

## 2M. Final Consolidated Current State（§50/§38）

```text
M_AUTH_EVIDENCE_CONSOLIDATION = COMPLETE
INITIAL_M_AUTH_VERDICT        = INCOMPLETE / HISTORICAL（PART I，不删除）
CURRENT_M_AUTH_STATUS         = COMPLETE
MERCHANT_CURRENT_REALITY      = RE_FROZEN
PRODUCTION_REALITY_DRIFT      = NO MATERIAL DRIFT DETECTED
EXTERNAL_HEALTH_RESTART       = NONE_DETECTED
BLOCKER-1                     = CLOSED（引用 a633b48，不重审）
BLOCKER-2                     = CANDIDATE_RESOLVED（不得自行 CLOSED）
BLOCKER-3                     = CANDIDATE_RESOLVED（不得自行 CLOSED）
PRODUCTION_AUTHORIZATION      = STILL NO_GO（本窗口不修改）
PRODUCTION_MIGRATION_AUTHORIZED = NO
PRODUCTION_EXECUTION_ENTRY    = BLOCKED
```

B2/B3 只能 CANDIDATE_RESOLVED 不能 CLOSED：本窗口是 evidence consolidation，不是独立审批（§39）。正式 closure 留给下一 Focused Authorization R1。

## 2N. Next Stage — Focused Authorization R1（§51~§54）

```text
下一窗口唯一 = PRODUCTION-BASELINE-CATCHUP-0028-TO-0034 / FOCUSED-PRODUCTION-AUTHORIZATION-R1
R1 只审   : BLOCKER-2（watchdog）/ BLOCKER-3（current reality）
           + new consolidated evidence 是否推翻原 runbook
R1 继承   : BLOCKER-1 = CLOSED（不得第三次完整重审 Release Freeze，除非 release artifact 变化）
原则上     : NO NEW MERCHANT EVIDENCE（本窗口目的即同步既有 evidence package；仅真正新矛盾才允许 targeted read-only 补证）
REHEARSAL_RE-RUN_REQUIRED = NO（application/migration/release artifact 未发生 correctness change）
```

## 2O. Git / Production Discipline（§47/§57）

```text
DO NOT COMMIT
DO NOT PUSH
DO NOT MODIFY MERCHANT
DO NOT MIGRATE / RESTART / BUILD / TAG / BACKUP / EDIT ENV
未在 Merchant repository 写任何文件（本 PART II 仅存于本地开发工作区治理报告）
```

## 2P. 文档影响检查（Consolidation 增量）

- 本轮唯一 MODIFY：`..._MERCHANT_M_AUTH_READ_ONLY.md`（本文件，原位更新 + PART II）。
- **未新增独立 consolidation report**（§6 默认 NO；PART I 附录 A 治理设计为"回填结果"，PART II 即回填产物，避免两个互相矛盾的 active truth）。
- `..._FOCUSED_PRODUCTION_AUTHORIZATION.md` 的 NO_GO **不修改**（基于当时 evidence package 的真实历史审批；B2/B3 正式 closure 由 R1 重裁）。
- Design / Rehearsal / Rehearsal Approval / Production Authorization / Release Freeze / Release Manifest / S10-B 系列（Approval / Correction / Implementation）结论**不受影响**（§48）。
- 无其他活动文档结论因本轮而过期。

---

*MERCHANT-M-AUTH-EVIDENCE-CONSOLIDATION 窗口结束。仅做本地只读核查与治理报告原位归并；未操作 Merchant，未 commit/push，未迁移/构建/备份/改 env/restart。最终裁定 `M_AUTH_EVIDENCE_CONSOLIDATION_COMPLETE`：B2/B3 = CANDIDATE_RESOLVED（closure 留给 R1），PRODUCTION_AUTHORIZATION = STILL NO_GO。立即停止。*
