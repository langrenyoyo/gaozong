# S10-B：9000/9100 部署镜像身份隔离 — Release Engineering Implementation（含 Correction-1）

> 本窗口为 **S10-B Release Engineering Implementation + Implementation Correction-1**（独立实施/修正窗口）。
> 产物为 implementation candidate + correction candidate，**未 commit / 未 push / 未操作 Merchant**。
> 独立实施审批裁决 `APPROVED_WITH_CORRECTIONS`（C1~C5 MUST_APPLY_BEFORE_REHEARSAL），
> 本窗口已完成 C1~C5，最终状态只能为 `S10_B_IMPLEMENTATION_CORRECTION_CANDIDATE_READY`（见 §Correction-1），
> 待独立 FOCUSED-CORRECTION-APPROVAL 复核。

```text
S10_B_IMPLEMENTATION_CONTRACT      = FROZEN（C3，来自 Production Baseline Catch-up 0028→0034 Design）
S10_B_IMPLEMENTATION_CANDIDATE     = READY（原实施窗口）
C3_IMPLEMENTATION                  = APPROVED_WITH_CORRECTIONS（独立实施审批）
C3_INDEPENDENT_APPROVAL            = APPROVED_WITH_CORRECTIONS
C3                                = NOT_CLOSED_PENDING_CORRECTIONS（Correction-1 已完成，待 FOCUSED 复核）
C1 / C2 / C3 / C4 / C5            = APPLIED / CANDIDATE_CLOSED（本窗口）
HOST_ENV_POLLUTION_GAP            = CANDIDATE_RESOLVED
S10_B_IMPLEMENTATION_CORRECTION   = CANDIDATE_READY_FOR_FOCUSED_APPROVAL
REHEARSAL_ENTRY_GATE              = STILL_BLOCKED
PRODUCTION_MIGRATION_AUTHORIZED   = NO
```

---

## 1. Implementation Scope（严格范围）

本窗口只做 **release-engineering 层**改造，解除 9000 与 9100 的 runtime deployment image identity coupling：

```text
改前：auto-wechat-api（9000） image: xg-ai-system-backend:latest
      xg-douyin-ai-cs（9100） image: xg-ai-system-backend:latest
      → 9000/9100 实际运行 IMAGE_ID 均为 sha256:93094f0...（M3 生产实测，S10 VERIFIED HARD GATE）

改后：auto-wechat-api（9000） image: ${AUTO_WECHAT_API_IMAGE:-xg-ai-system-backend:latest}
      xg-douyin-ai-cs（9100） image: ${XG_DOUYIN_AI_CS_IMAGE:-xg-ai-system-backend:latest}
      → 9000/9100 可分别指派独立 immutable image identity（RG-1/RG-2）
```

解除的是 `RUNTIME_DEPLOYMENT_IDENTITY_COUPLING`，**不是** Dockerfile sharing / source sharing / repository sharing（9000/9100 继续共享 `Dockerfile.backend.dev` 与源码仓库，属既有事实）。

### 修改文件清单（S10_B_CANDIDATE_DIFF = 原实施窗口）

```text
docker-compose.yml                 修改：两处 image 字段 env 化 + 顶部注释（S10-B 机制说明）
.env.production.example            修改：新增 02-A「Compose 部署镜像身份」分组（两个 IMAGE 变量 + 语义注释）
docs/config/ENV_VARIABLE_REFERENCE.md  修改：第 1 节新增「Compose 部署镜像身份」小节（变量登记）
tests/test_s10_b_image_identity_isolation.py  新增：RE-T01~T11 + Correction-1 C1/C2/C3 测试
docs/architecture/remediation/S10_B_9000_9100_IMAGE_IDENTITY_ISOLATION_IMPLEMENTATION.md  新增：本报告
```

准确计数：**3 个修改 + 2 个新增**（原报告误写「2 修改 + 3 新增」，已在 Correction-1 C5 原位修正）。

### 修改文件清单（S10_B_CORRECTION_DIFF = Correction-1 窗口）

```text
scripts/release_9000_s10b.py       新增：canonical 9000-only release wrapper + fail-closed preflight（C1/C2/C3 载体）
tests/test_s10_b_image_identity_isolation.py  修改：修复宿主环境污染（C3 根因）+ 补 preflight/序列/命令合同测试
.env.production.example            修改：02-A 分组修正（消费事实 + host env precedence 警告 + canonical 命令 + preflight）
docs/config/ENV_VARIABLE_REFERENCE.md  修改：Compose 镜像身份小节修正（同上）
docs/architecture/remediation/S10_B_9000_9100_IMAGE_IDENTITY_ISOLATION_IMPLEMENTATION.md  修改：本报告（C5 修正 + Correction-1 章节）
```

### 未修改 / 明确不触碰

```text
app/**            NO（无业务代码）
apps/**           NO（含 apps/xg_douyin_ai_cs、apps/compute）
migrations/**     NO（无数据库迁移）
frontend/**       NO（无前端）
19000             NO（Local Agent 业务代码）
Dockerfile*       NO（保持共享 Dockerfile.backend.dev，C3.1 明确不要求独立 9100 Dockerfile）
docker-compose.dev.yml   NO（dev 独立编排用 auto-wechat-backend-dev:local，不消费 IMAGE 变量）
docker-compose.staging.yml NO（字面量 :staging 覆盖继续有效）
scripts/production_pg_*.sh NO（继续用 --env-file .env.production.local，IMAGE 变量随其自然加载）
```

---

## 2. PRE_EXISTING_WORKTREE（前置未提交文件，非本窗口产物）

原实施窗口开始前 `git status --short` 记录（4 个 untracked remediation 文件，均非本窗口产生，**未触碰**）：

```text
?? docs/architecture/remediation/P2_M04_COORDINATED_CUTOVER_READINESS.md
?? docs/architecture/remediation/PRODUCTION_BASELINE_CATCHUP_0028_TO_0034_DESIGN.md
?? docs/architecture/remediation/PRODUCTION_BASELINE_CATCHUP_0028_TO_0034_DESIGN_APPROVAL.md
?? docs/architecture/remediation/PRODUCTION_SCHEMA_BASELINE_CATCHUP_0028_TO_0034_REALITY_AUDIT.md
```

