# PRODUCTION-BASELINE-CATCHUP-0028-TO-0034 — Production Authorization

> 窗口：`PRODUCTION-BASELINE-CATCHUP-0028-TO-0034-PRODUCTION-AUTHORIZATION`
> 窗口性质：**AUTHORIZATION ONLY / READ-ONLY** — 只授权不执行。禁止一边检查一边迁移。禁止任何生产 mutation。
> 前序：`PRODUCTION_BASELINE_CATCHUP_0028_TO_0034_ISOLATED_REHEARSAL.md` → `..._REHEARSAL_APPROVAL.md`（`APPROVED_WITH_NON_BLOCKING_FINDINGS`）
> 日期：2026-08-12
> 证据层级：`GIT_HISTORY_VERIFIED` / `CODE_VERIFIED` / `CONTAINER_CONFIG_VERIFIED` / `ISOLATED_REHEARSAL_APPROVED` / `DESIGN_VERIFIED` / `NOT_VERIFIED`（Merchant 侧待只读确认）。本窗口不写 `PRODUCTION_TARGET_RUNTIME_VERIFIED`（目标尚未部署）。

---

## 1. Authorization Scope

基于已 APPROVED 的 Isolated Rehearsal，重新冻结 Merchant 当前生产现实，逐项关闭生产执行前 Hard Gates，给出 GO / NO-GO。本窗口只授权，不执行；不构建镜像、不打 tag、不迁移、不备份、不改 env、不 restart/recreate、不 commit、不 push。

不审批 0035、不审批 P2 cutover、不审批 9100 0003→0005、不审批 P3a/P3b、不审批 RB-10。

## 2. Governance Baseline

```text
ISOLATED_REHEARSAL                = APPROVED_WITH_NON_BLOCKING_FINDINGS
PRODUCTION_AUTHORIZATION_ENTRY     = OPEN（本窗口开始时）
PRODUCTION_MIGRATION_AUTHORIZED    = NO（本窗口开始时）
PREFERRED_STRATEGY                 = SCHEMA_FIRST_WITH_MAINTENANCE_WINDOW
TARGET_9000_SOURCE                 = 9db3f5854095e483a55724e66d452792b354ff53
TARGET_9000_SCHEMA                 = 0034
CURRENT_PRODUCTION_SOURCE          = f453f44
CURRENT_PRODUCTION_SCHEMA          = 0028 + 0029_JSONB_TYPE_AHEAD_ONLY
TARGET_9100_CHANGE                 = NONE
EXPECTED_PRODUCTION_9100_DB        = 0003
```

## 3. Independent Rehearsal Verdict

承自 `..._REHEARSAL_APPROVAL.md`（`ISOLATED_REHEARSAL_APPROVED`）：

```text
ISOLATED_REHEARSAL = APPROVED_WITH_NON_BLOCKING_FINDINGS
BR-01~30 independently accepted（BR-01 PASS_WITH_FINDING）
9 carry-forward findings（§7 逐项裁定）
PRODUCTION_AUTHORIZATION_ENTRY = OPEN → 进入本窗口
```

本窗口不重跑 rehearsal，承用其 runtime 证据；对可在本地静态核实的 hard gate（artifact identity / target 隔离 / compose 机制 / writer 代码层）独立核实，对需 Merchant 只读访问的 reality gate 生成 evidence request。

## 4. Merchant Current Reality

本窗口（VibeCoding）无法直接访问 Merchant 主机。AUTH-R1~R15 是 §3 要求的"必须重新只读冻结"的 now-gate，但需 Merchant 侧执行只读命令包（§54，见 §63 M-AUTH-xx）。本窗口先给出 expected current reality（承自前序 reality audit / memory `production-dual-instance-reality` 2026-08-12 只读核实），并在 §63 列出重新冻结所需的只读命令包。

```text
# Expected（承自前序，须 Merchant 重新只读确认）
PRODUCTION_GIT_HEAD        = f453f44     （AUTH-R1）
git worktree status        = clean/detached（AUTH-R2，须确认无未预期变化）
9000 runtime image ID      = sha256:93094f0a02ba3a4570160ce90625cb80fdec85076046fc314f5fe407add36c68（AUTH-R3，承自 Design M3，须重新只读确认）
9100 runtime image ID      = 同上（共享镜像，AUTH-R4）
9000 Docker restart policy = unless-stopped（AUTH-R5，compose 核实）
9100 Docker restart policy = unless-stopped（AUTH-R6）
9000 app migration head    = 0028（AUTH-R7）
9000 DB current revision   = 0028（AUTH-R8）
9000 /ready                = expected 0028 / actual 0028 / PASS（AUTH-R9）
physical drift             = confirmed_fields_json=jsonb / inferred_fields_json=jsonb（AUTH-R10）
9100 app migration head    = 0003（AUTH-R11）
9100 DB current revision   = 0003（AUTH-R12）
9100 /ready                = PASS（AUTH-R13）
PostgreSQL DB identity     = merchant.xiaogaoai.cn PG（AUTH-R14）
critical preconditions     = cp=1 / ct=1698 / drj=0 / invalid JSON=0/0（AUTH-R15）
```

> ⚠ 前序 reality 核实（memory）发现生产双实例现实：callback.misanduo.com = SQLite/0033（违反硬约束 #2）、merchant.xiaogaoai.cn/api = PG/0028。本 catch-up 目标是 merchant.xiaogaoai.cn 的 PG（0028→0034）。callback SQLite 实例属范围外独立 blocker（B6 拓扑），本 catch-up 不动它，但 AUTH-R14 必须确认 catch-up 操作的 PG 实例身份正确。

