# 0028→0034 生产追平 — Release Package Freeze 报告

> 窗口：PRODUCTION-BASELINE-CATCHUP-0028-TO-0034 / RELEASE-PACKAGE-FREEZE
> 冻结时间：2026-08-12
> 职责：只关闭 BLOCKER-1（RELEASE_ENGINEERING_ARTIFACT_IDENTITY），把已 APPROVED 的 S10-B Release Engineering Candidate 冻结为 immutable release artifact。
> 关联清单：`PRODUCTION_BASELINE_CATCHUP_0028_TO_0034_RELEASE_MANIFEST.md`（machine-readable 身份/哈希）。

```text
FREEZE_VERDICT = RELEASE_PACKAGE_FREEZE_READY
BLOCKER-1      = CANDIDATE_RESOLVED（RELEASE_ENGINEERING_ARTIFACT_IDENTITY = FROZEN；待后续 Focused Authorization 独立认可）
RELEASE_TREE   = a633b4860b818ab48fda5e22f39aa311eb96e9eb（release/b7-0034-s10b-freeze，LOCAL ONLY）
```

---

## 1. Freeze Scope

本窗口唯一目标：把 2026-08-12 已独立 APPROVED 的 S10-B 发布工程候选冻结为不可变、可复现、可审计的 production release artifact（Release Tree）。

```text
只做：提取 approved S10-B overlay → 叠加到 9db3f58 → 创建 dedicated release commit → manifest/哈希 → 可复现性验证 → 静态回归。
不做：开发、生产部署、构建镜像、迁移 DB、操作 Merchant、rehearsal、0035、9100 升级、P2 cutover、P3a/P3b、RB-10。
```

## 2. Governance Baseline（冻结，不重新打开）

```text
ISOLATED_REHEARSAL               = APPROVED_WITH_NON_BLOCKING_FINDINGS
S10-B CORE MECHANISM             = APPROVED
S10-B CORRECTIONS C1-C5          = CLOSED
HOST_ENV_POLLUTION_GAP           = CLOSED
S10_SHARED_IMAGE_COUPLING        = MITIGATION_IMPLEMENTED_AND_APPROVED
PRODUCTION_AUTHORIZATION         = NO_GO（本窗口不修改）
```

## 3. Production Authorization NO-GO Source

`PRODUCTION_BASELINE_CATCHUP_0028_TO_0034_PRODUCTION_AUTHORIZATION.md` 记录 NO_GO，三项 blocker：

```text
BLOCKER-1 RELEASE_ENGINEERING_ARTIFACT_IDENTITY = NOT_READY   ← 本窗口关闭
BLOCKER-2 EXTERNAL_AUTOHEAL_WATCHDOG             = UNKNOWN     ← 并行 Merchant M-AUTH 只读取证
BLOCKER-3 MERCHANT_CURRENT_REALITY               = NOT RE-FROZEN ← 并行 Merchant M-AUTH 只读取证
```

本窗口**不得**自行关闭 BLOCKER-2/BLOCKER-3，**不得**把 NO_GO 原位改为 GO。

## 4. BLOCKER-1 判定（本窗口唯一职责）

```text
RELEASE_ENGINEERING_ARTIFACT_IDENTITY = FROZEN（a633b48）
BLOCKER-1 = CANDIDATE_RESOLVED（仍需后续 FOCUSED PRODUCTION AUTHORIZATION 独立认可）
PRODUCTION_AUTHORIZATION = STILL NO_GO
PRODUCTION_MIGRATION_AUTHORIZED = NO
```

## 5. Current Main Worktree（冻结前记录）

```text
HEAD                 = 36fe68a3f5c933d6bc2b50dd7c0bfcacfdb70ce2
M                    = .env.production.example / docker-compose.yml / docs/config/ENV_VARIABLE_REFERENCE.md（S10-B 候选）
?? S10-B candidate   = scripts/release_9000_s10b.py、tests/test_s10_b_image_identity_isolation.py、S10-B 三份报告
?? remediation 文档  = catch-up 设计/审批/rehearsal/authorization/reality-audit 等（PRE_EXISTING）
```

主工作区 **未 commit / 未 push**；全程 `NO git clean / NO reset --hard / NO destructive checkout`。

## 6. Target Application Base

```text
APPLICATION_CODE_BASE = 9db3f5854095e483a55724e66d452792b354ff53
```

- `9db3f58` 是 HEAD `36fe68a` 的**直接父提交**（`git log -1 --format=%P HEAD` = 9db3f58）；
- `git merge-base 9db3f58 <RELEASE>` = 9db3f58（release commit 直接派生于 9db3f58）；
- `9db3f58..36fe68a` 仅含 P2 M04（0035 migration + P2 业务代码 + P2 测试/文档），已排除出 release tree。