Correction-1 窗口开始前 `git status --short` 追加记录（原实施窗口产物，现为 S10_B_IMPLEMENTATION 归属）：

```text
?? docs/architecture/remediation/S10_B_9000_9100_IMAGE_IDENTITY_ISOLATION_APPROVAL.md
?? docs/architecture/remediation/S10_B_9000_9100_IMAGE_IDENTITY_ISOLATION_IMPLEMENTATION.md
?? tests/test_s10_b_image_identity_isolation.py
 M .env.production.example / docker-compose.yml / docs/config/ENV_VARIABLE_REFERENCE.md
```

全程 `NO git clean / NO destructive reset`，未删除、未覆盖、未归因这些文件。

---

## 3. Repository Reality（候选前基线事实，只读核实）

以下为原实施窗口修改前的仓库基线事实，非本窗口产物：

- `docker-compose.yml` 是唯一 production 主入口：9000 与 9100 均 `image: xg-ai-system-backend:latest` + `build: Dockerfile.backend.dev`，通过 `command` 区分入口。
- 仓库内无单独 9100 Dockerfile；9000/9100 共享 `Dockerfile.backend.dev` 与源码仓库（C3.1：既有事实，**不是本窗口要解除的对象**）。
- `.env.production.example` 无既有 image 变量；`test_env_profile_templates.py` 只扫描 app/apps/frontend 代码读取点与三模板，compose 级 `${VAR}` 不在扫描范围。
- production 部署脚本（`scripts/production_pg_*.sh`）已固定 `--env-file .env.production.local` 习惯（`test_production_pg_scripts_default_to_production_local_env` 强制）—— 选择 RE-B 的决定性事实。
- staging 先例：`docker-compose.yml + docker-compose.staging.yml` override 组合，staging 以字面量覆盖 image 为 `:staging`。

---

## 4. RE-A Review（Compose Override）

**方案**：新增 `docker-compose.production.yml` override 文件，仅覆盖 `auto-wechat-api.image` 与 `xg-douyin-ai-cs.image`；生产部署命令全部改为 `docker compose -f docker-compose.yml -f docker-compose.production.yml ...`。

**评估**（对照 C3.2 选择原则）：

| 维度 | 结论 |
|---|---|
| MINIMUM_DIFF | 差（需新增整个 override 文件 + 改造所有生产部署命令路径） |
| EXPLICIT_PRODUCTION_IDENTITY | 高（override 文件显式声明） |
| BACKWARD_COMPATIBLE_DEFAULT | 强（漏带 override 回落 :latest） |
| REHEARSABLE | 高（构造不同 override 组合） |
| ROLLBACK_FRIENDLY | 高（改 override 中 9000 image） |
| NO_9100_FUNCTIONAL_CHANGE | 满足（仅 image 选择） |
| operator error risk | **中**（漏带 `-f` 即回退共享 :latest，且所有既有部署脚本/命令都要改） |
| 与既有脚本习惯 | **冲突**（production_pg_*.sh 均不带 -f，改造面大） |

**结论**：可行但不首选。最大短板是「必须记得带 `-f` override，漏带即回落到歧义共享 `:latest`」+ 需要改造既有部署命令习惯。

---

## 5. RE-B Review（Per-Service Image Env Variables）

**方案**：把两处 image 字段改为 env 默认值插值；IMAGE 变量写入 `.env.production.example`（production 模板）。

```text
auto-wechat-api:
  image: ${AUTO_WECHAT_API_IMAGE:-xg-ai-system-backend:latest}
xg-douyin-ai-cs:
  image: ${XG_DOUYIN_AI_CS_IMAGE:-xg-ai-system-backend:latest}
```

**评估**：

| 维度 | 结论 |
|---|---|
| MINIMUM_DIFF | 优（docker-compose.yml 两行 + env example 分组 + 文档 + 测试） |
| EXPLICIT_PRODUCTION_IDENTITY | 高（变量名显式，`docker compose config` 可审计每个 service 解析值） |
| BACKWARD_COMPATIBLE_DEFAULT | 强（未设 env 回落 :latest，与现状完全一致，RG-7） |
| REHEARSABLE | 高（rehearsal 设不同 env 组合即可验证 BR-24~30） |
| ROLLBACK_FRIENDLY | 高（改 AUTO_WECHAT_API_IMAGE 即回滚 9000，9100 不动） |
| NO_9100_FUNCTIONAL_CHANGE | 满足（仅 image 字段，无业务逻辑） |
| operator error risk | **低**（变量在 .env.production.local 显式承载，compose config 可审计；漏设回落 :latest 与现状一致） |
| 与既有脚本习惯 | **天然吻合**（production_pg_*.sh 已用 --env-file .env.production.local，IMAGE 变量随 env-file 进入 Compose 插值，零脚本改动） |

**结论**：RE-B 更贴合仓库现实，且 diff 最小。

---

## 6. Chosen Mechanism

```text
CHOSEN = RE-B（Per-Service Image Env Variables）
NOT_CHOSEN = RE-A（Compose Override）
```

### Why Chosen（选择理由，对照 C3.2 实施窗口二选一约束）

1. **MINIMUM_DIFF**：RE-B 只改 docker-compose.yml 两处 image + env example 分组 + 参考文档 + 测试 + 报告；RE-A 需新增整个 override 文件并改造所有生产部署命令/脚本习惯。
2. **与既有 production 脚本习惯天然吻合**：`scripts/production_pg_*.sh` 已被测试强制 `--env-file .env.production.local`，RE-B 的 IMAGE 变量随该 env-file 自然进入 Compose 插值，**零部署脚本改动**；RE-A 则要求所有部署命令额外带 `-f`，漏带即回退共享 `:latest`。
3. **EXPLICIT_PRODUCTION_IDENTITY**：`AUTO_WECHAT_API_IMAGE` / `XG_DOUYIN_AI_CS_IMAGE` 显式承载 image ref，`docker compose config` 可在部署前审计每个 service 的实际解析值。
4. **BACKWARD_COMPATIBLE_DEFAULT**：未设 env 时两个 service 均解析为 `xg-ai-system-backend:latest`，与当前生产行为完全一致（RG-7）。
5. **REHEARSABLE / ROLLBACK_FRIENDLY**：BR-24~30 isolated rehearsal 与未来 9000 rollback 都只需改 env 值，9100 全程不受影响。
6. **NO_9100_FUNCTIONAL_CHANGE**：仅 image 选择字段，不触碰任何 9100 业务/配置。