## 5. Reality Comparison vs M1-M4

M1-M4 证据承自 Design 窗口（2026-08-12 早段），非今天仍成立的自动证据。本窗口要求重新冻结（§3）。由于本窗口无法访问 Merchant，M1-M4 reality gate 状态 = `NEEDS_MERCHANT_READ_ONLY_RECONFIRM`（§63 evidence request）。本窗口**不假定** M1-M4 仍成立，但在 §6 给出"若生产未变化则应观测到"的期望，供 Merchant evidence request 比对。

## 6. Expected Current Reality（若生产未变化）

```text
PRODUCTION_GIT_HEAD          = f453f44
9000 APP HEAD                = 0028
9000 DB CURRENT              = 0028
9000 /ready                  = expected 0028 / actual 0028 / PASS
confirmed_fields_json        = jsonb
inferred_fields_json         = jsonb
invalid JSON                  = 0 / 0
9100 APP HEAD                 = 0003
9100 DB CURRENT               = 0003
runtime image 参考            = sha256:93094f0...
```

## 7. Baseline Drift Hard Stop

本窗口未发现可在本地静态确认的生产 baseline drift。但生产 reality 是否仍匹配 expected（§6）需 Merchant 只读确认（§63）。若 Merchant evidence 显示任一关键现实变化（HEAD != f453f44 / 9000 DB != 0028 / drift scope 变 / 0030~0034 对象已存在 / invalid JSON > 0 / 9100 DB != 0003 / runtime image 意外变化），则 `PRODUCTION_BASELINE_DRIFT = YES` → `NO_GO`，回到 Reality Audit。本窗口暂不裁定（待 evidence），但 §59 已独立构成 NO_GO（与 drift 无关）。

## 8. Production Git Identity / Worktree / Protected Files

- Production git HEAD / worktree status：需 Merchant 只读确认（M-AUTH-01/02）。
- **保护未跟踪生产文件**（§6）：`.env.production.local.bak.20260804_172603`、`milvus_export_full.jsonl`、`milvus_export_no_vec.jsonl` 及可能新增的 production-only 文件。本窗口**禁止** git clean / destructive reset（§68）。未来 Execution Runbook 必须显式保护它们（§52 runbook contract + M-AUTH-03 核实存在性）。

## 9. 9000 Runtime Identity

承自 Design M3：9000 runtime image = `sha256:93094f0a02ba3a4570160ce90625cb80fdec85076046fc314f5fe407add36c68`（image label 仅 `com.docker.compose.*`，无 `org.opencontainers.image.revision`/`git.commit`）。须 Merchant 重新只读确认 image ID 未变（M-AUTH-04）。

## 10. 9000 DB Reality

须 Merchant 只读确认：app head=0028（M-AUTH-05）、DB current=0028（M-AUTH-06）、/ready=PASS（M-AUTH-07）。本窗口无法独立核实。

## 11. Physical JSONB Drift

须 Merchant 只读确认（M-AUTH-08）：`confirmed_fields_json`/`inferred_fields_json` 物理 = jsonb、invalid JSON = 0/0。这是 0029 迁移幂等性的生产前提。

## 12. Data Preconditions

须 Merchant 只读确认（M-AUTH-09）：cp≈1 / ct=1698 / drj=0；0030 前提 idempotency_key 全 NULL（NULL 不参与唯一约束）；0032 前提 daily_report_jobs 无 orphan。

## 13. 9100 Runtime Identity / DB 0003

须 Merchant 只读确认（M-AUTH-10/11/12）：9100 image ID、9100 DB=0003、9100 /ready。9100 冻结合约见 §30。

## 14. Carry-Forward Findings Matrix（9 项逐项裁定）

| CF | 来源 | 裁定 | 说明 |
| --- | --- | --- | --- |
| CF-1 | U1 old fresh-bootstrap defect | **ACCEPTED / OUT_OF_PRODUCTION_PATH** | §15 |
| CF-2 | U2 JSONB predeclaration | **SUPPORTING_EVIDENCE / ACCEPTED** | §16 |
| CF-3 | U3 transactional DDL | **ACCEPTED_WITH_SCOPE_LIMIT** | §17 |
| CF-4 | production write isolation gap | **FEASIBLE_CODE_LEVEL / EXECUTION_PREFLIGHT**（生产 topology 需 Merchant 确认）| §18~§20 |
| CF-5 | image provenance debt | **NON_BLOCKING / EXECUTION_PREFLIGHT** | §21~§22 |
| CF-6 | external autoheal unknown | **UNKNOWN → BLOCKING until Merchant 确认** | §23~§24 |
| CF-7 | small-scale timing | **OPERATOR_CAUTION** | §25 |
| CF-8 | BR-22 single failure mode | **ACCEPTED_WITH_SCOPE_LIMIT** | §26 |
| CF-9 | BR-15 partial runtime scope | **ACCEPTED / MAINTENANCE_FALLBACK_ONLY** | §27 |

## 15. CF-1 — U1 Old Fresh-Bootstrap Defect

生产执行路径 = existing DB 0028 → target 9db3f58 migration artifact → 0034，**完全不使用 f453f44 fresh bootstrap**；rollback 用旧应用 image + schema 0034 forward，**不使用 old migration chain**（§9 rehearsal approval 已证四问全成立）。

```text
CF-1 = ACCEPTED / OUT_OF_PRODUCTION_PATH
```

## 16. CF-2 — U2 JSONB Predeclaration

target baseline（9db3f58 0026）naturally produces JSONB state，与生产 drift-compatible rehearsal 一致（rehearsal approval §10 已核实 f453f44=TEXT / 9db3f58=JSONB）。