## 7. Migration Target

```text
ALEMBIC TARGET          = 0034
AUTO_WECHAT PG ALEMBIC HEAD（release tree）= 0034（versions 止于 0034_preview_executions.py）
0035_wechat_task_claim_lease.py           = ABSENT
```

> `migrations/versions/0035_douyin_webhook_event_merchant_scope.sql` 属 **SQLite 轨道**（非 PG Alembic revision graph），在 9db3f58 已存在，release tree 与 9db3f58 ZERO DIFF，不影响 head 判断。

## 8. S10-B Approved Candidate Source

Overlay 只取自分立 APPROVED 的候选：

```text
S10_B_9000_9100_IMAGE_IDENTITY_ISOLATION_APPROVAL.md          （APPROVED_WITH_CORRECTIONS）
S10_B_9000_9100_IMAGE_IDENTITY_ISOLATION_CORRECTION_APPROVAL.md（APPROVED，C1~C5 CLOSED）
S10_B_9000_9100_IMAGE_IDENTITY_ISOLATION_IMPLEMENTATION.md     （S10_B_CANDIDATE + S10_B_CORRECTION_DIFF）
```

Overlay 提取来源 = 主工作区当前候选（3 修改 + 5 新增），经 8 文件 SHA256 与主工作区逐字节一致核验（FREEZE-A 复制后 `sha256sum` 全部 OK）。

## 9. Freeze Candidate A / B 评估

| Candidate | 评估 |
|---|---|
| FREEZE-A（dedicated release commit on 9db3f58） | **选择**。9db3f58 是 HEAD 直接父提交 + BASE_DIFF=0，可安全实现且满足 IMMUTABLE/REPRODUCIBLE/AUDITABLE |
| FREEZE-B（overlay bundle + SHA256 manifest） | 备选，未采用（FREEZE-A 更优，git commit 提供 tree/parent/content 三重身份） |

## 10. Chosen Strategy

```text
CHOSEN = FREEZE-A
RELEASE_TREE_COMMIT = a633b4860b818ab48fda5e22f39aa311eb96e9eb
RELEASE_BRANCH      = release/b7-0034-s10b-freeze（LOCAL ONLY，DO NOT PUSH）
```

## 11. Isolated Worktree

```text
git worktree add --detach .worktrees/release-0034-s10b-freeze 9db3f58
git worktree add --detach .worktrees/repro-check-release-0034 <RELEASE_TREE_COMMIT>   # 可复现性复核
```

主工作区 **未** switch；release commit 只发生在隔离 worktree。

## 12. Approved Overlay Extraction

从主工作区候选提取 8 个 S10-B 文件（3 M + 5 A）：

```text
.env.production.example
docker-compose.yml
docs/config/ENV_VARIABLE_REFERENCE.md
scripts/release_9000_s10b.py
tests/test_s10_b_image_identity_isolation.py
S10_B_..._APPROVAL.md / S10_B_..._IMPLEMENTATION.md / S10_B_..._CORRECTION_APPROVAL.md
```

未加入 unapproved cleanup / 新功能 / 新 docker refactor / 其他工作区修改。**PRE_EXISTING 治理文档（catch-up 链 + P2 M04）不进 release commit**。

## 13. Compose Three-Way Audit

```text
BASE_DIFF  9db3f58 → 36fe68a 对 docker-compose.yml：0 差异（git diff 9db3f58 HEAD -- docker-compose.yml 为空）
S10B_DIFF  release tree 相对 9db3f58 的 compose 差异 = 15 行（image 字段 env 化 + 顶部注释），
           与 approved candidate `git diff HEAD` 完全一致
FINAL_OVERLAY = 只含 S10B_DIFF（无 36fe68a 无关改动混入）
```

## 14. Env Three-Way Audit

```text
BASE_DIFF  .env.production.example / docs/config/ENV_VARIABLE_REFERENCE.md 在 9db3f58→36fe68a 间：0 差异
S10B_DIFF  与 approved candidate 完全一致（02-A 分组 + host precedence 警告 + canonical 命令 + preflight 说明）
FINAL_OVERLAY = 只含 S10B_DIFF（非整文件盲覆盖）
```

## 15. Wrapper Integrity

```text
scripts/release_9000_s10b.py 与 Focused Approval 通过的 candidate 内容逐字节一致
（主工作区 ↔ release worktree `sha256sum` 一致：38a65f270963a712e13fce163ff85f43e3263743cf56ee20fc3d882725fa399c）
Freeze 阶段未修改 wrapper safety logic（仅复制 + 冻结）。
```

## 16. Release Tree Construction

```text
base = 9db3f58（detached worktree）
overlay = 8 个 approved S10-B 文件（复制 + hash 核验）
release commit = a633b48（parent = 9db3f58）
git commit message = "release: 冻结0034生产追平发布制品"
```