未混合 RE-A/RE-B（C3.2「不得混合扩大范围」）。

---

## 7. Runtime Guarantees（RG-1~RG-8）

证据等级说明（Correction-1 C5 修正）：本窗口只达到 `COMPOSE_CONFIG_VERIFIED / STATIC_TEST_VERIFIED / DESIGN_CONTRACT_VERIFIED / PREFLIGHT_STATIC_VERIFIED / COMMAND_CONTRACT_VERIFIED`，**未达到容器运行、演练或生产运行验证**（容器运行 / 生产运行验证 = NOT VERIFIED）。

```text
RG-1  9000 image identity 可被独立指定。        COMPOSE_CONFIG_VERIFIED（AUTO_WECHAT_API_IMAGE，RE-T02/COR-T06）
RG-2  9100 image identity 可被独立指定。        COMPOSE_CONFIG_VERIFIED（XG_DOUYIN_AI_CS_IMAGE，RE-T03）
RG-3  变更 9000 不要求变更 9100。               COMPOSE_CONFIG_VERIFIED（只设 9000 时 9100 回落默认，RE-T05）
RG-4  recreate 9000 不 recreate 9100。          COMPOSE_CONFIG_VERIFIED + STATIC_TEST_VERIFIED（9000/9100 无 depends_on 耦合；
                                               完整安全命令合同见 C1，canonical wrapper scripts/release_9000_s10b.py）
RG-5  9000 rollback image 可被独立选择。         COMPOSE_CONFIG_VERIFIED（AUTO_WECHAT_API_IMAGE 指回 preserved old image，
                                               STATE A/B/C 序列 COR-T12~T15）
RG-6  9100 DB/migration 不被 9000 deployment 触及。 STATIC_TEST_VERIFIED（无 migration 命令引入；9100 Freeze Contract §9）
RG-7  默认 local/dev 行为保持兼容。             COMPOSE_CONFIG_VERIFIED（未设 env 两 service 均 :latest；dev 独立 compose 不受影响；
                                               staging 组合仍 :staging，RE-T01/RE-T04-staging）
RG-8  生产 catch-up 可避免歧义共享 mutable :latest。 DESIGN_CONTRACT_VERIFIED + PREFLIGHT_STATIC_VERIFIED
                                               （IMAGE 变量强制显式 immutable identity；C2 fail-closed preflight 拒绝 :latest）
```

---

## 8. Production Contract

```text
AUTO_WECHAT_API_IMAGE  = <exact immutable target image built from 9db3f58>（catch-up 时）
XG_DOUYIN_AI_CS_IMAGE  = <exact preserved old image identity，等价 sha256:93094f0...>（catch-up 时冻结）
默认（未配置）         = xg-ai-system-backend:latest（开发/默认行为，非 catch-up 合法身份）
```

- 两变量构成 **9000 ≠ 9100 两个独立 image contract**（`docker compose config` 可逐 service 审计）。
- 准确限定（C5 修正）：本窗口**未把完整生产 identity 硬编码到 Compose/env 配置**——未写 `sha256:93094f0...`、未写 9db3f58 future target digest、未写生产 secret；env example 模板值保持默认 `:latest` 并在注释中声明「正式 catch-up 必须替换为 immutable identity」。生产真实值由 production 执行窗口通过 `.env.production.local` 或受控 release input 提供，本窗口未读取/未修改 Merchant 文件。
- 未修改 production_pg_*.sh（RE-B 无需改动部署脚本）。

---

## 9. 9100 Freeze Boundary

```text
9100_CODE_CHANGE   = NO
9100_DB_CHANGE     = NO
9100_MIGRATION = NO
9100_PRODUCTION_DB = 0003（保持不变）
```

- 本窗口实现**不含** `alembic upgrade` / 9100 restart / recreate / migration helper（RE-T08 断言）。
- 9100 image 由 `XG_DOUYIN_AI_CS_IMAGE` 独立承载，与 9000 完全解耦；9000 部署路径只操作 `auto-wechat-api`（canonical command 唯一 service target，COR-T05）。
- 独立 9100 `0003→0005` 治理边界（C10）不属于本任务，维持原样。

---

## 10. Rollback Contract

```text
未来回滚：
  9000 target image → 把 AUTO_WECHAT_API_IMAGE 改回 preserved old image identity 即可
  9100 image ref 不变 / 容器不 recreate / DB 保持 0003
ROLLBACK_RUNTIME_IMAGE_IDENTITY   = COMPOSE_CONFIG_VERIFIED（机制支持：STATE A/B/C 序列证明 9000 可独立指回 preserved old image）
ROLLBACK_SOURCE_COMMIT_PROVENANCE = UNVERIFIED / NON_BLOCKING（旧镜像无 provenance label，本任务不试图修复历史 provenance，C3.6）
```

---

## 11. Mutable `:latest` Boundary

- `xg-ai-system-backend:latest` 继续作为 **development / default fallback**（RG-7，未显式配置时回落）。
- **正式 production baseline catch-up MUST NOT 依赖歧义共享 mutable `:latest`**（RG-8 / RE-AC11）：catch-up 期间 9000 用 immutable target image、9100 用 frozen old image identity，二者由显式 env 变量承载，`docker compose config` 部署前可审计；**C2 fail-closed preflight 在 rehearsal/production 层拒绝 :latest**。
- 本任务不强制「整个项目永远不用 latest」，只治理正式 catch-up 的部署身份。

---

## 12. Target Provenance Contract

本任务**不负责真正 build 9db3f58 production image**（生产构建留给后续 authorized release build）。

但配置合同与文档要求后续 target build 至少存在一种可追踪身份：