```text
CF-2 = SUPPORTING_EVIDENCE / ACCEPTED
```

## 17. CF-3 — U3 Transactional DDL

仅作 SUPPORTING_EVIDENCE。不得把单一失败场景（0025 / 0030 lock-timeout）泛化为"all possible failures are always atomic"。

```text
CF-3 = ACCEPTED_WITH_SCOPE_LIMIT
```

## 18. CF-4 — Production Write Isolation Gap（最高优先级 Hard Gate 之一）

代码层 writer inventory（9db3f58 树，`CODE_VERIFIED`）—— 所有向 9000 PG 关键表写的路径：

### compute_transactions writer（record_usage 调用链）
| SOURCE | 文件 | PROCESS OWNER | MAINTENANCE CONTROL |
| --- | --- | --- | --- |
| webhook ingress | app/integrations/douyin_webhook.py:1242 | 9000 进程 | 停 9000 + 反代/webhook 暂停 |
| 9000 compute API | app/routers/compute.py:467 | 9000 进程 | 停 9000 |
| 9100→9000 回写 | apps/xg_douyin_ai_cs/services/compute_usage_client.py:163（经 AUTO_WECHAT_9000_BASE_URL HTTP 调 9000 compute internal API）| 9100 进程（但写入经 9000）| 停 9000 即切断回写落地；9100 侧 HTTP 失败须容错 |
| AI 剪辑 LAS | app/services/ai_edit_las_service.py:740 | 9000 进程 | 停 9000 |
| 素材分析 | app/services/material_analysis.py:282 | 9000 进程 | 停 9000 |
| 微信任务 | app/services/wechat_task_service.py:503 | 9000 进程 | 停 9000 |
| compute internal API | apps/compute/routers.py:362 | 9000 进程 | 停 9000 |

### customer_profiles writer
| SOURCE | 文件 | MAINTENANCE CONTROL |
| --- | --- | --- |
| customer profile service | app/services/customer_profile_service.py | 停 9000 |
| 对话历史 service | app/services/douyin_conversation_history_service.py | 停 9000 |
| admin test reset | app/routers/admin_test_customer_reset.py / test_customer_reset_service.py | 停 9000（test/admin 路径，生产不应触发）|

### daily_report_jobs writer
| SOURCE | 文件 | MAINTENANCE CONTROL |
| --- | --- | --- |
| daily report job service | app/services/daily_report_job_service.py | 停 9000 |

### compose 服务容器（9db3f58 树）
```text
postgres / auto-wechat-api(9000) / xg-douyin-ai-cs(9100) / auto-wechat-frontend(5173)
→ 无独立 background worker / scheduler 容器
```

## 19. Write Isolation 关键洞察

代码层所有 writer 经 **9000 进程本身**（auto-wechat-api 容器）。9100 不直写 9000 PG，而是 HTTP 调 9000 compute internal API（`compute_usage_client.py`）。compose 无独立 worker/scheduler 容器——9000 后台任务（daily report / outbox）应跑在 9000 进程内。

→ 代码层 `WRITE_ISOLATION_CONTROL = FEASIBLE`：停 9000 服务可切断绝大多数写。但须 Merchant 确认生产 topology 侧（§20）。

## 20. Write Isolation 生产 topology 待确认项

```text
- 是否有独立 cron/systemd/宝塔定时任务独立调 9000 API（非 9000 进程内）？→ M-AUTH-13
- 抖音 webhook ingress 路径（反代→9000）：maintenance 期如何暂停/丢弃重试？→ M-AUTH-14
- 9100→9000 回写失败时 9100 侧行为（容错/重试/阻塞）？→ M-AUTH-15
- 19000 Local Agent 回调 9000 路径？→ M-AUTH-16
- 是否有其他容器/进程直连 9000 PG（绕过 9000 API）？→ M-AUTH-17
```

## 21. CF-4 Authorization Gate

```text
WRITE_ISOLATION_CONTROL = FEASIBLE_CODE_LEVEL（代码层 writer 全经 9000 进程）
                         + EXECUTION_PREFLIGHT（生产 topology 侧需 M-AUTH-13~17 确认）
```

代码层不阻塞。生产 topology 侧若存在无法停止的 ACTIVE writer → CF-4 升级 BLOCKING。本窗口不允许为关闭 CF-4 新开发 feature flag（§14）；若需代码才能隔离 → NO_GO 进独立 remediation。当前可通过"停 9000 + 反代/webhook 暂停 + 9100 容错"运维控制完成，属 Execution Runbook 范畴，**不需新代码**。

## 22. CF-5 — Image Provenance Debt / Rollback Image Availability

旧生产 runtime：`ROLLBACK_RUNTIME_IMAGE_IDENTITY = known image ID`（93094f0...）、`ROLLBACK_SOURCE_COMMIT_PROVENANCE = UNVERIFIED`（image 无 provenance label）。`NON_BLOCKING`（§15 任务书），前提 Execution STEP 0~2 在任何 target build/tag 之前 preserve current runtime image under immutable rollback reference。

须 Merchant 只读确认（M-AUTH-18）：current old image ID 仍存在本地、可引用（RepoTags/RepoDigests/Created）。若已不可恢复 → `ROLLBACK_RUNTIME_IMAGE_UNAVAILABLE = BLOCKING` → NO_GO。本窗口无法核实，待 Merchant evidence。

## 23. CF-6 — External Autoheal / Watchdog（必须关闭的 Unknown）

代码/compose 层（`CONTAINER_CONFIG_VERIFIED`，9db3f58 树 docker-compose.yml + rehearsal approval §22）：compose 9000/9100 均 `restart: unless-stopped` + healthcheck 探 /ready，**仓库无 autoheal/watchtower/ofelia/supervisor**（grep 零命中）。`restart: unless-stopped` 不因 unhealthy 自动 restart。