## 17. Application Code Integrity

```text
git diff --name-only 9db3f58 <RELEASE> -- app apps frontend = EMPTY
APPLICATION_CODE_DIFF_FROM_9db3f58 = ZERO（除明确 approved release-engineering files）
```

## 18. Migration Integrity

```text
git diff --name-only 9db3f58 <RELEASE> -- migrations = EMPTY
MIGRATION_DIFF_FROM_9db3f58 = ZERO
ALEMBIC HEAD = 0034
```

## 19. 0035 Exclusion

```text
0035_wechat_task_claim_lease.py（Alembic）= ABSENT（git tree 与文件系统均不存在）
P2 M04 application deployment = NOT INCLUDED
SQLite 轨道 0035（migrations/versions/0035_douyin_webhook_event_merchant_scope.sql）= 非 PG Alembic revision，非排除对象
```

## 20. 9100 Boundary

```text
9100_CODE_CHANGE  = NO
9100_DB_CHANGE    = NONE
9100_MIGRATION    = NO
9100_DB_REVISION  = 0003（生产冻结）
9100 0004/0005    = NOT TARGETED（release tree 与 9db3f58 的 9100 migrations 完全一致）
```

## 21. Runtime Required Files（PRODUCTION_RUNTIME_REQUIRED）

```text
docker-compose.yml                       # 唯一 production 主入口
scripts/release_9000_s10b.py             # canonical 9000-only wrapper + fail-closed preflight
.env.production.example                  # template（生产真实值由 .env.production.local / 受控 release input 注入，不打包）
```

## 22. Audit/Test Files（不进部署清单）

```text
tests/test_s10_b_image_identity_isolation.py
docs/config/ENV_VARIABLE_REFERENCE.md
S10_B_..._APPROVAL.md / S10_B_..._IMPLEMENTATION.md / S10_B_..._CORRECTION_APPROVAL.md
（均为 audit-only，可随包携带但不参与运行）
```

## 23. Release Manifest

```text
docs/architecture/remediation/PRODUCTION_BASELINE_CATCHUP_0028_TO_0034_RELEASE_MANIFEST.md
```

## 24. Per-File SHA256

见 Manifest §3（8 文件，release tree blob 计算）。

## 25. Release Tree/Commit Identity

```text
RELEASE_ID            = B7-0034-S10B-FREEZE-001
RELEASE_TREE_COMMIT   = a633b4860b818ab48fda5e22f39aa311eb96e9eb
PARENT               = 9db3f5854095e483a55724e66d452792b354ff53
RELEASE_BRANCH       = refs/heads/release/b7-0034-s10b-freeze（本地持久 ref，cleanup 后仍可 git show）
```

## 26. Reproducibility Verification

```text
RF-T15 = PASS
  新 worktree checkout a633b48 →
    parent=9db3f58 ✓  alembic head=0034 ✓  0035 ABSENT ✓  S10-B runtime files PRESENT ✓
  8 文件 SHA256 与 Manifest 完全一致 ✓
```

## 27. Targeted Tests（静态回归，未重跑 isolated rehearsal）

```text
python -m pytest tests/test_s10_b_image_identity_isolation.py -q  →  37 passed（release tree 内）
python -m pytest tests/test_env_profile_templates.py -q            →  48 passed, 2 failed（pre-existing 基线，与审批记录一致）
alembic head 验证（release tree）                                    →  0034
```

两个 pre-existing failure（test_all_code_variables_are_classified / test_outbox_ten_variables_exact_defaults）与 S10-B 审批 §31/§32 记录完全一致，非本 release 引入。

## 28. Offline Transferability

```text
本地 git commit（a633b48）可 git archive / git bundle 离线转移；
Manifest §3.1 SHA256SUMS 可在 Merchant 侧本地校验；
不要求 Merchant maintenance 期间 git pull / fetch / 下载依赖。
```

## 29. Secret Audit

```text
PASS：release tree 无 .env.production.local / .pem / .key / credential；
.env.production.example 仅占位符（<请填写...>）；
无真实 DB password / JWT secret / Douyin secret / 生产 SHA（无 93094f0 硬编码）；
wrapper 无 build/pull/tag/migration/DB 副作用。
RELEASE_PACKAGE_FREEZE_BLOCKED_BY_SECRET = NO
```

## 30. Main Worktree Protection

```text
HEAD 保持 36fe68a ✓（冻结前记录复核）
主工作区 status 与冻结前一致 ✓（仅新增 manifest/报告 untracked，属本窗口预期产物）
无 git clean / reset --hard / destructive checkout ✓
主工作区 remediation candidate 未丢失 ✓
```

## 31. RF-T01~T18 Matrix