```text
immutable tag（如 xg-ai-system-backend:9db3f58-<ts>）
image digest
OCI revision label
build manifest linking 9db3f58
→ 未来必须能证明 TARGET_9000_IMAGE ↔ 9db3f58
```

- 不得继续只依赖 `latest`。
- 旧 provenance debt（`ROLLBACK_SOURCE_COMMIT_PROVENANCE = UNVERIFIED`）**不得复制到新 target**（新 target 须带 provenance，C3.6）。
- `AUTO_WECHAT_API_IMAGE` / `XG_DOUYIN_AI_CS_IMAGE` 是承载该 immutable identity 的部署契约入口。

---

## 13. RE-AC01~AC12 Matrix（Correction-1 复核后）

| AC | 验收 | 证据 | 状态 |
|---|---|---|---|
| RE-AC01 | 默认 compose 行为保持有效 | RE-T01：未设 env 两 service 均 `:latest`；staging 组合仍 `:staging` | ✅ PASS |
| RE-AC02 | 9000 显式 image 可独立指定 | RE-T02：设 AUTO_WECHAT_API_IMAGE → 9000 改变 | ✅ PASS |
| RE-AC03 | 9100 显式 image 可独立指定 | RE-T03：设 XG_DOUYIN_AI_CS_IMAGE → 9100 改变 | ✅ PASS |
| RE-AC04 | 9000/9100 同时解析不同 ref | RE-T04：两变量不同值同时生效 | ✅ PASS |
| RE-AC05 | 只改 9000 identity 后 9100 不变 | RE-T05：9100 config 与默认逐位一致 | ✅ PASS |
| RE-AC06 | 9000 有 service-specific recreate 路径 | canonical command（C1）：`up -d --no-deps --no-build auto-wechat-api`；依赖图不含 9100 | ✅ PASS |
| RE-AC07 | 9000 rollback image 可独立选择 | RE-T07 + STATE A/B/C（COR-T12~T15） | ✅ PASS |
| RE-AC08 | 身份机制不引入 migration 命令 | RE-T08：无 alembic upgrade / upgrade head | ✅ PASS |
| RE-AC09 | 不触发 9100 0003→0005 | §9 9100 Freeze Boundary + RE-T08 | ✅ PASS |
| RE-AC10 | 无业务/API/RAG 行为变更 | 仅 image 字段改动，app/apps/migrations 零改动（C4 真实 diff audit） | ✅ PASS |
| RE-AC11 | 文档显式禁止歧义共享 mutable :latest | .env.production.example 02-A + 报告 §11 + C2 preflight 拒绝 | ✅ PASS |
| RE-AC12 | 支持 BR-24~30 rehearsal | §14 + COR-T12~T15 + preflight 机制就绪 | ✅ PASS（MECHANISM_READY_FOR_REHEARSAL） |

---

## 14. BR-24~BR-30 Compatibility（Correction-1 修正后）

统一状态（C5 修正）：

```text
BR-24_TO_30 = MECHANISM_READY_FOR_REHEARSAL
BR-24_TO_30_VERIFIED = NO
容器运行验证（container runtime）= NOT VERIFIED
生产运行验证（production runtime）= NOT VERIFIED
BR-24~BR-30 容器运行验证 = NOT EXECUTED（留给下一独立 Rehearsal 窗口）
```

机制映射（已就绪，未执行）：

```text
BR-24  deployment identities isolated        ← AUTO_WECHAT_API_IMAGE ≠ XG_DOUYIN_AI_CS_IMAGE 可分别指定（RE-T04）+ preflight 拒绝相同共享 mutable（C2-T P4）
BR-25  target9000 only changes/recreates      ← 只设 AUTO_WECHAT_API_IMAGE + canonical `up -d --no-deps --no-build auto-wechat-api`（C1）
BR-26  9100 image identity unchanged          ← 不设 XG_DOUYIN_AI_CS_IMAGE（或冻结值），9100 保持 frozen（RE-T05 / STATE A/B/C）
BR-27  9100 DB remains 0003                   ← 9100 冻结，无 migration 路径（RE-T08 / §9）
BR-28  9100 不 recreate / migration 不运行     ← 9000 部署路径不触碰 9100（canonical command 唯一 target + 依赖图，C1）
BR-29  target9000 + schema0034 → /ready 200   ← 依赖 9000 target image + 0034 迁移（后续 rehearsal 执行，机制已就绪）
BR-30  rollback9000 without touching9100      ← 改 AUTO_WECHAT_API_IMAGE 即回滚（RE-T07 / STATE C）
```

Rehearsal 载体：`ISOLATED_REHEARSAL_TOPOLOGY`（§47 设计文档）第 6 项 `SERVICE_SPECIFIC_IMAGE_SELECTION_MECHANISM` 已由本实现落地为 RE-B env 变量机制 + `scripts/release_9000_s10b.py` wrapper/preflight。

---

## 15. Required Tests（Correction-1 复核后执行结果）

### 15.1 S10-B 专项测试（原 RE-T01~T11 + Correction-1 新增）

测试文件：`tests/test_s10_b_image_identity_isolation.py`

| 测试 | 内容 | 结果 |
|---|---|---|
| RE-T01 | compose config 默认/基线解析（两 service 均 `:latest`） | ✅ PASS |
| RE-T02 | 显式 9000 image override（9100 默认） | ✅ PASS |
| RE-T03 | 显式 9100 image override（9000 默认） | ✅ PASS |
| RE-T04 | 9000/9100 不同 ref 同时生效 | ✅ PASS |
| RE-T04-staging | staging 组合仍 `:staging` | ✅ PASS |
| RE-T05 | 只改 9000 → 9100 config 不变 | ✅ PASS |
| RE-T06 | service-specific recreate 路径（静态 + 动态 depends_on 图） | ✅ PASS |
| RE-T07 | rollback 9000 image 选择 | ✅ PASS |
| RE-T08 | 无 migration 命令引入 | ✅ PASS |
| RE-T09 | scope guard（含 S10_B_CORRECTION_DIFF 记录） | ✅ PASS |
| RE-T10 | BR-24~30 rehearsal 兼容契约 | ✅ PASS |
| RE-T11 | mutable `:latest` boundary 文档化 | ✅ PASS |
| C2-T01~T11 | fail-closed preflight（valid / missing / empty / latest / expected mismatch / env missing / config invalid） | ✅ PASS |
| C2-P4 边界 | 相同 mutable 拒绝 / 相同 immutable（rollback/freeze 合法）允许 | ✅ PASS |
| C2-digest | `repo@sha256:<digest>` immutable 形态接受 | ✅ PASS |
| Host Pollution ×3 | hostile host env 不改变 testcase 解析结果；compose_env 移除 IMAGE 变量 | ✅ PASS |
| STATE A/B/C | upgrade / freeze / rollback 全序列真实解析 | ✅ PASS |
| service targeting | canonical command 唯一 target `auto-wechat-api`，无 `xg-douyin-ai-cs` | ✅ PASS |
| C1 contract | canonical command 含 --env-file / --no-deps / --no-build / 单 target；不用 restart 作镜像切换 | ✅ PASS |
| C5 evidence | 报告证据等级不超限；env 文档含 precedence 警告 | ✅ PASS |