但生产 topology 侧（宝塔/systemd/cron/自定义 watchdog）= `UNKNOWN`，须 Merchant 只读审查（M-AUTH-19）：Docker containers/services / systemd units / cron / 宝塔进程守护配置（可读部分）/ 自定义 watchdog 脚本 / 部署脚本。

## 24. Autoheal Verdict

```text
compose 层  : EXTERNAL_HEALTH_RESTART = NONE_DETECTED
生产层      : UNKNOWN（须 M-AUTH-19 确认）
```

按 §18：若仍 UNKNOWN 且可能破坏 maintenance（unhealthy/stopped 时自动 restart/recreate 9000）→ NO_GO，不能带入 Execution。**本 gate 在 Merchant 确认前 = BLOCKING**（§57：本应现在可确认的 hard gate 不得"稍后确认"）。M-AUTH-19 是只读命令包，可在 RELEASE_PACKAGE_FREEZE 期间并行执行。

## 25. CF-7 — Small-Scale Timing

isolated rehearsal timing（0029:0.99s / 0030:0.87s / 0032:1.21s / 0033:0.85s / 0034:0.90s）= `PRODUCTION_LIKE_ISOLATED_RUNTIME`，不可预测生产 exact duration。

```text
CF-7 = OPERATOR_CAUTION
```

Execution Runbook 不得依赖"迁移一定在 X 秒内完成"，只使用确定性机制：`statement_timeout` / `lock_timeout` / monitoring / stop conditions。

## 26. CF-8 — BR-22 单 Failure Mode

```text
CF-8 = ACCEPTED_WITH_SCOPE_LIMIT
```

仅验证 lock_timeout failure → rollback。Production Runbook 对 migration nonzero exit / unexpected revision / partial state 全部 fail closed（§45 P-S09/P-S10/P-S12）。

## 27. CF-9 — BR-15 Partial Runtime Scope

old f453f44 + 0034 只证明 startup/core health level compatibility，且 /ready=503。不宣称全业务兼容。

```text
CF-9 = ACCEPTED / MAINTENANCE_FALLBACK_ONLY
```

生产 rollback = MAINTENANCE FALLBACK ONLY（非 normal healthy rollback service）。若 target deploy 失败 rollback old image：keep maintenance active 直到后续决策（§43）。

## 28. S10-B Production Delivery Hard Gate（§22~§25，决定性）

已批准的 S10-B implementation 当前来自**未提交 candidate**。本窗口独立核实（`GIT_HISTORY_VERIFIED`）：

```text
git status：
  M  docker-compose.yml            （未提交：per-service image env var 改动）
  M  .env.production.example        （未提交：S10-B IMAGE 变量）
  M  docs/config/ENV_VARIABLE_REFERENCE.md
  ?? scripts/release_9000_s10b.py   （从未 commit，untracked）

HEAD(36fe68a) 树：
  - 不含 scripts/release_9000_s10b.py（ls-tree HEAD 确认）
  - docker-compose.yml 仍是原始 image: xg-ai-system-backend:latest（无 env var）
  - .env.production.example 无 S10-B IMAGE 变量
```

→ **S10-B approved candidate（compose per-service image env var + wrapper + env contract）全部是未提交工作区 diff，无 immutable identity**（无 dedicated commit / signed patch / versioned release package / SHA256 manifest）。

## 29. Release Engineering Artifact Identity（§24/§25）

任务书 §59 Hard Gate：若 S10-B 仍只有 uncommitted diff → `RELEASE_ENGINEERING_ARTIFACT_IDENTITY = NOT_READY`，这是 Production GO 前 Hard Gate，应 NO_GO。

```text
RELEASE_ENGINEERING_ARTIFACT_IDENTITY = NOT_READY
```

下一阶段须先 `RELEASE_PACKAGE_FREEZE`：将 approved S10-B candidate（compose env var 改动 + release_9000_s10b.py + env contract + 文档）冻结成可重复 identity（dedicated commit 或 exact file bundle + SHA256 manifest），而非让 Production Execution 从开发机脏工作区复制未提交文件。

## 30. S10-B Source vs Deployment Mechanism 分离回答（§22/§51）

Production Execution 如何同时获得：
- exact application source/artifact = 9db3f58（target app，树 head=0034）
- independently approved S10-B deployment mechanism（compose env var + wrapper，当前未提交）

**当前答案：无法同时以 immutable identity 获得**。target app source 9db3f58 本身不包含 S10-B mechanism（9db3f58 树 docker-compose.yml 仍是 `image: xg-ai-system-backend:latest` 字面量，无 env var；9db3f58 树无 scripts/release_9000_s10b.py）。S10-B mechanism 存在于**未提交工作区**，叠加在 36fe68a（含 0035）之上。二者当前无统一 immutable release artifact。**必须先 RELEASE_PACKAGE_FREEZE 才能解决**（§65）。

## 31. Target Application Artifact Identity（§26/§60）

本窗口独立核实（`GIT_HISTORY_VERIFIED`）：

```text
TARGET_9000_APPLICATION_SOURCE = 9db3f5854095e483a55724e66d452792b354ff53 ✅（commit 存在）
9db3f58 树 9000 alembic head   = 0034 ✅（只含 0034，不含 0035/0036）
```

target 严格隔离到 9db3f58。生产执行**不得**依赖 origin/master / current HEAD(36fe68a) / latest source。current HEAD(36fe68a) 树 head=0035（含 0035_wechat_task_claim_lease.py），**不可作为 target artifact**（§60）。