| 测试 | 内容 | 结果 |
|---|---|---|
| RF-T01 | base identity = 9db3f58 | ✅ PASS |
| RF-T02 | release tree created from exact base（parent=9db3f58） | ✅ PASS |
| RF-T03 | approved S10-B runtime files present | ✅ PASS |
| RF-T04 | wrapper content matches approved candidate | ✅ PASS |
| RF-T05 | per-service image identity compose config present | ✅ PASS（37 passed 动态测试） |
| RF-T06 | host env sanitization mechanism present | ✅ PASS |
| RF-T07 | fail-closed preflight present | ✅ PASS |
| RF-T08 | canonical9000-only path present | ✅ PASS |
| RF-T09 | application/business diff from 9db3f58 = none | ✅ PASS |
| RF-T10 | migration diff from 9db3f58 = none | ✅ PASS |
| RF-T11 | alembic head = 0034 | ✅ PASS |
| RF-T12 | 0035 Alembic migration absent | ✅ PASS |
| RF-T13 | 9100 migration upgrade not introduced | ✅ PASS |
| RF-T14 | S10-B targeted tests PASS | ✅ PASS（37 passed） |
| RF-T15 | fresh reconstruction from frozen artifact PASS | ✅ PASS |
| RF-T16 | manifest hashes PASS | ✅ PASS |
| RF-T17 | offline transferability established | ✅ PASS |
| RF-T18 | main worktree remains intact | ✅ PASS |

## 32. Blocking Findings

```text
NONE
```

## 33. Non-Blocking Findings

```text
NB-1  两个 env profile pre-existing failure 非本 release 引入（与审批记录一致）。
NB-2  ROLLBACK_SOURCE_COMMIT_PROVENANCE 仍 UNVERIFIED（S10-B 已知 debt，非本窗口）。
NB-3  生产真实 image identity 未写入 artifact（符合设计；由 Production Execution 按 manifest 契约显式注入）。
NB-4  本窗口未构建任何生产镜像（构建留给后续 authorized release build）。
```

## 34. Freeze Verdict

```text
RELEASE_PACKAGE_FREEZE_READY
```

满足 READY 全部条件（§46 任务书）：immutable artifact identity ✓ / base=9db3f58 proven ✓ / application code unchanged ✓ / migration head=0034 ✓ / 0035 excluded ✓ / approved S10-B mechanism present ✓ / artifact reproducible ✓ / manifest+hash verification passes ✓ / offline-capable ✓ / no secrets ✓ / main worktree protected ✓。

## 35. Blocker-1 Status

```text
BLOCKER-1 = CANDIDATE_RESOLVED
RELEASE_ENGINEERING_ARTIFACT_IDENTITY = FROZEN
（仍需后续 Focused Production Authorization 独立认可，本窗口不自行升级为 GO）
```

## 36. Production Authorization Status

```text
PRODUCTION_AUTHORIZATION     = STILL NO_GO（本窗口未修改 NO_GO 报告）
PRODUCTION_MIGRATION_AUTHORIZED = NO
PRODUCTION_BUILD_AUTHORIZED  = NO
```

## 37. Next Stage

```text
并行：Merchant M-AUTH 只读取证（BLOCKER-2/BLOCKER-3）
随后：FOCUSED PRODUCTION AUTHORIZATION（重新裁定，本窗口产物作为输入）
未来 Production Execution：根据 frozen artifact（a633b48）构建/加载 exact target image → 校验 provenance → 按 S10-B preflight/canonical 命令执行
```

## 38. Git Discipline / Cleanup

```text
DO NOT PUSH（release/b7-0034-s10b-freeze 为本地持久 ref）
主工作区 DO NOT COMMIT
临时 worktree（release-0034-s10b-freeze / repro-check-release-0034）可保留用于复现或后续清理；
分支 ref 已持久化，清理 worktree 后 commit 仍可经 `git show a633b48` / `git show release/b7-0034-s10b-freeze` 访问。
```

## 39. Documentation Impact Check

- 本轮新增 2 份文档（Release Manifest + 本 Freeze 报告），未修改活动治理文档（CLAUDE.md/AGENTS.md/docs/ai 01~05/Reality Map）。
- `PRODUCTION_BASELINE_CATCHUP_0028_TO_0034_PRODUCTION_AUTHORIZATION.md` 的 NO_GO **不修改**（历史审计事实；由后续 Focused Authorization 重新裁定）。
- 无其他活动文档结论过期。
- 结论：除新增本窗口报告与 manifest 外，无文档影响。

## 40. STOP

Freeze 完成，立即停止。未 push / 未 touch Merchant / 未迁移 / 未 build 生产镜像 / 未 apply 0035 / 未升级 9100 / 未进入 P2 cutover / P3a / P3b / RB-10。