运行结果：`python -m pytest tests/test_s10_b_image_identity_isolation.py -v` → **37 passed**。

### 15.2 既有测试套件回归（Correction-1 复核）

`python -m pytest tests/test_env_profile_templates.py` → **48 passed, 2 failed**。

两个 failure 均为 **PRE-EXISTING 基线失败，与本窗口零交集**（真实 Git diff audit §C4 证明改动文件清单不含其涉及文件）：

```text
1. test_all_code_variables_are_classified：
   未分类变量清单全为既有代码读取点（LAS_*/TOS_*/ARK_*/DAILY_REPORT_*/CONTACT_INVALID_FOLLOWUP_*/
   MILVUS_SEARCH_HARD_TIMEOUT_SECONDS 等），**不含** AUTO_WECHAT_API_IMAGE / XG_DOUYIN_AI_CS_IMAGE
   （compose 级变量不在 app/apps/frontend 代码扫描范围）。失败源 = 仓库既有未登记变量（其他窗口引入
   后未同步分类表），非本窗口。

2. test_outbox_ten_variables_exact_defaults：
   失败在 .env.development.example（AI_AUTO_REPLY_OUTBOX_INTERVAL_SECONDS=10 期望 60），
   本窗口未改 dev example。
```

结论：这两个 pre-existing failure **不是 S10-B 引入的 REGRESSION**（§31/§32：baseline evidence = 原实施窗口报告 §15 与独立实施审批 §14.3 均记录同一组 2 failed；S10-B_CORRECTION_DIFF 未触碰相关文件）。

未启动真实生产服务；全部基于 `docker compose config` 静态/动态解析 + wrapper preflight（dry-run/static，不启动容器）。

---

## 16. Scope Guard（Correction-1 真实 Git diff audit 摘要）

完整真实 Git diff audit 见 §Correction-1 C4。结论：

```text
S10_B_CORRECTION_DIFF 文件分类：
  release-engineering / config / tests / report = S10_B_CORRECTION_1（本窗口）
  .env.production.example / docker-compose.yml / docs/config/ENV_VARIABLE_REFERENCE.md = S10_B_IMPLEMENTATION（原窗口）
  4 个 catch-up/P2 remediation 文档 + S10-B 审批文档 = PRE_EXISTING / S10_B_IMPLEMENTATION 归属
  app/** / apps/** / migrations/** / frontend/** = ZERO S10-B DIFF（NOT INTRODUCED_BY_S10_B）
UNKNOWN = NONE
SCOPE_VIOLATION = NONE_DETECTED
```

---

## 17. Known Limitations（Correction-1 C5 修正后）

1. **机制提供显式隔离入口，但不防漏设/误操作**：RE-B 靠 env 显式承载 identity；Correction-1 新增的 `scripts/release_9000_s10b.py` fail-closed preflight 会在 rehearsal/production 执行前**拒绝** missing/empty/:latest/相同共享 mutable/expected 不一致，把「漏设」从 fail-open 变为 fail-closed。但 preflight 之外的人工直接调用 `docker compose up`（绕过 wrapper）仍可回落 `:latest`——这是执行窗口纪律问题，机制本身不越权阻止。
2. **`build:` 仍与 `image:` 共存**：docker-compose.yml 保留 `build: Dockerfile.backend.dev`（C3.1 明确不要求删共享 Dockerfile）。canonical command 带 `--no-build` 禁止 recreate 时基于当前 source 意外重建；对冻结的 9100，catch-up 纪律是**不对 9100 执行任何 up/build**（§9）。
3. **provenance 未修复**：旧 9100 镜像 `ROLLBACK_SOURCE_COMMIT_PROVENANCE = UNVERIFIED`，本任务不修复历史 provenance（C3.6，NON_BLOCKING）。
4. **生产真实值未验证**：生产 `.env.production.local` 实际配置与 image 引用未读取（本窗口不操作 Merchant）；生产侧最终身份由 production 执行窗口按 §8 契约 + preflight 落实。
5. **preflight 不做 registry-side immutability 证明**：仅拒绝精确 known mutable `:latest` 后缀；不验证 registry 上 tag 的不可变性 / digest 存在性（§12 简单规则，文档已声明范围）。

---

## 18. Non-Blocking Debt

- `ROLLBACK_SOURCE_COMMIT_PROVENANCE = UNVERIFIED`（C3.6，非阻塞）：future preflight 把 old runtime image 用 `docker tag` 固化保存为 immutable rollback reference。
- 生产部署 runbook 尚未写入「catch-up 前必须运行 preflight + 审计两个 service image」的强制步骤（属 production execution 窗口文档，非本窗口 release-engineering 实现）。

---

## 19. Candidate Verdict（Correction-1 后）

```text
S10_B_IMPLEMENTATION_CORRECTION = CANDIDATE_READY_FOR_FOCUSED_APPROVAL
C1 = APPLIED / CANDIDATE_CLOSED
C2 = APPLIED / CANDIDATE_CLOSED
C3 = APPLIED / CANDIDATE_CLOSED
C4 = APPLIED / CANDIDATE_CLOSED
C5 = APPLIED / CANDIDATE_CLOSED
HOST_ENV_POLLUTION_GAP = CANDIDATE_RESOLVED
C3 = STILL_NOT_CLOSED_PENDING_FOCUSED_APPROVAL
REHEARSAL_ENTRY_GATE = STILL_BLOCKED
PRODUCTION_MIGRATION_AUTHORIZED = NO
```