```text
TARGET_ARTIFACT_0035_ISOLATION = VERIFIED（9db3f58 严格隔离，无 0035）
```

## 32. Target Image Strategy（§27/§28/§29）

本窗口 READ-ONLY，target image = `NOT_BUILT_YET`（允许，§28）。Execution Runbook 须 fail-closed 定义：

```text
build context = 9db3f58 worktree（git worktree add --detach 9db3f58）
build         = docker build -f Dockerfile.backend.dev -t <immutable-tag> <worktree>
image tag     = service-specific exact identity（如 xg-ai-system-backend:9db3f58-<ts>），NOT shared :latest
provenance    = org.opencontainers.image.revision=9db3f58 label
transfer      = pre-stage 到 Merchant（离线就绪，§50），不依赖运行时公网
verify        = image ID/digest + 9db3f58 source 一致性
```

```text
TARGET_IMAGE_STRATEGY = EXECUTION_PRECONDITION_DEFINED（未构建，runbook 已定义）
```

禁止 `docker build -t xg-ai-system-backend:latest` 作为 9000 target release（§29）。必须 service-specific exact identity。

## 33. 9100 Freeze Hard Contract（§30）

```text
9100_EXPECTED_DB                   = 0003
9100_EXPECTED_CURRENT_RUNTIME_IMAGE = <current exact image identity>（须 M-AUTH-10 确认）
9100_RECREATE                       = FORBIDDEN
9100_MIGRATION                      = FORBIDDEN
9100_UPGRADE                        = OUT_OF_SCOPE
```

Production execution commands 不得隐式改变 9100。wrapper `canonical_up_command` 只 target `auto-wechat-api`（--no-deps 保护 9100，已 rehearsal 验证 BR-26/28）。

## 34. Production S10-B Env Contract（§31）

须 Merchant 只读核实 `.env.production.local` 当前 required keys（M-AUTH-20，只记 present/absent，不输出 secret）。S10-B 新变量（`AUTO_WECHAT_API_IMAGE` / `XG_DOUYIN_AI_CS_IMAGE`）目前 absent 是正常的（生产尚未部署 mechanism）。未来 Execution 须设置：9000 explicit image identity / 9100 frozen image identity / expected-9000 / expected-9100（按 wrapper `--expected-9000`/`--expected-9100` contract）。

## 35. Host Environment Pollution Production Gate（§32）

未来执行 wrapper 前必须：use approved sanitization（`compose_env()` 移除宿主 IMAGE 变量，已 CODE_VERIFIED）+ explicit env file + preflight resolved identities。rehearsal §38 已 CONTAINER_RUNTIME 验证宿主 precedence 被克服。

Production Runbook 不得有旁路（manual `docker compose up` 绕开 wrapper）。唯一 execution path 见 §37。

## 36. Canonical Production Command Package（§33）

冻结唯一 execution path，基于已批准 `scripts/release_9000_s10b.py`（当前未提交，§28）：

```text
preflight   : python scripts/release_9000_s10b.py --env-file <f> --expected-9000 <tgt> --expected-9100 <frozen>
dry-run     : python scripts/release_9000_s10b.py --env-file <f> --dry-run
apply       : python scripts/release_9000_s10b.py --env-file <f> --apply
verification: curl GET /ready + docker inspect + psql SELECT version_num
rollback    : python scripts/release_9000_s10b.py --env-file <f-with-9000=old> --apply
```

**注意**：wrapper 本身属未提交 candidate（§28），在 RELEASE_PACKAGE_FREEZE 前无 immutable identity。此 command package 在 freeze 后才正式成立。

## 37. Migration Command Package（§34/§35）

```text
TARGET = 0034（显式），NOT upgrade head
命令   : alembic upgrade 0034（从 9db3f58 artifact）
artifact source = 9db3f58 ✅（非 36fe68a/head0035）
```

若 artifact head 未来意外 != 0034 → STOP（P-S05）。不得用 36fe68a 制品即使 `upgrade 0034` 理论可行（§35）。

## 38. Rollback Image Preservation Plan（§36）

本窗口不得 docker tag。冻结未来 Execution 顺序：

```text
STEP 0  verify current runtime image（M-AUTH-04/18 已确认存在）
STEP 1  preserve current image under immutable rollback reference（docker tag <id> xg-ai-system-backend:rollback-0028-<ts>）
STEP 2  verify preserved reference resolves exact same Image ID
ONLY THEN proceed with target artifact preparation
```

STEP 1/2 失败 → STOP BEFORE MIGRATION（P-S02）。

## 39. Backup Plan（§37/§38）

本窗口不得创建 production backup。冻结：

```text
BACKUP_METHOD      = pg_dump -F c auto_wechat
BACKUP_DESTINATION = <Merchant 本地安全路径，须 M-AUTH-21 确认容量>
BACKUP_NAMING      = aw_backup_<YYYYMMDD_HHMMSS>.dump（含 sha256 校验）
BACKUP_VERIFICATION= artifact exists + nonzero size + pg_restore -l 列出内容 + dump integrity check
RESTORE_COMMAND    = pg_restore -d <disposable> <dump>（rehearsal §31 已验证流程）
```

Execution 中 migration 前必须 create backup + verify artifact（M4）。backup command fails / artifact missing / insufficient disk / destination unsafe → STOP BEFORE MIGRATION（P-S03）。

## 40. Storage / Resource Readiness（§39）

须 Merchant 只读确认（M-AUTH-21）：

```text
- disk free（backup destination + PG data）
- Docker disk usage
- PostgreSQL storage
- backup destination capacity
```

不得因数据量目前不大跳过。容量明显不足 → NO_GO。