（非 APPROVED / 非 C3 CLOSED / 非 REHEARSAL READY / 非 PRODUCTION READY。）

---

## 20. Next Stage

```text
下一阶段：S10-B-9000-9100-IMAGE-IDENTITY-ISOLATION FOCUSED-CORRECTION-APPROVAL
  → 独立复核 C1~C5（不从头重审整个 RE-B）
  → 复核通过 → C3 CLOSED → REHEARSAL_ENTRY_GATE OPEN
  → PRODUCTION-BASELINE-CATCHUP-0028-TO-0034-ISOLATED-REHEARSAL（下一独立阶段，BR-24~30）
```

---

## 21. Git Discipline

本窗口 **DO NOT COMMIT / DO NOT PUSH**。implementation candidate + correction candidate（§1 文件清单）留给独立 FOCUSED-CORRECTION-APPROVAL 窗口审阅。

---

## 22. STOP

Candidate + correction + tests + real diff audit + 文档修正已完成，立即停止。

- 未 commit / 未 push
- 未运行 baseline rehearsal（0028→0034 / BR-01~30 / BR-24~30 属下一独立阶段）
- 未 build/tag 生产镜像、未 docker pull
- 未 touch Merchant
- 未 migrate 生产（0028→0034 未执行）
- 未 deploy target9000 / 未 recreate / restart 任何生产容器
- 未 restart/recreate/upgrade 9100
- 未 apply 0035
- 未进入 P3a / RB-10

---

# Correction-1 章节（独立实施审批 C1~C5 闭环证据）

> 审批裁决：`C3_IMPLEMENTATION = APPROVED_WITH_CORRECTIONS`，C1~C5 = MUST_APPLY_BEFORE_REHEARSAL。
> 本窗口唯一目标：关闭 C1~C5，不重新设计 RE-B，不跑 baseline rehearsal。

## Correction-1 Scope