## 41. Maintenance Window Contract（§40/§41）

```text
M0  PRE-MAINTENANCE     : reality reconfirm / protected files / storage / rollback image identity
M1  ENTER MAINTENANCE   : maintenance begin
M2  VERIFY WRITE ISOLATION : 9000 stopped + webhook paused + 9100 容错 + 无独立 cron writer
M3  PRESERVE ROLLBACK IMAGE : STEP 0~2（§38）
M4  CREATE/VERIFY DB BACKUP : backup + verify
M5  VERIFY TARGET ARTIFACTS : 9db3f58 source / image built / head=0034
M6  MIGRATE 0028→0034   : alembic upgrade 0034
M7  VERIFY DB 0034       : version_num=0034 + objects
M8  DEPLOY TARGET 9000   : wrapper --apply（9000-only）
M9  VERIFY /ready 200    : expected=actual=0034
M10 VERIFY 9100 UNCHANGED: container/image/DB=0003
M11 EXIT MAINTENANCE     : 仅 target ready 后
```

顺序不得反转（§41）：NO target9000 startup before DB0034 / NO migration before backup / NO target build/tag endangering rollback image before preservation / NO maintenance exit before target ready。

## 42. Migration During Maintenance / Write Boundary（§42/§43）

生产执行停止正常 9000 写入。不得设计"旧 9000 继续正常对外服务同时后台升级 0034"（已批准策略非 zero-downtime Candidate A）。old app + schema0034 boundary：migration 成功但 target deploy 失败 → old app rollback 仅作 MAINTENANCE FALLBACK（/ready=503），**DO NOT EXIT MAINTENANCE**（§43）。

## 43. Schema Downgrade Boundary（§44）

```text
0034 → 0028 = EMERGENCY_ONLY
```

不得成为普通 target deployment failure 的默认 rollback。

## 44. Production Execution Stop Conditions（§45）

```text
P-S01 current reality differs from authorization freeze
P-S02 rollback image preservation fails
P-S03 backup fails
P-S04 target source identity != 9db3f58
P-S05 target migration head != 0034
P-S06 resolved 9000 image != expected target
P-S07 resolved 9100 image != frozen identity
P-S08 write isolation cannot be proven
P-S09 migration nonzero exit
P-S10 DB revision after migration != 0034
P-S11 unexpected 0035
P-S12 data/schema verification failure
P-S13 target 9000 /ready != 200
P-S14 9100 container/image/revision changes
P-S15 rollback 9000 fails
P-S16 external watchdog breaks maintenance assumptions
```

任一触发 → STOP，DO NOT CONTINUE。

## 45. Production Verification Matrix（§46）

```text
PV-01 target source/image identity（9db3f58）
PV-02 DB current 0034
PV-03 app head 0034
PV-04 /ready 200
PV-05 0030 objects（idempotency_key/payload_evidence + UK）
PV-06 0032 objects（daily_report_generations + FK/CHECK/index）
PV-07 0033 objects（ai_edit_material_analysis_executions）
PV-08 0034 objects（ai_preview_executions）
PV-09 row preservation（cp/ct/drj）
PV-10 JSONB preservation（object/array/NULL）
PV-11 logs
PV-12 P1 deployment artifacts（record_usage/FC-F1/三模型）
PV-13 9100 container unchanged
PV-14 9100 image unchanged
PV-15 9100 DB 0003
PV-16 no 0035
PV-17 no unexpected schema drift
```

## 46. P1 / P2 Boundary（§47/§48）

PV 只证明 P1 previously-closed artifacts 已部署到生产 baseline，**不重开 P1 technical review**。catch-up 完成后 **DO NOT apply 0035 / DO NOT cut over M04**，须先 B7/B8 production verification closure，再返回 P2 blockers。

## 47. Offline / Network Readiness（§49/§50）

生产历史有 GitHub TLS/443 问题。Production Authorization **不批准**依赖 maintenance 期 `git pull` 的方案。Target artifact 必须 pre-stage / exact local package / prebuilt image + checksum verification。若完全依赖运行时公网 → NO_GO（§50）。

```text
OFFLINE_READINESS = REQUIRES_RELEASE_PACKAGE_FREEZE（artifact 需冻结为可 pre-stage 包）
```

## 48. Protected Production Files（§6/§8）

未来 Execution Runbook 显式保护（M-AUTH-03 核实存在性）：

```text
.env.production.local.bak.20260804_172603
milvus_export_full.jsonl
milvus_export_no_vec.jsonl
（+ 可能新增 production-only 文件）
```

NO git clean / NO destructive reset。

## 49. Authorization-Now Gates（§56A）

```text
GATE                                            STATUS
production baseline unchanged（M1-M4 reconfirm）  NEEDS_MERCHANT_READ_ONLY（M-AUTH-01~12）→ §57 不允许"稍后确认"，但需 Merchant 执行；RELEASE_PACKAGE_FREEZE 期间并行
9100 still 0003                                 NEEDS_MERCHANT_READ_ONLY（M-AUTH-11/12）
current runtime image known                    NEEDS_MERCHANT_READ_ONLY（M-AUTH-04/18）
write isolation feasible                       FEASIBLE_CODE_LEVEL + NEEDS_MERCHANT_TOPOLOGY（M-AUTH-13~17）
external watchdog understood                    UNKNOWN → BLOCKING until M-AUTH-19
release package design closed                   ❌ BLOCKED（S10-B candidate 未提交，§28/§29）
target artifact 9db3f58/head=0034 隔离           ✅ VERIFIED（§31）
0035 isolation（current HEAD 含0035，target 严格9db3f58） ✅ VERIFIED（§31）
```