允许修改：release-engineering files / minimal tests / minimal deployment/preflight helper / implementation report / relevant env/template documentation。严格禁止 app/**、apps/**、migrations/**、frontend/**、19000、9100 RAG/business、Prompt、Milvus、API、DB model、Alembic revision；禁止 9100 0003→0005、0035、P2 production cutover、P3a、RB-10。

## Host Environment Pollution Root Cause（C3）

**根因（真实验证）**：Docker Compose 插值 precedence 是 **宿主 shell env > `--env-file` 文件**。

用真实 `docker compose config --format json` 验证：

```text
Case1 无宿主 env，仅 --env-file    → 9000=repo/from-envfile:9000（env-file 生效）
Case2 宿主 shell 导出 hostile 变量 + --env-file → 9000=hostile/9000:bad（宿主覆盖 env-file）
Case3 wrapper 语义：先 unset 宿主 IMAGE 变量再 --env-file → 9000=repo/from-envfile:9000（unset 后 env-file 生效）
Case4 env-file 中空值（AUTO_WECHAT_API_IMAGE=） → resolved=xg-ai-system-backend:latest（${VAR:-default} 对 empty 也回落）
```

原候选测试声称「`--env-file` 覆盖宿主环境」**不成立**，导致独立审批在宿主预设 IMAGE 变量后定向运行 RE-T01~03 出现 **3 failed**（宿主污染）。

**修复（非清理 shell 后重跑）**：
- 新增 `scripts/release_9000_s10b.py::compose_env()`：所有 compose 子进程调用以 os.environ 为基底、移除 `AUTO_WECHAT_API_IMAGE` / `XG_DOUYIN_AI_CS_IMAGE` 两个宿主变量后再执行 → 插值真正落在显式 env file 上。
- 测试全部通过 `compose_env()`（或 `host_env` 参数合并后再移除）调用 compose，任何测试不再依赖宿主环境。
- 新增 `TestHostEnvPollutionRegression`：pre-set hostile host env（9000=host-wrong-image / 9100=host-wrong-image）下，preflight 与真实 compose config 仍解析到 testcase 指定值。

```text
HOST_ENV_POLLUTION_REGRESSION = CLOSED（37 passed 含 hostile 回归）
```

## Compose Precedence Verification（C3 真实验证）

| 场景 | resolved 9000 | 结论 |
|---|---|---|
| 无宿主 env + --env-file 提供值 | env-file 值 | env-file 正常生效 |
| 宿主 shell 导出变量 + --env-file 提供同 key | 宿主值 | **宿主 > --env-file**（必须 sanitize） |
| wrapper unset 宿主变量后 + --env-file | env-file 值 | wrapper sanitization 保证隔离 |
| env-file 空值 | :latest | `${VAR:-default}` 对 empty 回落默认（preflight 拒绝） |

因此 **`--env-file` 单独不能保证 fail-closed**（§38 分支命中），必须采用最小 wrapper（§39）：
`scripts/release_9000_s10b.py` 只负责（1）environment sanitization（2）fail-closed preflight（3）canonical 9000-only compose invocation；**不** build/pull/migrate/restart 9100/修改 env（§39 边界，测试断言）。

## C1 Closure Evidence — 唯一 9000-only 命令合同

```text
SUPPORTED_9000_ONLY_RELEASE_COMMAND = ONE CANONICAL CONTRACT
docker compose --env-file <EXPLICIT_ENV_FILE> -f docker-compose.yml \
    up -d --no-deps --no-build auto-wechat-api
```

- 该命令由 `scripts/release_9000_s10b.py::canonical_up_command()` 统一构造（唯一实现点），文档（env example 02-A / ENV_VARIABLE_REFERENCE / 本报告）只引用 wrapper 或该单一命令形态，**未文档化多套等价命令**（§6）。
- 每参数治理目的（§5）：
  - `--env-file` → 强制使用显式 production/rehearsal identity contract，避免错误继承宿主 shell 环境
  - `--no-deps` → 9000-only，避免依赖服务（postgres）被带动，特别保护 frozen 9100（本就不在 9000 依赖图）
  - `--no-build` → 禁止 recreate 时基于当前 source 意外重建，保持 exact prebuilt image identity
- `restart` 边界（§7）：`docker compose restart auto-wechat-api` **不负责按新 image identity recreate container**，不得用作镜像切换（测试 `test_c1_restart_not_used_as_image_switch`）。
- 明确禁止本 catch-up 使用 `production_pg_switch_and_verify.sh` / `production_pg_rollback.sh` / 无 service target 的 `compose up -d`（沿用独立审批 C1）。
- C1 验收：AC01 显式加载 env file ✓ / AC02 只 target auto-wechat-api ✓ / AC03 --no-deps ✓ / AC04 --no-build ✓ / AC05 无 9100 service target ✓ / AC06 唯一文档化 ✓。

## C2 Closure Evidence — Image Identity Fail-Closed Preflight

`scripts/release_9000_s10b.py`（preflight 可执行机制，非人工 checklist）：

- 解析：`docker compose --env-file <ENV> config --format json` → RESOLVED_9000_IMAGE / RESOLVED_9100_IMAGE（§10）。
- Fail-closed（P1~P6）：
  - P1/P2 9000 / 9100 missing / empty / invalid → resolved 为空或回落 `:latest` → 拒绝
  - P3 production/rehearsal 模式下任一服务解析为 `:latest`（共享 mutable default）→ 拒绝
  - P4 9000 与 9100 解析为相同 shared mutable identity → 拒绝；相同 immutable（rollback/freeze 合法状态）→ 允许
  - P5 env file 不存在/不可读 → 拒绝
  - P6 compose config 解析失败 → 拒绝
  - P-EXPECTED `--expected-9000` / `--expected-9100` 与 resolved 不一致 → 拒绝（§13/§14）
- Immutable 判定（§12）：拒绝精确 known mutable `:latest` 后缀；接受 `repository:immutable-tag` 或 `repository@sha256:<digest>`；简单规则，**不声称验证 registry-side immutability**（文档已声明范围）。
- 9100 Freeze 校验（§13）：通过 `--expected-9100 <FROZEN_9100_IMAGE>` 显式输入提供，**不硬编码生产 `sha256:93094f0...`**（§41：NO production SHA hardcoded）。
- 输出（§15）：成功输出非 secret resolved 9000 / resolved 9100 / `identity isolation PASS`；失败输出明确 reason + exit 1。
- 无副作用（§16）：默认 static/preflight 模式只 `compose config` + 校验；`--dry-run` 打印命令；`--apply` 才执行 canonical up。无 docker pull / build / compose up（默认）/ restart / migration / DB write。
- C2 验收测试：C2-T01~T11 + P4 边界 + digest 形态 → 全 PASS（见 §15.1）。

## C3 Closure Evidence — Host Pollution 修复 + Upgrade/Freeze/Rollback 全序列

- Host pollution 根因与修复见「Host Environment Pollution Root Cause」。
- 测试环境显式构造（§19）：每个测试独立控制 `AUTO_WECHAT_API_IMAGE` / `XG_DOUYIN_AI_CS_IMAGE`，通过临时 env file + `compose_env()` 隔离，不继承 os.environ / PowerShell env / bash env / parent process env 的 IMAGE 值。
- Upgrade / Freeze / Rollback 全序列（§22）真实 config resolution 验证：

```text
STATE A（baseline）  9000=old-image-A     9100=frozen-image-B
STATE B（upgrade）   9000=target-image-C  9100=frozen-image-B
STATE C（rollback）  9000=old-image-A     9100=frozen-image-B
```

关键断言（§23，测试 `test_full_sequence_with_real_resolution` 全 PASS）：

```text
A.9100 == B.9100 == C.9100 == FROZEN_9100_IMAGE   ✓（9100 全程冻结不变）
A.9000 != B.9000                                    ✓（升级变化）
B.9000 != C.9000                                    ✓（回滚变化）
C.9000 == A.9000                                    ✓（回滚还原）
```

- Service Targeting（§24）：canonical command 唯一 target `auto-wechat-api`，无 `xg-douyin-ai-cs`（测试 `test_service_targeting_only_9000`）。
- 原 13 项测试未废弃：修复隔离 + 扩展覆盖 → 修正后 **37 passed**（§15.1）。

## C4 Closure Evidence — 真实 Git Diff Scope / Migration Side-Effect Audit

开始修改前基线（`git status --short` / `git diff --name-only` / `git diff --stat`）：

```text
 M .env.production.example / docker-compose.yml / docs/config/ENV_VARIABLE_REFERENCE.md
?? P2_M04_COORDINATED_CUTOVER_READINESS.md（PRE_EXISTING）
?? PRODUCTION_BASELINE_CATCHUP_0028_TO_0034_{DESIGN,DESIGN_APPROVAL,REALITY_AUDIT}.md（PRE_EXISTING）
?? S10_B_9000_9100_IMAGE_IDENTITY_ISOLATION_{APPROVAL,IMPLEMENTATION}.md（S10_B_IMPLEMENTATION）
?? tests/test_s10_b_image_identity_isolation.py（S10_B_IMPLEMENTATION）
```

完成后 `git status --short` / `git diff` 新增（S10_B_CORRECTION_DIFF）：

```text
?? scripts/release_9000_s10b.py（S10_B_CORRECTION_1）
 M tests/test_s10_b_image_identity_isolation.py（S10_B_IMPLEMENTATION + S10_B_CORRECTION_1：原 RE-T 测试 + correction 扩展）
 M .env.production.example / docs/config/ENV_VARIABLE_REFERENCE.md（S10_B_IMPLEMENTATION + S10_B_CORRECTION_1 合并修正）
 M 本报告（S10_B_CORRECTION_1：C5 原位修正 + Correction-1 章节）
```

Scope 分类（§28）：每文件归类 PRE_EXISTING / S10_B_IMPLEMENTATION / S10_B_CORRECTION_1 / UNKNOWN；**UNKNOWN = NONE**。

Hard Scope Guard（§29）：真实 diff 证明 `app/**`、`apps/**`、`migrations/**`、`frontend/**` **ZERO S10-B diff**（包括 correction 后）；无 pre-existing diff 在这些目录需证明 NOT_INTRODUCED_BY_S10_B 的情况。

Migration Side-Effect Audit（§30）：真实搜索 correction diff 中 `alembic / upgrade / downgrade / 0004 / 0005 / 0035 / migration`：

```text
命中均为 documentation mention（注释/文档），无 executable side effect
S10_B_EXECUTABLE_MIGRATION_SIDE_EFFECT = NONE
9100_DB_CHANGE = NONE
9100_MIGRATION_SIDE_EFFECT = NONE
```

## C5 Closure Evidence — Implementation Report / Env 文档事实与证据等级修正

- 原位修正 `docs/architecture/remediation/S10_B_9000_9100_IMAGE_IDENTITY_ISOLATION_IMPLEMENTATION.md`（未新建第二份 correction report）。
- 修正项：
  - `2 修改 + 3 新增` → `3 修改 + 2 新增`（§1 修正）
  - Repository Reality 标为「候选前基线事实」（§3 修正）
  - 「机制防漏设」→「提供显式隔离入口，但不防漏设/误操作」+ preflight fail-closed（§17 修正）
  - 「IMAGE 变量不进容器」→「Compose 插值消费；因 .env.production.local 同时是 service env_file，真实文件中的键也会进入容器环境，但应用不消费」（env example 02-A + ENV_VARIABLE_REFERENCE 修正）
  - 「未写入生产 SHA」→「未把完整生产 identity 硬编码到 Compose/env 配置」（§8 修正）
  - 证据等级统一：只使用 `COMPOSE_CONFIG_VERIFIED / STATIC_TEST_VERIFIED / DESIGN_CONTRACT_VERIFIED / PREFLIGHT_STATIC_VERIFIED / COMMAND_CONTRACT_VERIFIED / MECHANISM_READY_FOR_REHEARSAL`；**不得声称容器运行或生产运行已验证**（§7/§14 修正）
  - BR-24~BR-30 统一改为 `MECHANISM_READY_FOR_REHEARSAL = NOT EXECUTED`（§14 修正）
- env 文档（§36/§37）：`.env.production.example` 02-A 与 `docs/config/ENV_VARIABLE_REFERENCE.md` 均加入：
  - service-specific image vars / default behavior / production/rehearsal explicit requirement
  - host env precedence 警告（宿主 shell env > --env-file，--env-file 单独不能保证隔离）
  - canonical `--env-file` 命令（--no-deps / --no-build / auto-wechat-api）
  - fail-closed preflight 用法与边界
  - 不得把 shell env inheritance 写成安全 fallback

## Pre-existing Test Failures（Correction-1 复核）

`tests/test_env_profile_templates.py` 的 2 个失败为 **PRE-EXISTING 基线失败**（§15.2）：

```text
1. test_all_code_variables_are_classified —— 既有代码未登记变量清单（LAS_*/TOS_*/ARK_*/DAILY_REPORT_*/...），
   不含两个 S10-B Compose 变量；失败源 = 仓库既有未登记变量（其他窗口引入），非本窗口。