## 50. Execution-Time Gates（§56B，fail-closed，仅 Execution 时完成）

```text
rollback tag actually created                  P-S02
backup actually created                         P-S03
target image actual digest obtained             PV-01
maintenance actually entered                    M1
writes actually stopped                         M2/P-S08
```

## 51. Blocking Findings

```text
BLOCKER-1（决定性）：RELEASE_ENGINEERING_ARTIFACT_IDENTITY = NOT_READY
  S10-B approved candidate（docker-compose.yml per-service image env var + scripts/release_9000_s10b.py
  + .env.production.example + docs）全部是未提交工作区 diff，无 immutable identity
  （无 dedicated commit / signed patch / versioned package / SHA256 manifest）。
  OWNER/STAGE : RELEASE_PACKAGE_FREEZE
  MINIMUM NEXT ACTION : 将 approved S10-B candidate 冻结成可重复 immutable artifact
                        （dedicated commit 或 exact file bundle + SHA256 manifest），然后重新 Focused Authorization。

BLOCKER-2：EXTERNAL_HEALTH_RESTART（生产 autoheal/watchdog）= UNKNOWN
  compose 层 NONE_DETECTED，但生产宝塔/systemd/cron 侧未确认。
  OWNER/STAGE : Merchant 只读 evidence（M-AUTH-19）
  MINIMUM NEXT ACTION : Merchant 执行 M-AUTH-19 只读命令包，确认无 unhealthy/stopped 时自动 restart/recreate 9000 的外部守护。
                        若存在且不可控 → NO_GO 进独立 remediation；若可控/无 → gate CLOSED。

BLOCKER-3：Merchant Current Reality 重新冻结未完成
  AUTH-R1~R15 为 now-gate（§57 不允许"稍后确认"），但本窗口无法访问 Merchant。
  OWNER/STAGE : Merchant 只读 evidence（M-AUTH-01~12/18/21）
  MINIMUM NEXT ACTION : Merchant 执行只读命令包重新冻结 reality；若 drift → 回 Reality Audit。
```

BLOCKER-1 与 Merchant 无关、可在本地静态确证，是本窗口独立裁定的决定性 NO_GO 依据。

## 52. Non-Blocking Findings（carry-forward 到 Execution）

```text
CF-1 old fresh-bootstrap defect（OUT_OF_PRODUCTION_PATH）
CF-2 JSONB predeclaration（SUPPORTING）
CF-3 transactional DDL scope limit
CF-4 write isolation EXECUTION_PREFLIGHT（生产 topology 须 M-AUTH-13~17）
CF-5 image provenance debt（EXECUTION_PREFLIGHT：rollback image preservation STEP 0~2）
CF-7 small-scale timing（OPERATOR_CAUTION，runbook 不依赖固定秒数）
CF-8 BR-22 single failure mode（scope limit，runbook fail closed）
CF-9 old runtime partial scope（MAINTENANCE_FALLBACK_ONLY）
IMAGE_BUILD_PROVENANCE_DEBT（target image 须 OCI revision label）
OFFLINE_READINESS（artifact 需 pre-stage）
PRODUCTION_EXTERNAL_AUTOHEAL_UNKNOWN（即 BLOCKER-2）
```

## 53. GO/NO-GO Verdict

```text
PRODUCTION_AUTHORIZATION = NO_GO
```

依据（§63 任一 hard gate 未关闭即 NO_GO）：

- **BLOCKER-1（决定性）**：RELEASE_ENGINEERING_ARTIFACT_IDENTITY = NOT_READY。S10-B approved candidate 未冻结成 immutable release artifact（§28/§29/§59）。本 gate 与 Merchant 无关，本地静态确证。
- BLOCKER-2：EXTERNAL_HEALTH_RESTART 生产侧 UNKNOWN（§24/§49）。
- BLOCKER-3：Merchant reality 重新冻结未完成（§4/§49）。

不裁定 GO / GO_WITH_NON_BLOCKING_FINDINGS：存在未关闭 hard gate（BLOCKER-1~3），不满足 §61/§62 条件。

## 54. 按 §65 分类（这不是失败）

所有生产现实（待 Merchant 只读确认）+ runbook 可就绪，**只差 approved S10-B candidate 尚未冻结成 immutable release artifact**：

```text
PRODUCTION_REALITY              = READY（待 M-AUTH 重新冻结确认）
PRODUCTION_RUNBOOK              = READY（maintenance window / stop conditions / verification 已设计）
RELEASE_ARTIFACT_IDENTITY       = BLOCKED（§28/§29）
PRODUCTION_AUTHORIZATION        = NO_GO
```

下一步只做最小动作（§65）：**RELEASE_PACKAGE_FREEZE**，然后重新 Focused Authorization，**不必重跑 rehearsal**（rehearsal approval 仍有效，target artifact 隔离仍 VERIFIED）。

## 55. Production Migration Authorization / Execution Entry

```text
PRODUCTION_MIGRATION_AUTHORIZED = NO
PRODUCTION_EXECUTION_ENTRY       = BLOCKED
```

## 56. Next Stage

```text
当前 : Production Authorization = NO_GO（本窗口）
  ↓
RELEASE_PACKAGE_FREEZE（独立窗口）
  - 将 approved S10-B candidate 冻结成 immutable artifact（dedicated commit 或 file bundle + SHA256 manifest）
  - 并行：Merchant 执行 M-AUTH-01~21 只读命令包（重新冻结 reality + 关闭 BLOCKER-2/3）
  ↓
重新 Focused Production Authorization（不必重跑 rehearsal）
  - 验证 release artifact identity
  - 验证 Merchant reality 无 drift
  - 验证 external watchdog gate CLOSED
  ↓
（若全 hard gate 关闭）Production Execution（独立执行窗口）
  M0~M11 → PV-01~PV-17 → B7/B8 closure → return P2
```