2. test_outbox_ten_variables_exact_defaults —— .env.development.example 的 outbox interval=10 期望 60，
   本窗口未改 dev example。
```

Baseline evidence：原实施窗口报告 §15 与独立实施审批 §14.3 均记录同一组 `48 passed, 2 failed`；S10_B_CORRECTION_DIFF 未触碰相关文件 → **NOT REGRESSION**（§32）。

## RE-AC 与 RG 回归（§42/§43）

- RE-AC01~12：Correction 后全 PASS（§13 矩阵，含 RE-AC05/06/07/08/09/12 专项复核）。
- RG-1~8：全部至少 `COMPOSE_CONFIG_VERIFIED / STATIC_VERIFIED`（§7 表）。

## Final Correction Test Matrix（§44）

```text
COR-T01 canonical command shape                      PASS（docker compose ... up -d ... auto-wechat-api）
COR-T02 includes --env-file                          PASS
COR-T03 includes --no-deps                           PASS
COR-T04 includes --no-build                          PASS
COR-T05 only targets 9000（无 9100 service target）    PASS
COR-T06 valid preflight                              PASS
COR-T07 missing9000 fail                             PASS
COR-T08 missing9100 fail                             PASS
COR-T09 mutable latest fail                          PASS
COR-T10 frozen9100 mismatch fail                     PASS
COR-T11 hostile host env isolation                   PASS（Host Pollution ×3）
COR-T12 baseline A/B                                 PASS
COR-T13 upgrade C/B                                  PASS
COR-T14 rollback A/B                                 PASS
COR-T15 9100 stable across sequence（A.9100==B.9100==C.9100） PASS
COR-T16 real git scope audit                         PASS（§C4）
COR-T17 migration side-effect audit                  PASS（S10_B_EXECUTABLE_MIGRATION_SIDE_EFFECT=NONE）
COR-T18 evidence-level/document consistency          PASS（§C5）
另加：C2-T01~T11 + C2-P4 边界 + C2-digest + C1 contract ×3 + C5 evidence ×2 → 全 PASS
```

---

## Final Correction Status（§48）

```text
C1 = APPLIED / CANDIDATE_CLOSED
C2 = APPLIED / CANDIDATE_CLOSED
C3 = APPLIED / CANDIDATE_CLOSED
C4 = APPLIED / CANDIDATE_CLOSED
C5 = APPLIED / CANDIDATE_CLOSED

HOST_ENV_POLLUTION_GAP
= CANDIDATE_RESOLVED

S10_B_IMPLEMENTATION_CORRECTION
= CANDIDATE_READY_FOR_FOCUSED_APPROVAL

C3
= STILL_NOT_CLOSED_PENDING_FOCUSED_APPROVAL

REHEARSAL_ENTRY_GATE
= STILL_BLOCKED

PRODUCTION_MIGRATION_AUTHORIZED
= NO
```

未出现任一 Mandatory Correction 无法安全关闭的情况，因此不输出 `S10_B_IMPLEMENTATION_CORRECTION_BLOCKED`。