不得跨级。不得借 catch-up 执行 0035 / P3a / RB-10 / 9100 升级 / P2 cutover。

## 57. Merchant Read-Only Evidence Requests（§54）

以下只读命令包供 Merchant 执行，每个 `READ_ONLY = YES`，不夹带 mutation。`DECISION BLOCKED IF UNKNOWN`。

```text
M-AUTH-01  git -C <repo> rev-parse HEAD                  PURPOSE: 确认生产 git HEAD=f453f44
M-AUTH-02  git -C <repo> status --porcelain              PURPOSE: worktree 状态无未预期变化
M-AUTH-03  ls -la .env.production.local.bak.* milvus_export_*.jsonl  PURPOSE: 保护文件存在
M-AUTH-04  docker inspect xg-auto-wechat-api --format '{{.Image}}'  PURPOSE: 9000 runtime image ID=93094f0...
M-AUTH-05  docker exec xg-auto-wechat-api python -c "<alembic heads>"  PURPOSE: 9000 app head=0028
M-AUTH-06  docker exec <pg> psql -U auto_wechat -d auto_wechat -c "SELECT version_num FROM alembic_version"  PURPOSE: DB=0028
M-AUTH-07  curl -s http://127.0.0.1:9000/ready            PURPOSE: /ready PASS（expected=actual=0028）
M-AUTH-08  psql ... -c "SELECT data_type FROM information_schema.columns WHERE table_name='customer_profiles' AND column_name IN ('confirmed_fields_json','inferred_fields_json')"  PURPOSE: 物理=jsonb
M-AUTH-09  psql ... -c "SELECT (SELECT count(*) FROM customer_profiles),(SELECT count(*) FROM compute_transactions),(SELECT count(*) FROM daily_report_jobs)"  PURPOSE: cp/ct/drj 前提
M-AUTH-10  docker inspect xg-douyin-ai-cs --format '{{.Image}}'  PURPOSE: 9100 image ID
M-AUTH-11  docker exec <pg> psql -U auto_wechat -d xg_douyin_ai_cs -c "SELECT version_num FROM alembic_version"  PURPOSE: 9100 DB=0003
M-AUTH-12  curl -s http://127.0.0.1:9100/ready            PURPOSE: 9100 /ready
M-AUTH-13  crontab -l ; systemctl list-timers ; 宝塔计划任务  PURPOSE: 独立 cron/systemd writer
M-AUTH-14  反代/webhook 路由配置（nginx conf）            PURPOSE: webhook ingress maintenance 暂停方式
M-AUTH-15  9100 compute_usage_client 失败行为（日志/配置）  PURPOSE: 9100→9000 回写容错
M-AUTH-16  19000 callback 路径配置                         PURPOSE: 19000 回调
M-AUTH-17  是否有进程直连 9000 PG（绕过 API）              PURPOSE: 直连 writer
M-AUTH-18  docker image inspect <93094f0...>              PURPOSE: rollback image 仍存在可引用
M-AUTH-19  systemd units / cron / 宝塔进程守护 / watchdog 脚本  PURPOSE: external autoheal（BLOCKER-2）
M-AUTH-20  grep -E 'AUTO_WECHAT_API_IMAGE|XG_DOUYIN_AI_CS_IMAGE' .env.production.local（只记 present/absent）  PURPOSE: S10-B env keys
M-AUTH-21  df -h ; docker system df ; du -sh <pg data> <backup dest>  PURPOSE: 存储容量
```

DECISION BLOCKED IF UNKNOWN：M-AUTH-01/04/05/06/07/08/10/11/18/19 为 hard gate，UNKNOWN 即 NO_GO。

## 58. Evidence Levels

本窗口使用：`GIT_HISTORY_VERIFIED` / `CODE_VERIFIED` / `CONTAINER_CONFIG_VERIFIED` / `ISOLATED_REHEARSAL_APPROVED` / `DESIGN_VERIFIED` / `NOT_VERIFIED`（Merchant 侧）。未写 `PRODUCTION_TARGET_RUNTIME_VERIFIED`（目标未部署）。

---

# 59. Candidate Diff（§67）

```text
本窗口唯一新增 = docs/architecture/remediation/PRODUCTION_BASELINE_CATCHUP_0028_TO_0034_PRODUCTION_AUTHORIZATION.md
```

未修改：business code / migration / compose / wrapper / env / tests / rehearsal report / approval reports。

# 60. Git Discipline（§68）

```text
DO NOT COMMIT
DO NOT PUSH
```

# 61. STOP

```text
PRODUCTION_AUTHORIZATION         = NO_GO
PRODUCTION_MIGRATION_AUTHORIZED  = NO
PRODUCTION_EXECUTION_ENTRY       = BLOCKED
```

立即停止。禁止自行：

```text
migrate Merchant / build or tag production image / create production backup
edit production env / checkout target code / restart or recreate service
apply 0035 / upgrade 9100 / P2 cutover / P3a/P3b / RB-10 / commit / push
enter Production Execution
```

下一阶段唯一为 **RELEASE_PACKAGE_FREEZE**（独立窗口）+ 并行 Merchant 只读 evidence（M-AUTH-01~21）。冻结后重新 Focused Authorization，不必重跑 rehearsal。

---

*Production Authorization 窗口结束。未执行任何迁移/部署/构建/tag/备份/env 修改/restart，未 commit、未 push，未操作 Merchant。仅留下本授权报告文件。*
